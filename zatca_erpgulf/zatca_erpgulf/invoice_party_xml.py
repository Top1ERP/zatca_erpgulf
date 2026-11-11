"""Shared reference/party/payment assembly using existing Sales/POS builders.

The adapter owns invoice classification, identity allocation, issuer selection,
taxes, discounts and advance rows. This sequence only composes its existing
builders; it does not read Frappe, select credentials, persist or send anything.
"""

from dataclasses import dataclass, fields
from typing import Callable


PURPOSES = ("invoice", "debug", "compliance")
PAYMENT_BUILDERS = {
    "Sales Invoice": "delivery_and_payment_means",
    "POS Invoice": "delivery_and_paymentmeans",
}


@dataclass(frozen=True, repr=False)
class PartyXmlTools:
    """Bind one adapter's existing functions for one explicit preparation mode.

    Declared DocType chooses the legacy function spelling, not a credential
    owner or source record. Preserve imports/overrides at their current module
    paths; retain no namespace, document or issuer material in this binding.
    """

    purpose: str
    reference: Callable
    additional_reference: Callable
    company_data: Callable
    customer_data: Callable
    payment: Callable

    def __post_init__(self):
        if type(self.purpose) is not str or self.purpose not in PURPOSES:
            raise ValueError("party_xml_purpose")
        if not all(callable(getattr(self, item.name)) for item in fields(self) if item.name != "purpose"):
            raise TypeError("party_xml_tools")

    @classmethod
    def from_namespace(cls, namespace, *, doctype, purpose="invoice"):
        if type(purpose) is not str or purpose not in PURPOSES:
            raise ValueError("party_xml_purpose")
        if type(doctype) is not str or doctype not in PAYMENT_BUILDERS:
            raise ValueError("party_xml_doctype")
        reference = "doc_reference_compliance" if purpose == "compliance" else "doc_reference"
        payment = PAYMENT_BUILDERS[doctype] + ("_for_compliance" if purpose == "compliance" else "")
        return cls(purpose, namespace[reference], namespace["additional_reference"],
                   namespace["company_data"], namespace["customer_data"], namespace[payment])


def populate_invoice_parties(invoice, source_doc, invoice_number, company_abbr,
                             *, tools: PartyXmlTools, compliance_type=None):
    """Preserve builder order, returned roots and late payment-argument reads.

    Debug supplies debug=True only to its ordinary reference builder. Compliance
    uses its separate reference/payment functions with the explicit sample code.
    Ordinary references omit the Debug argument, retaining existing defaults.
    Read is_return only at the final payment step, after all party builders,
    just as the old sequences did. A failing step propagates unchanged.
    """
    if tools.purpose == "compliance":
        invoice = tools.reference(invoice, source_doc, invoice_number, compliance_type)
    elif tools.purpose == "debug":
        invoice = tools.reference(invoice, source_doc, invoice_number, debug=True)
    else:
        invoice = tools.reference(invoice, source_doc, invoice_number)
    invoice = tools.additional_reference(invoice, company_abbr, source_doc)
    invoice = tools.company_data(invoice, source_doc)
    invoice = tools.customer_data(invoice, source_doc)
    payment_value = compliance_type if tools.purpose == "compliance" else source_doc.is_return
    return tools.payment(invoice, source_doc, payment_value)
