"""Internal saved-source/ACL boundary for unactivated pending CSR custody.

No whitelist, key generation, plaintext export, provider installation, HTTP,
active credential write or transaction ownership. The server supplies exact
historical bindings and protected resources, never request-selected keys/SQL.
On ANY failure the caller must roll back its whole transaction and discard this
service/resources. Observed source hashes are not independently verified epochs.
"""

import hashlib
from dataclasses import dataclass, field
from types import MappingProxyType

import frappe
from frappe import _
from frappe.permissions import has_permission

from .api_routing import ENVIRONMENT_FIELDS, resolve_api_route
from .credential_bundle_access import CredentialStorageScope
from .credential_write_access import CredentialWriteAccessError, load_credential_write_source
from .issuance_candidate import _canonical_uuid, _fingerprint, _sha256
from .operation_messages import mute_operation_messages
from .permission_compat import saved_row_has_permission
from .pending_csr import (
    PendingCSRCipher, PendingCSRManifest, SealedPendingCSR, _key_id, decode_pending_manifest,
)
from .pending_csr_repository import MariaDBPendingCSRRepository
from .pending_csr_password_state import (
    CREDENTIAL_FIELDS, TEXT_FIELD_TYPES, PasswordStateSource, capture_password_state,
)
from .saved_form_source import saved_form_name, saved_form_revision


DENIED_MESSAGE = "You do not have permission to store or inspect pending ZATCA CSR drafts."
FAILED_MESSAGE = (
    "Pending ZATCA CSR custody could not be confirmed. Keep the original sealed draft. "
    "The transaction owner must roll back and review the source settings before retrying. "
    "No certificate was activated or request sent."
)
COMMON_FIELDS = CREDENTIAL_FIELDS
FIELD_MAP = MappingProxyType({
    "Company": ("abbr", "tax_id", "custom_select", *ENVIRONMENT_FIELDS.values(), *COMMON_FIELDS),
    "ZATCA Multiple Setting": ("custom_linked_doctype", "custom__use_company_certificate__keys", *COMMON_FIELDS),
})
REQUIRED_FIELDS = MappingProxyType({
    "Company": ("abbr", "tax_id", "custom_select", "custom_csr_config"),
    "ZATCA Multiple Setting": ("custom_linked_doctype", "custom__use_company_certificate__keys", "custom_csr_config"),
})
MAX_FIELD_CHARS = 65536
LINK_FLAG = "custom__use_company_certificate__keys"


class PendingCSRAccessError(ValueError):
    """Static internal failure only, not diagnostic/source/material export."""

    def __init__(self):
        super().__init__("pending_csr_access_unconfirmed")


def _value(name, value):
    if name == LINK_FLAG:
        if type(value) is str and value in ("0", "1"):
            return int(value)
        if type(value) in (int, bool) and value in (0, 1):
            return int(value)
        raise PendingCSRAccessError()
    if value is not None and (type(value) is not str or len(value) > MAX_FIELD_CHARS):
        raise PendingCSRAccessError()
    if type(value) is str:
        value.encode("utf-8")
    return value


@dataclass(frozen=True, repr=False)
class _PendingSourceRow:
    """Protected exact projection; never RPC-export or log this raw object."""

    doctype: str
    name: str
    revision: str
    fields: tuple
    values: tuple = field(repr=False)
    password_fields: tuple = ()

    @classmethod
    def capture(cls, doc):
        kind, identity = doc.doctype, saved_form_name(doc.name)
        if kind not in FIELD_MAP:
            raise PendingCSRAccessError()
        # Schema presence is part of the binding; absent aliases are not treated
        # as present empty columns, and only app-constant identifiers reach SQL.
        present = tuple(name for name in FIELD_MAP[kind] if doc.meta.has_field(name) is True)
        if not set(REQUIRED_FIELDS[kind]).issubset(present):
            raise PendingCSRAccessError()
        password_fields = []
        for name in present:
            if name in COMMON_FIELDS:
                definition = doc.meta.get_field(name)
                fieldtype = getattr(definition, "fieldtype", None)
                if type(fieldtype) is not str or fieldtype not in TEXT_FIELD_TYPES:
                    raise PendingCSRAccessError()
                if fieldtype == "Password":
                    password_fields.append(name)
        return cls(kind, identity, saved_form_revision(doc.get("modified")).isoformat(sep=" ", timespec="microseconds"),
                   present, tuple(_value(name, doc.get(name)) for name in present), tuple(password_fields))

    def get(self, name):
        return dict(zip(self.fields, self.values)).get(name)

    def __repr__(self):
        return "_PendingSourceRow(<protected saved observation>)"

    def __reduce_ex__(self, protocol):
        raise PendingCSRAccessError()


def _rows_sha256(rows):
    # This protected digest is only an observed local comparison, not authority
    # provenance or a public fingerprint of low-entropy settings/password masks.
    return _fingerprint({"pending_csr_source_schema": 2, "rows": [
        {"doctype": row.doctype, "name": row.name, "revision": row.revision,
         "fields": row.fields, "values": row.values, "password_fields": row.password_fields} for row in rows]})


@dataclass(frozen=True, repr=False)
class PendingCSRSourceBinding:
    """Server lookup declaration, not independently verified historic evidence."""

    scope: CredentialStorageScope
    manifest: PendingCSRManifest
    source_rows_sha256: str
    key_id: str
    password_state_sha256: str

    def __post_init__(self):
        if type(self.scope) is not CredentialStorageScope or type(self.manifest) is not PendingCSRManifest:
            raise PendingCSRAccessError()
        self.scope.__post_init__()
        _sha256(self.source_rows_sha256, "pending_csr_access_source")
        _sha256(self.password_state_sha256, "pending_csr_access_password_state")
        _key_id(self.key_id)
        object.__setattr__(self, "manifest", decode_pending_manifest(self.manifest.encode()))

    def __repr__(self):
        return "PendingCSRSourceBinding(<server-selected exact declaration>)"

    def __reduce_ex__(self, protocol):
        raise PendingCSRAccessError()


@dataclass(frozen=True, repr=False)
class PendingCSRResources:
    """Explicit caller-owned transaction/cipher; no ownership/origin proof."""

    scope: CredentialStorageScope
    key_id: str
    connection: object = field(repr=False, compare=False)
    cipher: PendingCSRCipher = field(repr=False, compare=False)

    def __post_init__(self):
        if type(self.scope) is not CredentialStorageScope or type(self.cipher) is not PendingCSRCipher:
            raise PendingCSRAccessError()
        self.scope.__post_init__()
        _key_id(self.key_id)
        if not callable(getattr(self.connection, "cursor", None)):
            raise PendingCSRAccessError()

    def __repr__(self):
        return "PendingCSRResources(<protected caller-owned resources>)"

    def __reduce_ex__(self, protocol):
        raise PendingCSRAccessError()


def _verify_locked_rows(connection, rows):
    """Bounded exact reads in the SAME staging transaction, no schema repair."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT @@session.autocommit")
        setting = cursor.fetchone()
        if type(setting) is not tuple or len(setting) != 1 or type(setting[0]) is not int or setting[0] != 0:
            raise PendingCSRAccessError()
        for row in rows:
            columns = ["`name`", "`modified`"] + [
                "`" + name + "`" if name == LINK_FLAG else "SUBSTRING(`" + name + "`,1,%s)"
                for name in row.fields]
            limits = tuple(MAX_FIELD_CHARS + 1 for name in row.fields if name != LINK_FLAG)
            cursor.execute("SELECT " + ",".join(columns) + " FROM `tab" + row.doctype
                           + "` WHERE `name`=%s FOR UPDATE", (*limits, row.name))
            raw = cursor.fetchone()
            if type(raw) is not tuple or len(raw) != 2 + len(row.fields):
                raise PendingCSRAccessError()
            actual = _PendingSourceRow(row.doctype, saved_form_name(raw[0]),
                saved_form_revision(raw[1]).isoformat(sep=" ", timespec="microseconds"), row.fields,
                tuple(_value(name, value) for name, value in zip(row.fields, raw[2:])), row.password_fields)
            if actual != row:
                raise PendingCSRAccessError()


class SavedPendingCSRService:
    """Metadata-only stage/inspect; callers retain exact ciphertext independently.

    Source READ+WRITE, related Company READ and System Manager/Administrator are
    required before lookup/resources. Providers are trusted SERVER dependencies.
    Calls reload source/ACL observations around provider and locked SQL work;
    they do not atomically lock permission tables or prove a credential epoch.
    Never share this per-transaction service across threads or serialize it.
    """

    def __init__(self, scope, lookup_provider, resource_provider):
        if type(scope) is not CredentialStorageScope or not callable(lookup_provider) or not callable(resource_provider):
            raise PendingCSRAccessError()
        scope.__post_init__()
        self._scope, self._lookup, self._resources = scope, lookup_provider, resource_provider
        self._failed, self._busy = False, False

    def __repr__(self):
        return "SavedPendingCSRService(<permissioned unactivated staging>)"

    def __reduce_ex__(self, protocol):
        raise PendingCSRAccessError()

    def _actor(self):
        if self._failed:
            raise PendingCSRAccessError()
        site, user = getattr(frappe.local, "site", None), getattr(frappe.session, "user", None)
        if site != self._scope.site or type(user) is not str or not user or user == "Guest":
            raise CredentialWriteAccessError("permission")
        if user != "Administrator":
            roles = frappe.get_roles(user)
            if type(roles) not in (list, tuple) or "System Manager" not in roles:
                raise CredentialWriteAccessError("permission")
        return site, user

    def _source(self, company_abbr, identity, actor):
        if self._actor() != actor:
            raise CredentialWriteAccessError("permission")
        def permission(doctype, operation, *, doc, user, raise_exception=True):
            if self._actor() != actor or user != actor[1]:
                raise CredentialWriteAccessError("permission")
            allowed = saved_row_has_permission(has_permission, doctype, operation, doc=doc, user=user)
            if self._actor() != actor:
                raise CredentialWriteAccessError("permission")
            return allowed

        source = load_credential_write_source(frappe, permission, company_abbr, identity)
        rows = {_row_key(doc): _PendingSourceRow.capture(doc) for doc in (source.target, source.company)}
        rows = tuple(rows[key] for key in sorted(rows))
        if self._actor() != actor:
            raise CredentialWriteAccessError("permission")
        target, company = next(row for row in rows if _row_key(row) == _row_key(source.target)), next(
            row for row in rows if _row_key(row) == _row_key(source.company))
        if target.doctype == "ZATCA Multiple Setting" and target.get(LINK_FLAG) != 0:
            # Do not silently stage a device key when signing uses Company keys.
            # The linked Company must instead be selected explicitly with WRITE.
            raise PendingCSRAccessError()
        route = resolve_api_route(dict(zip(company.fields, company.values)), "compliance/invoices")
        return rows, target, company, route.environment

    def stage(self, company_abbr, source_identity, sealed):
        """Stage exact retained ciphertext; no commit, reseal or plaintext return."""
        return self._execute("stage", company_abbr, source_identity, sealed)

    def inspect(self, company_abbr, source_identity, *, draft_id):
        """Inspect one server-bound draft; no latest lookup or ciphertext export."""
        return self._execute("inspect", company_abbr, source_identity, draft_id)

    def _execute(self, operation, company_abbr, identity, value):
        entered = False
        try:
            if self._busy or self._failed:
                raise PendingCSRAccessError()
            self._busy, entered = True, True
            with mute_operation_messages(frappe):
                return self._work(operation, company_abbr, identity, value)
        except CredentialWriteAccessError as error:
            denied = error.code == "permission"
        except frappe.PermissionError:
            denied = True
        except Exception:
            denied = False
        except BaseException:
            self._failed = True
            raise
        finally:
            if entered:
                self._busy = False
        self._failed = True
        # Outside catches: private provider/SQL/source errors must not become
        # implicit context or raw text of the single translated public failure.
        frappe.throw(_(DENIED_MESSAGE if denied else FAILED_MESSAGE),
                     frappe.PermissionError if denied else frappe.ValidationError)

    def _work(self, operation, company_abbr, identity, value):
        actor = self._actor()
        if operation == "stage":
            if type(value) is not SealedPendingCSR:
                raise PendingCSRAccessError()
            value.__post_init__()
            if value.storage_namespace != self._scope.storage_namespace:
                raise PendingCSRAccessError()
            draft_id = value.manifest.context.draft_id
        else:
            _canonical_uuid(value, "pending_csr_access_draft")
            draft_id = value
        # Freeze caller identity before callbacks; only saved doctype/name count.
        if type(identity) is not dict:
            raise PendingCSRAccessError()
        identity = {"doctype": identity.get("doctype"), "name": identity.get("name")}
        rows, target, company, environment = self._source(company_abbr, identity, actor)

        def recheck():
            current = self._source(company_abbr, identity, actor)
            if current[0] != rows or current[3] != environment:
                raise PendingCSRAccessError()

        recheck()
        binding = self._lookup(self._scope, target.doctype, target.name, draft_id)
        if type(binding) is not PendingCSRSourceBinding:
            raise PendingCSRAccessError()
        binding.__post_init__()
        manifest, context = binding.manifest, binding.manifest.context
        if (binding.scope != self._scope or binding.source_rows_sha256 != _rows_sha256(rows)
                or context.draft_id != draft_id or context.slot.owner_doctype != target.doctype
                or context.slot.owner_name != target.name or context.company_name != company.name
                or context.source_kind != ("company" if target.doctype == "Company" else "multiple_setting")
                or saved_form_revision(context.source_revision) != saved_form_revision(target.revision)
                or context.slot.environment != environment
                or type(target.get("custom_csr_config")) is not str
                or hashlib.sha256(target.get("custom_csr_config").encode()).hexdigest() != manifest.configuration_sha256):
            raise PendingCSRAccessError()

        def check_envelope(sealed):
            if (type(sealed) is not SealedPendingCSR or sealed.storage_namespace != self._scope.storage_namespace
                    or sealed.manifest_bytes != manifest.encode() or sealed.key_id != binding.key_id):
                raise PendingCSRAccessError()

        if operation == "stage":
            check_envelope(value)
        recheck()
        resources = self._resources(self._scope)
        if type(resources) is not PendingCSRResources:
            raise PendingCSRAccessError()
        resources.__post_init__()
        if resources.scope != self._scope or resources.key_id != binding.key_id:
            raise PendingCSRAccessError()
        if resources.connection is frappe.db or resources.connection is getattr(frappe.db, "_conn", None):
            raise PendingCSRAccessError()
        recheck()
        _verify_locked_rows(resources.connection, rows)
        password_sources = tuple(PasswordStateSource(row.doctype, row.name, row.password_fields) for row in rows)

        def check_password_state():
            if capture_password_state(resources.connection, self._scope.storage_namespace, password_sources) != binding.password_state_sha256:
                raise PendingCSRAccessError()

        check_password_state()
        recheck()
        repository = MariaDBPendingCSRRepository(resources.connection, self._scope.storage_namespace, resources.cipher)
        sealed = repository.stage(value) if operation == "stage" else repository.load(context)
        check_envelope(sealed)
        _verify_locked_rows(resources.connection, rows)
        check_password_state()
        recheck()
        report = manifest.diagnostic_projection()
        report.update(state="PENDING_CSR_STAGED_UNCOMMITTED" if operation == "stage" else "PENDING_CSR_INSPECTION_OBSERVATION",
                      current_source_match_observed=True, current_permissions_observed=True,
                      password_backing_state_match_observed=True)
        return report


def _row_key(doc):
    return doc.doctype, doc.name
