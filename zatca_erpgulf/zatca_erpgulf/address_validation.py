"""ZATCA Saudi National Address validation for Address documents."""
from __future__ import annotations

import json
import re
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint

from zatca_erpgulf.zatca_erpgulf.customer_validation import _company_names, _normalise_country
from zatca_erpgulf.ksa_compliance.field_compat import get_alias_value
from zatca_erpgulf.zatca_erpgulf.zatca_runtime import PHASE_1_VALUE, PHASE_2_VALUE, is_zatca_invoice_enabled, resolve_zatca_phase


COMPANY_ADDRESS_SETTING = "custom_enable_zatca_address_validation_for_company"
CUSTOMER_ADDRESS_SETTING = "custom_enable_zatca_address_validation_for_customers"


def _value(doc: Any, fieldname: str, default: Any = None) -> Any:
    getter = getattr(doc, "get", None)
    if callable(getter):
        return getter(fieldname, default)
    return getattr(doc, fieldname, default)


def _linked_names(doc, doctype: str) -> list[str]:
    names = []
    for row in _value(doc, "links", []) or []:
        if str(_value(row, "link_doctype", "") or "").strip() == doctype:
            name = str(_value(row, "link_name", "") or "").strip()
            if name:
                names.append(name)
    return sorted(set(names))


def _policy_level(company_name: str, setting: str) -> int:
    """Return 2 for enabled Phase-2, 1 for enabled Phase-1, otherwise 0."""
    try:
        company = frappe.get_cached_doc("Company", company_name)
        phase = str(resolve_zatca_phase(company) or "").strip().replace(" ", "-").casefold()
        if not is_zatca_invoice_enabled(company) or phase not in {"phase-1", "phase1", "phase-2", "phase2"}:
            return 0
        if not cint(_value(company, setting, 1) or 0):
            return 0
        return 2 if phase in {"phase-2", "phase2"} else 1
    except Exception:
        return 0


def _linked_customer_docs(doc):
    customers = []
    for customer in _linked_names(doc, "Customer"):
        try:
            customers.append(frappe.get_doc("Customer", customer))
        except Exception:
            continue
    return customers


def _customer_policy_level(doc) -> int:
    customer_docs = _linked_customer_docs(doc)
    # Standard ERPNext B2C customers are exempt from these B2B national-address rules.
    b2b_docs = [customer for customer in customer_docs if not cint(get_alias_value("customer_b2c", customer, 0) or 0)]
    if customer_docs and not b2b_docs:
        return 0
    companies = []
    for customer in b2b_docs:
        companies.extend(_company_names(customer))
    return max((_policy_level(name, CUSTOMER_ADDRESS_SETTING) for name in sorted(set(companies))), default=0)

def _validation_scope(doc) -> str:
    if _normalise_country(_value(doc, "country")) != "SA":
        return "none"
    company_links = _linked_names(doc, "Company")
    if cint(_value(doc, "is_your_company_address", 0) or 0) and any(_policy_level(name, COMPANY_ADDRESS_SETTING) for name in company_links):
        return "company-block"
    level = _customer_policy_level(doc)
    if level == 2:
        return "customer-block"
    if level == 1:
        return "customer-warning"
    return "none"


def _errors(doc) -> list[str]:
    errors: list[str] = []
    building = str(_value(doc, "custom_building_number", "") or "")
    postal = str(_value(doc, "pincode", "") or "")
    short = str(_value(doc, "address_line2", "") or "")
    english = str(_value(doc, "address_line1", "") or "")

    if not english.strip():
        errors.append(_("Address in English is required for a Saudi National Address."))
    if not re.fullmatch(r"\d{4}", building):
        errors.append(_("Building Number must contain exactly 4 digits and no spaces."))
    if not re.fullmatch(r"\d{5}", postal):
        errors.append(_("Postal Code must contain exactly 5 digits and no spaces."))
    if not re.fullmatch(r"[A-Za-z]{4}\d{4}", short):
        errors.append(_("Short Address must contain 8 characters: 4 letters followed by 4 digits, with no spaces."))
    elif short[-4:] != building:
        errors.append(_("The last 4 digits of Short Address must match Building Number."))
    return errors


def validate_zatca_address(doc, method=None) -> None:
    """Block invalid Saudi company/customer addresses when the relevant policy is enabled."""
    scope = _validation_scope(doc)
    if scope == "none":
        return
    errors = _errors(doc)
    if not errors:
        return
    message = "<br>".join(f"• {item}" for item in errors)
    if scope.startswith("customer-"):
        message = _("Customer classification: B2B. Country: Saudi Arabia.") + "<br>" + message
        message += '<br><br><small>' + _("You can disable this ZATCA address warning/blocking rule from the Company ZATCA Address Validation Settings.") + "</small>"
    if scope == "customer-warning":
        frappe.msgprint(message, title=_("ZATCA Address Validation"), indicator="orange", alert=True)
    else:
        frappe.throw(message, title=_("ZATCA Address Validation"))


@frappe.whitelist()
def get_zatca_address_validation_state(doc: dict | str | None = None) -> dict:
    if isinstance(doc, str):
        try:
            doc = json.loads(doc)
        except (TypeError, ValueError):
            doc = {}
    doc = frappe._dict(doc or {})
    scope = _validation_scope(doc)
    errors = _errors(doc) if scope != "none" else []
    return {"scope": "warning" if scope == "customer-warning" else ("block" if scope != "none" else "none"), "errors": errors}
