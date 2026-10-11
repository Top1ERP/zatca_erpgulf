"""Read-only original-XML advance reference observations, not issuance authority.

The caller supplies exact bytes and explicit expected invoice/UUID/seller identity.
No current posting fields, timezone setting, clock, file selection, credentials,
database, or remote response is consulted. Preserve the original lexical clock;
normalizing it with today's timezone would rewrite historical evidence.

This checks bounded metadata only. It does NOT authenticate a file, validate its
signature/XSD/accounting, prove acceptance, or authorize settlement. Adoption
requires a separately audited immutable original-artifact selection service.
"""

import hashlib
import re
from dataclasses import dataclass, field
from uuid import UUID

from zatca_erpgulf.zatca_erpgulf.artifact_evidence import (
    ArtifactEvidenceError,
    NS,
    UUID_PATTERN,
    parse_diagnostic_xml,
)
from zatca_erpgulf.zatca_erpgulf.issue_timestamp import (
    IssueTimestampError,
    parse_issue_datetime,
)

SUPPLIER_PATH = "./cac:AccountingSupplierParty"
PARTY_PATH = SUPPLIER_PATH + "/cac:Party"
VAT_PATH = PARTY_PATH + "/cac:PartyTaxScheme[cac:TaxScheme/cbc:ID='VAT']"
XML_CLOCK_PATTERN = re.compile(
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})?"
)


class AdvanceReferenceError(ValueError):
    """Static codes only; never expose XML, caller identity or parser messages."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class AdvanceReferenceEvidence:
    """Immutable observations, not a trusted-source or acceptance capability."""

    invoice_id: str = field(repr=False)
    uuid: str = field(repr=False)
    seller_tax_id: str = field(repr=False)
    issue_date: str = field(repr=False)
    issue_time: str = field(repr=False)
    file_sha256: str
    byte_length: int
    document_type_code: str = "386"


def _identity_text(value, code, *, maximum=140):
    if (
        type(value) is not str
        or not 0 < len(value) <= maximum
        or value != value.strip()
        or any(ord(char) < 32 for char in value)
    ):
        raise AdvanceReferenceError(code)
    return value


def _uuid(value, code):
    value = _identity_text(value, code, maximum=36)
    if UUID_PATTERN.fullmatch(value) is None:
        raise AdvanceReferenceError(code)
    return str(UUID(value))


def _seller(value, code):
    if type(value) is not str or re.fullmatch(r"[0-9]{15}", value) is None:
        raise AdvanceReferenceError(code)
    return value


def _one_text(root, xpath, code):
    nodes = root.xpath(xpath, namespaces=NS)
    if (
        len(nodes) != 1
        or len(nodes[0])
        or nodes[0].text is None
        or nodes[0].text != nodes[0].text.strip()
        or not nodes[0].text
    ):
        raise AdvanceReferenceError(code)
    return nodes[0].text


def _clock(day, clock):
    """Validate a conservative XML clock subset, without changing its text.

    Require two-digit HH:MM:SS, optional 1..6 fraction digits and optional
    Z/HH:MM offset bounded to XML's +/-14:00. No invented offset or midnight.
    Valid midnight is preserved. Unsupported precision/24:00:00 fail closed;
    these limits are adapter policy, not a claim about the entire XSD language.
    """
    if (
        re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day) is None
        or XML_CLOCK_PATTERN.fullmatch(clock) is None
    ):
        raise AdvanceReferenceError("reference_clock")
    offset = re.search(r"[+-]([0-9]{2}):([0-9]{2})$", clock)
    if offset and (
        int(offset[1]) > 14 or (int(offset[1]) == 14 and int(offset[2]) != 0)
    ):
        raise AdvanceReferenceError("reference_clock")
    try:
        parse_issue_datetime(day, clock)
        return
    except IssueTimestampError:
        pass
    raise AdvanceReferenceError("reference_clock")


def inspect_advance_reference(
    content, *, expected_invoice_id, expected_uuid, expected_seller_tax_id
):
    """Observe ONE type-386 Invoice against explicit expected source identity.

    UUID comparison permits case differences, but the returned UUID/date/time
    retain original XML text. Unqualified/nested/first-match fields cannot
    replace direct namespace-qualified root metadata. Exact-byte SHA256 is an
    evidence fingerprint, NOT ZATCA's transformed invoice/signature digest.
    """
    expected_id = _identity_text(expected_invoice_id, "expected_invoice_id")
    expected_uuid = _uuid(expected_uuid, "expected_uuid")
    expected_seller = _seller(expected_seller_tax_id, "expected_seller_tax_id")
    # Raise outside the handler so parser tracebacks cannot leak XML content.
    try:
        root = parse_diagnostic_xml(content)
    except ArtifactEvidenceError as error:
        parse_error = error.code
    else:
        parse_error = None
    if parse_error is not None:
        raise AdvanceReferenceError(parse_error)

    invoice_id = _identity_text(
        _one_text(root, "./cbc:ID", "reference_invoice_id"), "reference_invoice_id"
    )
    uuid = _one_text(root, "./cbc:UUID", "reference_uuid")
    normalized_uuid = _uuid(uuid, "reference_uuid")
    code = _one_text(root, "./cbc:InvoiceTypeCode", "reference_type")
    if code != "386":
        raise AdvanceReferenceError("reference_type")
    # Check each parent cardinality before selecting a VAT scheme; no arbitrary
    # supplier or tax-scheme first match, even if another branch looks valid.
    for xpath in (SUPPLIER_PATH, PARTY_PATH, VAT_PATH):
        if len(root.xpath(xpath, namespaces=NS)) != 1:
            raise AdvanceReferenceError("reference_seller_tax_id")
    if _one_text(root, VAT_PATH + "/cac:TaxScheme/cbc:ID", "reference_seller_tax_id") != "VAT":
        raise AdvanceReferenceError("reference_seller_tax_id")
    seller = _seller(
        _one_text(root, VAT_PATH + "/cbc:CompanyID", "reference_seller_tax_id"),
        "reference_seller_tax_id",
    )
    day = _one_text(root, "./cbc:IssueDate", "reference_issue_date")
    clock = _one_text(root, "./cbc:IssueTime", "reference_issue_time")
    _clock(day, clock)
    if invoice_id != expected_id:
        raise AdvanceReferenceError("reference_invoice_id_mismatch")
    if normalized_uuid != expected_uuid:
        raise AdvanceReferenceError("reference_uuid_mismatch")
    if seller != expected_seller:
        raise AdvanceReferenceError("reference_seller_tax_id_mismatch")
    return AdvanceReferenceEvidence(
        invoice_id, uuid, seller, day, clock,
        hashlib.sha256(content).hexdigest(), len(content),
    )
