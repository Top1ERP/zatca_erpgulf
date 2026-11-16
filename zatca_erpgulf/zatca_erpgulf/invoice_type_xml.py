"""Compose existing type builders independently of scheduling and GPOS hints.

The caller retains permission, saved-source, identity, reference, financial and
signing ownership. Bind imported builders at invocation time, never globally.
This is not a new invoice-code implementation or authority acceptance check.
"""

from .compliance_types import normalize_submission_compliance_type


TYPE_REVIEW = "Select a valid invoice type for Debug XML: the original invoice or one of the six compliance sample types."


class InvoiceTypeSelectionError(ValueError):
    """Static English diagnostics; never retain the rejected request value."""
    template = TYPE_REVIEW

    def __init__(self):
        self.code = "debug_invoice_type_selector"
        super().__init__(TYPE_REVIEW)


def checked_debug_type(value):
    """Normalize Debug selectors before identity generation or XML builders."""
    try:
        return normalize_submission_compliance_type(value)
    except ValueError:
        raise InvoiceTypeSelectionError() from None


def populate_invoice_type(invoice, doc, customer, *, namespace, doctype,
                          compliance_type="0", standard_builder=None):
    """Use explicit sample first, then original Sales advance/B2C classification.

    Preserve short-circuit reads and each existing builder's actual XML rules.
    POS Debug supplies its original rejecting standard callback; ordinary POS
    retains its supported standard builder. Neither scheduling nor a saved GPOS
    identifier is evidence that a customer is B2C.
    """
    if doctype not in ("Sales Invoice", "POS Invoice"):
        raise ValueError("invoice_type_doctype")
    code = normalize_submission_compliance_type(compliance_type)
    if code != "0":
        return namespace["invoice_typecode_compliance"](invoice, code)
    if doctype == "Sales Invoice" and namespace["is_advance_payment_invoice"](doc):
        if not doc.is_return and not getattr(doc, "is_debit_note", 0):
            return namespace["invoice_typecode_advance_payment"](invoice, doc)
    if namespace["get_alias_value"]("customer_b2c", customer, 0) == 1:
        return namespace["invoice_typecode_simplified"](invoice, doc)
    standard = standard_builder if standard_builder is not None else namespace["invoice_typecode_standard"]
    return standard(invoice, doc)
