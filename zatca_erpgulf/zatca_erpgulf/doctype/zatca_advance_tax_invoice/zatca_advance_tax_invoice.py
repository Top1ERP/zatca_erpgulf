from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import money_in_words


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
            self.letter_head = getattr(payment_entry, "letter_head", None) or self.letter_head
        if self.meta.has_field("tc_name") and not self.tc_name:
            self._set_default_terms_template(payment_entry.company)

        self.advance_amount = q2(getattr(payment_entry, "paid_amount", 0))
        self.taxable_amount = self.advance_amount
        self.tax_amount = q2(getattr(payment_entry, "total_taxes_and_charges", 0))
        self.total_amount = q2(getattr(payment_entry, "paid_amount_after_tax", 0)) or q2(self.taxable_amount + self.tax_amount)
        self.tax_rate = self._payment_tax_rate(payment_entry)

        if self.meta.has_field("base_taxable_amount"):
            self.base_taxable_amount = q2(getattr(payment_entry, "base_paid_amount", 0))
        if self.meta.has_field("base_tax_amount"):
            self.base_tax_amount = q2(getattr(payment_entry, "base_total_taxes_and_charges", 0))
        if self.meta.has_field("base_total_amount"):
            self.base_total_amount = q2(getattr(payment_entry, "base_paid_amount_after_tax", 0)) or q2(self.base_taxable_amount + self.base_tax_amount)

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
            frappe.throw(_(
                f"ZATCA Advance Tax Invoice amount validation failed. Expected Total Amount "
                f"{expected_total} = Taxable Amount {taxable_amount} + Tax Amount {tax_amount}, "
                f"but found {total_amount}."
            ))

        if self.meta.has_field("base_taxable_amount"):
            base_taxable_amount = q2(self.base_taxable_amount)
            base_tax_amount = q2(self.base_tax_amount)
            base_total_amount = q2(self.base_total_amount)
            expected_base_total = q2(base_taxable_amount + base_tax_amount)

            if base_total_amount != expected_base_total:
                frappe.throw(_(
                    f"ZATCA Advance Tax Invoice base amount validation failed. Expected Base Total Amount "
                    f"{expected_base_total} = Base Taxable Amount {base_taxable_amount} + Base Tax Amount "
                    f"{base_tax_amount}, but found {base_total_amount}."
                ))

    def _set_amount_in_words(self):
        if self.meta.has_field("in_words"):
            self.in_words = money_in_words(self.total_amount, self.currency)

        if self.meta.has_field("base_in_words"):
            base_currency = self.company_currency if self.meta.has_field("company_currency") else self.currency
            base_total = self.base_total_amount if self.meta.has_field("base_total_amount") else self.total_amount
            self.base_in_words = money_in_words(base_total, base_currency)

    def on_trash(self):
        if not self.payment_entry or not frappe.db.exists("Payment Entry", self.payment_entry):
            return

        values = {
            "custom_zatca_is_advance_payment": 0,
            "custom_zatca_advance_tax_invoice": "",
            "custom_zatca_advance_invoice_status": "Not Created",
            "custom_zatca_advance_invoice_uuid": "",
            "custom_zatca_advance_xml": "",
            "custom_zatca_advance_last_debug_at": None,
            "custom_zatca_advance_full_response": "",
        }

        payment_entry_meta = frappe.get_meta("Payment Entry")
        for fieldname, value in values.items():
            if payment_entry_meta.has_field(fieldname):
                frappe.db.set_value("Payment Entry", self.payment_entry, fieldname, value, update_modified=False)
