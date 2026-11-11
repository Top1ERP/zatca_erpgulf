"""Compose existing document discount/tax builders without changing arithmetic.

Adapters retain tax-source discovery, nominal-field policy and item/advance
selection. Bind only their current builder functions; no Frappe, settings read,
numeric conversion, signing, file, transaction or authority operation lives here.
"""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, repr=False)
class DocumentTaxTools:
    """One template branch and optional nominal builders, bound per invocation."""

    discount: Callable
    tax: Callable
    nominal_discount: Callable | None = None
    nominal_tax: Callable | None = None

    def __post_init__(self):
        if not callable(self.discount) or not callable(self.tax):
            raise TypeError("document_tax_tools")
        nominal = self.nominal_discount, self.nominal_tax
        if not (all(value is None for value in nominal) or all(callable(value) for value in nominal)):
            raise TypeError("document_tax_tools")

    @classmethod
    def from_namespace(cls, namespace, *, has_template, include_nominal=False):
        """Preserve existing template-flag truthiness and imported overrides.

        POS does not bind or consume Sales-only nominal functions. The binding
        retains neither its namespace nor a document/credential value.
        """
        discount = "add_document_level_discount_with_tax_template" if has_template else "add_document_level_discount_with_tax"
        tax = "tax_data_with_template" if has_template else "tax_data"
        if include_nominal:
            nominal_tax = "tax_data_with_template_nominal" if has_template else "tax_data_nominal"
            return cls(namespace[discount], namespace[tax],
                       namespace["add_nominal_discount_tax"], namespace[nominal_tax])
        return cls(namespace[discount], namespace[tax])


def populate_document_tax(invoice, source_doc, *, tools: DocumentTaxTools, is_nominal=None):
    """Append allowance then tax totals, preserving returned roots and errors.

    Sales ordinary/Compliance pass a field reader evaluated before EACH step,
    matching their original two reads. Sales Debug captures its optional field
    once and passes a reader of that value, matching its original outer branch.
    POS passes no nominal reader. Item and advance builders remain with callers.
    """
    if is_nominal is not None and not callable(is_nominal):
        raise TypeError("document_tax_nominal_reader")
    for ordinary, nominal in ((tools.discount, tools.nominal_discount), (tools.tax, tools.nominal_tax)):
        builder = nominal if is_nominal is not None and is_nominal() else ordinary
        if builder is None:
            raise ValueError("document_tax_nominal_tools")
        invoice = builder(invoice, source_doc)
    return invoice
