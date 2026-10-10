"""Internal two-transaction Compliance collector with NO default HTTP sender.

The server must authorize saved source/tenant scope BEFORE constructing/calling
this component. Supplied dependencies are not proven transport/CSR provenance.
One owned transaction reserves an identity; it commits AND closes before the
transport callable. A second owned transaction stores a bound immutable receipt.
Unknown results never authorize replay. Never whitelist, pickle or log objects.
"""

import hashlib
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import timedelta

from zatca_erpgulf.zatca_erpgulf.compliance_archive import (
    ComplianceArchiveCipher, SealedComplianceObservation,
)
from zatca_erpgulf.zatca_erpgulf.compliance_archive_repository import MariaDBComplianceArchiveRepository
from zatca_erpgulf.zatca_erpgulf.compliance_evidence import (
    ComplianceExchangeObservation, ComplianceRequirements,
)
from zatca_erpgulf.zatca_erpgulf.credential_bundle import CredentialBundleCipher, _key_id, _validate
from zatca_erpgulf.zatca_erpgulf.credential_bundle_repository import MariaDBCredentialBundleRepository
from zatca_erpgulf.zatca_erpgulf.credential_snapshot import CredentialSnapshot, validate_snapshot_time
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import _canonical_uuid
from zatca_erpgulf.zatca_erpgulf.response_json import MAX_RESPONSE_BYTES


MAX_PREPARATION_AGE = timedelta(seconds=30)
CAPTURE_STATES = (
    "PREPARATION_UNCONFIRMED_NO_SEND", "DISPATCH_PREFLIGHT_FAILED_NO_SEND",
    "TRANSPORT_UNKNOWN_NO_REPLAY", "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY",
    "RECEIPT_CAPTURED_OBSERVATION",
)


class ComplianceCaptureError(ValueError):
    """Internal static code only; operator adapters must translate/redact."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ComplianceTransportRequest:
    """Ephemeral exact body and snapshot-derived header, NEVER archive/export.

    A transport must use these bytes and headers unchanged, perform one POST,
    verify TLS/approved destination, disable redirects/retries/ambient credentials
    and return a bounded complete response. This object cannot prove it did so.
    """

    start: ComplianceExchangeObservation = field(repr=False)
    snapshot: CredentialSnapshot = field(repr=False)

    def __post_init__(self):
        if (type(self.start) is not ComplianceExchangeObservation or self.start.http_status is not None
                or type(self.snapshot) is not CredentialSnapshot):
            raise ComplianceCaptureError("capture_request")
        manifest = self.start.requirements.manifest
        material = self.snapshot
        if (material.route != self.start.route or material.authorization.purpose != "compliance"
                or material.owner.company_name != manifest.company_name
                or material.owner.doctype != manifest.slot.owner_doctype or material.owner.name != manifest.slot.owner_name
                or material.owner.source_kind != manifest.source_kind
                or material.certificate_der_sha256 != manifest.certificate_der_sha256
                or material.public_key_sha256 != manifest.public_key_sha256
                or hashlib.sha256(material.certificate_text.encode("ascii")).hexdigest() != manifest.certificate_text_sha256
                or not self.start.started_at <= material.observed_at <= self.start.started_at + MAX_PREPARATION_AGE):
            raise ComplianceCaptureError("capture_material_binding")

    @property
    def url(self):
        return self.start.route.url

    @property
    def body(self):
        return self.start.request_bytes

    def headers(self):
        return {"Accept": "application/json", "Accept-Encoding": "identity", "Accept-Language": "en", "Accept-Version": "V2",
                "Content-Type": "application/json", "Authorization": self.snapshot.authorization.header}

    def __reduce_ex__(self, protocol):
        raise ComplianceCaptureError("capture_not_pickleable")


@dataclass(frozen=True)
class ComplianceTransportResponse:
    """One supplied complete response; no proof of TLS/source or remote success."""

    http_status: int
    body: bytes = field(repr=False)

    def __post_init__(self):
        if (type(self.http_status) is not int or not 100 <= self.http_status <= 599
                or type(self.body) is not bytes or len(self.body) > MAX_RESPONSE_BYTES):
            raise ComplianceCaptureError("capture_response")

    def __reduce_ex__(self, protocol):
        raise ComplianceCaptureError("capture_not_pickleable")


@dataclass(frozen=True)
class ComplianceCaptureResult:
    """Protected recovery envelope, not a UI payload or proof of commit/provenance.

    On receipt commit failure retain the EXACT envelope for reviewed persistence
    reconciliation only. Never reseal/re-send automatically. Process loss before
    durable receipt commit can leave only the reservation, even after HTTP success.
    """

    state: str
    exchange_id: str
    version_id: str
    start_envelope: SealedComplianceObservation | None = field(default=None, repr=False)
    receipt_envelope: SealedComplianceObservation | None = field(default=None, repr=False)
    observation: ComplianceExchangeObservation | None = field(default=None, repr=False)
    response: ComplianceTransportResponse | None = field(default=None, repr=False)

    def __post_init__(self):
        try:
            if type(self.state) is not str or self.state not in CAPTURE_STATES:
                raise ComplianceCaptureError("capture_result_state")
            for identity in (self.exchange_id, self.version_id):
                _validate(identity, "capture_result_identity", _canonical_uuid)
            if self.observation is not None:
                if (type(self.observation) is not ComplianceExchangeObservation
                        or self.observation.exchange_id != self.exchange_id
                        or self.observation.requirements.manifest.version_id != self.version_id):
                    raise ComplianceCaptureError("capture_result_binding")
            if self.response is not None and type(self.response) is not ComplianceTransportResponse:
                raise ComplianceCaptureError("capture_result_response")
            if (self.observation is None
                    or (self.state != "PREPARATION_UNCONFIRMED_NO_SEND" and self.start_envelope is None)
                    or (self.state in ("PREPARATION_UNCONFIRMED_NO_SEND", "DISPATCH_PREFLIGHT_FAILED_NO_SEND")
                        and (self.response is not None or self.observation.http_status is not None))
                    or (self.state not in ("RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY", "RECEIPT_CAPTURED_OBSERVATION")
                        and self.receipt_envelope is not None)):
                raise ComplianceCaptureError("capture_result_stage")
            for sequence, envelope in ((1, self.start_envelope), (2, self.receipt_envelope)):
                if envelope is not None:
                    if (type(envelope) is not SealedComplianceObservation or envelope.sequence != sequence
                            or envelope.exchange_id != self.exchange_id or envelope.version_id != self.version_id
                            or self.observation is None
                            or envelope.storage_namespace != self.observation.requirements.storage_namespace):
                        raise ComplianceCaptureError("capture_result_binding")
                    expected = self.observation if sequence == 2 else replace(
                        self.observation, http_status=None, response_bytes=None, received_at=None,
                    )
                    if envelope.observation_sha256 != expected.observation_sha256:
                        raise ComplianceCaptureError("capture_result_binding")
            if self.observation.http_status is not None and (self.response is None
                    or self.observation.http_status != self.response.http_status
                    or self.observation.response_bytes != self.response.body):
                raise ComplianceCaptureError("capture_result_response")
            if self.state in ("RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY", "RECEIPT_CAPTURED_OBSERVATION"):
                if (self.start_envelope is None or self.receipt_envelope is None or self.response is None
                        or self.observation.http_status != self.response.http_status
                        or self.observation.response_bytes != self.response.body):
                    raise ComplianceCaptureError("capture_result_receipt")
        except ValueError:
            raise ComplianceCaptureError("capture_result") from None

    def diagnostic_projection(self):
        return {"state": self.state, "exchange_id": self.exchange_id, "version_id": self.version_id,
                "observation": None if self.observation is None else self.observation.diagnostic_projection(),
                "request_dispatched_verified": False, "remote_receipt_verified": False,
                "source_snapshot_verified": False, "credential_epoch_verified": False,
                "csr_issuance_provenance_verified": False, "compliance_completion_verified": False,
                "activation_authorized": False, "dispatch_authorized": False, "replay_authorized": False}

    def __reduce_ex__(self, protocol):
        raise ComplianceCaptureError("capture_not_pickleable")


class ComplianceCaptureCoordinator:
    """Explicit server dependencies; no Frappe/clock/connection/HTTP discovery.

    connection_factory() MUST return a fresh owned non-autocommit transaction,
    never a shared Frappe/borrowed connection. The factory owns failed acquisition;
    this component commits, rolls back and closes successfully acquired resources.
    transport(request) MUST make at most one application-level send; reviewed
    transport/source providers, deployment approval and provenance remain gates.
    """

    def __init__(self, storage_namespace, bundle_cipher, archive_cipher, key_id, *, connection_factory, transport, clock):
        try:
            _validate(storage_namespace, "capture_namespace", _canonical_uuid)
            _key_id(key_id)
        except ValueError:
            raise ComplianceCaptureError("capture_binding") from None
        if (type(bundle_cipher) is not CredentialBundleCipher or type(archive_cipher) is not ComplianceArchiveCipher
                or key_id not in archive_cipher._keys
                or set(bundle_cipher._keys.values()) & set(archive_cipher._keys.values())
                or any(not callable(value) for value in (connection_factory, transport, clock))):
            raise ComplianceCaptureError("capture_dependencies")
        self._namespace, self._bundle_cipher, self._archive_cipher, self._key_id = storage_namespace, bundle_cipher, archive_cipher, key_id
        self._factory, self._transport, self._clock = connection_factory, transport, clock

    def __repr__(self):
        return "ComplianceCaptureCoordinator(<protected explicit dependencies>)"

    def __reduce_ex__(self, protocol):
        raise ComplianceCaptureError("capture_not_pickleable")

    def _now(self):
        now = self._clock()
        validate_snapshot_time(now)
        return now

    def _transaction(self, work):
        """Own cleanup; a failed/unknown commit or close never permits HTTP."""
        connection = self._factory()
        try:
            if any(not callable(getattr(connection, name, None)) for name in ("cursor", "commit", "rollback", "close")):
                raise ComplianceCaptureError("capture_connection")
            result = work(connection)
            connection.commit()
        except BaseException:
            # Best-effort cleanup does not resolve an uncertain commit outcome.
            with suppress(Exception):
                connection.rollback()
            with suppress(Exception):
                connection.close()
            raise
        try:
            connection.close()
        except BaseException:
            with suppress(Exception):
                connection.rollback()
            raise
        return result

    def capture(self, requirements, *, exchange_id, route, request_bytes):
        """Reserve once, close before transport, preserve raw response once.

        Invalid arguments fail before acquisition. Every returned state is a
        local observation, NOT authority to dispatch another attempt or activate.
        Missing/error/duplicate reservations all fail closed without transport.
        """
        try:
            if type(requirements) is not ComplianceRequirements or requirements.storage_namespace != self._namespace:
                raise ComplianceCaptureError("capture_requirements")
            start = ComplianceExchangeObservation(requirements, exchange_id, route, self._now(), None, request_bytes, None, None)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise ComplianceCaptureError("capture_input")

        left, right, observed, response = None, None, start, None

        def result(state):
            return ComplianceCaptureResult(state, exchange_id, requirements.manifest.version_id, left, right, observed, response)

        try:
            left = self._archive_cipher.seal(start, sequence=1, key_id=self._key_id)
            def reserve(connection):
                bundle = MariaDBCredentialBundleRepository(connection, self._namespace, self._bundle_cipher).load(
                    requirements.manifest.slot, requirements.manifest.version_id,
                )
                if bundle.manifest_bytes != requirements.manifest.encode():
                    raise ComplianceCaptureError("capture_version_binding")
                material = self._bundle_cipher.open(bundle, observed_at=start.started_at)
                ComplianceTransportRequest(start, material)  # Validate BEFORE reservation.
                MariaDBComplianceArchiveRepository(connection, self._namespace, self._bundle_cipher, self._archive_cipher).reserve_request(left)
                return bundle
            bundle = self._transaction(reserve)
        except Exception:
            return result("PREPARATION_UNCONFIRMED_NO_SEND")

        try:
            # Recheck local certificate validity and bounded age after locks are
            # released, using the SAME exact stored envelope/credential material.
            material = self._bundle_cipher.open(bundle, observed_at=self._now())
            request = ComplianceTransportRequest(start, material)
        except Exception:
            return result("DISPATCH_PREFLIGHT_FAILED_NO_SEND")

        try:
            returned = self._transport(request)  # Exactly ONE dependency invocation.
            if type(returned) is not ComplianceTransportResponse:
                raise ComplianceCaptureError("capture_response")
            response = returned
            observed = replace(start, received_at=self._now(), http_status=response.http_status, response_bytes=response.body)
            right = self._archive_cipher.seal(observed, sequence=2, key_id=self._key_id)
        except Exception:
            # No complete timed/bound receipt. Reservation remains spent. A
            # complete response (if obtained) is retained privately for review.
            return result("TRANSPORT_UNKNOWN_NO_REPLAY")

        try:
            def persist(connection):
                return MariaDBComplianceArchiveRepository(connection, self._namespace, self._bundle_cipher, self._archive_cipher).append_receipt(right)
            self._transaction(persist)
        except Exception:
            return result("RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY")
        return result("RECEIPT_CAPTURED_OBSERVATION")
