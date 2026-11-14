"""VAT group arithmetic; source selection and invoice reconciliation stay upstream."""

from decimal import Decimal, ROUND_HALF_UP


def vat_from_group(taxable_amount, tax_rate):
    """Calculate VAT once from a complete category/rate group's taxable base.

    XML-standard sections 9.6/10 require final half-up rounding, rather than
    adding separately rounded line VAT amounts. Callers supply the complete net
    base, including applicable adjustments, and own category/account identity.
    Native Decimal values never pass through float; other numeric inputs use
    their decimal text. This does not select rates or validate fiscal sources.
    """
    base = (
        taxable_amount if isinstance(taxable_amount, Decimal)
        else Decimal(str(taxable_amount))
    )
    rate = tax_rate if isinstance(tax_rate, Decimal) else Decimal(str(tax_rate))
    return (base * rate / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP,
    )
