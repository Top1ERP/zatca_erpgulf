"""Single shared field-alias registry, without Frappe or schema discovery.

Readers retain ownership of missing/blank/zero policy and secret handling.
Keep ordering stable; pure versioned observations must audit profile changes.
"""

FIELD_ALIAS_GROUPS = {
    "multiple_setting_certificate": {
        "doctype": "ZATCA Multiple Setting",
        "canonical": "custom_certificate",
        # Preserve the historical signing field's bytes when both values agree.
        # Credential readers additionally reject conflicting nonempty values.
        "aliases": ["custom_certficate", "custom_certificate"],
    },
    "company_arabic_name": {
        "doctype": "Company",
        "canonical": "custom_company_name_in_arabic",
        "aliases": [
            "custom_company_name_in_arabic",
            "company_name_in_arabic",
            "custom__company_name_in_arabic__",
        ],
    },
    "customer_arabic_name": {
        "doctype": "Customer",
        "canonical": "custom_customer_name_in_arabic",
        "aliases": [
            "custom_customer_name_in_arabic",
            "customer_name_in_arabic",
            "zatca_customer_name_in_arabic",
        ],
    },
    "supplier_arabic_name": {
        "doctype": "Supplier",
        "canonical": "supplier_name_in_arabic",
        "aliases": [
            "supplier_name_in_arabic",
            "custom_supplier_name_in_arabic",
            "zatca_supplier_name_in_arabic",
        ],
    },
    "address_arabic": {
        "doctype": "Address",
        "canonical": "address_in_arabic",
        "aliases": [
            "address_in_arabic",
            "custom_address_in_arabic",
            "zatca_address_in_arabic",
            "address_line1_in_arabic",
            "custom_address_line1_in_arabic",
            "custom__address_in_arabic__",
        ],
    },
    "sales_invoice_qr": {
        "doctype": "Sales Invoice",
        "canonical": "ksa_einv_qr",
        "aliases": [
            "ksa_einv_qr",
            "custom_ksa_einv_qr",
        ],
    },
    "pos_invoice_qr": {
        "doctype": "POS Invoice",
        "canonical": "ksa_einv_qr",
        "aliases": [
            "ksa_einv_qr",
            "custom_ksa_einv_qr",
        ],
    },
    "customer_b2c": {
        "doctype": "Customer",
        "canonical": "custom_b2c",
        "aliases": [
            "custom_b2c",
            "b2c",
            "is_b2c",
            "zatca_b2c",
        ],
    },
    "customer_buyer_id_type": {
        "doctype": "Customer",
        "canonical": "custom_buyer_id_type",
        "aliases": [
            "custom_buyer_id_type",
            "buyer_id_type",
            "zatca_buyer_id_type",
        ],
    },
    "customer_buyer_id": {
        "doctype": "Customer",
        "canonical": "custom_buyer_id",
        "aliases": [
            "custom_buyer_id",
            "buyer_id",
            "zatca_buyer_id",
        ],
    },
    "customer_unn": {
        "doctype": "Customer",
        "canonical": "custom_unified_national_number",
        "aliases": [
            "custom_unified_national_number",
            "unified_national_number",
            "unn",
        ],
    },
    "item_is_zero_rated": {
        "doctype": "Item",
        "canonical": "is_zero_rated",
        "aliases": [
            "is_zero_rated",
            "custom_is_zero_rated",
            "zatca_is_zero_rated",
        ],
    },
    "item_is_exempt": {
        "doctype": "Item",
        "canonical": "is_exempt",
        "aliases": [
            "is_exempt",
            "custom_is_exempt",
            "zatca_is_exempt",
        ],
    },
}
