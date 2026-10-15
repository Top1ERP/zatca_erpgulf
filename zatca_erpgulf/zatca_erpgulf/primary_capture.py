"""Opt-in LOCAL primary observation coordinator; no authenticated HTTP adapter.

Only explicit server-owned SQL/key/guard/observer dependencies are accepted.
Tests use synthetic observers. No default sender, credential discovery, Frappe
registration, clock/ID allocation, replay, hold release or invoice/status writes.
Correlation declarations/local commits do NOT attest transport or remote success.
"""

import base64
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json

from .compliance_capture import _owned_transaction
from .credential_bundle import _key_id
from .dispatch_journal import DispatchEvent
from .issuance_candidate import _canonical_uuid, _sha256
from .journal_repository import MariaDBJournalRepository
from .primary_attempt_hold import MariaDBPrimaryAttemptHoldRepository, _declaration, _started_journal
from .primary_receipt_custody import (
    MariaDBPrimaryReceiptCustodyRepository, PrimaryReceiptCustodyCipher,
    SealedPrimaryReceipt, encode_retained_receipt,
)
from .primary_receipt_persistence import RetainedPrimaryReceipt, _validate_retained
from .response_json import MAX_RESPONSE_BYTES


REQUEST_CODEC = 1
CAPTURE_STATES = (
    "RESERVATION_UNCONFIRMED_NO_OBSERVER", "PREFLIGHT_FAILED_NO_OBSERVER",
    "OBSERVER_OUTCOME_UNKNOWN_NO_REPLAY", "RESPONSE_UNBOUND_NO_REPLAY",
    "RECEIPT_PREPARATION_UNCONFIRMED_NO_REPLAY", "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY",
    "RECEIPT_CAPTURED_OBSERVATION_NO_REPLAY",
)


class PrimaryCaptureError(ValueError):
    """Static internal code only; never a raw observer/SQL/body/key exception."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class PrimaryCaptureRequest:
    """Deterministic v1 body from exact archived XML; no auth/signing material.

    Reconstructible from the immutable candidate with a persisted codec/hash.
    Future approved adapters must send THESE bytes, never reserialize with json=.
    This object is NOT an authenticated wire request or dispatch capability.
    """

    started: object = field(repr=False)
    body: bytes = field(init=False, repr=False)
    body_sha256: str = field(init=False, repr=False)

    def __post_init__(self):
        try:
            started = _started_journal(self.started)
            candidate = started.candidate
            body = json.dumps({"invoiceHash": candidate.artifact.invoice_digest,
                "uuid": candidate.artifact.uuid, "invoice": base64.b64encode(candidate.xml_bytes).decode("ascii")},
                sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PrimaryCaptureError("primary_capture_request")
        object.__setattr__(self, "started", started)  # Detached rebuilt nested snapshot.
        object.__setattr__(self, "body", body)
        object.__setattr__(self, "body_sha256", hashlib.sha256(body).hexdigest())

    @property
    def url(self):
        return self.started.candidate.context.route.url

    def __repr__(self):
        return "PrimaryCaptureRequest(<protected exact auth-free request>)"

    def __reduce_ex__(self, protocol):
        raise PrimaryCaptureError("primary_capture_not_pickleable")


def _request(value):
    try:
        if type(value) is not PrimaryCaptureRequest:
            raise ValueError
        rebuilt = PrimaryCaptureRequest(value.started)
        if rebuilt != value:
            raise ValueError
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        raise PrimaryCaptureError("primary_capture_request")
    return rebuilt


@dataclass(frozen=True, repr=False)
class PrimaryObservedResponse:
    """Supplied complete response/correlation, NOT attested TLS/authority origin."""

    request_sha256: str
    attempt_id: str
    event_id: str
    received_at: datetime
    http_status: int
    body: bytes = field(repr=False)
    request_id: str | None = None

    def __post_init__(self):
        try:
            _sha256(self.request_sha256, "primary_capture_request_hash")
            for identity in (self.attempt_id, self.event_id):
                _canonical_uuid(identity, "primary_capture_identity")
            if self.request_id is not None:
                _canonical_uuid(self.request_id, "primary_capture_request_id")
            if (type(self.received_at) is not datetime or self.received_at.tzinfo is not timezone.utc
                    or type(self.http_status) is not int or not 200 <= self.http_status <= 599
                    or type(self.body) is not bytes or len(self.body) > MAX_RESPONSE_BYTES):
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PrimaryCaptureError("primary_capture_response")

    def __repr__(self):
        return "PrimaryObservedResponse(<protected supplied observation>)"

    def __reduce_ex__(self, protocol):
        raise PrimaryCaptureError("primary_capture_not_pickleable")


def _retained(namespace, request, response):
    if response.request_sha256 != request.body_sha256 or response.attempt_id != request.started.events[0].attempt_id:
        raise PrimaryCaptureError("primary_capture_response_binding")
    candidate = request.started.candidate
    observed = DispatchEvent(response.event_id, response.attempt_id, 2, response.received_at,
        "HTTP_RESPONSE", candidate.key_sha256, candidate.manifest_sha256,
        response.http_status, response.body, response.request_id)
    return RetainedPrimaryReceipt(namespace, request.started, observed)


@dataclass(frozen=True, repr=False)
class PrimaryCaptureResult:
    """Protected exact recovery input, NOT acceptance, replay or an operator JSON."""

    state: str
    request: PrimaryCaptureRequest = field(repr=False)
    response: PrimaryObservedResponse | None = field(default=None, repr=False)
    receipt: RetainedPrimaryReceipt | None = field(default=None, repr=False)
    sealed: SealedPrimaryReceipt | None = field(default=None, repr=False)

    def __post_init__(self):
        try:
            if type(self.state) is not str or self.state not in CAPTURE_STATES:
                raise ValueError
            _request(self.request)
            stage = CAPTURE_STATES.index(self.state)
            if (stage < 3 and any(value is not None for value in (self.response, self.receipt, self.sealed))
                    or stage >= 3 and type(self.response) is not PrimaryObservedResponse
                    or stage == 3 and (self.receipt is not None or self.sealed is not None)
                    or stage == 4 and self.sealed is not None):
                raise ValueError
            if self.response is not None:
                self.response.__post_init__()
            if stage >= 4:
                if type(self.receipt) is not RetainedPrimaryReceipt:
                    raise ValueError
                if _retained(self.receipt.storage_namespace, self.request, self.response) != self.receipt:
                    raise ValueError
            if stage >= 5:
                if type(self.sealed) is not SealedPrimaryReceipt:
                    raise ValueError
                self.sealed.__post_init__()
                if (self.sealed.storage_namespace != self.receipt.storage_namespace
                        or self.sealed.candidate_sha256 != self.request.started.candidate.key_sha256
                        or self.sealed.attempt_id != self.response.attempt_id
                        or self.sealed.predecessor_sha256 != self.request.started.journal_sha256
                        or self.sealed.receipt_sha256 != hashlib.sha256(encode_retained_receipt(self.receipt)).hexdigest()):
                    raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PrimaryCaptureError("primary_capture_result")

    def diagnostic_projection(self):
        return {"state": self.state,
            "local_transaction_completed": self.state == "RECEIPT_CAPTURED_OBSERVATION_NO_REPLAY",
            "provider_origin_verified": False, "historical_source_verified": False,
            "credential_epoch_verified": False, "transport_verified": False,
            "remote_receipt_verified": False, "remote_acceptance_verified": False,
            "dispatch_authorized": False, "replay_authorized": False}

    def __repr__(self):
        return "PrimaryCaptureResult(<protected exact local recovery input>)"

    def __reduce_ex__(self, protocol):
        raise PrimaryCaptureError("primary_capture_not_pickleable")


class _RequestBinding:
    """Strict fixed SQL; no plaintext request copy, commit or duplicate adoption.

    The v1 body is deterministically reconstructed from archived XML; its codec
    and hash are persisted WITH start/hold, detecting later serializer drift.
    """

    def __init__(self, connection, namespace):
        self.connection, self.namespace = connection, namespace

    def check(self, request, *, insert=False):
        expected = _declaration(self.namespace, request.started)
        if MariaDBPrimaryAttemptHoldRepository(self.connection, self.namespace).load(request.started) != expected:
            raise PrimaryCaptureError("primary_capture_hold")
        with self.connection.cursor() as cursor:
            if insert:
                cursor.execute("INSERT INTO zatca_primary_request_binding_v1 "
                    "(storage_namespace,source_sha256,candidate_sha256,attempt_id,request_codec,request_sha256) "
                    "VALUES (%s,%s,%s,%s,%s,%s)", (self.namespace, expected.source_sha256,
                        expected.candidate_sha256, expected.attempt_id, REQUEST_CODEC, request.body_sha256))
            cursor.execute("SELECT candidate_sha256,attempt_id,request_codec,request_sha256 "
                "FROM zatca_primary_request_binding_v1 WHERE storage_namespace=%s AND source_sha256=%s FOR UPDATE",
                (self.namespace, expected.source_sha256))
            row = cursor.fetchone()
            if (type(row) is not tuple or len(row) != 4 or type(row[2]) is not int
                    or row != (expected.candidate_sha256, expected.attempt_id, REQUEST_CODEC, request.body_sha256)):
                raise PrimaryCaptureError("primary_capture_request_binding")


class PrimaryCaptureCoordinator:
    """Explicit non-activated observer coordinator with THREE owned transactions.

    The server must authorize source/keys/providers before use. Factories supply
    fresh owned handles, never ambient Frappe connections, and own failed acquire.
    Mandatory guard returns literal True before/after work in each transaction.
    The observer is a trusted dependency, NOT authenticated HTTP or attestation.
    No SQL lock survives its one invocation. There is no resume/retry method.
    """

    def __init__(self, namespace, cipher, key_id, *, connection_factory, observe, source_guard):
        try:
            _canonical_uuid(namespace, "primary_capture_namespace")
            _key_id(key_id)
            if (type(cipher) is not PrimaryReceiptCustodyCipher or key_id not in cipher._keys
                    or any(not callable(value) for value in (connection_factory, observe, source_guard))):
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PrimaryCaptureError("primary_capture_dependencies")
        self._namespace, self._cipher, self._key_id = namespace, cipher, key_id
        self._factory, self._observe, self._guard = connection_factory, observe, source_guard

    def __repr__(self):
        return "PrimaryCaptureCoordinator(<protected explicit local dependencies>)"

    def __reduce_ex__(self, protocol):
        raise PrimaryCaptureError("primary_capture_not_pickleable")

    def _check(self, connection, request):
        if _request(request) != request or self._guard(connection, request) is not True:
            raise PrimaryCaptureError("primary_capture_source_guard")
        _request(request)  # Detect changed protected input during the guard.

    def capture(self, supplied):
        """Reserve once/close, preflight/close, observe ONCE, store exact receipt.

        Caller retains protected result/input; commit/close ambiguity never loops.
        Interruptions propagate after owned cleanup; a previously committed hold
        stays spent. No returned state changes remote acceptance/provenance flags.
        """
        request = _request(supplied)
        response, receipt, sealed = None, None, None
        def result(state):
            return PrimaryCaptureResult(state, request, response, receipt, sealed)

        try:
            def reserve(connection):
                self._check(connection, request)
                MariaDBPrimaryAttemptHoldRepository(connection, self._namespace).reserve(request.started)
                _RequestBinding(connection, self._namespace).check(request, insert=True)
                self._check(connection, request)
            _owned_transaction(self._factory, reserve)
        except Exception:
            return result("RESERVATION_UNCONFIRMED_NO_OBSERVER")

        try:
            def preflight(connection):
                self._check(connection, request)
                _RequestBinding(connection, self._namespace).check(request)
                if MariaDBJournalRepository(connection, self._namespace).load(request.started.candidate.key_sha256) != request.started:
                    raise PrimaryCaptureError("primary_capture_preflight")
                self._check(connection, request)
            _owned_transaction(self._factory, preflight)
        except Exception:
            return result("PREFLIGHT_FAILED_NO_OBSERVER")

        try:
            returned = self._observe(_request(request))  # Independent nested snapshot; ONE invocation.
            if type(returned) is not PrimaryObservedResponse:
                raise PrimaryCaptureError("primary_capture_response")
            response = replace(returned)  # Revalidate/copy immutable complete observation.
        except Exception:
            return result("OBSERVER_OUTCOME_UNKNOWN_NO_REPLAY")
        try:
            receipt = _retained(self._namespace, request, response)
        except Exception:
            return result("RESPONSE_UNBOUND_NO_REPLAY")
        try:
            sealed = self._cipher.seal(receipt, key_id=self._key_id)  # Seal EXACTLY once.
            if self._cipher.open(sealed) != receipt:
                raise PrimaryCaptureError("primary_capture_seal")
        except Exception:
            sealed = None
            return result("RECEIPT_PREPARATION_UNCONFIRMED_NO_REPLAY")

        try:
            def persist(connection):
                self._check(connection, request)
                _RequestBinding(connection, self._namespace).check(request)
                after = _validate_retained(receipt)
                repository = MariaDBJournalRepository(connection, self._namespace)
                if repository.load(request.started.candidate.key_sha256) not in (request.started, after):
                    raise PrimaryCaptureError("primary_capture_predecessor")
                stored = MariaDBPrimaryReceiptCustodyRepository(connection, self._namespace, self._cipher).stage(sealed)
                if stored != sealed or repository.append(request.started.candidate.key_sha256, receipt.response_event,
                        expected_journal_sha256=request.started.journal_sha256) != after:
                    raise PrimaryCaptureError("primary_capture_receipt")
                self._check(connection, request)
            _owned_transaction(self._factory, persist)
        except Exception:
            return result("RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY")
        return result("RECEIPT_CAPTURED_OBSERVATION_NO_REPLAY")
