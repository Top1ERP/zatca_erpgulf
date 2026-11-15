"""Explicit currency bindings for fiscal rendering; no FX or framework access.

Company.default_currency owns base amounts. An optional invoice helper field
may confirm that currency, never override it. Conversion rate, POS Profile,
party-account currency and the user's display currency are not substitutes.
"""
from dataclasses import dataclass


class InvoiceCurrencyError(ValueError):
    """Stable English diagnostic codes, independent of user language."""


def _currency(value):
    return isinstance(value, str) and bool(value) and value == value.strip()


@dataclass(frozen=True)
class InvoiceCurrency:
    document: str
    accounting: str

    @property
    def uses_base_amounts(self):
        return self.document == self.accounting


def bind_invoice_currency(document, company_currency, *, invoice_override=None):
    """Resolve only the supported SAR accounting scope, with exact declarations.

    NULL/blank override means no override. Other malformed/foreign/conflicting
    observations are errors; do not normalize names, infer an FX rate or repair
    saved amounts. A bound currency is not source/ACL/transaction attestation.
    """
    if not _currency(document) or not _currency(company_currency):
        raise InvoiceCurrencyError("invoice_currency_missing_or_invalid")
    if invoice_override not in (None, ""):
        if not _currency(invoice_override) or invoice_override != company_currency:
            raise InvoiceCurrencyError("invoice_currency_override_conflict")
    if company_currency != "SAR":
        raise InvoiceCurrencyError("invoice_accounting_currency_unsupported")
    return InvoiceCurrency(document, company_currency)
