"""Local five-tag QR observations and missing-original advance review policy.

Never turn a QR, copied row, saved status or absent archive into invented XML,
UUID/ICV/type/date/time or acceptance. No file/image scan, ERP/timezone lookup,
accounting change, migration, signing, transport or settlement authorization.
Supported lexical subsets are diagnostic policy, NOT full XSD/legal validation.
"""

import base64
import binascii
from dataclasses import dataclass, field
import hashlib
import re

from zatca_erpgulf.zatca_erpgulf.advance_reference import AdvanceReferenceError, _clock


MAX_TLV_BYTES = 5 * (2 + 255)
MAX_PAYLOAD_BYTES = 4 * ((MAX_TLV_BYTES + 2) // 3)
MISSING_REFERENCE_FIELDS = ("invoice_id", "uuid", "icv", "document_type_code", "original_xml")
ORIGINS = ("PHASE1_QR_ONLY", "LEGACY_COPIED_REFERENCE", "PHASE2_ARCHIVE_MISSING", "AMBIGUOUS_ORIGINAL")
PHASES = ("Phase-1", "Phase-2")


class AdvanceSourceGapError(ValueError):
    """Static codes only; never expose supplied QR/private source text."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _read_payload(payload, seller):
    if type(seller) is not str or re.fullmatch(r"[0-9]{15}", seller) is None:
        raise AdvanceSourceGapError("gap_expected_seller")
    if type(payload) not in (str, bytes):
        raise AdvanceSourceGapError("gap_payload_type")
    if not 0 < len(payload) <= MAX_PAYLOAD_BYTES:
        raise AdvanceSourceGapError("gap_payload_size")
    try:
        raw = payload.encode("ascii") if type(payload) is str else payload
        decoded = base64.b64decode(raw, validate=True)
    except (UnicodeEncodeError, ValueError, binascii.Error):
        invalid = True
    else:
        invalid = False
    if invalid:
        raise AdvanceSourceGapError("gap_payload_base64")
    if not decoded or len(decoded) > MAX_TLV_BYTES:
        raise AdvanceSourceGapError("gap_tlv_size")
    if base64.b64encode(decoded) != raw:
        raise AdvanceSourceGapError("gap_payload_noncanonical")
    values, offset = [], 0
    for expected_tag in range(1, 6):
        if offset + 2 > len(decoded):
            raise AdvanceSourceGapError("gap_tlv_truncated")
        tag, length = decoded[offset:offset + 2]
        offset += 2
        if tag != expected_tag:
            raise AdvanceSourceGapError("gap_tlv_tags")
        if length == 0 or offset + length > len(decoded):
            raise AdvanceSourceGapError("gap_tlv_length")
        try:
            value = decoded[offset:offset + length].decode("utf-8")
        except UnicodeDecodeError:
            invalid_text = True
        else:
            invalid_text = False
        if invalid_text:
            raise AdvanceSourceGapError("gap_tlv_utf8")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise AdvanceSourceGapError("gap_tlv_text")
        values.append(value)
        offset += length
    if offset != len(decoded):
        # Do not truncate a Phase-2/binary payload to five first-match fields.
        raise AdvanceSourceGapError("gap_tlv_extra")
    if values[1] != seller:
        raise AdvanceSourceGapError("gap_seller_mismatch")
    timestamp = values[2]
    valid_clock = False
    if len(timestamp) <= 64 and timestamp.count("T") == 1:
        day, clock = timestamp.split("T")
        try:
            _clock(day, clock)
        except AdvanceReferenceError:
            pass
        else:
            valid_clock = True
    if not valid_clock:
        raise AdvanceSourceGapError("gap_timestamp")
    for amount in values[3:]:
        if re.fullmatch(r"[+-]?[0-9]{1,24}(?:\.[0-9]{1,6})?", amount) is None:
            raise AdvanceSourceGapError("gap_amount_text")
    return raw, decoded, tuple(values), clock


@dataclass(frozen=True)
class FiveTagQRObservation:
    """Decode bounded supplied bytes, not an issued/authenticated invoice.

    Amount and timestamp text is preserved; no VAT math or timezone conversion.
    Exactly five tags describe format only, not historical phase/provenance.
    """

    payload: object = field(repr=False)
    expected_seller_tax_id: str = field(repr=False)
    seller_name: str = field(init=False, repr=False)
    seller_tax_id: str = field(init=False, repr=False)
    timestamp: str = field(init=False, repr=False)
    total_text: str = field(init=False, repr=False)
    vat_text: str = field(init=False, repr=False)
    payload_sha256: str = field(init=False)
    payload_byte_length: int = field(init=False)
    tlv_byte_length: int = field(init=False)
    offset_declared: bool = field(init=False)

    def __post_init__(self):
        raw, decoded, values, clock = _read_payload(self.payload, self.expected_seller_tax_id)
        for name, value in zip(("seller_name", "seller_tax_id", "timestamp", "total_text", "vat_text"), values):
            object.__setattr__(self, name, value)
        object.__setattr__(self, "payload_sha256", hashlib.sha256(raw).hexdigest())
        object.__setattr__(self, "payload_byte_length", len(raw))
        object.__setattr__(self, "tlv_byte_length", len(decoded))
        object.__setattr__(self, "offset_declared", clock.endswith("Z") or bool(re.search(r"[+-][0-9]{2}:[0-9]{2}$", clock)))

    def diagnostic_projection(self):
        return {
            "schema_version": 1, "observed_format": "FIVE_TAG_QR",
            "payload_sha256": self.payload_sha256,
            "payload_byte_length": self.payload_byte_length,
            "tlv_byte_length": self.tlv_byte_length,
            "offset_declared": self.offset_declared,
            "missing_reference_fields": list(MISSING_REFERENCE_FIELDS),
            "phase_verified": False, "source_provenance_verified": False,
            "business_data_verified": False, "remote_acceptance_verified": False,
            "phase2_reference_ready": False, "settlement_authorized": False,
        }


@dataclass(frozen=True)
class MissingAdvanceSourcePlan:
    """Explicit diagnostic review plan, not new accounting eligibility rules.

    Inputs describe a gap already observed by a future authorized service.
    This class does not search for a missing source or prove it is absent.
    """

    origin: str
    target_phase: str
    qr: FiveTagQRObservation | None = field(default=None, repr=False)

    def __post_init__(self):
        if type(self.origin) is not str or self.origin not in ORIGINS:
            raise AdvanceSourceGapError("gap_origin")
        if type(self.target_phase) is not str or self.target_phase not in PHASES:
            raise AdvanceSourceGapError("gap_target_phase")
        if self.qr is not None and (self.origin != "PHASE1_QR_ONLY" or type(self.qr) is not FiveTagQRObservation):
            raise AdvanceSourceGapError("gap_qr_binding")

    def diagnostic_projection(self):
        phase1_only = self.target_phase == "Phase-1" and self.origin == "PHASE1_QR_ONLY"
        return {
            "schema_version": 1, "origin": self.origin, "target_phase": self.target_phase,
            "outcome": "SOURCE_GAP_REVIEW_REQUIRED",
            "required_action": "KEEP_EXISTING_PHASE1_WORKFLOW" if phase1_only else "EXPLICIT_HISTORICAL_RECONCILIATION",
            "qr_observation": self.qr.diagnostic_projection() if self.qr is not None else None,
            "accounting_eligibility_changed": False,
            "phase2_reference_ready": False, "missing_source_verified": False,
            "source_provenance_verified": False, "settlement_authorized": False,
            "reconstruction_authorized": False, "migration_authorized": False,
            "dispatch_authorized": False, "remote_acceptance_verified": False,
        }
