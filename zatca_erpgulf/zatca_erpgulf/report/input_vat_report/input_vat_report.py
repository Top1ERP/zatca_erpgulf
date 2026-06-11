import frappe


OUT_OF_SCOPE = "Services outside scope of tax / Not subject to VAT"


def execute(filters=None):
    filters = frappe._dict(filters or {})
    return get_columns(), get_data(filters)


def get_conditions(filters, alias):
    conditions = [f"{alias}.docstatus = 1"]
    values = {}

    if filters.get("company"):
        conditions.append(f"{alias}.company = %(company)s")
        values["company"] = filters.company

    if filters.get("from_date"):
        conditions.append(f"{alias}.posting_date >= %(from_date)s")
        values["from_date"] = filters.from_date

    if filters.get("to_date"):
        conditions.append(f"{alias}.posting_date <= %(to_date)s")
        values["to_date"] = filters.to_date

    return " AND ".join(conditions), values


def signed_values(is_return, base_amount, vat_amount):
    base_amount = base_amount or 0
    vat_amount = vat_amount or 0

    if is_return:
        return 0, -abs(base_amount), -abs(vat_amount)

    return base_amount, 0, vat_amount


def get_data(filters):
    where_clause, values = get_conditions(filters, "pi")

    rows = frappe.db.sql(
        f"""
        SELECT
            pi.name AS invoice,
            pi.posting_date,
            pi.supplier,
            pi.supplier_name,
            pi.is_return,
            pi.net_total,
            pi.grand_total,
            pi.total_taxes_and_charges,
            pi.custom_zatca_tax_category AS invoice_category,
            pi.custom_exemption_reason_code AS invoice_exemption_code,
            pi.custom_zatca_import_invoice AS import_invoice,
            pii.name AS item_row,
            pii.item_code,
            pii.item_name,
            pii.net_amount AS item_net_amount,
            pii.amount AS item_amount,
            pii.item_tax_template,
            itt.custom_zatca_tax_category AS template_category,
            itt.custom_exemption_reason_code AS template_exemption_code,
            tax.tax_rate AS template_tax_rate
        FROM `tabPurchase Invoice` pi
        LEFT JOIN `tabPurchase Invoice Item` pii
            ON pii.parent = pi.name
        LEFT JOIN `tabItem Tax Template` itt
            ON itt.name = pii.item_tax_template
        LEFT JOIN `tabItem Tax Template Detail` tax
            ON tax.parent = itt.name AND tax.idx = 1
        WHERE {where_clause}
        ORDER BY pi.posting_date, pi.name, pii.idx
        """,
        values,
        as_dict=True,
    )

    data = []
    seen_invoice_fallback = set()

    for row in rows:
        category = row.template_category or row.invoice_category or "Standard"

        if filters.get("zatca_tax_category") and category != filters.zatca_tax_category:
            continue

        has_item_template = bool(row.item_tax_template)

        if has_item_template:
            taxable_base = row.item_net_amount if row.item_net_amount is not None else row.item_amount
            vat_amount = (taxable_base or 0) * (row.template_tax_rate or 0) / 100
        else:
            if row.invoice in seen_invoice_fallback:
                continue
            seen_invoice_fallback.add(row.invoice)
            taxable_base = row.net_total or row.grand_total or 0
            vat_amount = row.total_taxes_and_charges or 0

        if category in ["Zero Rated", "Exempted", OUT_OF_SCOPE]:
            vat_amount = 0

        amount, adjustment, vat = signed_values(
            row.is_return,
            taxable_base,
            vat_amount,
        )

        data.append(
            {
                "invoice": row.invoice,
                "posting_date": row.posting_date,
                "party": row.supplier,
                "party_name": row.supplier_name,
                "item_code": row.item_code,
                "item_name": row.item_name,
                "item_tax_template": row.item_tax_template,
                "zatca_tax_category": category,
                "exemption_reason_code": row.template_exemption_code or row.invoice_exemption_code or "",
                "is_import_invoice": row.import_invoice or 0,
                "amount": amount,
                "adjustment": adjustment,
                "vat": vat,
            }
        )

    return data


def get_columns():
    return [
        {"label": "Purchase Invoice", "fieldname": "invoice", "fieldtype": "Link", "options": "Purchase Invoice", "width": 180},
        {"label": "Posting Date", "fieldname": "posting_date", "fieldtype": "Date", "width": 110},
        {"label": "Supplier", "fieldname": "party", "fieldtype": "Link", "options": "Supplier", "width": 160},
        {"label": "Supplier Name", "fieldname": "party_name", "fieldtype": "Data", "width": 180},
        {"label": "Item Code", "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 140},
        {"label": "Item Name", "fieldname": "item_name", "fieldtype": "Data", "width": 180},
        {"label": "Item Tax Template", "fieldname": "item_tax_template", "fieldtype": "Link", "options": "Item Tax Template", "width": 180},
        {"label": "ZATCA Tax Category", "fieldname": "zatca_tax_category", "fieldtype": "Data", "width": 260},
        {"label": "Exemption Reason Code", "fieldname": "exemption_reason_code", "fieldtype": "Data", "width": 180},
        {"label": "Import Invoice", "fieldname": "is_import_invoice", "fieldtype": "Check", "width": 110},
        {"label": "Amount (SAR)", "fieldname": "amount", "fieldtype": "Currency", "width": 140},
        {"label": "Adjustment (SAR)", "fieldname": "adjustment", "fieldtype": "Currency", "width": 150},
        {"label": "VAT Amount (SAR)", "fieldname": "vat", "fieldtype": "Currency", "width": 150},
    ]
