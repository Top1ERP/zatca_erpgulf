"""POS XML from recorded ERP nets, with one explicit VAT account.

This adapter never recalculates an ERP invoice or distributes its discount.
Only optional gross-unit-price presentation removes included VAT. The recorded
net fields remain authoritative. Unsupported tax roles and reconciliation gaps
fail before any financial node is appended. No site initialization, HTTP or
source write belongs here. Callers supply document/native-rate readers; the UI
boundary records one canonical diagnostic and presents its translated key.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import xml.etree.ElementTree as ET

import frappe

from zatca_erpgulf.ksa_compliance.vat_math import vat_from_group
from zatca_erpgulf.zatca_erpgulf import create_xml_final_part as lines
from zatca_erpgulf.zatca_erpgulf import xml_tax_data as totals


ZERO = Decimal("0.00")
CATEGORIES = {
    "Standard", "Zero Rated", "Exempted",
    "Services outside scope of tax / Not subject to VAT",
}
REVIEW = "POS XML requires review before generation: {0}"
UNSUPPORTED = "Use one explicit VAT account charged on net total; other tax roles require a separate review."
RECALCULATE = "Recorded POS totals do not match the final line nets and VAT groups. Review the invoice calculation and rounding settings."
MISSING = "Final POS amounts, quantities or VAT classification are missing or invalid. Recalculate and review the invoice."
SPECIAL = "This POS discount or nominal transaction needs a separate fiscal calculation review."


class PosFinancialError(frappe.ValidationError):
    """Keep canonical English diagnostics independent of translated UI text."""

    def __init__(self, code, message, details=""):
        self.code, self.template, self.details = code, message, details
        self.diagnostic_logged = False
        self.canonical = REVIEW.format(message) + (" " + details if details else "")
        super().__init__(self.canonical)

    def __str__(self):
        return self.canonical

    def display_message(self, translate):
        return translate(REVIEW).format(translate(self.template))


def _number(value):
    try:
        result = Decimal(str(value))
        if result.is_finite():
            return result
    except (InvalidOperation, ValueError, TypeError):
        pass
    raise PosFinancialError("invalid_source", MISSING)


def _amount(doc, field):
    return _quantized(doc.get(field))


def _quantized(value, *, price=False):
    try:
        number = _number(value)
        return lines._quantize_price_amount(number) if price else totals.q2(number)
    except InvalidOperation:
        raise PosFinancialError("invalid_source", MISSING) from None


def _flag(doc, field):
    return _number(doc.get(field) or 0) != 0


def _rounding_disabled(doc):
    """Read native controls without recalculation or a POS-profile override.

    POS may have no disable_rounded_total field: AccountsController then reads
    Global Defaults. A consolidated invoice's existing nonzero adjustment
    bypasses that disabled branch in both inspected controller versions.
    """
    if _flag(doc, "is_consolidated") and _number(doc.get("rounding_adjustment") or 0) != 0:
        return False
    native = getattr(doc, "is_rounded_total_disabled", None)
    if callable(native):
        return _number(native() or 0) != 0
    if doc.get("disable_rounded_total") is None:
        raise PosFinancialError("rounding_source", MISSING)
    return _flag(doc, "disable_rounded_total")


def _classification(source, rate):
    category = source.get("custom_zatca_tax_category")
    reason = source.get("custom_exemption_reason_code")
    if (category not in CATEGORIES or rate < 0
            or (category == "Standard" and rate <= 0)
            or (category != "Standard" and (rate != 0 or not reason))):
        raise PosFinancialError("classification", MISSING)
    return category, reason if category != "Standard" else None


@dataclass(frozen=True)
class PosLine:
    source: object
    net: Decimal
    price: Decimal
    rate: Decimal
    category: str
    reason: str | None
    template: object | None
    gross_price: Decimal | None


@dataclass(frozen=True)
class PosFinancials:
    source: object
    lines: tuple
    breakdown: tuple
    net: Decimal
    vat: Decimal
    accounting_vat: Decimal
    rounding: Decimal
    show_discount: bool


def prepare_pos_financials(doc, *, has_template, get_doc, read_rate):
    """Read source metadata once per call and validate a complete ordinary POS.

    Different VAT percentages on items are supported on the same VAT account.
    Multiple tax accounts are deliberately not interpreted as multiple VAT rates.
    Native v15/v16 detail readers select rates; neither JSON nor child-table
    amounts override recorded net fields. Copies/views never mutate ERP rows.
    """
    if (_flag(doc, "custom_zatca_nominal_invoice") or
            (doc.get("apply_discount_on") == "Grand Total"
             and _flag(doc, "is_cash_or_non_trade_discount")
             and _number(doc.get("discount_amount") or 0))):
        raise PosFinancialError("special_transaction", SPECIAL)
    if not doc.items or not doc.get("currency"):
        raise PosFinancialError("invalid_source", MISSING)
    if (_number(doc.get("discount_amount") or 0) != 0
            and not any(_number(item.get("distributed_discount_amount") or 0) != 0
                        for item in doc.items)):
        raise PosFinancialError("undistributed_discount", SPECIAL)
    if len(doc.taxes or []) != 1:
        raise PosFinancialError("tax_roles", UNSUPPORTED)
    tax = doc.taxes[0]
    if (tax.get("charge_type") != "On Net Total" or not tax.get("account_head")
            or tax.get("add_deduct_tax") not in (None, "", "Add")):
        raise PosFinancialError("tax_roles", UNSUPPORTED)
    company = get_doc("Company", doc.company)
    company_currency = doc.get("company_currency") or company.get("default_currency")
    if company_currency and company_currency != "SAR":
        raise PosFinancialError("accounting_currency", UNSUPPORTED)
    show_discount = _flag(company, "custom_submit_line_item_discount_to_zatca")
    category_source = None
    if not has_template:
        template_name = doc.get("taxes_and_charges")
        if not template_name and doc.get("pos_profile"):
            template_name = get_doc("POS Profile", doc.pos_profile).get("taxes_and_charges")
        template = get_doc("Sales Taxes and Charges Template", template_name) if template_name else None
        category_source = {
            "custom_zatca_tax_category": doc.get("custom_zatca_tax_category")
                or (template.get("custom_zatca_tax_category") if template else None),
            "custom_exemption_reason_code": doc.get("custom_exemption_reason_code")
                or (template.get("custom_exemption_reason_code") if template else None),
        }
    rows, groups, templates = [], {}, {}
    sign = Decimal("-1") if _flag(doc, "is_return") else Decimal("1")
    for item in doc.items:
        if bool(item.get("item_tax_template")) != bool(has_template):
            raise PosFinancialError("mixed_template_sources", MISSING)
        if has_template:
            name = item.item_tax_template
            if name not in templates:
                templates[name] = get_doc("Item Tax Template", name)
            template = templates[name]
            if (len(template.taxes or []) != 1
                    or template.taxes[0].get("tax_type") != tax.account_head):
                raise PosFinancialError("tax_roles", UNSUPPORTED)
            rate = _quantized(template.taxes[0].tax_rate)
            source = template
        else:
            template = None
            selected = read_rate(doc, item, default=None)
            rate = _quantized(tax.rate if selected is None else selected)
            source = category_source
        category, reason = _classification(source, rate)
        net_field = "base_net_amount" if doc.currency == "SAR" else "net_amount"
        signed_net = _amount(item, net_field)
        quantity = _number(item.qty)
        if quantity == 0 or signed_net * sign < 0 or quantity * sign < 0:
            raise PosFinancialError("invalid_source", MISSING)
        net = abs(signed_net)
        price = _quantized(net / abs(quantity), price=True)
        if _quantized(price * abs(quantity)) != net:
            raise PosFinancialError("unit_price_precision", MISSING)
        gross = None
        if show_discount:
            # Single On Net Total VAT is the only accepted inclusive-price
            # fraction here. This affects presentation, never line net/VAT.
            raw = next((item.get(field) for field in
                ("rate_with_margin", "price_list_rate", "rate")
                if item.get(field) is not None and _number(item.get(field)) != 0), 0)
            gross = abs(_number(raw))
            if _flag(tax, "included_in_print_rate"):
                gross /= 1 + rate / 100
            gross = _quantized(gross, price=True)
        rows.append(PosLine(item, net, price, rate, category, reason, template, gross))
        key = category, rate, reason
        if any(previous[:2] == key[:2] and previous[2] != reason for previous in groups):
            raise PosFinancialError("conflicting_exemptions", MISSING)
        if key not in groups:
            groups[key] = totals._new_tax_rate_bucket(category, rate, reason)
        groups[key]["taxable_amount"] += net
    for bucket in groups.values():
        bucket["taxable_amount"] = totals.q2(bucket["taxable_amount"])
        bucket["tax_amount"] = vat_from_group(bucket["taxable_amount"], bucket["tax_rate"])
    net = sum((row.net for row in rows), ZERO)
    vat = sum((row["tax_amount"] for row in groups.values()), ZERO)
    rounding_disabled = _rounding_disabled(doc)
    rounding = ZERO if rounding_disabled else _amount(doc, "rounding_adjustment") * sign
    accounting_vat = abs(_amount(doc, "base_total_taxes_and_charges"))
    if _amount(doc, "base_total_taxes_and_charges") * sign < 0:
        raise PosFinancialError("invalid_source", MISSING)
    expected = {"net_total": net, "total_taxes_and_charges": vat, "grand_total": net + vat}
    if not rounding_disabled:
        expected["rounded_total"] = net + vat + rounding
    if doc.currency == "SAR":
        expected.update(base_net_total=net, base_total_taxes_and_charges=vat)
    mismatches = [f"{field}: ERP={doc.get(field)}, XML={value}"
        for field, value in expected.items() if _amount(doc, field) * sign != value]
    if mismatches:
        raise PosFinancialError("reconciliation", RECALCULATE, "; ".join(mismatches))
    return PosFinancials(doc, tuple(rows), tuple(groups.values()), net, vat, accounting_vat,
                         rounding, show_discount)


def append_pos_totals(invoice, financials):
    """Emit group VAT and ERP-reconciled money without a second allowance."""
    doc = financials.source
    # The view supplies an absolute accounting amount for credit-note XML.
    view = _DocumentView(doc, base_total_taxes_and_charges=financials.accounting_vat)
    start = len(invoice)
    totals._append_tax_totals(invoice, doc.currency, financials.breakdown, view)
    # Preserve the historical POS order: accounting summary before detail.
    summary = invoice[-1]
    invoice.remove(summary)
    invoice.insert(start, summary)
    totals._build_legal_monetary_total(invoice, doc.currency, financials.net,
        financials.net, financials.vat, ZERO, payable_rounding_amount=financials.rounding)
    return invoice


class _DocumentView:
    """Read-through presentation overrides; never assign to the original doc."""

    def __init__(self, source, **values):
        self.source, self.values = source, values

    def get(self, key, default=None):
        return self.values[key] if key in self.values else self.source.get(key, default)

    def __getattr__(self, key):
        return self.values[key] if key in self.values else getattr(self.source, key)


def append_pos_lines(invoice, financials):
    """Share Sales line emission with precise final-net unit prices for POS."""
    doc = financials.source
    for row in financials.lines:
        view = _DocumentView(doc, custom_zatca_tax_category=row.category)
        node = lines._append_sales_invoice_line(invoice, view, row.source, row.net,
            row.price, lines._line_tax_amount_from_net(row.net, row.rate), row.rate,
            has_template=row.template is not None, item_tax_template=row.template)
        node.find("cac:Item").find("cbc:Name").text = f"{row.source.item_code}:{row.source.item_name}"
        if financials.show_discount:
            price = node.find("cac:Price")
            ET.SubElement(price, "cbc:BaseQuantity", unitCode=str(row.source.uom)).text = "1"
            if row.gross_price > row.price:
                allowance = ET.SubElement(price, "cac:AllowanceCharge")
                ET.SubElement(allowance, "cbc:ChargeIndicator").text = "false"
                for tag, value in (("cbc:Amount", row.gross_price - row.price),
                                   ("cbc:BaseAmount", row.gross_price)):
                    ET.SubElement(allowance, tag, currencyID=doc.currency).text = lines._format_price_amount(value)
    return invoice


def render_pos_financials(invoice, doc, *, has_template, get_doc, read_rate, section):
    """Compatibility entry: validate first, then append only the requested part."""
    financials = prepare_pos_financials(doc, has_template=has_template,
        get_doc=get_doc, read_rate=read_rate)
    if section == "totals":
        return append_pos_totals(invoice, financials)
    if section == "lines":
        return append_pos_lines(invoice, financials)
    raise ValueError("pos_financial_section")


def render_pos_section(invoice, doc, *, has_template, section, runtime, translate, read_rate):
    """Present one translated outcome; exception/log text stays in English."""
    try:
        return render_pos_financials(invoice, doc, has_template=has_template,
            section=section, get_doc=runtime.get_doc, read_rate=read_rate)
    except PosFinancialError as error:
        if not error.diagnostic_logged:
            runtime.log_error(title="POS XML validation failed", message=f"{error.code}: {error}")
            error.diagnostic_logged = True
        runtime.throw(error.display_message(translate), exc=error)
        raise  # A test/runtime adapter must not turn validation into success.
