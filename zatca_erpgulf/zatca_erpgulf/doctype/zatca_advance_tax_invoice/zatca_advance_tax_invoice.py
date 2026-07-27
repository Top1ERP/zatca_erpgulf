from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import cint, money_in_words


TWOPLACES = Decimal("0.01")

COUNTRY_OVERRIDES = {
    "saudi arabia": "SA", "kingdom of saudi arabia": "SA", "ksa": "SA", "السعودية": "SA", "المملكة العربية السعودية": "SA",
    "jordan": "JO", "hashemite kingdom of jordan": "JO", "الأردن": "JO", "الاردن": "JO",
    "oman": "OM", "sultanate of oman": "OM", "عمان": "OM", "سلطنة عمان": "OM",
    "united arab emirates": "AE", "uae": "AE", "الإمارات": "AE", "الامارات": "AE",
    "kuwait": "KW", "qatar": "QA", "bahrain": "BH", "egypt": "EG", "iraq": "IQ",
    "united states": "US", "usa": "US", "united kingdom": "GB", "uk": "GB",
}


def q2(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def safe_text(value) -> str:
    return str(value or "").strip()


def first_existing_value(doc, fieldnames: tuple[str, ...]) -> str:
    meta = getattr(doc, "meta", None)
    for fieldname in fieldnames:
        if not fieldname:
            continue
        if meta and not meta.has_field(fieldname):
            continue
        value = safe_text(getattr(doc, fieldname, None))
        if value:
            return value
    return ""


def country_code(country_name: str) -> str:
    country_name = safe_text(country_name)
    if not country_name:
        return "SA"

    normalized = country_name.lower()
    if normalized in COUNTRY_OVERRIDES:
        return COUNTRY_OVERRIDES[normalized]

    if len(country_name) == 2 and country_name.isalpha():
        return country_name.upper()

    if frappe.db.exists("Country", country_name):
        meta = frappe.get_meta("Country")
        for fieldname in ("code", "country_code", "iso_2", "iso_code", "alpha_2_code"):
            if meta.has_field(fieldname):
                value = safe_text(frappe.db.get_value("Country", country_name, fieldname))
                if value:
                    return value.upper()[:2]

    return country_name[:2].upper()


def company_abbr(company: str) -> str:
    abbr = frappe.db.get_value("Company", company, "abbr") or company
    abbr = re.sub(r"[^A-Za-z0-9]+", "", str(abbr).upper())
    return abbr[:10] or "CO"


def company_currency(company: str) -> str:
    return frappe.db.get_value("Company", company, "default_currency") or "SAR"


def get_company_default_letter_head(company: str) -> str:
    if not company or not frappe.db.exists("Company", company):
        return ""

    meta = frappe.get_meta("Company")

    for fieldname in ("default_letter_head", "letter_head"):
        if meta.has_field(fieldname):
            value = safe_text(frappe.db.get_value("Company", company, fieldname))
            if value:
                return value

    return ""


def payment_document_currency(payment_entry) -> str:
    return (
        safe_text(getattr(payment_entry, "paid_from_account_currency", None))
        or safe_text(getattr(payment_entry, "paid_to_account_currency", None))
        or company_currency(payment_entry.company)
    )


def payment_exchange_rate(payment_entry, currency: str, base_currency: str) -> Decimal:
    if currency == base_currency:
        return Decimal("1.00")
    if currency == safe_text(getattr(payment_entry, "paid_from_account_currency", None)):
        return q2(getattr(payment_entry, "source_exchange_rate", 1))
    if currency == safe_text(getattr(payment_entry, "paid_to_account_currency", None)):
        return q2(getattr(payment_entry, "target_exchange_rate", 1))
    return q2(getattr(payment_entry, "target_exchange_rate", 1) or 1)


def first_linked_address(link_doctype: str, link_name: str) -> str:
    return (
        frappe.db.get_value(
            "Dynamic Link",
            {"link_doctype": link_doctype, "link_name": link_name, "parenttype": "Address"},
            "parent",
        )
        or ""
    )


def address_values(address_name: str) -> dict:
    if not address_name or not frappe.db.exists("Address", address_name):
        return {}

    address = frappe.get_doc("Address", address_name)

    return {
        "address_line1": first_existing_value(address, (
            "address_line1", "custom_address_line1", "street_name", "custom_street_name"
        )),
        "address_line2": first_existing_value(address, (
            "address_line2", "custom_address_line2", "additional_street_name", "custom_additional_street_name",
            "custom_building_number", "building_number"
        )),
        "city": first_existing_value(address, ("city", "custom_city", "city_name", "custom_city_name")),
        "postal_code": first_existing_value(address, ("pincode", "postal_code", "custom_postal_code", "zip_code")),
        "country": first_existing_value(address, ("country", "custom_country")),
    }



def payment_tax_included_in_paid_amount(payment_entry) -> bool:
    """Return True when any Advance Taxes and Charges row is considered inside paid amount."""
    for row in getattr(payment_entry, "taxes", []) or []:
        if cint(getattr(row, "included_in_paid_amount", 0)):
            return True
    return False


def payment_entry_advance_amounts(payment_entry) -> dict:
    """Compute ZATCA advance invoice amounts from Payment Entry.

    Required policy for ZATCA advance payments:
    - VAT must be Considered In Paid Amount.
    - paid_amount is tax-inclusive.
    - taxable_amount = paid_amount - tax_amount.
    - total_amount = paid_amount.
    """
    tax_amount = q2(getattr(payment_entry, "total_taxes_and_charges", 0))
    base_tax_amount = q2(getattr(payment_entry, "base_total_taxes_and_charges", 0))

    tax_included = payment_tax_included_in_paid_amount(payment_entry)

    if tax_amount > Decimal("0.00") and not tax_included:
        frappe.throw(
            _(
                "For ZATCA Advance Tax Invoice, VAT must be marked as Considered In Paid Amount "
                "on the Payment Entry tax row."
            )
        )

    total_amount = q2(getattr(payment_entry, "paid_amount_after_tax", 0))
    if total_amount <= Decimal("0.00"):
        total_amount = q2(getattr(payment_entry, "paid_amount", 0))

    base_total_amount = q2(getattr(payment_entry, "base_paid_amount_after_tax", 0))
    if base_total_amount <= Decimal("0.00"):
        base_total_amount = q2(getattr(payment_entry, "base_paid_amount", 0))

    taxable_amount = q2(total_amount - tax_amount)
    base_taxable_amount = q2(base_total_amount - base_tax_amount)

    if total_amount <= Decimal("0.00"):
        frappe.throw(_("Advance payment total amount must be greater than zero."))

    if taxable_amount <= Decimal("0.00"):
        frappe.throw(
            _(
                "ZATCA Advance Tax Invoice taxable amount must be greater than zero. "
                "Paid Amount {0}, Tax Amount {1}."
            ).format(total_amount, tax_amount)
        )

    if q2(taxable_amount + tax_amount) != total_amount:
        frappe.throw(
            _(
                "ZATCA Advance Tax Invoice amount validation failed. "
                "Expected Total Amount {0} = Taxable Amount {1} + Tax Amount {2}, but found {3}."
            ).format(q2(taxable_amount + tax_amount), taxable_amount, tax_amount, total_amount)
        )

    if q2(base_taxable_amount + base_tax_amount) != base_total_amount:
        frappe.throw(
            _(
                "ZATCA Advance Tax Invoice base amount validation failed. "
                "Expected Base Total Amount {0} = Base Taxable Amount {1} + Base Tax Amount {2}, but found {3}."
            ).format(
                q2(base_taxable_amount + base_tax_amount),
                base_taxable_amount,
                base_tax_amount,
                base_total_amount,
            )
        )

    return {
        "taxable_amount": taxable_amount,
        "tax_amount": tax_amount,
        "total_amount": total_amount,
        "base_taxable_amount": base_taxable_amount,
        "base_tax_amount": base_tax_amount,
        "base_total_amount": base_total_amount,
        "tax_included_in_paid_amount": tax_included,
    }



def select_has_option(doc, fieldname: str, option: str) -> bool:
    df = doc.meta.get_field(fieldname)
    if not df:
        return False
    return option in (df.options or "").splitlines()


def set_select_if_allowed(doc, fieldname: str, value: str) -> None:
    if doc.meta.has_field(fieldname) and select_has_option(doc, fieldname, value):
        setattr(doc, fieldname, value)


def zadv_series_prefix_and_number(name: str):
    match = re.search(r"(\d+)$", str(name or ""))
    if not match:
        return "", 0
    return str(name)[: match.start(1)], int(match.group(1))


def company_phase2_advance_mode(company: str) -> bool:
    if not company or not frappe.db.exists("Company", company):
        return False

    company_doc = frappe.get_doc("Company", company)
    mode = safe_text(getattr(company_doc, "custom_zatca_advance_payment_submission_mode", "Local Only"))
    signing_enabled = int(getattr(company_doc, "custom_zatca_advance_signing_enabled", 0) or 0)
    api_enabled = int(getattr(company_doc, "custom_zatca_advance_api_submission_enabled", 0) or 0)

    return mode == "Submit to ZATCA" or signing_enabled or api_enabled


def active_sales_invoices_using_payment_entry(payment_entry: str) -> list[str]:
    if not payment_entry:
        return []

    parents = frappe.get_all(
        "Sales Invoice Advance",
        filters={
            "reference_type": "Payment Entry",
            "reference_name": payment_entry,
            "parenttype": "Sales Invoice",
        },
        pluck="parent",
    )

    result = []
    for name in parents:
        docstatus = frappe.db.get_value("Sales Invoice", name, "docstatus")
        if docstatus is not None and int(docstatus) != 2:
            result.append(name)

    return result


def later_zadv_in_same_company_exists(company: str, current_name: str) -> bool:
    prefix, number = zadv_series_prefix_and_number(current_name)
    if not prefix or not number:
        return False

    candidates = frappe.get_all(
        "ZATCA Advance Tax Invoice",
        filters=[
            ["ZATCA Advance Tax Invoice", "company", "=", company],
            ["ZATCA Advance Tax Invoice", "name", "like", prefix + "%"],
            ["ZATCA Advance Tax Invoice", "name", "!=", current_name],
        ],
        fields=["name"],
    )

    for row in candidates:
        _, other_number = zadv_series_prefix_and_number(row.name)
        if other_number > number:
            return True

    return False


def reset_zadv_series_to_highest_existing(deleted_name: str) -> None:
    prefix, _number = zadv_series_prefix_and_number(deleted_name)
    if not prefix:
        return

    existing = frappe.get_all(
        "ZATCA Advance Tax Invoice",
        filters=[
            ["ZATCA Advance Tax Invoice", "name", "like", prefix + "%"],
            ["ZATCA Advance Tax Invoice", "name", "!=", deleted_name],
        ],
        pluck="name",
    )

    max_number = 0
    for name in existing:
        _, n = zadv_series_prefix_and_number(name)
        if n > max_number:
            max_number = n

    if frappe.db.sql("select name from `tabSeries` where name = %s", prefix):
        frappe.db.sql(
            "update `tabSeries` set current = %s where name = %s",
            (max_number, prefix),
        )


def clear_payment_entry_advance_link(payment_entry: str) -> None:
    if not payment_entry or not frappe.db.exists("Payment Entry", payment_entry):
        return

    values = {
        "custom_zatca_is_advance_payment": 0,
        "custom_zatca_advance_tax_invoice": "",
        "custom_zatca_advance_invoice_status": "Not Created",
        "custom_zatca_advance_invoice_uuid": "",
        "custom_zatca_advance_qr_code": "",
        "custom_zatca_advance_xml": "",
        "custom_zatca_advance_last_debug_at": None,
        "custom_zatca_advance_full_response": "",
    }

    payment_entry_meta = frappe.get_meta("Payment Entry")
    for fieldname, value in values.items():
        if payment_entry_meta.has_field(fieldname):
            frappe.db.set_value("Payment Entry", payment_entry, fieldname, value, update_modified=False)


def assert_zadv_can_cancel_or_delete(doc, action: str) -> None:
    """Block cancel/delete if the advance invoice is fiscally unsafe to remove."""
    if company_phase2_advance_mode(doc.company) or safe_text(getattr(doc, "zatca_status", "")).upper() in {"REPORTED", "CLEARED"}:
        frappe.throw(
            _(
                "Cannot {0} ZATCA Advance Tax Invoice {1} because it is in Phase 2/API mode "
                "or has already been reported/cleared."
            ).format(action, doc.name)
        )

    sales_invoices = active_sales_invoices_using_payment_entry(doc.payment_entry)
    if sales_invoices:
        frappe.throw(
            _(
                "Cannot {0} ZATCA Advance Tax Invoice {1} because its Payment Entry is used "
                "in Sales Invoice(s): {2}."
            ).format(action, doc.name, ", ".join(sales_invoices))
        )

    if later_zadv_in_same_company_exists(doc.company, doc.name):
        frappe.throw(
            _(
                "Cannot {0} ZATCA Advance Tax Invoice {1} because a later advance tax invoice "
                "exists for the same company. Delete/cancel the latest invoice first."
            ).format(action, doc.name)
        )



def local_only_phase1_qr_mode(company: str) -> bool:
    if not company or not frappe.db.exists("Company", company):
        return True

    company_doc = frappe.get_doc("Company", company)
    mode = safe_text(getattr(company_doc, "custom_zatca_advance_payment_submission_mode", "Local Only"))
    signing_enabled = int(getattr(company_doc, "custom_zatca_advance_signing_enabled", 0) or 0)
    api_enabled = int(getattr(company_doc, "custom_zatca_advance_api_submission_enabled", 0) or 0)

    return mode != "Submit to ZATCA" and not signing_enabled and not api_enabled


def run_local_phase1_preflight_without_save(doc) -> None:
    """Run advance preflight during Submit without calling doc.save().

    Do not call advance_payment_debug._run_preflight_or_throw here because that helper
    persists the document and causes TimestampMismatchError inside Frappe submit.
    """
    from zatca_erpgulf.zatca_erpgulf.advance_payment_debug import (
        _preflight_issues,
        _set_preflight_result,
    )

    issues = _preflight_issues(doc)

    ignored_warnings = []
    blocking_issues = list(issues)

    if local_only_phase1_qr_mode(doc.company):
        # Phase-1 local QR should not be blocked only because the company postal code is missing.
        ignored_warnings = [
            issue for issue in blocking_issues
            if str(issue).strip() == "Company postal code is missing."
        ]
        blocking_issues = [
            issue for issue in blocking_issues
            if str(issue).strip() != "Company postal code is missing."
        ]

    _set_preflight_result(doc, blocking_issues)

    if ignored_warnings and not blocking_issues:
        if doc.meta.has_field("preflight_status"):
            doc.preflight_status = "Passed"
        if doc.meta.has_field("preflight_details"):
            doc.preflight_details = _(
                "Local Only / Phase 1 QR validation warning(s): {0}"
            ).format("; ".join(ignored_warnings))
        if doc.meta.has_field("zatca_status"):
            doc.zatca_status = "Preflight Passed"

    if blocking_issues:
        frappe.throw(
            _(
                "Cannot continue because ZATCA preflight validation failed: {0}"
            ).format("; ".join(blocking_issues)),
            title=_("ZATCA Preflight Failed"),
        )


class ZATCAAdvanceTaxInvoice(Document):
    def autoname(self):
        abbr = company_abbr(self.company)
        self.naming_series = f"ZADV-{abbr}-.YYYY.-.#####"
        self.name = make_autoname(self.naming_series)

    def validate(self):
        self.invoice_type_code = "386"

        if not self.status:
            self.status = "Draft"
        if self.meta.has_field("zatca_status") and not self.zatca_status:
            self.zatca_status = "Not Submitted"

        if self.meta.has_field("print_heading") and not self.print_heading:
            self.print_heading = "Advance Tax Invoice"

        if self.payment_entry:
            self._sync_from_payment_entry()

        self._validate_unique_payment_entry()
        self._validate_amount_equations()
        self._set_amount_in_words()

    def _sync_from_payment_entry(self):
        payment_entry = frappe.get_doc("Payment Entry", self.payment_entry)

        if payment_entry.docstatus != 1:
            frappe.throw(_("Payment Entry must be submitted before creating a ZATCA Advance Tax Invoice."))
        if payment_entry.payment_type != "Receive":
            frappe.throw(_("ZATCA Advance Tax Invoice is supported only for Receive Payment Entries."))
        if payment_entry.party_type != "Customer":
            frappe.throw(_("ZATCA Advance Tax Invoice requires Party Type to be Customer."))

        base_currency = company_currency(payment_entry.company)
        doc_currency = payment_document_currency(payment_entry)

        self.company = payment_entry.company
        self.customer = payment_entry.party
        self.posting_date = payment_entry.posting_date
        self.posting_time = getattr(payment_entry, "posting_time", None)
        self.currency = doc_currency

        if self.meta.has_field("company_currency"):
            self.company_currency = base_currency
        if self.meta.has_field("exchange_rate"):
            self.exchange_rate = payment_exchange_rate(payment_entry, doc_currency, base_currency)
        if self.meta.has_field("mode_of_payment"):
            self.mode_of_payment = payment_entry.mode_of_payment
        if self.meta.has_field("payment_means_code"):
            self.payment_means_code = "10"
        if self.meta.has_field("letter_head"):
            self.letter_head = (
                safe_text(getattr(payment_entry, "letter_head", None))
                or self.letter_head
                or get_company_default_letter_head(payment_entry.company)
            )

        if self.meta.has_field("print_heading") and not self.print_heading:
            self.print_heading = safe_text(getattr(payment_entry, "print_heading", None)) or "Advance Tax Invoice"

        if self.meta.has_field("tc_name") and not self.tc_name:
            self._set_default_terms_template(payment_entry.company)

        amounts = payment_entry_advance_amounts(payment_entry)

        self.advance_amount = amounts["taxable_amount"]
        self.taxable_amount = amounts["taxable_amount"]
        self.tax_amount = amounts["tax_amount"]
        self.total_amount = amounts["total_amount"]
        self.tax_rate = self._payment_tax_rate(payment_entry)

        if self.meta.has_field("base_taxable_amount"):
            self.base_taxable_amount = amounts["base_taxable_amount"]
        if self.meta.has_field("base_tax_amount"):
            self.base_tax_amount = amounts["base_tax_amount"]
        if self.meta.has_field("base_total_amount"):
            self.base_total_amount = amounts["base_total_amount"]

        if self.meta.has_field("tax_account"):
            self.tax_account = self._payment_tax_account(payment_entry)
        if self.meta.has_field("tax_description"):
            self.tax_description = self._payment_tax_description(payment_entry)

        self._sync_party_snapshot(payment_entry)

    def _set_default_terms_template(self, company):
        company_meta = frappe.get_meta("Company")
        if not company_meta.has_field("custom_zatca_advance_default_tc_name"):
            return

        tc_name = frappe.db.get_value("Company", company, "custom_zatca_advance_default_tc_name") or ""
        if tc_name:
            self.tc_name = tc_name
            self.terms = frappe.db.get_value("Terms and Conditions", tc_name, "terms") or ""

    def _payment_tax_rate(self, payment_entry):
        for row in getattr(payment_entry, "taxes", []) or []:
            rate = q2(getattr(row, "rate", 0))
            if rate > 0:
                return rate
        return Decimal("0.00")

    def _payment_tax_account(self, payment_entry):
        for row in getattr(payment_entry, "taxes", []) or []:
            account = safe_text(getattr(row, "account_head", None))
            if account:
                return account
        return ""

    def _payment_tax_description(self, payment_entry):
        for row in getattr(payment_entry, "taxes", []) or []:
            description = safe_text(getattr(row, "description", None))
            if description:
                return description
        return ""

    def _sync_party_snapshot(self, payment_entry):
        company_doc = frappe.get_doc("Company", payment_entry.company)
        customer_doc = frappe.get_doc("Customer", payment_entry.party)

        company_address_name = first_linked_address("Company", company_doc.name)
        customer_address_name = first_linked_address("Customer", customer_doc.name)

        company_address = address_values(company_address_name)
        customer_address = address_values(customer_address_name)

        company_country = company_address.get("country", "")
        customer_country = customer_address.get("country", "")

        values = {
            "company_name": first_existing_value(company_doc, ("company_name", "custom_company_name")),
            "company_name_arabic": first_existing_value(company_doc, (
                "custom_company_name_in_arabic", "company_name_in_arabic", "custom_company_arabic_name",
                "company_arabic_name", "custom_arabic_name"
            )),
            "company_vat_number": first_existing_value(company_doc, (
                "tax_id", "vat_number", "custom_vat_number", "custom_vat_registration_number"
            )),
            "company_address": company_address_name,
            "company_address_line1": company_address.get("address_line1", ""),
            "company_address_line2": company_address.get("address_line2", ""),
            "company_city": company_address.get("city", ""),
            "company_postal_code": company_address.get("postal_code", ""),
            "company_country": company_country,
            "company_country_code": country_code(company_country),

            "customer_name": first_existing_value(customer_doc, ("customer_name", "customer_name_en", "custom_customer_name_en")),
            "customer_name_arabic": first_existing_value(customer_doc, (
                "custom_customer_name_in_arabic", "customer_name_in_arabic", "customer_arabic_name",
                "custom_customer_arabic_name", "custom_arabic_name"
            )),
            "customer_vat_number": first_existing_value(customer_doc, (
                "tax_id", "vat_number", "custom_vat_number", "custom_vat_registration_number"
            )),
            "customer_b2c": getattr(customer_doc, "custom_b2c", 0) if customer_doc.meta.has_field("custom_b2c") else 0,
            "customer_buyer_id_type": first_existing_value(customer_doc, (
                "custom_buyer_id_type", "buyer_id_type", "custom_zatca_buyer_id_type"
            )),
            "customer_buyer_id": first_existing_value(customer_doc, (
                "custom_buyer_id", "buyer_id", "custom_zatca_buyer_id", "customer_primary_address"
            )),
            "customer_address": customer_address_name,
            "customer_address_line1": customer_address.get("address_line1", ""),
            "customer_address_line2": customer_address.get("address_line2", ""),
            "customer_city": customer_address.get("city", ""),
            "customer_postal_code": customer_address.get("postal_code", ""),
            "customer_country": customer_country,
            "customer_country_code": country_code(customer_country),

            "tax_category": "Standard",
            "tax_category_code": "S",
        }

        for fieldname, value in values.items():
            if self.meta.has_field(fieldname):
                setattr(self, fieldname, value)

    def _validate_unique_payment_entry(self):
        if not self.payment_entry:
            frappe.throw(_("Payment Entry is required for ZATCA Advance Tax Invoice."))

        existing = frappe.db.get_value(
            "ZATCA Advance Tax Invoice",
            {
                "payment_entry": self.payment_entry,
                "name": ["!=", self.name],
            },
            "name",
        )

        if existing:
            frappe.throw(
                _(
                    "Payment Entry {0} is already linked to ZATCA Advance Tax Invoice {1}."
                ).format(self.payment_entry, existing)
            )

    def _validate_amount_equations(self):
        taxable_amount = q2(self.taxable_amount)
        tax_amount = q2(self.tax_amount)
        total_amount = q2(self.total_amount)
        expected_total = q2(taxable_amount + tax_amount)

        if total_amount != expected_total:
            frappe.throw(
                _(
                    "ZATCA Advance Tax Invoice amount validation failed. "
                    "Expected Total Amount {0} = Taxable Amount {1} + Tax Amount {2}, but found {3}."
                ).format(expected_total, taxable_amount, tax_amount, total_amount)
            )

        if self.meta.has_field("base_taxable_amount"):
            base_taxable_amount = q2(self.base_taxable_amount)
            base_tax_amount = q2(self.base_tax_amount)
            base_total_amount = q2(self.base_total_amount)
            expected_base_total = q2(base_taxable_amount + base_tax_amount)

            if base_total_amount != expected_base_total:
                frappe.throw(
                    _(
                        "ZATCA Advance Tax Invoice base amount validation failed. "
                        "Expected Base Total Amount {0} = Base Taxable Amount {1} + Base Tax Amount {2}, but found {3}."
                    ).format(expected_base_total, base_taxable_amount, base_tax_amount, base_total_amount)
                )

    def _set_amount_in_words(self):
        if self.meta.has_field("in_words"):
            self.in_words = money_in_words(self.total_amount, self.currency)

        if self.meta.has_field("base_in_words"):
            base_currency = self.company_currency if self.meta.has_field("company_currency") else self.currency
            base_total = self.base_total_amount if self.meta.has_field("base_total_amount") else self.total_amount
            self.base_in_words = money_in_words(base_total, base_currency)


    def before_submit(self):
        """Standard ERPNext Submit should finalize local Phase-1 QR advance invoice."""
        self._sync_from_payment_entry()
        self._validate_unique_payment_entry()
        self._validate_amount_equations()

        from zatca_erpgulf.zatca_erpgulf.advance_payment_debug import _attach_phase1_advance_qr_code

        run_local_phase1_preflight_without_save(self)
        _attach_phase1_advance_qr_code(self)

        self.status = "Final"
        if self.meta.has_field("zatca_status"):
            self.zatca_status = "Phase 1 QR Created"

    def on_submit(self):
        from zatca_erpgulf.zatca_erpgulf.advance_payment_debug import _set_payment_entry_advance_fields

        _set_payment_entry_advance_fields(
            self.payment_entry,
            self,
            status=self.zatca_status or self.status,
            full_response="ZATCA Advance Tax Invoice submitted and Phase 1 QR generated.",
        )
    def before_cancel(self):
        assert_zadv_can_cancel_or_delete(self, "cancel")

    def on_cancel(self):
        set_select_if_allowed(self, "status", "Cancelled")
        set_select_if_allowed(self, "zatca_status", "Cancelled")
        clear_payment_entry_advance_link(self.payment_entry)



    def on_trash(self):
        assert_zadv_can_cancel_or_delete(self, "delete")

        payment_entry = self.payment_entry
        current_name = self.name

        clear_payment_entry_advance_link(payment_entry)
        reset_zadv_series_to_highest_existing(current_name)

def _zadv_user_can_force_cancel():
    """Allow force-cancel only for Administrator/System Manager."""
    if frappe.session.user == "Administrator":
        return True

    return "System Manager" in set(frappe.get_roles(frappe.session.user))


def _active_transaction_links_for_zadv(doc):
    """Return active business transactions that use this advance invoice.

    Payment Entry itself is the source document and is not considered a blocking
    downstream transaction. Final Sales Invoices using the advance are blocking.
    """
    links = set()

    # Direct detail table reference created by this app.
    if frappe.db.exists("DocType", "ZATCA Sales Invoice Advance Deduction"):
        rows = frappe.get_all(
            "ZATCA Sales Invoice Advance Deduction",
            filters={
                "zatca_advance_tax_invoice": doc.name,
                "parenttype": "Sales Invoice",
            },
            fields=["parent"],
        )

        for row in rows:
            if row.parent and frappe.db.exists("Sales Invoice", row.parent):
                si_docstatus = frappe.db.get_value("Sales Invoice", row.parent, "docstatus")
                if int(si_docstatus or 0) != 2:
                    links.add(f"Sales Invoice {row.parent}")

    # Standard ERPNext advance allocation through Payment Entry.
    payment_entry = doc.get("payment_entry")
    if payment_entry and frappe.db.exists("DocType", "Sales Invoice Advance"):
        rows = frappe.get_all(
            "Sales Invoice Advance",
            filters={
                "reference_type": "Payment Entry",
                "reference_name": payment_entry,
                "parenttype": "Sales Invoice",
            },
            fields=["parent"],
        )

        for row in rows:
            if row.parent and frappe.db.exists("Sales Invoice", row.parent):
                si_docstatus = frappe.db.get_value("Sales Invoice", row.parent, "docstatus")
                if int(si_docstatus or 0) != 2:
                    links.add(f"Sales Invoice {row.parent}")

    return sorted(links)


def _zadv_status_requires_system_manager_override(doc):
    """Return override warning reasons for reported/cleared/protected ZADV."""
    reasons = []

    zatca_status = (doc.get("zatca_status") or "").strip()
    normalized_zatca_status = zatca_status.upper().replace("-", " ")

    status = (doc.get("status") or "").strip()
    normalized_status = status.upper().replace("-", " ")

    protected_statuses = {
        "REPORTED",
        "CLEARED",
        "PHASE 2 REPORTED",
        "PHASE 2 CLEARED",
        "PHASE 2 CLEARANCE",
        "PHASE 2 REPORTING",
        "PHASE 1 QR CREATED",
        "PHASE 1 QR GENERATED",
    }

    if normalized_zatca_status in protected_statuses:
        reasons.append(frappe._("ZATCA Status is {0}.").format(zatca_status))

    if normalized_status in {"FINAL", "SUBMITTED"}:
        reasons.append(frappe._("Document status is {0}.").format(status))

    if company_phase2_advance_mode(doc.company):
        reasons.append(
            frappe._("The company is configured for Phase 2/API advance invoice handling.")
        )

    if later_zadv_in_same_company_exists(doc.company, doc.name):
        reasons.append(
            frappe._("A later ZATCA Advance Tax Invoice exists for this company.")
        )

    return reasons


def _zadv_force_cancel_warning(doc, reasons):
    reason_items = "".join(
        f"<li>{frappe.utils.escape_html(str(reason))}</li>"
        for reason in reasons
    )

    frappe.msgprint(
        title=frappe._("Force Cancel ZATCA Advance Tax Invoice"),
        indicator="orange",
        msg=frappe._(
            """
            <b>Warning:</b> This ZATCA Advance Tax Invoice is being cancelled/deleted by a System Manager override.
            <br><br>
            This is an internal system cancellation/deletion only. It does not reverse, cancel, amend, or notify ZATCA about any invoice already reported or cleared.
            <br><br>
            Reasons:
            <ul>{0}</ul>
            """
        ).format(reason_items),
    )


def assert_zadv_can_cancel_or_delete(doc, action="cancel"):
    """Validate cancel/delete for ZATCA Advance Tax Invoice.

    Rules:
    - Normal users cannot cancel/delete protected/reported/cleared advance invoices.
    - System Manager/Administrator can force-cancel or force-delete protected documents.
    - No one can cancel/delete if the advance invoice is linked to active downstream transactions.
    """
    action_text = str(action or "cancel").lower()

    is_cancel_action = (
        "cancel" in action_text
        or "إلغاء" in action_text
    )

    is_delete_action = (
        "delete" in action_text
        or "trash" in action_text
        or "حذف" in action_text
    )

    is_protected_action = is_cancel_action or is_delete_action
    system_manager_override_allowed = is_protected_action and _zadv_user_can_force_cancel()

    active_links = _active_transaction_links_for_zadv(doc)
    if active_links:
        frappe.throw(
            frappe._(
                "This ZATCA Advance Tax Invoice is linked to active transaction(s): {0}. "
                "Cancel or reverse those transaction(s) first."
            ).format(", ".join(active_links))
        )

    override_reasons = _zadv_status_requires_system_manager_override(doc)

    if override_reasons:
        if system_manager_override_allowed:
            _zadv_force_cancel_warning(doc, override_reasons)
            return

        frappe.throw(
            frappe._(
                "This ZATCA Advance Tax Invoice cannot be cancelled or deleted by this user. "
                "Only System Manager or Administrator can force-cancel or force-delete a reported/cleared/protected advance invoice."
            )
        )
