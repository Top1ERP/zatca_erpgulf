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
from .issuance_candidate import _canonical_uuid, _fingerprint
from .operation_messages import mute_operation_messages
from .permission_compat import saved_row_has_permission
from .pending_csr import (
    PendingCSRCipher, SealedPendingCSR, _key_id,
)
from .pending_csr_binding import SOURCE_SCHEMA, PendingCSRAccessError, PendingCSRSourceBinding
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
    return _fingerprint({"pending_csr_source_schema": SOURCE_SCHEMA, "rows": [
        {"doctype": row.doctype, "name": row.name, "revision": row.revision,
         "fields": row.fields, "values": row.values, "password_fields": row.password_fields} for row in rows]})


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

    def stage_new_bound(self, company_abbr, source_identity, sealed):
        """Capture current authorized/locked source state and stage a NEW pair.

        No historical lookup is invoked or invented. Existing pairs and unbound
        drafts are refused; retry/recovery is a separate reviewed operation.
        Caller owns the entire transaction, including rollback after failure.
        """
        return self._execute("create_bound", company_abbr, source_identity, sealed)

    def _create_bound_for_commit(self, company_abbr, source_identity, sealed, completion):
        """Protected initial-capture handoff to the same owned coordinator."""
        if not callable(completion):
            raise PendingCSRAccessError()
        return self._execute("create_bound", company_abbr, source_identity, sealed, completion=completion)

    def _stage_for_commit(self, company_abbr, source_identity, sealed, completion):
        """Protected owned-coordinator handoff only; never expose through RPC.

        The completion receives exact resources plus locked/current rechecks.
        Existing stage/inspect callers keep their caller-owned transaction API.
        """
        if not callable(completion):
            raise PendingCSRAccessError()
        return self._execute("stage", company_abbr, source_identity, sealed, completion=completion)

    def inspect(self, company_abbr, source_identity, *, draft_id):
        """Inspect one server-bound draft; no latest lookup or ciphertext export."""
        return self._execute("inspect", company_abbr, source_identity, draft_id)

    def _observe_for_review(self, company_abbr, source_identity, original, completion):
        """Protected read-only handoff; exact original input, no repair or replay."""
        if not callable(completion):
            raise PendingCSRAccessError()
        return self._execute("observe", company_abbr, source_identity, original, completion=completion)

    def _observe_bound_for_review(self, company_abbr, source_identity, original, completion):
        """Protected owned pair review; no lookup, recapture or repair callback."""
        if not callable(completion):
            raise PendingCSRAccessError()
        return self._execute("observe_bound", company_abbr, source_identity, original, completion=completion)

    def _execute(self, operation, company_abbr, identity, value, *, completion=None):
        entered = False
        try:
            if self._busy or self._failed:
                raise PendingCSRAccessError()
            self._busy, entered = True, True
            with mute_operation_messages(frappe):
                return self._work(operation, company_abbr, identity, value, completion=completion)
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

    def _work(self, operation, company_abbr, identity, value, *, completion=None):
        actor = self._actor()
        initial = operation == "create_bound"
        pair_review = operation == "observe_bound"
        if operation not in ("stage", "inspect", "observe", "create_bound", "observe_bound"):
            raise PendingCSRAccessError()
        if operation != "inspect":
            if type(value) is not SealedPendingCSR:
                raise PendingCSRAccessError()
            value.__post_init__()
            value = SealedPendingCSR(value.storage_namespace, value.manifest_bytes, value.key_id, value.nonce, value.ciphertext)
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
        binding = None
        if initial or pair_review:
            manifest, key_id = value.manifest, value.key_id
        else:
            binding = self._lookup(self._scope, target.doctype, target.name, draft_id)
            if type(binding) is not PendingCSRSourceBinding:
                raise PendingCSRAccessError()
            binding.__post_init__()
            # Snapshot primitives, not a provider-owned mutable interpretation.
            binding = PendingCSRSourceBinding(binding.scope, binding.manifest, binding.source_rows_sha256,
                                             binding.key_id, binding.password_state_sha256)
            if binding.scope != self._scope or binding.source_rows_sha256 != _rows_sha256(rows):
                raise PendingCSRAccessError()
            manifest, key_id = binding.manifest, binding.key_id
        context = manifest.context
        if (context.draft_id != draft_id or context.slot.owner_doctype != target.doctype
                or context.slot.owner_name != target.name or context.company_name != company.name
                or context.source_kind != ("company" if target.doctype == "Company" else "multiple_setting")
                or saved_form_revision(context.source_revision) != saved_form_revision(target.revision)
                or context.slot.environment != environment
                or type(target.get("custom_csr_config")) is not str
                or hashlib.sha256(target.get("custom_csr_config").encode()).hexdigest() != manifest.configuration_sha256):
            raise PendingCSRAccessError()

        def check_envelope(sealed):
            if (type(sealed) is not SealedPendingCSR or sealed.storage_namespace != self._scope.storage_namespace
                    or sealed.manifest_bytes != manifest.encode() or sealed.key_id != key_id):
                raise PendingCSRAccessError()

        if operation != "inspect":
            check_envelope(value)
        recheck()
        resources = self._resources(self._scope)
        if type(resources) is not PendingCSRResources:
            raise PendingCSRAccessError()
        resources.__post_init__()
        if resources.scope != self._scope or resources.key_id != key_id:
            raise PendingCSRAccessError()
        if resources.connection is frappe.db or resources.connection is getattr(frappe.db, "_conn", None):
            raise PendingCSRAccessError()
        recheck()
        _verify_locked_rows(resources.connection, rows)
        repository = MariaDBPendingCSRRepository(resources.connection, self._scope.storage_namespace, resources.cipher)
        password_sources = tuple(PasswordStateSource(row.doctype, row.name, row.password_fields) for row in rows)
        pair_result = None
        if pair_review:
            pair_result = repository.observe_bound(self._scope, value)
            _, binding = pair_result
            if binding is not None and (binding.scope != self._scope
                    or binding.manifest.encode() != manifest.encode() or binding.key_id != key_id
                    or binding.source_rows_sha256 != _rows_sha256(rows)):
                raise PendingCSRAccessError()
            recheck()
        if initial or (pair_review and binding is None):
            # Capture backing bytes only AFTER normal ACLs, scoped acquisition
            # and same-transaction locked source checks. Never use a placeholder
            # digest or recalculate a historical binding from today's settings.
            password_digest = capture_password_state(resources.connection, self._scope.storage_namespace, password_sources)
            recheck()
            if initial:
                binding = PendingCSRSourceBinding(self._scope, manifest, _rows_sha256(rows), key_id, password_digest)
            # An incomplete/conflicting pair has NO adopted historical binding.
            # This digest observes CURRENT backing stability only, not history.
        else:
            password_digest = binding.password_state_sha256

        def check_password_state():
            if capture_password_state(resources.connection, self._scope.storage_namespace, password_sources) != password_digest:
                raise PendingCSRAccessError()

        check_password_state()
        recheck()
        observation = None
        if initial:
            if repository.create_bound(binding, value) != binding:
                raise PendingCSRAccessError()
            if repository.load_binding(self._scope, context) != binding:
                raise PendingCSRAccessError()
            sealed = value
        elif pair_review:
            sealed = value
        elif operation == "observe":
            observation = repository.observe(value)
            sealed = value  # Never substitute conflicting stored ciphertext.
        else:
            sealed = repository.stage(value) if operation == "stage" else repository.load(context)
            check_envelope(sealed)
        _verify_locked_rows(resources.connection, rows)
        check_password_state()
        recheck()
        report = manifest.diagnostic_projection()
        report.update(state="PENDING_CSR_STAGED_UNCOMMITTED" if operation == "stage" else "PENDING_CSR_INSPECTION_OBSERVATION",
                      current_source_match_observed=True, current_permissions_observed=True,
                      password_backing_state_match_observed=not pair_review or binding is not None)
        if operation == "observe":
            report.update(state="PENDING_CSR_REVIEW_UNCLOSED", envelope_observation=observation)
        if initial:
            report.update(state="PENDING_CSR_BOUND_CREATION_UNCOMMITTED", original_source_binding_observed=True)
        if pair_review:
            report.update(state="PENDING_CSR_BOUND_REVIEW_UNCLOSED", pair_observation=pair_result[0],
                          original_source_binding_observed=binding is not None,
                          current_password_backing_stable_observed=True)
        if completion is not None:
            def binding_projection(selected):
                if type(selected) is not PendingCSRSourceBinding:
                    raise PendingCSRAccessError()
                selected.__post_init__()
                return (selected.scope.site, selected.scope.storage_namespace, selected.manifest.encode(),
                        selected.source_rows_sha256, selected.key_id, selected.password_state_sha256)

            expected_binding = None if binding is None else binding_projection(binding)

            def current_guard():
                recheck()
                if not (initial or pair_review):
                    selected = self._lookup(self._scope, target.doctype, target.name, draft_id)
                    if binding_projection(selected) != expected_binding:
                        raise PendingCSRAccessError()
                recheck()

            def locked_guard(connection):
                if connection is not resources.connection:
                    raise PendingCSRAccessError()
                current_guard()
                _verify_locked_rows(connection, rows)
                check_password_state()
                if initial and binding_projection(repository.load_binding(self._scope, context)) != expected_binding:
                    raise PendingCSRAccessError()
                if pair_review:
                    stable = repository.observe_bound(self._scope, sealed) == pair_result
                else:
                    stable = (repository.observe(sealed) == observation if operation == "observe"
                              else repository.load(context) == sealed)
                if not stable:
                    raise PendingCSRAccessError()
                _verify_locked_rows(connection, rows)
                check_password_state()
                current_guard()

            return completion(resources, locked_guard, current_guard, report)
        return report


def _row_key(doc):
    return doc.doctype, doc.name
