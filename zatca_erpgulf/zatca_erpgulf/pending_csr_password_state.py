"""Bounded encrypted Password backing observations for pending CSR custody.

No Frappe decryption/key discovery, active epoch, HTTP, DDL or transaction
ownership. The caller authorizes exact saved sources before invoking this
helper and must roll back/discard on failure. A digest observes encrypted bytes;
it does not prove their plaintext, validity, historical origin or remote status.
"""

import hashlib
from dataclasses import dataclass

from .csr_key_preservation import PROTECTED_CREDENTIAL_FIELDS
from .issuance_candidate import _canonical_uuid, _fingerprint
from .saved_form_source import saved_form_name


CREDENTIAL_FIELDS = ("custom_csr_config", "custom_private_key", "custom_csr_data", *PROTECTED_CREDENTIAL_FIELDS)
TEXT_FIELD_TYPES = frozenset(("Data", "Small Text", "Text", "Long Text", "Code", "Read Only", "Password"))
MAX_PASSWORD_BYTES = 65536


class PendingCSRPasswordStateError(ValueError):
    def __init__(self):
        super().__init__("pending_csr_password_state_unconfirmed")


@dataclass(frozen=True, repr=False)
class PasswordStateSource:
    """Authorized source/schema declaration, not row or field ACL proof."""

    doctype: str
    name: str
    password_fields: tuple

    def __post_init__(self):
        valid = False
        try:
            if type(self.doctype) is not str or self.doctype not in ("Company", "ZATCA Multiple Setting"):
                raise PendingCSRPasswordStateError()
            saved_form_name(self.name)
            if (type(self.password_fields) is not tuple
                    or len(self.password_fields) > len(CREDENTIAL_FIELDS)
                    or any(type(name) is not str or name not in CREDENTIAL_FIELDS for name in self.password_fields)
                    or self.password_fields != tuple(name for name in CREDENTIAL_FIELDS if name in self.password_fields)):
                raise PendingCSRPasswordStateError()
            valid = True
        except Exception:
            pass
        if not valid:
            raise PendingCSRPasswordStateError()

    def __repr__(self):
        return "PasswordStateSource(<protected saved schema observation>)"

    def __reduce_ex__(self, protocol):
        raise PendingCSRPasswordStateError()


def capture_password_state(connection, storage_namespace, sources):
    """Return only a protected aggregate digest of exact locked backing state.

    Query ALL known credential field names, including absent/non-Password fields:
    unexpected orphan backing rows fail closed rather than being silently ignored.
    No secret plaintext is read, reconstructed, logged or returned. Missing rows
    are observed absence, not proof that an issuing unit was never enrolled.
    """
    result = None
    try:
        if type(storage_namespace) is not str:
            raise PendingCSRPasswordStateError()
        _canonical_uuid(storage_namespace, "pending_csr_password_namespace")
        if type(sources) is not tuple or not 1 <= len(sources) <= 2:
            raise PendingCSRPasswordStateError()
        for source in sources:
            if type(source) is not PasswordStateSource:
                raise PendingCSRPasswordStateError()
            source.__post_init__()
        identities = tuple((source.doctype, source.name) for source in sources)
        if identities != tuple(sorted(set(identities))):
            raise PendingCSRPasswordStateError()
        observations = []
        with connection.cursor() as cursor:
            cursor.execute("SELECT @@session.autocommit")
            setting = cursor.fetchone()
            if type(setting) is not tuple or len(setting) != 1 or type(setting[0]) is not int or setting[0] != 0:
                raise PendingCSRPasswordStateError()
            for source in sources:
                cursor.execute("SELECT fieldname,encrypted,SUBSTRING(password,1,%s) FROM `__Auth` "
                    "WHERE doctype=%s AND name=%s AND fieldname IN ("
                    + ",".join("%s" for _ in CREDENTIAL_FIELDS)
                    + ") ORDER BY fieldname LIMIT %s FOR UPDATE",
                    (MAX_PASSWORD_BYTES + 1, source.doctype, source.name, *CREDENTIAL_FIELDS, len(CREDENTIAL_FIELDS) + 1))
                records = cursor.fetchall()
                if type(records) not in (tuple, list) or len(records) > len(CREDENTIAL_FIELDS):
                    raise PendingCSRPasswordStateError()
                fingerprints = {}
                for record in records:
                    if type(record) is not tuple or len(record) != 3:
                        raise PendingCSRPasswordStateError()
                    name, encrypted, token = record
                    if (type(name) is not str or name not in source.password_fields or name in fingerprints
                            or type(encrypted) is not int or encrypted != 1
                            or type(token) is not str or not 0 < len(token) <= MAX_PASSWORD_BYTES):
                        raise PendingCSRPasswordStateError()
                    content = token.encode("utf-8")
                    if len(content) > MAX_PASSWORD_BYTES:
                        raise PendingCSRPasswordStateError()
                    fingerprints[name] = hashlib.sha256(content).hexdigest()
                observations.append({"doctype": source.doctype, "name": source.name,
                    "password_fields": source.password_fields,
                    "state": tuple((name, fingerprints.get(name)) for name in CREDENTIAL_FIELDS)})
        result = _fingerprint({"password_state_schema": 1, "storage_namespace": storage_namespace,
                               "sources": observations})
    except Exception:
        pass
    if result is None:
        # Outside the catch: SQL/parser diagnostics cannot become error context.
        raise PendingCSRPasswordStateError()
    return result
