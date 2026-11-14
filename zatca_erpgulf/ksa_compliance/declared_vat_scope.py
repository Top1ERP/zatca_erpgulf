"""Shared account/native-rate reconciliation; callers own money readers and UI.

Extracted without changing the POS arithmetic, group keys or native bindings.
No framework, document writes, transport, implicit tax roles or FX repair.
"""
from decimal import Decimal
from .account_tax_rates import AccountTaxRateError, index_item_account_rates
from .vat_math import vat_from_group
ZERO = Decimal("0.00")

class VatScopeError(ValueError):
    def __init__(self, code, details=""):
        self.code, self.details = code, details
        super().__init__(code + (": " + details if details else ""))

def reconcile_vat_accounts(doc, prepared_lines, tax_by_account, sign, *, quantize, amount):
    """Validate the new multi-account scope before any financial XML output.

    Each template declares one VAT role. Every invoice tax account must be used;
    no unclassified freight/retention row is dropped, including zero rows.
    Other accounts must have native zero rates for that physical item. Ledger
    accounts are reconciled separately; XML still groups by category/rate only.
    Existing single-account behavior and legacy native readers stay unchanged.
    """
    if {line.account for line in prepared_lines} != set(tax_by_account):
        raise VatScopeError("tax_roles")
    try:
        native = index_item_account_rates(doc)
    except AccountTaxRateError as error:
        raise VatScopeError("account_source", str(error)) from None
    issues, groups = [], {}
    for line in prepared_lines:
        for account in tax_by_account:
            actual = quantize(native.rate(line.item, account))
            expected = line.rate if line.account == account else ZERO
            if actual != expected:
                issues.append(f"item {line.item.idx}, account {account}: native rate={actual}, template rate={expected}")
        key = line.account, line.category, line.rate, line.reason
        groups[key] = groups.get(key, ZERO) + line.net
    if issues:
        raise VatScopeError("account_rate_mismatch", "; ".join(issues))

    expected_tax = dict.fromkeys(tax_by_account, ZERO)
    for (account, _category, rate, _reason), net in groups.items():
        expected_tax[account] += vat_from_group(net, rate)
    observed_doc, observed_base = ZERO, ZERO
    for account, tax in tax_by_account.items():
        document_tax = amount(tax, "tax_amount_after_discount_amount") * sign
        base_tax = amount(tax, "base_tax_amount_after_discount_amount") * sign
        if document_tax != expected_tax[account]:
            issues.append(f"account {account}: ERP tax={document_tax}, XML tax={expected_tax[account]}")
        if base_tax < 0 or (doc.currency == "SAR" and base_tax != expected_tax[account]):
            issues.append(f"account {account}: ERP base tax={base_tax}, document tax={expected_tax[account]}")
        observed_doc += document_tax
        observed_base += base_tax
    if observed_doc != amount(doc, "total_taxes_and_charges") * sign:
        issues.append("sum of after-discount account taxes differs from recorded document VAT")
    # Native calculate_totals converts the whole VAT total independently.
    # In foreign currency its rounded base header can differ from the sum of
    # individually converted account rows. Do not replace or reject that
    # recorded header through a second rounding policy here.
    if (doc.currency == "SAR"
            and observed_base != amount(doc, "base_total_taxes_and_charges") * sign):
        issues.append("sum of after-discount base account taxes differs from recorded accounting VAT")
    if issues:
        raise VatScopeError("account_amount_mismatch", "; ".join(issues))
