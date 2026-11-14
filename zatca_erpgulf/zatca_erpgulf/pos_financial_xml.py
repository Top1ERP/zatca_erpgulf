"""POS XML from recorded ERP nets and explicitly scoped VAT accounts.

This adapter never recalculates an ERP invoice or distributes its discount.
Only optional gross-unit-price presentation removes included VAT. The recorded
net fields remain authoritative. Unsupported tax roles and reconciliation gaps
fail before any financial node is appended. No site initialization, HTTP or
source write belongs here. Callers supply document/native-rate readers; the UI
boundary records one canonical diagnostic and presents its translated key.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
import xml.etree.ElementTree as ET

import frappe

from zatca_erpgulf.ksa_compliance.vat_math import vat_from_group
from zatca_erpgulf.ksa_compliance.account_tax_rates import (
    AccountTaxRateError, index_item_account_rates,
)
from zatca_erpgulf.zatca_erpgulf import create_xml_final_part as lines
from zatca_erpgulf.zatca_erpgulf import xml_tax_data as totals


ZERO = Decimal("0.00")
CATEGORIES = {
    "Standard", "Zero Rated", "Exempted",
    "Services outside scope of tax / Not subject to VAT",
}
REVIEW = "POS XML requires review before generation: {0}"
UNSUPPORTED = "The POS VAT account sources are ambiguous or use unsupported tax roles. Review the tax rows and item templates."
ACCOUNT_SOURCE = "The POS item tax sources do not match their declared VAT accounts. Review item templates and native tax details."
ACCOUNT_AMOUNTS = "Recorded POS VAT amounts do not match their declared accounts. Review the tax rows after discount."
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
            or (category != "Standard" and (rate != 0 or not reason or not isinstance(reason, str)))):
        raise PosFinancialError("classification", MISSING)
    return category, reason if category != "Standard" else None


@dataclass(frozen=True)
class PosItemValues:
    """Only immutable presentation values consumed by the shared line emitter."""

    name: object
    idx: object
    qty: object
    uom: object
    item_code: object
    item_name: object
    description: object

    def get(self, key, default=None):
        return getattr(self, key, default)


@dataclass(frozen=True)
class PosDocumentValues:
    """Rendering values only; never a saved document or authorization context."""

    currency: str
    custom_exemption_reason: object
    base_total_taxes_and_charges: Decimal

    def get(self, key, default=None):
        return getattr(self, key, default)


@dataclass(frozen=True)
class PosTemplateValues:
    custom_zatca_tax_category: str


def _presentation_value(doc, field):
    value = doc.get(field)
    if value is not None and not isinstance(value, (str, int, float, Decimal)):
        raise PosFinancialError("invalid_source", MISSING, f"Invalid presentation field: {field}")
    return value


@dataclass(frozen=True)
class PosLine:
    item: PosItemValues
    net: Decimal
    price: Decimal
    rate: Decimal
    category: str
    reason: str | None
    template: object | None
    account: str
    gross_price: Decimal | None


@dataclass(frozen=True)
class PosFinancials:
    document: PosDocumentValues
    lines: tuple
    breakdown: tuple
    net: Decimal
    vat: Decimal
    accounting_vat: Decimal
    rounding: Decimal
    show_discount: bool


def prepare_pos_financials(doc, *, has_template, get_doc, read_rate):
    """Read source metadata once per call and validate a complete ordinary POS.

    Item templates may declare one VAT account per item across several invoice
    accounts. Native per-account rates and after-discount amounts must agree.
    Other multi-account sources remain ambiguous and are not summed as VAT.
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
    currency = _presentation_value(doc, "currency")
    if not isinstance(currency, str):
        raise PosFinancialError("invalid_source", MISSING)
    if (_number(doc.get("discount_amount") or 0) != 0
            and not any(_number(item.get("distributed_discount_amount") or 0) != 0
                        for item in doc.items)):
        raise PosFinancialError("undistributed_discount", SPECIAL)
    taxes = doc.taxes or []
    if not taxes or (len(taxes) > 1 and not has_template):
        raise PosFinancialError("tax_roles", UNSUPPORTED)
    tax_by_account = {}
    for tax in taxes:
        account = tax.get("account_head")
        if (tax.get("charge_type") != "On Net Total" or not isinstance(account, str)
                or not account or account in tax_by_account
                or tax.get("add_deduct_tax") not in (None, "", "Add")):
            raise PosFinancialError("tax_roles", UNSUPPORTED)
        tax_by_account[account] = tax
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
                    or not isinstance(template.taxes[0].get("tax_type"), str)
                    or template.taxes[0].get("tax_type") not in tax_by_account):
                raise PosFinancialError("tax_roles", UNSUPPORTED)
            tax = tax_by_account[template.taxes[0].tax_type]
            rate = _quantized(template.taxes[0].tax_rate)
            source = template
        else:
            template = None
            tax = taxes[0]
            selected = read_rate(doc, item, default=None)
            rate = _quantized(tax.rate if selected is None else selected)
            source = category_source
        category, reason = _classification(source, rate)
        net_field = "base_net_amount" if currency == "SAR" else "net_amount"
        signed_net = _amount(item, net_field)
        presentation = PosItemValues(*(_presentation_value(item, field) for field in
            ("name", "idx", "qty", "uom", "item_code", "item_name", "description")))
        quantity = _number(presentation.qty)
        if quantity == 0 or signed_net * sign < 0 or quantity * sign < 0:
            raise PosFinancialError("invalid_source", MISSING)
        net = abs(signed_net)
        price = _quantized(net / abs(quantity), price=True)
        if _quantized(price * abs(quantity)) != net:
            raise PosFinancialError("unit_price_precision", MISSING)
        gross = None
        if show_discount:
            # One applicable On Net Total VAT account per item is enforced
            # before emission. This affects presentation, never line net/VAT.
            raw = next((item.get(field) for field in
                ("rate_with_margin", "price_list_rate", "rate")
                if item.get(field) is not None and _number(item.get(field)) != 0), 0)
            gross = abs(_number(raw))
            if _flag(tax, "included_in_print_rate"):
                gross /= 1 + rate / 100
            gross = _quantized(gross, price=True)
        template_values = PosTemplateValues(category) if template is not None else None
        rows.append(PosLine(presentation, net, price, rate, category, reason, template_values,
                            tax.account_head, gross))
        key = category, rate, reason
        if any(previous[:2] == key[:2] and previous[2] != reason for previous in groups):
            raise PosFinancialError("conflicting_exemptions", MISSING)
        if key not in groups:
            groups[key] = totals._new_tax_rate_bucket(category, rate, reason)
        groups[key]["taxable_amount"] += net
    for bucket in groups.values():
        bucket["taxable_amount"] = totals.q2(bucket["taxable_amount"])
        bucket["tax_amount"] = vat_from_group(bucket["taxable_amount"], bucket["tax_rate"])
    if len(taxes) > 1:
        _reconcile_vat_accounts(doc, rows, tax_by_account, sign)
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
    if currency == "SAR":
        expected.update(base_net_total=net, base_total_taxes_and_charges=vat)
    mismatches = [f"{field}: ERP={doc.get(field)}, XML={value}"
        for field, value in expected.items() if _amount(doc, field) * sign != value]
    if mismatches:
        raise PosFinancialError("reconciliation", RECALCULATE, "; ".join(mismatches))
    document_values = PosDocumentValues(currency,
        _presentation_value(doc, "custom_exemption_reason"), accounting_vat)
    breakdown = tuple(MappingProxyType(dict(bucket)) for bucket in groups.values())
    return PosFinancials(document_values, tuple(rows), breakdown, net, vat, accounting_vat,
                         rounding, show_discount)


def _reconcile_vat_accounts(doc, prepared_lines, tax_by_account, sign):
    """Validate the new multi-account scope before any financial XML output.

    Each template declares one VAT role. Every invoice tax account must be used;
    no unclassified freight/retention row is dropped, including zero rows.
    Other accounts must have native zero rates for that physical item. Ledger
    accounts are reconciled separately; XML still groups by category/rate only.
    Existing single-account behavior and legacy native readers stay unchanged.
    """
    if {line.account for line in prepared_lines} != set(tax_by_account):
        raise PosFinancialError("tax_roles", UNSUPPORTED)
    try:
        native = index_item_account_rates(doc)
    except AccountTaxRateError as error:
        raise PosFinancialError("account_source", ACCOUNT_SOURCE, str(error)) from None
    issues, groups = [], {}
    for line in prepared_lines:
        for account in tax_by_account:
            actual = _quantized(native.rate(line.item, account))
            expected = line.rate if line.account == account else ZERO
            if actual != expected:
                issues.append(f"item {line.item.idx}, account {account}: native rate={actual}, template rate={expected}")
        key = line.account, line.category, line.rate, line.reason
        groups[key] = groups.get(key, ZERO) + line.net
    if issues:
        raise PosFinancialError("account_rate_mismatch", ACCOUNT_SOURCE, "; ".join(issues))

    expected_tax = dict.fromkeys(tax_by_account, ZERO)
    for (account, _category, rate, _reason), net in groups.items():
        expected_tax[account] += vat_from_group(net, rate)
    observed_doc, observed_base = ZERO, ZERO
    for account, tax in tax_by_account.items():
        document_tax = _amount(tax, "tax_amount_after_discount_amount") * sign
        base_tax = _amount(tax, "base_tax_amount_after_discount_amount") * sign
        if document_tax != expected_tax[account]:
            issues.append(f"account {account}: ERP tax={document_tax}, XML tax={expected_tax[account]}")
        if base_tax < 0 or (doc.currency == "SAR" and base_tax != expected_tax[account]):
            issues.append(f"account {account}: ERP base tax={base_tax}, document tax={expected_tax[account]}")
        observed_doc += document_tax
        observed_base += base_tax
    if observed_doc != _amount(doc, "total_taxes_and_charges") * sign:
        issues.append("sum of after-discount account taxes differs from recorded document VAT")
    # Native calculate_totals converts the whole VAT total independently.
    # In foreign currency its rounded base header can differ from the sum of
    # individually converted account rows. Do not replace or reject that
    # recorded header through a second rounding policy here.
    if (doc.currency == "SAR"
            and observed_base != _amount(doc, "base_total_taxes_and_charges") * sign):
        issues.append("sum of after-discount base account taxes differs from recorded accounting VAT")
    if issues:
        raise PosFinancialError("account_amount_mismatch", ACCOUNT_AMOUNTS, "; ".join(issues))


def append_pos_totals(invoice, financials):
    """Emit group VAT and ERP-reconciled money without a second allowance."""
    doc = financials.document
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
    doc = financials.document
    for row in financials.lines:
        view = _DocumentView(doc, custom_zatca_tax_category=row.category)
        node = lines._append_sales_invoice_line(invoice, view, row.item, row.net,
            row.price, lines._line_tax_amount_from_net(row.net, row.rate), row.rate,
            has_template=row.template is not None, item_tax_template=row.template)
        node.find("cac:Item").find("cbc:Name").text = f"{row.item.item_code}:{row.item.item_name}"
        if financials.show_discount:
            price = node.find("cac:Price")
            ET.SubElement(price, "cbc:BaseQuantity", unitCode=str(row.item.uom)).text = "1"
            if row.gross_price > row.price:
                allowance = ET.SubElement(price, "cac:AllowanceCharge")
                ET.SubElement(allowance, "cbc:ChargeIndicator").text = "false"
                for tag, value in (("cbc:Amount", row.gross_price - row.price),
                                   ("cbc:BaseAmount", row.gross_price)):
                    ET.SubElement(allowance, tag, currencyID=doc.currency).text = lines._format_price_amount(value)
    return invoice


def render_pos_financials(invoice, doc, *, has_template, get_doc, read_rate, section):
    """Compatibility entry: validate first, then append only the requested part."""
    if section not in ("totals", "lines", "complete"):
        raise ValueError("pos_financial_section")
    financials = prepare_pos_financials(doc, has_template=has_template,
        get_doc=get_doc, read_rate=read_rate)
    if section == "totals":
        return append_pos_totals(invoice, financials)
    if section == "lines":
        return append_pos_lines(invoice, financials)
    # Build both parts from one immutable projection. If emission fails, keep
    # the caller's root intact rather than leaving a partial financial section.
    staging = ET.Element("POSFinancials")
    append_pos_totals(staging, financials)
    append_pos_lines(staging, financials)
    invoice.extend(list(staging))
    return invoice


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
