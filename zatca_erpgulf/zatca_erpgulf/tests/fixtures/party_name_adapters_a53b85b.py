"""Frozen increment223 party/QR adapters; test-only previous-source oracle."""

SOURCES = {
'zatca_erpgulf/zatca_erpgulf/createxml.py': r'''
def _first_available_value(doc, fieldnames):
    """Return first non-empty value from the given field list when the field exists."""
    meta = frappe.get_meta(doc.doctype)
    for fieldname in fieldnames:
        if meta.get_field(fieldname):
            value = getattr(doc, fieldname, None)
            if value is not None:
                value = str(value).strip()
                if value:
                    return value
    return ""

_NAME_NOISE_WORDS = {
    "company", "co", "co.", "corp", "corporation", "inc", "inc.", "ltd", "ltd.",
    "llc", "llp", "est", "est.", "factory", "trading", "group", "holding", "holdings",
    " المؤسسة", "شركة", "شركه", "مؤسسة", "مؤسسه", "محددودة", "محدودة", "ذ", "م", "م.",
}

def _normalize_name_for_similarity(value):
    """Normalize text so cosmetic differences do not create duplicate PartyName entries."""
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", str(value)).lower().strip()
    value = re.sub(r"[ـ]", "", value)
    value = re.sub(r"[^\w\s؀-ۿ]", " ", value)
    tokens = [token for token in value.split() if token and token not in _NAME_NOISE_WORDS]
    return " ".join(tokens)

def _script_type(value):
    """Return rough script bucket for text: arabic, latin, mixed, or other."""
    if not value:
        return "other"
    has_arabic = bool(re.search(r"[؀-ۿ]", value))
    has_latin = bool(re.search(r"[A-Za-z]", value))
    if has_arabic and has_latin:
        return "mixed"
    if has_arabic:
        return "arabic"
    if has_latin:
        return "latin"
    return "other"

def _names_are_highly_similar(name1, name2, threshold=0.90):
    """Treat two names as duplicates when they differ only cosmetically.

    Arabic-vs-English representations are kept as separate names by default because
    text similarity alone is not reliable across scripts.
    """
    if not name1 or not name2:
        return False

    normalized_1 = _normalize_name_for_similarity(name1)
    normalized_2 = _normalize_name_for_similarity(name2)

    if not normalized_1 or not normalized_2:
        return False

    if normalized_1 == normalized_2:
        return True

    script_1 = _script_type(normalized_1)
    script_2 = _script_type(normalized_2)
    if script_1 != script_2 and {script_1, script_2} == {"arabic", "latin"}:
        return False

    return SequenceMatcher(None, normalized_1, normalized_2).ratio() >= threshold

def _deduplicate_names(names):
    """Keep names in order, dropping blanks and near-duplicates."""
    unique_names = []
    for name in names:
        clean_name = str(name or "").strip()
        if not clean_name:
            continue
        if any(_names_are_highly_similar(clean_name, existing) for existing in unique_names):
            continue
        unique_names.append(clean_name)
    return unique_names

def _get_company_display_names(company_doc, sales_invoice_doc=None):
    """Return supplier names in preferred order: Arabic first, then English if distinct."""
    arabic_name = _first_available_value(
        company_doc,
        [
            "company_name_in_arabic",
            "custom_company_name_in_arabic",
            "custom__company_name_in_arabic__",
        ],
    )
    english_name = str(getattr(company_doc, "company_name", "") or getattr(sales_invoice_doc, "company", "") or "").strip()
    return _deduplicate_names([arabic_name, english_name])

def _get_customer_display_names(customer_doc):
    """Return customer names in preferred order: Arabic first, then English if distinct."""
    arabic_name = _first_available_value(
        customer_doc,
        [
            "customer_name_in_arabic",
            "custom_customer_name_in_arabic",
            "zatca_customer_name_in_arabic",
        ],
    )
    english_name = str(getattr(customer_doc, "customer_name", "") or "").strip()
    return _deduplicate_names([arabic_name, english_name])
''',
'zatca_erpgulf/zatca_erpgulf/posxml.py': r'''
def _first_available_value(doc, fieldnames):
    meta = frappe.get_meta(doc.doctype)
    for fieldname in fieldnames:
        if meta.get_field(fieldname):
            value = getattr(doc, fieldname, None)
            if value:
                return str(value).strip()
    return ""

_NAME_NOISE_WORDS = {"company", "co", "ltd", "llc", "corp", "inc", "شركة", "مؤسسة"}

def _normalize_name(val):
    val = unicodedata.normalize("NFKD", str(val)).lower()
    val = re.sub(r"[^\w\s؀-ۿ]", " ", val)
    tokens = [t for t in val.split() if t not in _NAME_NOISE_WORDS]
    return " ".join(tokens)

def _similar(a, b):
    if not a or not b:
        return False
    a = _normalize_name(a)
    b = _normalize_name(b)
    return SequenceMatcher(None, a, b).ratio() > 0.9

def _unique(names):
    out = []
    for n in names:
        if not n:
            continue
        if any(_similar(n, x) for x in out):
            continue
        out.append(n)
    return out

def _company_names(doc):
    ar = _first_available_value(
        doc,
        [
            "company_name_in_arabic",
            "custom_company_name_in_arabic",
            "custom__company_name_in_arabic__",
        ],
    )
    en = str(getattr(doc, "company_name", "")).strip()
    return _unique([ar, en])

def _customer_names(doc):
    ar = _first_available_value(
        doc,
        [
            "customer_name_in_arabic",
            "custom_customer_name_in_arabic",
            "zatca_customer_name_in_arabic",
        ],
    )
    en = str(getattr(doc, "customer_name", "")).strip()
    return _unique([ar, en])
''',
'zatca_erpgulf/zatca_erpgulf/create_qr.py': r'''
def get_company_arabic_name(company_name: str) -> str:
    """
    Return company Arabic name using the required fallback order:
    1. company_name_in_arabic
    2. custom_company_name_in_arabic
    3. custom__company_name_in_arabic__
    """
    meta = frappe.get_meta("Company")
    fallback_fields = [
        "company_name_in_arabic",
        "custom_company_name_in_arabic",
        "custom__company_name_in_arabic__",
    ]

    for fieldname in fallback_fields:
        if meta.get_field(fieldname):
            value = frappe.db.get_value("Company", company_name, fieldname)
            if value:
                return value

    return ""

def create_qr_code(doc, method=None):  # pylint: disable=unused-argument
    """Stage a Phase-1 QR without owning the caller's transaction or schema."""
    region = get_region(doc.company)
    if not is_saudi_country(region):
        return

    # Schema setup/DDL belongs to an approved install/migration, never a hook.
    if not hasattr(doc, "ksa_einv_qr"):
        frappe.throw(_(MISSING_QR_FIELD))

    # Preserve only the current same-invoice reference, never auto-clean/relink.
    if _existing_qr_reference(doc):
        return

    meta = frappe.get_meta(doc.doctype)

    if "ksa_einv_qr" in [d.fieldname for d in meta.get_image_fields()]:
        # Seller's Name
        seller_name = get_company_arabic_name(doc.company)

        if not seller_name:
            frappe.throw(
                _(
                    "Arabic name missing for {} in the company document. "
                    "Checked fields: company_name_in_arabic, "
                    "custom_company_name_in_arabic, "
                    "custom__company_name_in_arabic__"
                ).format(doc.company)
            )

        # VAT Number
        tax_id = frappe.db.get_value("Company", doc.company, "tax_id")
        if not tax_id:
            frappe.throw(
                _("Tax ID missing for {} in the company document").format(doc.company)
            )

        # Time Stamp
        time_stamp = format_zatca_qr_timestamp(doc.posting_date, doc.posting_time)

        amounts = checked_phase1_amounts(doc, runtime=frappe, translate=_)
        invoice_amount, vat_amount = amounts.invoice_total, amounts.vat_total
        try:
            base64_string = encode_phase1_qr(
                seller_name=seller_name, vat_number=tax_id, timestamp=time_stamp,
                invoice_total=invoice_amount, vat_total=vat_amount,
            )
        except Phase1QREncodingError as error:
            invalid_tag = error.tag
        else:
            invalid_tag = None
        if invalid_tag is not None:
            frappe.throw(_(PHASE1_QR_VALUE_ERROR).format(invalid_tag))

        qr_image = io.BytesIO()
        url = qr_create(base64_string, error="L")
        url.png(qr_image, scale=4, quiet_zone=4)

        # Make file
        filename = f"QR-Phase1-{doc.name}.png".replace(os.path.sep, "__")
        _file = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": filename,
                "is_private": 0,
                "content": qr_image.getvalue(),
                "attached_to_doctype": doc.get("doctype"),
                "attached_to_name": doc.get("name"),
                "attached_to_field": "ksa_einv_qr",
            }
        )

        _file.save()

        _persist_phase1_qr_metadata(doc, _file.file_url)
''',
'zatca_erpgulf/zatca_erpgulf/advance_deduction.py': r'''
def ensure_final_sales_invoice_qr_for_print(doc, event=None, force=False):
    """Stage a first advance-aware QR, never repair or replace stored artifacts.

    This keeps existing print formats stable because they continue using doc.ksa_einv_qr.
    ``force`` is retained for call compatibility, not as a preservation bypass.
    A print hook is not an artifact-repair or historical-data migration boundary.

    Applies only when:
    - DocType is Sales Invoice.
    - Document is submitted.
    - Sales Invoice has custom_zatca_advance_deducted_taxable_amount > 0.
    - ksa_einv_qr field exists.

    The initial advance uses its native saved gross and VAT in document
    currency. This print hook does not calculate a later invoice's settlement.
    """
    from frappe.utils import flt

    if getattr(doc, "doctype", None) != "Sales Invoice":
        return

    company_doc = frappe.get_cached_doc("Company", doc.company)
    if is_zatca_invoice_enabled(company_doc) and resolve_zatca_phase(company_doc) == PHASE_2_VALUE:
        # Phase-2 QR must come from the returned ZATCA XML artifact.
        return

    if not supports_advance_deduction_schema(doc):
        return

    if int(getattr(doc, "docstatus", 0) or 0) != 1:
        return

    if not doc.meta.has_field("ksa_einv_qr"):
        return

    # This hook owns initial advances only. Never delete/relink a final invoice's
    # historical attachments based on filename hints, even if force was supplied.
    if not is_advance_payment_invoice(doc):
        return

    advance_taxable = flt(doc.get("custom_zatca_advance_deducted_taxable_amount") or 0)
    if advance_taxable <= 0:
        return

    # Reuse the bounded same-invoice policy, including missing/orphan review.
    # Preserving a link is not proof of valid contents or remote acceptance.
    if _existing_qr_reference(doc):
        return

    import io

    import pyqrcode
    from frappe.utils.file_manager import save_file

    company = frappe.get_doc("Company", doc.company)

    seller_name = (
        company.get("company_name_in_arabic")
        or company.get("custom_company_name_in_arabic")
        or company.company_name
    )

    vat_number = company.get("tax_id")
    if not vat_number:
        frappe.throw("Company Tax ID is required to generate ZATCA QR.")

    # Same explicit conversion as ordinary Phase-1 and XML-derived Phase-2.
    # Do not invent midnight for a missing field. The Phase-2 guard above still
    # preserves the authoritative stored QR and all amount calculations below.
    timestamp = format_zatca_qr_timestamp(doc.posting_date, doc.get("posting_time"))

    amounts = checked_phase1_amounts(doc, runtime=frappe, translate=_)

    try:
        payload = encode_phase1_qr(
            seller_name=str(seller_name or ""), vat_number=str(vat_number or ""),
            timestamp=timestamp, invoice_total=amounts.invoice_total,
            vat_total=amounts.vat_total,
        )
    except Phase1QREncodingError as error:
        invalid_tag = error.tag
    else:
        invalid_tag = None
    if invalid_tag is not None:
        frappe.throw(_(PHASE1_QR_VALUE_ERROR).format(invalid_tag))

    png = io.BytesIO()
    pyqrcode.create(payload, error="L").png(png, scale=4, quiet_zone=4)

    file_name = f"QR-ZATCA-Advance-Aware-{doc.name}.png"

    file_doc = save_file(
        file_name,
        png.getvalue(),
        "Sales Invoice",
        doc.name,
        is_private=0,
    )

    file_doc.attached_to_field = "ksa_einv_qr"
    file_doc.save(ignore_permissions=True)

    frappe.db.set_value(
        "Sales Invoice",
        doc.name,
        "ksa_einv_qr",
        file_doc.file_url,
        update_modified=False,
    )

    doc.ksa_einv_qr = file_doc.file_url
''',
}
