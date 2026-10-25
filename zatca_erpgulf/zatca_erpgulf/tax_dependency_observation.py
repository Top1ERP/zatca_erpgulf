"""Explicit tax-template dependencies of a PARTIAL financial observation.

Pure capture of supplied authorized records; no loads, cache, ACL/SQL, rounding,
tax-source choice, credential lookup or authority transport. Both invoice and
item templates are captured, even if a current XML branch ignores one of them.
This partial digest is NOT the full PreparationContext source fingerprint.
"""

from dataclasses import dataclass, field
import hashlib
import json
from types import MappingProxyType

from .financial_source_observation import (
    InvoiceFinancialObservation, MAX_PAYLOAD_BYTES, TAX_FIELDS, _canonical, _capture_table, _name,
    _pin_financial, _present, _projection, _reference, _scalar,
    _validate_projection, _validate_scalar, _validate_table,
)

PROFILE = "invoice-tax-dependencies/v1"
MAX_TEMPLATES = 128
MAX_TAX_ROWS = 512
TEMPLATE_FIELDS = ("company", "disabled", "is_default", "tax_category",
    "custom_zatca_tax_category", "custom_exemption_reason_code", "custom_exemption_reason")
REQUIRED_TEMPLATE_FIELDS = ("company",)
TABLE_PROFILES = MappingProxyType({
    "Sales Taxes and Charges Template": ("Sales Taxes and Charges", TAX_FIELDS,
        ("charge_type", "rate", "tax_amount", "item_wise_tax_detail")),
    "Item Tax Template": ("Item Tax Template Detail", ("tax_type", "tax_rate"), ("tax_type", "tax_rate")),
})


class TaxDependencyError(ValueError):
    """Static internal errors; not a user message or financial validation claim."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _dependencies(financial):
    body = json.loads(financial._payload)
    header = dict(body["header"])
    company = _reference(header["company"])
    if company is None:
        raise ValueError
    references = set()
    invoice_template = _reference(header["taxes_and_charges"])
    if invoice_template is not None:
        references.add(("Sales Taxes and Charges Template", invoice_template))
    items = dict(body["tables"])["items"]["rows"]
    for _name_value, _index, values in items:
        item_template = _reference(dict(values)["item_tax_template"])
        if item_template is not None:
            references.add(("Item Tax Template", item_template))
    if len(references) > MAX_TEMPLATES:
        raise ValueError
    return company, tuple(sorted(references))


def _validate_records(financial, records):
    company, references = _dependencies(financial)
    if type(records) is not list or len(records) != len(references):
        raise ValueError
    identities, count = set(), 0
    for record, (doctype, name) in zip(records, references):
        if (type(record) is not dict or set(record) != {"doctype", "name", "modified", "header", "taxes"}
            or (record["doctype"], record["name"]) != (doctype, name)):
            raise ValueError
        _validate_scalar(record["modified"])
        if record["modified"][0] not in ("str", "datetime") or not record["modified"][1]:
            raise ValueError
        _validate_projection(record["header"], TEMPLATE_FIELDS, REQUIRED_TEMPLATE_FIELDS)
        if dict(record["header"])["company"] != ["str", company]:
            raise ValueError
        count += _validate_table(record["taxes"], *TABLE_PROFILES[doctype], identities)
        if count > MAX_TAX_ROWS:
            raise ValueError


@dataclass(frozen=True, repr=False)
class TaxDependencyObservation:
    """Protected invoice + exact referenced tax records, still PARTIAL/unverified."""

    financial: InvoiceFinancialObservation = field(repr=False)
    _payload: bytes = field(repr=False)
    sha256: str = field(init=False)

    def __post_init__(self):
        try:
            financial = _pin_financial(self.financial)
            # Same streamed canonical bound as financial observations; no new
            # JSON/value normalization or different representation policy.
            if type(self._payload) is not bytes or not 0 < len(self._payload) <= MAX_PAYLOAD_BYTES:
                raise ValueError
            body = json.loads(self._payload)
            if (type(body) is not dict or set(body) != {"profile", "financial_sha256", "records"}
                or body["profile"] != PROFILE or body["financial_sha256"] != financial.sha256
                or _canonical(body) != self._payload):
                raise ValueError
            _validate_records(financial, body["records"])
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise TaxDependencyError("tax_dependency_observation")
        object.__setattr__(self, "financial", financial)
        object.__setattr__(self, "sha256", hashlib.sha256(
            b"zatca-invoice-tax-dependencies/v1\0" + self._payload).hexdigest())

    def __repr__(self):
        return "<TaxDependencyObservation protected PARTIAL source, not verified>"

    def __reduce__(self):
        raise TypeError("tax_dependency_not_serializable")


def capture_tax_dependency_observation(financial, *, templates, child_metas):
    """Require the EXACT referenced record set; missing != fallback permission.

    templates: {(DocType, name): already-authorized saved template}.
    child_metas: {referenced template DocType: explicit taxes child metadata}.
    Both use server-selected dependencies, never browser JSON or implicit fetch.
    Exact Company binding is a conservative LOCAL capture policy, not a claim
    about legal tax rules. Current generator tax precedence remains unchanged.
    """
    try:
        financial = _pin_financial(financial)
        company, references = _dependencies(financial)
        if (type(templates) is not dict or type(child_metas) is not dict
            or set(templates) != set(references) or set(child_metas) != {dt for dt, _name_value in references}):
            raise ValueError
        records, identities, count = [], set(), 0
        for doctype, name in references:
            document = templates[doctype, name]
            if (document.doctype, document.name, document.meta.name) != (doctype, name, doctype):
                raise ValueError
            header = _projection(document, document.meta, TEMPLATE_FIELDS, REQUIRED_TEMPLATE_FIELDS)
            if dict(header)["company"] != ["str", company] or not _present(document.meta, "taxes"):
                raise ValueError
            modified = _scalar(document.get("modified"))
            if modified[0] not in ("str", "datetime") or not modified[1]:
                raise ValueError
            taxes = _capture_table(document, child_metas[doctype], "taxes",
                *TABLE_PROFILES[doctype], identities, max_rows=MAX_TAX_ROWS-count)
            count += len(taxes["rows"])
            records.append(dict(doctype=doctype, name=name, modified=modified, header=header, taxes=taxes))
        payload = _canonical(dict(profile=PROFILE, financial_sha256=financial.sha256, records=records))
        result = TaxDependencyObservation(financial, payload)
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        raise TaxDependencyError("tax_dependency_capture")
    return result
