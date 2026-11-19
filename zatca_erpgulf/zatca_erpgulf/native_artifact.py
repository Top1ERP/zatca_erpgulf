"""Read native XML/QR display data from committed custody, without re-signing.

Simplified documents retain their seller-generated XML/QR before Reporting.
Standard documents require matched cleared XML, or accepted Reporting after the
bound303 fallback. This reader never creates a File, image or acceptance status.
"""

from dataclasses import dataclass, field
import hashlib

from .artifact_evidence import ArtifactEvidenceError
from .issuance_candidate import IssuanceContractError, _invoice_classification
from .issue_timestamp import IssueTimestampError
from .native_dispatch import NativeDispatchError, read_retained_invoice
from .qr_xml_contract import QRXMLContractError, _clock, _payload


@dataclass(frozen=True, repr=False)
class NativeInvoiceArtifact:
    issuance_id: str
    state: str
    source_kind: str
    accepted: bool
    xml_bytes: bytes = field(repr=False)
    qr_payload: str = field(repr=False)
    xml_sha256: str
    qr_payload_sha256: str
    issue_date: str
    issue_time: str
    source_sha256: str | None = field(default=None, repr=False)
    invoice_uuid: str | None = field(default=None, repr=False)
    icv: str | None = field(default=None, repr=False)
    chain_id: str | None = field(default=None, repr=False)
    publication_sha256: str | None = field(default=None, repr=False)
    render_source_sha256: str | None = field(default=None, repr=False)

    def __reduce_ex__(self, protocol):
        raise TypeError('native_invoice_artifact_not_serializable')


def read_native_artifact(doctype, invoice_name, *, runtime, for_publication=False):
    """Read ACL and current saved identity are checked by the custody reader.

    No current signing key, gateway or phase is consulted. A legacy source
    returns None for its separate adapter; a native source with missing or
    contradictory custody raises, never silently falls back to a stale File.
    Returned metadata matching remains distinct from workstream6 crypto/SDK
    verification and workstream3 financial reconciliation.
    """
    view = read_retained_invoice(doctype, invoice_name, runtime=runtime,
        require_current_source=for_publication)
    if view is None:
        return None
    if for_publication and view.state not in (
            'PREPARED', 'DISPATCHING', 'OUTCOME_UNKNOWN', 'REPORTED', 'CLEARED'):
        raise NativeDispatchError('native_publication_state_review')
    failed = False
    try:
        _code, indicator = _invoice_classification(view.original_xml)
        original_clock = _clock(view.original_xml)
        if indicator.startswith('02'):
            kind, content = 'SIMPLIFIED_GENERATED_XML', view.original_xml
        elif indicator.startswith('01') and view.accepted:
            if view.outcome in ('CLEARANCE_MATCHED', 'CLEARANCE_DUPLICATE_MATCHED') and view.returned_xml is not None:
                kind, content = 'STANDARD_CLEARED_XML', view.returned_xml
            elif view.outcome == 'REPORTING_MATCHED' and view.state == 'REPORTED':
                # For a Standard original the custody reader requires the
                # retained clearance303 when assessing this Reporting outcome.
                kind, content = 'STANDARD_303_REPORTED_XML', view.original_xml
            else:
                raise NativeDispatchError('native_standard_publication_unconfirmed')
        else:
            raise NativeDispatchError('native_standard_publication_unconfirmed')
        if content is not view.original_xml and _clock(content) != original_clock:
            raise NativeDispatchError('native_artifact_returned_clock_mismatch')
        qr, _length = _payload(content)
    except (ArtifactEvidenceError, IssuanceContractError, IssueTimestampError, QRXMLContractError):
        failed = True
    if failed:
        raise NativeDispatchError('native_artifact_xml_or_qr_review')
    # Retained rejected originals remain available for diagnosis. Consumers must
    # display this state; QR presence never makes a rejected document valid.
    return NativeInvoiceArtifact(view.issuance_id, view.state, kind, view.accepted, content, qr,
        hashlib.sha256(content).hexdigest(), hashlib.sha256(qr.encode('ascii')).hexdigest(),
        *original_clock, view.source_sha256, view.invoice_uuid, view.icv, view.chain_id,
        view.publication_sha256, view.render_source_sha256)
