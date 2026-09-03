"""Localized presentation of ZATCA API responses.

The raw response remains available in logs; this helper only translates the
user-facing copy when the current Frappe language is Arabic.
"""

import json

import frappe


_MESSAGES = {
    "Complied with UBL 2.1 standards in line with ZATCA specifications":
        "تم الامتثال لمعايير UBL 2.1 بما يتماشى مع مواصفات هيئة الزكاة والضريبة والجمارك",
    "Invoice xml hash does not match with qr code invoice xml hash":
        "تجزئة XML للفاتورة لا تطابق تجزئة XML الموجودة في رمز QR",
    "UUID is not present in the API body":
        "معرّف UUID غير موجود في بيانات طلب API",
    "The request you are sending to ZATCA is in incorrect format. Please report to system administrator.":
        "الطلب المرسل إلى هيئة الزكاة والضريبة والجمارك (ZATCA) بتنسيق غير صحيح. يرجى إبلاغ مسؤول النظام.",
}


def format_zatca_response(response_text, status_code=None):
    """Return a readable, localized ZATCA response while preserving codes."""
    try:
        payload = json.loads(response_text) if isinstance(response_text, str) else response_text
    except (TypeError, ValueError):
        return response_text

    if getattr(frappe.local, "lang", "en") != "ar":
        return response_text

    validation = payload.get("validationResults") or {}
    for bucket in ("infoMessages", "warningMessages", "errorMessages"):
        for item in validation.get(bucket) or []:
            if item.get("message") in _MESSAGES:
                item["message"] = _MESSAGES[item["message"]]
            if item.get("category") == "XSD validation":
                item["category"] = "تحقق XSD"
            if item.get("status") == "PASS":
                item["status"] = "ناجح"

    localized = {
        "status_code": status_code,
        "validationResults": validation,
        "reportingStatus": payload.get("reportingStatus"),
        "clearanceStatus": payload.get("clearanceStatus"),
    }
    return json.dumps({k: v for k, v in localized.items() if v is not None}, ensure_ascii=False)
