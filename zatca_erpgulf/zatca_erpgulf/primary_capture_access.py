"""Internal saved-source ACL boundary for LOCAL auth-free capture only.

No whitelist, UI/job/provider installation, HTTP/auth adapter or raw export.
Successful callers receive metadata ONLY. Explicit trusted server custody gets
the protected result before final ACL disclosure checks. Custody acknowledgment
is not proof of durable storage; interrupted/pre-result observations remain the
observer's custody responsibility. Never log/serialize protected recovery data.
"""

from dataclasses import dataclass, field
import hashlib

import frappe
from frappe import _
from frappe.permissions import has_permission

from .archive_source_access import ArchiveSourceBinding, _verify_rows
from .credential_bundle import _key_id
from .credential_bundle_access import CredentialStorageScope
from .issuance_candidate import _canonical_uuid, _sha256
from .journal_storage import encode_dispatch_event
from .primary_capture import PrimaryCaptureCoordinator, PrimaryCaptureResult, _request
from .primary_receipt_access import (
    PrimaryReceiptAccessError, _SavedPrimaryReceiptSource, _owned_saved_receipt_connection,
)
from .primary_receipt_custody_access import PrimaryReceiptCustodyKeys


DENIED_MESSAGE = "You do not have permission to run staged ZATCA invoice capture."
FAILED_MESSAGE = "Staged ZATCA invoice capture access failed. Do not retry automatically. Review server-side custody before any further action."
HANDOFF_MESSAGE = "Protected ZATCA capture requires server-side custody. Keep the protected recovery result and do not retry automatically."


class PrimaryCaptureAccessError(PrimaryReceiptAccessError):
    """Static internal code only; boundary messages are translated/redacted."""


@dataclass(frozen=True, repr=False)
class PrimaryCaptureBinding(ArchiveSourceBinding):
    """Exact server-declared start/request/key, not attested historic provenance."""

    attempt_id: str
    start_event_sha256: str
    request_sha256: str
    custody_key_id: str
    ERROR = PrimaryCaptureAccessError
    ERROR_PREFIX = "primary_capture_access"

    def __post_init__(self):
        super().__post_init__()
        _canonical_uuid(self.attempt_id, "primary_capture_access_attempt")
        for value in (self.start_event_sha256, self.request_sha256):
            _sha256(value, "primary_capture_access_fingerprint")
        _key_id(self.custody_key_id)


@dataclass(frozen=True, repr=False)
class PrimaryCaptureResources:
    """Trusted scoped dependencies only; no discovery or default no-op custody.

    observe() must retain original complete responses until custody accepts the
    result, including interruptions before a coordinator result exists. retain()
    receives protected server input and must return literal True. Neither a
    callback declaration nor its acknowledgment proves ownership or durability.
    """

    scope: CredentialStorageScope
    keys: PrimaryReceiptCustodyKeys = field(repr=False)
    observe: object = field(repr=False, compare=False)
    retain: object = field(repr=False, compare=False)

    def __post_init__(self):
        if (type(self.scope) is not CredentialStorageScope or type(self.keys) is not PrimaryReceiptCustodyKeys
                or not callable(self.observe) or not callable(self.retain)):
            raise PrimaryCaptureAccessError("primary_capture_access_resources")
        self.scope.__post_init__()
        self.keys.__post_init__()
        if self.keys.scope != self.scope:
            raise PrimaryCaptureAccessError("primary_capture_access_resources")

    def __repr__(self):
        return "PrimaryCaptureResources(<protected explicit server dependencies>)"

    def __reduce_ex__(self, protocol):
        raise PrimaryCaptureAccessError("primary_capture_access_not_pickleable")


class PrimaryCaptureHandoffRequired(RuntimeError):
    """Server-only recovery carrier, NEVER JSON/asdict/log/queue this exception.

    A failed/interrupted custody callback must not drop the exact result. Its
    protected payload is available ONLY to the trusted server owner. The public
    string/repr has no bytes or identities. This is not a user export capability.
    """

    def __init__(self, result, *, interrupted=False):
        self.result, self.interrupted = result, interrupted
        super().__init__(_(HANDOFF_MESSAGE))

    def __repr__(self):
        return "PrimaryCaptureHandoffRequired(<protected server recovery required>)"

    def __reduce_ex__(self, protocol):
        raise PrimaryCaptureAccessError("primary_capture_access_not_pickleable")


class _SavedCaptureSource(_SavedPrimaryReceiptSource):
    BINDING_TYPE = PrimaryCaptureBinding
    ERROR = PrimaryCaptureAccessError
    ERROR_PREFIX = "primary_capture_access"
    DENIED_MESSAGE = DENIED_MESSAGE
    FAILED_MESSAGE = FAILED_MESSAGE

    def _dependencies(self):
        return frappe, _, has_permission, None  # Saved-row selection only.


def _bind_request(binding, request):
    candidate, started = request.started.candidate, request.started
    if (binding.context != candidate.context or binding.uuid != candidate.artifact.uuid
            or binding.icv != candidate.artifact.icv or binding.journal_sha256 != started.journal_sha256
            or binding.attempt_id != started.events[0].attempt_id or binding.request_sha256 != request.body_sha256
            or binding.start_event_sha256 != hashlib.sha256(encode_dispatch_event(started.events[0])).hexdigest()):
        raise PrimaryCaptureAccessError("primary_capture_access_binding")


class SavedPrimaryCaptureService:
    """WRITE invoice/READ related rows before resources or scoped owned SQL.

    Exact server inputs only. No real authenticated sender or runtime activation.
    Source/ACL checks repeat before observer entry and after custody handoff; no
    SQL lock/permission-table atomicity is claimed across the observer callback.
    """

    def __init__(self, scope, lookup_provider, resource_provider, connection_factory):
        if not callable(resource_provider):
            raise PrimaryCaptureAccessError("primary_capture_access_dependencies")
        self._policy = _SavedCaptureSource(scope, lookup_provider, connection_factory)
        self._resources = resource_provider

    def __repr__(self):
        return "SavedPrimaryCaptureService(<permissioned metadata-only local capture>)"

    def __reduce_ex__(self, protocol):
        raise PrimaryCaptureAccessError("primary_capture_access_not_pickleable")

    def capture(self, invoice_name, supplied, *, doctype="Sales Invoice"):
        """Authorize, guard three owned transactions, hand off before disclosure.

        Failed final ACL checks cannot undo a committed hold/receipt. All returned
        coordinator results go to the server custodian BEFORE such checks. A
        failed/interrupted handoff raises a protected recovery carrier instead
        of hiding/dropping the result in an ordinary validation/permission error.
        """
        try:
            policy = self._policy
            actor = policy._actor()
            request = _request(supplied)
            source = request.started.candidate.context.scope
            if source.doctype != doctype or source.invoice_name != invoice_name:
                raise PrimaryCaptureAccessError("primary_capture_access_target")
            binding, rows, recheck = policy._saved_binding(invoice_name, doctype, actor)
            binding.__post_init__()
            _bind_request(binding, request)
            recheck()
            resources = self._resources(policy._scope)
            if type(resources) is not PrimaryCaptureResources:
                raise PrimaryCaptureAccessError("primary_capture_access_resources")
            resources.__post_init__()
            if resources.scope != policy._scope or resources.keys.key_id != binding.custody_key_id:
                raise PrimaryCaptureAccessError("primary_capture_access_resources")
            recheck()

            def guard(connection, pinned):
                if pinned != request:
                    raise PrimaryCaptureAccessError("primary_capture_access_request")
                recheck()
                _verify_rows(connection, rows)
                recheck()
                return True

            def observe(pinned):
                recheck()  # Close may have revoked ACL after the SQL preflight.
                _bind_request(binding, pinned)
                # Do NOT recheck after a complete response and thereby discard
                # it. The coordinator retains/seals it before later guard failure.
                return resources.observe(pinned)

            coordinator = PrimaryCaptureCoordinator(policy._scope.storage_namespace, resources.keys.cipher,
                resources.keys.key_id, connection_factory=lambda: _owned_saved_receipt_connection(policy, recheck),
                observe=observe, source_guard=guard)
            result = coordinator.capture(request)
            if type(result) is not PrimaryCaptureResult or result.request != request:
                raise PrimaryCaptureAccessError("primary_capture_access_result")
            result.__post_init__()
            acknowledged, interrupted = False, False
            try:
                acknowledged = resources.retain(policy._scope, result) is True
            except BaseException as error:
                interrupted = not isinstance(error, Exception)
            if not acknowledged:
                raise PrimaryCaptureHandoffRequired(result, interrupted=interrupted)
            recheck()  # No metadata disclosure if final actor/source/ACL changed.
            return {**result.diagnostic_projection(), "server_custody_acknowledged": True,
                "server_custody_durable_verified": False}
        except PrimaryCaptureHandoffRequired:
            raise  # Dedicated protected transfer, never convert/drop its payload.
        except frappe.PermissionError:
            denied = True
        except Exception:
            denied = False
        frappe.throw(_(DENIED_MESSAGE if denied else FAILED_MESSAGE),
            frappe.PermissionError if denied else frappe.ValidationError)
