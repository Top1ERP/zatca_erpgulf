"""Declared template VAT adapters and per-builder source checks.

The optional selector never opts legacy templates in implicitly. Draft
preflight uses row selection; XML builders additionally verify saved native
account/rate/amount observations. No data repair, persistence or HTTP occurs.
"""

from .issuing_reads import read_issuing_doc
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from types import SimpleNamespace
import frappe

from zatca_erpgulf.ksa_compliance.item_vat_selection import (
    MESSAGE, VatSelectionError, declared_account, select_declared_vat,
)
from zatca_erpgulf.ksa_compliance.declared_vat_scope import VatScopeError, reconcile_vat_accounts
from zatca_erpgulf.ksa_compliance.vat_math import vat_from_group
from zatca_erpgulf.ksa_compliance.invoice_currency import InvoiceCurrencyError, bind_invoice_currency
from zatca_erpgulf.ksa_compliance.item_template_mode import (
    ItemTemplateModeError, REVIEW as ITEM_TEMPLATE_REVIEW, item_template_mode,
)

SOURCE = "The declared VAT source does not match the saved invoice tax data. Recalculate and save the invoice before generating XML."
# Retained for integrations translating the earlier failure key.
CURRENCY = "The declared VAT source needs a confirmed company currency before foreign-currency Sales XML can be generated."
CURRENCY_REVIEW = "The invoice currency context could not be confirmed with its Company. Review the Company currency and any invoice currency override."


class DeclaredVatError(frappe.ValidationError):
    def __init__(self, code, message, details=""):
        self.code, self.template = code, message
        self.canonical = message + (" " + details if details else "")
        self.diagnostic_logged = False
        super().__init__(self.canonical)

    def __str__(self):
        return self.canonical


def fail_declared_vat(runtime, translate, code, message=MESSAGE, details=""):
    error = DeclaredVatError(code, message, details)
    runtime.log_error(title="ZATCA VAT source validation failed", message=f"{code}: {error}")
    error.diagnostic_logged = True
    runtime.throw(translate(message), exc=error)
    raise error


def resolve_invoice_template_mode(doc, *, runtime, translate):
    """Use the loaded invoice's rows; no master lookup, hint, repair or write.

    Metadata/preview creation may already have occurred at the caller. This is
    not a new UUID/ICV transaction or source-revision/permission guarantee.
    """
    try:
        getter = getattr(doc, "get", None)
        rows = getter("items") if callable(getter) else getattr(doc, "items", None)
        return item_template_mode(rows)
    except ItemTemplateModeError as error:
        fail_declared_vat(runtime, translate, error.code, ITEM_TEMPLATE_REVIEW)


def confirm_invoice_template_mode(doc, expected, *, runtime, translate, read_mode):
    """Detect observed mode drift across identity callbacks, without rollback.

    The original reader is passed explicitly so metadata integrations retain
    their current binding. Same-mode template/value changes are outside this
    scalar observation; no row revision or transaction snapshot is attested.
    """
    current = read_mode(doc, runtime=runtime, translate=translate)
    if current != expected:
        fail_declared_vat(runtime, translate, "metadata_item_template_changed", ITEM_TEMPLATE_REVIEW)
    return current


def declared_vat_row(template, *, runtime, translate, company=None):
    try:
        selection = select_declared_vat(template, company=company)
    except VatSelectionError as error:
        fail_declared_vat(runtime, translate, str(error))
    return selection.row if selection is not None else None


def item_vat_rows(template, *, runtime, translate, company=None):
    """Default callers keep their existing list; opt-in callers get the VAT row."""
    row = declared_vat_row(template, runtime=runtime, translate=translate, company=company)
    return [row] if row is not None else list(getattr(template, "taxes", []) or [])


def q2(value):
    try:
        value = Decimal(str(value))
        if value.is_finite():
            return value.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    except (ValueError, TypeError, InvalidOperation):
        pass
    raise VatSelectionError("declared_vat_invalid_amount")


@dataclass(frozen=True, repr=False)
class CurrencyRenderDocument:
    """Local rendering adapter, never an invoice or a signing/source owner.

    Only company_currency is supplied from a checked Company observation. All
    other reads delegate to the original document. This is not an immutable
    source snapshot; the original invoice and child rows are never modified.
    Settlement, ACL, signing and persistence continue to receive the original.
    """
    _source: object = field(repr=False)
    company_currency: str

    def get(self, key, default=None):
        if key == "company_currency":
            return self.company_currency
        return self._source.get(key, default)

    def __getattr__(self, key):
        return getattr(self._source, key)


class DeclaredVatContext:
    """One XML builder's checked source; not a tenant/credential snapshot.

    Legacy template reads keep their existing cache policy. Foreign Sales and
    explicit conflicting SAR helper declarations bind Company currency.
    Once an explicit selection is encountered, verify the complete invoice
    account scope. Unselected companions must have a single unambiguous row.
    """

    def __init__(self, doc, runtime, translate, *, require_sales_currency=True):
        self.doc, self.runtime, self.translate = doc, runtime, translate
        self.templates, self.checked = {}, False
        self.require_sales_currency = require_sales_currency
        self.currency_binding, self._currency_document = None, None

    def _bind_currency(self):
        if self.currency_binding is None:
            missing_company = getattr(self.runtime, "DoesNotExistError", KeyError)
            try:
                company = read_issuing_doc(self.runtime, "Company", self.doc.company)
            except (KeyError, missing_company):
                fail_declared_vat(self.runtime, self.translate,
                    "invoice_currency_company_missing", CURRENCY_REVIEW)
            try:
                binding = bind_invoice_currency(self.doc.currency, company.get("default_currency"),
                    invoice_override=self.doc.get("company_currency"))
            except InvoiceCurrencyError as error:
                fail_declared_vat(self.runtime, self.translate, str(error), CURRENCY_REVIEW)
            self.currency_binding = binding
            self._currency_document = CurrencyRenderDocument(self.doc, binding.accounting)
        return self._currency_document

    def document_for_amounts(self):
        """Bind foreign Sales and conflicting explicit SAR helper declarations.

        Partial public-helper inputs without Company retain their old fallback.
        Normal native invoices have Company. Resolve it once per builder before
        any line, so an unselected companion before a selected item is correct.
        A foreign invoice's explicit helper must agree with Company too.
        Ordinary SAR with an absent/valid helper retains its legacy path; VAT
        selection separately requires full Company/source verification.
        """
        if self._currency_document is not None:
            return self._currency_document
        if (self.require_sales_currency and getattr(self.doc, "company", None)
                and (self.doc.currency != "SAR"
                     or self.doc.get("company_currency") not in (None, "", "SAR"))):
            return self._bind_currency()
        return self.doc

    def get_template(self, name):
        if self.checked and name in self.templates:
            return self.templates[name]
        template = read_issuing_doc(self.runtime, "Item Tax Template", name)
        self.templates[name] = template
        return template

    def row(self, template):
        row = declared_vat_row(template, runtime=self.runtime, translate=self.translate,
                               company=self.doc.company if declared_account(template) else None)
        if row is not None and not self.checked:
            try:
                self._verify()
            except (VatSelectionError, VatScopeError) as error:
                fail_declared_vat(self.runtime, self.translate,
                    getattr(error, "code", str(error)), SOURCE, str(error))
            self.checked = True
        return row

    def _verify(self):
        doc = self.doc
        # Explicit VAT selection checks Company ownership of base amounts,
        # including conflicts hidden by an invoice-only helper attribute.
        self._bind_currency()
        if (not doc.get("custom_zatca_nominal_invoice") and q2(doc.get("discount_amount") or 0) != 0
                and not any(q2(item.get("distributed_discount_amount") or 0) != 0 for item in doc.items)):
            raise VatSelectionError("declared_vat_discount_not_allocated")
        sign = Decimal(-1 if doc.get("is_return") else 1)
        tax_by_account = {}
        for tax in doc.taxes or []:
            account = tax.get("account_head")
            if (not isinstance(account, str) or not account or account in tax_by_account
                    or tax.get("charge_type") != "On Net Total"
                    or tax.get("add_deduct_tax") not in (None, "", "Add")):
                raise VatSelectionError("declared_vat_invoice_roles")
            tax_by_account[account] = tax
        lines, groups = [], {}
        for item in doc.items:
            name = item.get("item_tax_template")
            if not name:
                raise VatSelectionError("declared_vat_mixed_item_sources")
            template = self.templates.get(name)
            if template is None:
                template = read_issuing_doc(self.runtime, "Item Tax Template", name)
                self.templates[name] = template
            if template.get("company") != doc.company:
                raise VatSelectionError("declared_vat_company_mismatch")
            selected = select_declared_vat(template, company=doc.company)
            rows = [selected.row] if selected is not None else template.taxes
            if len(rows or []) != 1:
                raise VatSelectionError("declared_vat_unresolved_companion_template")
            row = rows[0]
            rate = q2(row.tax_rate)
            if rate != Decimal(str(row.tax_rate)):
                raise VatSelectionError("declared_vat_rate_precision")
            category, reason = template.get("custom_zatca_tax_category"), template.get("custom_exemption_reason_code")
            if ((category == "Standard" and (rate <= 0 or reason))
                    or (category in ("Zero Rated", "Exempted", "Services outside scope of tax / Not subject to VAT")
                        and (rate != 0 or not isinstance(reason, str) or not reason))
                    or category not in ("Standard", "Zero Rated", "Exempted", "Services outside scope of tax / Not subject to VAT")):
                raise VatSelectionError("declared_vat_classification")
            net = q2(item.get("base_net_amount" if doc.currency == "SAR" else "net_amount")) * sign
            if net < 0:
                raise VatSelectionError("declared_vat_line_sign")
            lines.append(SimpleNamespace(item=item, account=row.tax_type, rate=rate,
                category=category, reason=reason, net=net))
            key = category, rate, reason
            groups[key] = groups.get(key, Decimal(0)) + net
        reconcile_vat_accounts(doc, lines, tax_by_account, sign, quantize=q2,
                               amount=lambda source, field: q2(source.get(field)))
        net = sum((line.net for line in lines), Decimal(0))
        vat = sum((vat_from_group(base, key[1]) for key, base in groups.items()), Decimal(0))
        if (net != q2(doc.net_total) * sign or vat != q2(doc.total_taxes_and_charges) * sign
                or net + vat != q2(doc.grand_total) * sign):
            raise VatSelectionError("declared_vat_header_reconciliation")


def verified_declared_templates(doc, *, runtime, translate, sales=True):
    """Allow the included-price guard's new scope only after source proof."""
    context = DeclaredVatContext(doc, runtime, translate, require_sales_currency=sales)
    templates = []
    for item in doc.items:
        if not item.get("item_tax_template"):
            return False
        templates.append(context.get_template(item.item_tax_template))
    if not any(declared_account(template) for template in templates):
        return False
    for template in templates:
        context.row(template)
    return context.checked
