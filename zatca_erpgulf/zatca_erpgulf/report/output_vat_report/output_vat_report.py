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


def signed_values(is_return, is_debit_note, base_amount, vat_amount):
    base_amount = base_amount or 0
    vat_amount = vat_amount or 0

    if is_return:
        return 0, -abs(base_amount), -abs(vat_amount)

    if is_debit_note:
        return 0, abs(base_amount), abs(vat_amount)

    return base_amount, 0, vat_amount


def get_data(filters):
    where_clause, values = get_conditions(filters, "si")

    rows = frappe.db.sql(
        f"""
        SELECT
            si.name AS invoice,
            si.posting_date,
            si.customer,
            si.customer_name,
            si.is_return,
            si.is_debit_note,
            si.net_total,
            si.grand_total,
            si.total_taxes_and_charges,
            si.custom_zatca_tax_category AS invoice_category,
            si.custom_exemption_reason_code AS invoice_exemption_code,
            si.custom_zatca_export_invoice AS export_invoice,
            si.custom_zatca_status,
            sii.name AS item_row,
            sii.item_code,
            sii.item_name,
            sii.net_amount AS item_net_amount,
            sii.amount AS item_amount,
            sii.item_tax_template,
            itt.custom_zatca_tax_category AS template_category,
            itt.custom_exemption_reason_code AS template_exemption_code,
            tax.tax_rate AS template_tax_rate
        FROM `tabSales Invoice` si
        LEFT JOIN `tabSales Invoice Item` sii
            ON sii.parent = si.name
        LEFT JOIN `tabItem Tax Template` itt
            ON itt.name = sii.item_tax_template
        LEFT JOIN `tabItem Tax Template Detail` tax
            ON tax.parent = itt.name AND tax.idx = 1
        WHERE {where_clause}
        ORDER BY si.posting_date, si.name, sii.idx
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
            row.is_debit_note,
            taxable_base,
            vat_amount,
        )

        data.append(
            {
                "invoice": row.invoice,
                "posting_date": row.posting_date,
                "party": row.customer,
                "party_name": row.customer_name,
                "item_code": row.item_code,
                "item_name": row.item_name,
                "item_tax_template": row.item_tax_template,
                "zatca_tax_category": category,
                "exemption_reason_code": row.template_exemption_code or row.invoice_exemption_code or "",
                "amount": amount,
                "adjustment": adjustment,
                "vat": vat,
                "status": row.custom_zatca_status,
            }
        )

    return data


def get_columns():
    return [
        {"label": "Sales Invoice", "fieldname": "invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 180},
        {"label": "Posting Date", "fieldname": "posting_date", "fieldtype": "Date", "width": 110},
        {"label": "Customer", "fieldname": "party", "fieldtype": "Link", "options": "Customer", "width": 160},
        {"label": "Customer Name", "fieldname": "party_name", "fieldtype": "Data", "width": 180},
        {"label": "Item Code", "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 140},
        {"label": "Item Name", "fieldname": "item_name", "fieldtype": "Data", "width": 180},
        {"label": "Item Tax Template", "fieldname": "item_tax_template", "fieldtype": "Link", "options": "Item Tax Template", "width": 180},
        {"label": "ZATCA Tax Category", "fieldname": "zatca_tax_category", "fieldtype": "Data", "width": 260},
        {"label": "Exemption Reason Code", "fieldname": "exemption_reason_code", "fieldtype": "Data", "width": 180},
        {"label": "Amount (SAR)", "fieldname": "amount", "fieldtype": "Currency", "width": 140},
        {"label": "Adjustment (SAR)", "fieldname": "adjustment", "fieldtype": "Currency", "width": 150},
        {"label": "VAT Amount (SAR)", "fieldname": "vat", "fieldtype": "Currency", "width": 150},
        {"label": "ZATCA Status", "fieldname": "status", "fieldtype": "Data", "width": 140},
    ]
