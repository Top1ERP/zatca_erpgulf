"""Customer-only ZATCA buyer identification validation.

Customer is shared between companies, so the effective policy is the strictest
ZATCA policy among the customer's Party Account companies.  This module does
not validate Sales Invoices or XML; those paths have their own rules.
"""

from __future__ import annotations

import re
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint

from zatca_erpgulf.ksa_compliance.field_compat import get_alias_value
from zatca_erpgulf.zatca_erpgulf.zatca_runtime import (
    PHASE_1_VALUE,
    PHASE_2_VALUE,
    is_zatca_invoice_enabled,
    resolve_zatca_phase,
)


CUSTOMER_VALIDATION_FIELD = "custom_enable_zatca_customer_validation"
REQUIRE_ON_SAVE_FIELD = "custom_require_zatca_buyer_id_on_customer_save"
VALIDATE_FORMAT_FIELD = "custom_validate_zatca_buyer_id_format"
TAX_ID_FALLBACK_FIELD = "custom_allow_zatca_tax_id_fallback"


def _value(doc: Any, fieldname: str, default: Any = None) -> Any:
    if not doc:
        return default
    getter = getattr(doc, "get", None)
    if callable(getter):
        return getter(fieldname, default)
    return getattr(doc, fieldname, default)


def _normalise_country(value: Any) -> str:
    value = str(value or "").strip().casefold()
    if value in {"sa", "s.a.", "saudi arabia", "kingdom of saudi arabia"}:
        return "SA"
    return value.upper()


def _company_policy(company_name: str) -> dict[str, Any]:
    try:
        company = frappe.get_cached_doc("Company", company_name)
    except Exception:
        return {"rank": 0, "enabled": False, "phase": "", "require_on_save": False, "validate_format": False, "tax_id_fallback": False}

    if not is_zatca_invoice_enabled(company):
        return {"rank": 0, "enabled": False, "phase": "", "require_on_save": False, "validate_format": False, "tax_id_fallback": False}

    phase = str(resolve_zatca_phase(company) or "").strip().replace(" ", "-")
    if phase.casefold() in {"phase-2", "phase2"}:
        phase, rank = PHASE_2_VALUE, 2
    elif phase.casefold() in {"phase-1", "phase1"}:
        phase, rank = PHASE_1_VALUE, 1
    else:
        return {"rank": 0, "enabled": False, "phase": "", "require_on_save": False, "validate_format": False, "tax_id_fallback": False}

    return {
        "rank": rank,
        "enabled": bool(cint(_value(company, CUSTOMER_VALIDATION_FIELD, 1) or 0)),
        "phase": phase,
        "require_on_save": bool(cint(_value(company, REQUIRE_ON_SAVE_FIELD, 0) or 0)),
        "validate_format": bool(cint(_value(company, VALIDATE_FORMAT_FIELD, 1) or 0)),
        "tax_id_fallback": bool(cint(_value(company, TAX_ID_FALLBACK_FIELD, 1) or 0)),
    }


def _company_names(customer) -> list[str]:
    names: list[str] = []
    try:
        if frappe.db.exists("DocType", "Party Account"):
            names = [
                row.company
                for row in frappe.get_all(
                    "Party Account",
                    filters={"parent": customer.name, "parenttype": "Customer"},
                    fields=["company"],
                )
                if row.company
            ]
    except Exception:
        names = []

    if names:
        return sorted(set(names))

    # A Customer is shared and may have no Party Account rows yet.  In that
    # case evaluate all companies; this preserves the user's strictest-policy
    # rule without inventing a company context on the Customer form.
    try:
        return [row.name for row in frappe.get_all("Company", fields=["name"])]
    except Exception:
        return []


def get_customer_validation_policy(customer=None, custom_b2c=0, customer_primary_address=None, territory=None) -> dict[str, Any]:
    """Return the strictest effective policy for a Customer form."""
    if customer:
        try:
            customer_doc = frappe.get_doc("Customer", customer)
        except Exception:
            customer_doc = frappe._dict({"name": customer})
    else:
        customer_doc = frappe._dict({"name": "__unsaved__"})

    policies = [_company_policy(name) for name in _company_names(customer_doc)]
    policy = max(policies, key=lambda item: item.get("rank", 0), default={})
    policy = {
        "enabled": bool(policy.get("enabled")),
        "phase": policy.get("phase", ""),
        "require_on_save": bool(policy.get("require_on_save")),
        "validate_format": bool(policy.get("validate_format")),
        "tax_id_fallback": bool(policy.get("tax_id_fallback")),
    }
    return policy


def _customer_country(customer) -> str:
    address_name = _value(customer, "customer_primary_address")
    if address_name:
        try:
            country = frappe.db.get_value("Address", address_name, "country")
            if country:
                return _normalise_country(country)
        except Exception:
            pass
    return _normalise_country(_value(customer, "territory"))


def _buyer_errors(customer, policy: dict[str, Any]) -> tuple[list[str], list[str]]:
    if not policy.get("enabled") or _customer_country(customer) != "SA" or cint(get_alias_value("customer_b2c", customer, 0) or 0):
        return [], []

    raw_buyer_id = str(get_alias_value("customer_buyer_id", customer, "") or "")
    raw_tax_id = str(_value(customer, "tax_id", "") or "")
    buyer_id = raw_buyer_id.strip()
    tax_id = raw_tax_id.strip()
    buyer_type = str(get_alias_value("customer_buyer_id_type", customer, "") or "").strip().upper()
    errors: list[str] = []
    warnings: list[str] = []
    def add_issue(message: str) -> None:
        errors.append(message)


    if any(char.isspace() for char in raw_buyer_id):
        add_issue(_("Buyer ID must not contain spaces."))
    if any(char.isspace() for char in raw_tax_id):
        add_issue(_("Tax ID must not contain spaces."))
    if not tax_id:
        warnings.append(_("Tax ID is empty for this Saudi B2B customer. Provide a 15-digit Tax ID when available."))
    elif policy.get("validate_format") and not re.fullmatch(r"3\d{13}3", tax_id):
        add_issue(_("Tax ID for a Saudi customer must contain 15 digits, start with 3, and end with 3."))

    if not buyer_id and policy.get("tax_id_fallback"):
        if tax_id:
            warnings.append(_("Buyer ID is empty; Tax ID fallback is being used for this Saudi B2B customer."))
            return errors, warnings

    if not buyer_id:
        message = _(
            "Buyer ID is required for a Saudi B2B customer before ZATCA customer validation can be completed."
        )
        (errors if policy.get("require_on_save") else warnings).append(message)
        return errors, warnings

    if not policy.get("validate_format"):
        return errors, warnings

    rules = {
        "TIN": (r"3\d{9}$", "10 digits starting with 3"),
        "CRN": (r"\d{10}$", "10 digits"),
        "MOM": (r"\d{10}$", "10 digits"),
        "MLS": (r"\d{10}$", "10 digits"),
        "700": (r"\d{10}$", "10 digits"),
        "SAG": (r"\d{10}$", "10 digits"),
        "NAT": (r"\d{10}$", "10 digits"),
        "IQA": (r"\d{10}$", "10 digits"),
        "GCC": (r"\d{15}$", "15 digits"),
        "PAS": (r"[A-Za-z0-9]{9,12}$", "9 to 12 letters or digits"),
        "OTH": (r".{1,60}$", "1 to 60 characters"),
    }
    if not buyer_type or buyer_type not in rules:
        add_issue(_("Buyer ID Type is required and must be a supported ZATCA identification scheme."))
    elif not re.fullmatch(rules[buyer_type][0], buyer_id):
        add_issue(_("Buyer ID for {0} must contain {1}.").format(buyer_type, rules[buyer_type][1]))
    if buyer_type == "TIN" and tax_id and not tax_id.startswith(buyer_id):
        add_issue(
            _("TIN and Tax ID do not match. TIN must equal the first 10 digits of Tax ID.<br>TIN: {0}<br>Tax ID: {1}").format(buyer_id, tax_id)
        )
    return errors, warnings


def validate_customer_zatca(doc, method=None) -> None:
    """Validate Customer only; no Sales Invoice/XML behavior is changed."""
    policy = get_customer_validation_policy(doc.name)
    errors, warnings = _buyer_errors(doc, policy)
    if warnings:
        frappe.msgprint("<br>".join(f"• {message}" for message in warnings), indicator="orange", alert=True)
    if errors:
        frappe.throw("<br>".join(f"• {message}" for message in errors), title=_("ZATCA Customer Validation"))


@frappe.whitelist()
def get_customer_validation_policy_for_form(customer=None, custom_b2c=0, customer_primary_address=None, territory=None):
    return get_customer_validation_policy(customer, custom_b2c, customer_primary_address, territory)
