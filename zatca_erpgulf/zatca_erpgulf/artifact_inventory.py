"""Operator-only attached-XML evidence inventory; no writes or remote requests.

Not whitelisted or registered as a hook. The default covers saved invoice fields
and local attached XML. Optional history includes stored responses and the saved
unit's counter. Neither mode scans loose files or signing credentials.
"""

import hashlib
import os
import stat
from pathlib import Path
from urllib.parse import unquote

import frappe
from frappe import _

from zatca_erpgulf.zatca_erpgulf.artifact_evidence import (
    MAX_XML_BYTES,
    ArtifactEvidenceError,
    SavedInvoiceIdentity,
    compare_saved_identity,
    inspect_invoice_artifact,
)
from zatca_erpgulf.zatca_erpgulf.counter_inventory import read_invoice_counter_evidence
from zatca_erpgulf.zatca_erpgulf.history_evidence import inspect_stored_response


def _read_local_attachment(file_doc, doctype, invoice_name):
    """Read bounded exact bytes only from this invoice's private local folder."""
    if (
        file_doc.get("attached_to_doctype") != doctype
        or file_doc.get("attached_to_name") != invoice_name
    ):
        raise ArtifactEvidenceError("attachment_owner")
    if file_doc.get("is_private") not in (1, "1"):
        raise ArtifactEvidenceError("attachment_not_private")
    name = str(file_doc.get("file_name") or "")
    if not name.lower().endswith(".xml") or name.upper().startswith("DEBUG_"):
        raise ArtifactEvidenceError("attachment_kind")
    url = file_doc.get("file_url")
    if not isinstance(url, str):
        raise ArtifactEvidenceError("attachment_path")
    url = unquote(url)
    prefix = "/private/files/"
    if not url.startswith(prefix):
        raise ArtifactEvidenceError("attachment_path")
    filename = url[len(prefix):]
    if (
        not filename or filename in (".", "..")
        or any(c in filename for c in ("/", "\\", "\x00"))
    ):
        raise ArtifactEvidenceError("attachment_path")
    try:
        folder = Path(frappe.get_site_path("private", "files")).resolve(strict=True)
        path = folder / filename
        if not path.resolve(strict=True).is_relative_to(folder):
            raise ArtifactEvidenceError("attachment_path")
        # Do not follow a leaf symlink after validation; do not normalize bytes.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ArtifactEvidenceError("attachment_file_type")
            if not 0 < info.st_size <= MAX_XML_BYTES:
                raise ArtifactEvidenceError("xml_size")
            with os.fdopen(fd, "rb", closefd=False) as handle:
                content = handle.read(MAX_XML_BYTES + 1)
        finally:
            os.close(fd)
    except ArtifactEvidenceError:
        raise
    except (OSError, ValueError):
        raise ArtifactEvidenceError("attachment_read") from None
    if not content or len(content) > MAX_XML_BYTES:
        raise ArtifactEvidenceError("xml_size")
    return content


def _inspect_candidate_bytes(content, saved):
    """Share identity inspection for attachments and embedded response XML."""
    result = {
        "file_sha256": hashlib.sha256(content).hexdigest(),
        "byte_length": len(content), "issues": [],
    }
    try:
        evidence = inspect_invoice_artifact(content)
        result.update(
            invoice_id=evidence.invoice_id, uuid=evidence.uuid, icv=evidence.icv,
            seller_tax_id=evidence.seller_tax_id, qr_present=evidence.qr_present,
            issues=list(compare_saved_identity(saved, evidence)),
        )
    except ArtifactEvidenceError as exc:
        result["issues"] = [exc.code]
        return result, None
    return result, evidence.file_sha256


def inspect_saved_invoice_artifacts(doctype, invoice_name, *, include_history=False):
    """Report all attached XML candidates without selecting an authoritative file.

    Explicit read permissions apply even though this is not an HTTP endpoint.
    Neither a consistent result nor stored acceptance status authorizes replay.
    """
    if not isinstance(include_history, bool):
        frappe.throw(_("The artifact history inspection option must be true or false."))
    if doctype not in ("Sales Invoice", "POS Invoice"):
        frappe.throw(
            _("Only Sales Invoice and POS Invoice artifact inspection is supported.")
        )
    if not isinstance(invoice_name, str) or not invoice_name.strip():
        frappe.throw(_("An invoice name is required for artifact inspection."))
    invoice = frappe.get_doc(doctype, invoice_name)
    invoice.check_permission("read")
    if not invoice.get("company"):
        frappe.throw(_("Company is required for invoice artifact inspection."))
    company = frappe.get_doc("Company", invoice.company)
    company.check_permission("read")
    saved = SavedInvoiceIdentity(
        doctype, invoice.name, company.name, str(company.get("tax_id") or ""),
        str(company.get("custom_select") or "").strip(),
        invoice.get("custom_uuid"), invoice.get("custom_zatca_icv"),
        str(invoice.get("custom_zatca_issuing_unit") or ""),
        str(invoice.get("custom_zatca_status") or ""),
    )
    rows = frappe.get_all(
        "File", filters={"attached_to_doctype": doctype, "attached_to_name": invoice.name},
        fields=["name", "file_name"], order_by="creation asc",
    )
    candidates, skipped, fingerprints = [], [], set()
    for row in rows:
        name = str(row.get("file_name") or "")
        if not name.lower().endswith(".xml") or name.upper().startswith("DEBUG_"):
            skipped.append({"file": row["name"], "reason": "non_xml_or_debug"})
            continue
        result = {"file": row["name"], "issues": []}
        try:
            file_doc = frappe.get_doc("File", row["name"])
            file_doc.check_permission("read")
            content = _read_local_attachment(file_doc, doctype, invoice.name)
            facts, fingerprint = _inspect_candidate_bytes(content, saved)
            result.update(facts)
            if fingerprint:
                fingerprints.add(fingerprint)
        except ArtifactEvidenceError as exc:
            result["issues"] = [exc.code]
        except frappe.PermissionError:
            result["issues"] = ["attachment_permission"]
        except frappe.DoesNotExistError:
            result["issues"] = ["attachment_missing"]
        candidates.append(result)
    issues = []
    response_report, counter_report, response_candidates = None, None, []
    if include_history:
        observation = inspect_stored_response(
            invoice.get("custom_zatca_full_response"), saved.status
        )
        response_report = {
            "format": observation.format, "outcome": observation.outcome,
            "issues": list(observation.issues), "text_sha256": observation.text_sha256,
            "byte_length": observation.byte_length,
        }
        for fieldname, content in observation.xml_candidates:
            candidate, fingerprint = _inspect_candidate_bytes(content, saved)
            candidate["source"] = f"stored_response:{fieldname}"
            if fingerprint:
                fingerprints.add(fingerprint)
            response_candidates.append(candidate)
        counter_report = read_invoice_counter_evidence(saved)
    if len(fingerprints) > 1:
        issues.append("artifact_bytes_conflict")
    if issues:
        state = "CONFLICT"
    elif (
        any(candidate["issues"] for candidate in candidates + response_candidates)
        or (response_report and response_report["issues"])
        or (counter_report and (
            counter_report["issues"]
            or any(candidate["issues"] for candidate in counter_report["candidates"])
        ))
    ):
        state = "RECONCILIATION_REQUIRED"
    elif candidates or response_candidates:
        state = "IDENTITY_CONSISTENT"
    else:
        state = "NO_XML_EVIDENCE" if include_history else "NO_ATTACHED_XML"
    report = {
        "scope": (
            "saved_identity_attached_xml_response_and_counter" if include_history
            else "saved_identity_and_attached_xml_only"
        ),
        "doctype": doctype, "invoice": invoice.name, "company": company.name,
        "environment": saved.environment, "saved_status": saved.status,
        "saved_issuing_unit": saved.issuing_unit,
        "saved_uuid": str(saved.uuid) if saved.uuid is not None else None,
        "saved_icv": str(saved.icv) if saved.icv is not None else None,
        "saved_seller_tax_id": saved.seller_tax_id,
        "state": state, "issues": issues, "candidates": candidates, "skipped": skipped,
        "signature_verified": False, "remote_acceptance_verified": False,
        "replay_authorized": False,
    }
    if include_history:
        report.update(
            response=response_report, counter=counter_report,
            response_candidates=response_candidates, history_complete=False,
        )
    return report
