from __future__ import annotations

import frappe
from frappe import _


KSA_TAX_DEFINITIONS = [
    {
        "title": "KSA VAT 15%",
        "account_name": "VAT 15%",
        "rate": 15.0,
        "description": "VAT 15%",
        "is_sales_default": True,
    },
    {
        "title": "KSA VAT 5%",
        "account_name": "VAT 5%",
        "rate": 5.0,
        "description": "VAT 5%",
        "is_sales_default": False,
    },
    {
        "title": "KSA VAT Zero",
        "account_name": "VAT Zero",
        "rate": 0.0,
        "description": "VAT Zero",
        "is_sales_default": False,
    },
    {
        "title": "KSA VAT Exempted",
        "account_name": "VAT Exempted",
        "rate": 0.0,
        "description": "VAT Exempted",
        "is_sales_default": False,
    },
    {
        "title": "KSA Excise 50%",
        "account_name": "Excise 50%",
        "rate": 50.0,
        "description": "Excise 50%",
        "is_sales_default": False,
    },
    {
        "title": "KSA Excise 100%",
        "account_name": "Excise 100%",
        "rate": 100.0,
        "description": "Excise 100%",
        "is_sales_default": False,
    },
]


def get_company_doc(company: str):
    if not company:
        frappe.throw(_("Company is required"))

    if not frappe.db.exists("Company", company):
        frappe.throw(_("Company {0} does not exist").format(company))

    return frappe.get_doc("Company", company)


def make_company_suffix(company_doc) -> str:
    if not company_doc.abbr:
        frappe.throw(_("Company abbreviation is required for {0}").format(company_doc.name))

    return company_doc.abbr


def make_template_name(title: str, company_doc) -> str:
    return f"{title} - {make_company_suffix(company_doc)}"


def find_existing_doc_by_name_or_title(doctype: str, name: str, title: str, company: str) -> str | None:
    if frappe.db.exists(doctype, name):
        return name

    existing = frappe.db.get_value(
        doctype,
        {
            "company": company,
            "title": title,
        },
        "name",
    )

    return existing


def find_account_by_name_or_account_name(company: str, account_name: str, company_abbr: str) -> str | None:
    canonical_name = f"{account_name} - {company_abbr}"

    if frappe.db.exists("Account", canonical_name):
        return canonical_name

    existing = frappe.db.get_value(
        "Account",
        {
            "company": company,
            "account_name": account_name,
            "is_group": 0,
        },
        "name",
    )

    if existing:
        return existing

    existing_tax = frappe.db.get_value(
        "Account",
        {
            "company": company,
            "account_type": "Tax",
            "account_name": account_name,
        },
        "name",
    )

    return existing_tax


def find_tax_parent_account(company: str, company_abbr: str) -> str:
    preferred_names = [
        f"Duties and Taxes - {company_abbr}",
        f"Taxes - {company_abbr}",
        f"Tax - {company_abbr}",
        f"VAT - {company_abbr}",
    ]

    for account in preferred_names:
        if frappe.db.exists("Account", account):
            is_group = frappe.db.get_value("Account", account, "is_group")
            if int(is_group or 0) == 1:
                return account

    preferred_account_names = [
        "Duties and Taxes",
        "Taxes",
        "Tax",
        "VAT",
    ]

    for account_name in preferred_account_names:
        existing = frappe.db.get_value(
            "Account",
            {
                "company": company,
                "account_name": account_name,
                "is_group": 1,
            },
            "name",
        )
        if existing:
            return existing

    tax_group = frappe.db.get_value(
        "Account",
        {
            "company": company,
            "account_type": "Tax",
            "is_group": 1,
        },
        "name",
    )
    if tax_group:
        return tax_group

    liability_group = frappe.db.get_value(
        "Account",
        {
            "company": company,
            "root_type": "Liability",
            "is_group": 1,
            "account_name": ["like", "%Current%"],
        },
        "name",
    )
    if liability_group:
        return liability_group

    liability_group = frappe.db.get_value(
        "Account",
        {
            "company": company,
            "root_type": "Liability",
            "is_group": 1,
        },
        "name",
    )
    if liability_group:
        return liability_group

    frappe.throw(
        _(
            "Could not find a suitable parent Account for VAT accounts in company {0}. "
            "Create a Liability group account such as Duties and Taxes, then retry."
        ).format(company)
    )


def ensure_tax_account(company_doc, account_name: str) -> dict:
    company_abbr = make_company_suffix(company_doc)
    existing = find_account_by_name_or_account_name(company_doc.name, account_name, company_abbr)

    if existing:
        return {
            "name": existing,
            "created": False,
            "updated": False,
        }

    parent_account = find_tax_parent_account(company_doc.name, company_abbr)

    account = frappe.new_doc("Account")
    account.account_name = account_name
    account.company = company_doc.name
    account.parent_account = parent_account
    account.is_group = 0
    account.account_type = "Tax"

    if company_doc.default_currency:
        account.account_currency = company_doc.default_currency

    account.insert(ignore_permissions=True)

    return {
        "name": account.name,
        "created": True,
        "updated": False,
    }


def reset_sales_default_for_company(company: str) -> None:
    frappe.db.sql(
        """
        update `tabSales Taxes and Charges Template`
        set is_default = 0
        where company = %s
        """,
        company,
    )


def ensure_sales_tax_template(company_doc, tax_def: dict, account_name: str) -> dict:
    template_name = make_template_name(tax_def["title"], company_doc)

    existing_name = find_existing_doc_by_name_or_title(
        "Sales Taxes and Charges Template",
        template_name,
        tax_def["title"],
        company_doc.name,
    )

    created = False

    if existing_name:
        doc = frappe.get_doc("Sales Taxes and Charges Template", existing_name)
    else:
        doc = frappe.new_doc("Sales Taxes and Charges Template")
        doc.name = template_name
        created = True

    doc.title = tax_def["title"]
    doc.company = company_doc.name
    doc.disabled = 0
    doc.is_default = 1 if tax_def.get("is_sales_default") else 0

    doc.set("taxes", [])
    doc.append(
        "taxes",
        {
            "charge_type": "On Net Total",
            "account_head": account_name,
            "rate": tax_def["rate"],
            "description": tax_def["description"],
            "included_in_print_rate": 0,
        },
    )

    if created:
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    return {
        "doctype": "Sales Taxes and Charges Template",
        "name": doc.name,
        "title": doc.title,
        "created": created,
        "is_default": doc.is_default,
        "description": tax_def["description"],
    }


def ensure_purchase_tax_template(company_doc, tax_def: dict, account_name: str) -> dict:
    template_name = make_template_name(tax_def["title"], company_doc)

    existing_name = find_existing_doc_by_name_or_title(
        "Purchase Taxes and Charges Template",
        template_name,
        tax_def["title"],
        company_doc.name,
    )

    created = False

    if existing_name:
        doc = frappe.get_doc("Purchase Taxes and Charges Template", existing_name)
    else:
        doc = frappe.new_doc("Purchase Taxes and Charges Template")
        doc.name = template_name
        created = True

    doc.title = tax_def["title"]
    doc.company = company_doc.name
    doc.disabled = 0
    doc.is_default = 0

    doc.set("taxes", [])
    doc.append(
        "taxes",
        {
            "charge_type": "On Net Total",
            "account_head": account_name,
            "rate": tax_def["rate"],
            "description": tax_def["description"],
            "included_in_print_rate": 0,
        },
    )

    if created:
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    return {
        "doctype": "Purchase Taxes and Charges Template",
        "name": doc.name,
        "title": doc.title,
        "created": created,
        "is_default": doc.is_default,
        "description": tax_def["description"],
    }


def ensure_item_tax_template(company_doc, tax_def: dict, account_name: str) -> dict:
    template_name = make_template_name(tax_def["title"], company_doc)

    existing_name = find_existing_doc_by_name_or_title(
        "Item Tax Template",
        template_name,
        tax_def["title"],
        company_doc.name,
    )

    created = False

    if existing_name:
        doc = frappe.get_doc("Item Tax Template", existing_name)
    else:
        doc = frappe.new_doc("Item Tax Template")
        doc.name = template_name
        created = True

    doc.title = tax_def["title"]
    doc.company = company_doc.name
    doc.disabled = 0

    doc.set("taxes", [])
    doc.append(
        "taxes",
        {
            "tax_type": account_name,
            "tax_rate": tax_def["rate"],
        },
    )

    if created:
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    return {
        "doctype": "Item Tax Template",
        "name": doc.name,
        "title": doc.title,
        "created": created,
        "description": tax_def["description"],
    }


@frappe.whitelist()
def create_or_update_ksa_tax_templates(company: str) -> dict:
    """Create/update KSA VAT tax accounts and tax templates for one company.

    This function is idempotent:
    - It does not duplicate accounts if the account already exists by name or account_name.
    - It does not duplicate templates if a template already exists by name or by title+company.
    - It updates only the canonical KSA templates.
    - It makes KSA VAT 15% the default Sales Taxes and Charges Template.
    """

    company_doc = get_company_doc(company)

    if company_doc.country and company_doc.country != "Saudi Arabia":
        frappe.msgprint(
            _("Company country is {0}. KSA templates are intended for Saudi Arabia.").format(
                company_doc.country
            )
        )

    reset_sales_default_for_company(company_doc.name)

    result = {
        "company": company_doc.name,
        "abbr": company_doc.abbr,
        "accounts": [],
        "sales_templates": [],
        "purchase_templates": [],
        "item_tax_templates": [],
    }

    for tax_def in KSA_TAX_DEFINITIONS:
        account_result = ensure_tax_account(company_doc, tax_def["account_name"])
        account_name = account_result["name"]

        result["accounts"].append(
            {
                "title": tax_def["title"],
                "account": account_name,
                "created": account_result["created"],
            }
        )

        result["sales_templates"].append(
            ensure_sales_tax_template(company_doc, tax_def, account_name)
        )
        result["purchase_templates"].append(
            ensure_purchase_tax_template(company_doc, tax_def, account_name)
        )
        result["item_tax_templates"].append(
            ensure_item_tax_template(company_doc, tax_def, account_name)
        )

    frappe.db.commit()
    frappe.clear_cache()

    return result


def get_template_row_status(company: str) -> dict:
    company_doc = get_company_doc(company)

    rows = {
        "sales": frappe.db.sql(
            """
            select
                st.name,
                st.title,
                st.company,
                st.disabled,
                st.is_default,
                tc.account_head,
                tc.rate,
                tc.description
            from `tabSales Taxes and Charges Template` st
            left join `tabSales Taxes and Charges` tc
                on tc.parent = st.name
                and tc.parenttype = 'Sales Taxes and Charges Template'
            where st.company = %s
              and st.title like 'KSA %%'
            order by st.name, tc.idx
            """,
            company_doc.name,
            as_dict=True,
        ),
        "purchase": frappe.db.sql(
            """
            select
                pt.name,
                pt.title,
                pt.company,
                pt.disabled,
                pt.is_default,
                tc.account_head,
                tc.rate,
                tc.description
            from `tabPurchase Taxes and Charges Template` pt
            left join `tabPurchase Taxes and Charges` tc
                on tc.parent = pt.name
                and tc.parenttype = 'Purchase Taxes and Charges Template'
            where pt.company = %s
              and pt.title like 'KSA %%'
            order by pt.name, tc.idx
            """,
            company_doc.name,
            as_dict=True,
        ),
        "item_tax": frappe.db.sql(
            """
            select
                it.name,
                it.title,
                it.company,
                it.disabled,
                td.tax_type,
                td.tax_rate
            from `tabItem Tax Template` it
            left join `tabItem Tax Template Detail` td
                on td.parent = it.name
            where it.company = %s
              and it.title like 'KSA %%'
            order by it.name, td.idx
            """,
            company_doc.name,
            as_dict=True,
        ),
    }

    return rows


@frappe.whitelist()
def report_ksa_tax_template_status(company: str) -> dict:
    return get_template_row_status(company)
