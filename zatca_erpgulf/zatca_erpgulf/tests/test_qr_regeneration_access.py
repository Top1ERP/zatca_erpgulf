"""Saved-row QR endpoint access with synthetic ERP/File/IO only.

Signature-shaped v15/v16 ACL engines are not installed v16 acceptance. Recovery
preserves current owned references or requires review, with no content IO/writes.
"""

import ast
import csv
from datetime import timedelta
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import qr_regeneration as qr
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document


class Denied(Exception):
    pass


class Row(dict):
    __getattr__ = dict.__getitem__


@pytest.fixture(params=[15, 16])
def access(monkeypatch, request):
    actor = "SYNTHETIC-USER"
    invoice = Document(doctype="Sales Invoice", name="SYNTHETIC-INVOICE", company="SYNTHETIC-COMPANY",
        docstatus=1, posting_date="2026-10-14", posting_time="09:00:00", ksa_einv_qr=None,
        custom_zatca_status="Not Submitted", flags=SimpleNamespace(ignore_permissions=True),
        save=Mock(), check_permission=Mock(side_effect=AssertionError("Do not trust Document flags")))
    company = Document(doctype="Company", name=invoice.company, tax_id="SYNTHETIC-VAT")
    file = Document(doctype="File", name="SYNTHETIC-FILE", file_name="QR-SYNTHETIC.png",
        file_url="/files/SYNTHETIC.png", attached_to_doctype=invoice.doctype, attached_to_name=invoice.name,
        attached_to_field=None, creation="2026-10-14 09:00:00", save=Mock())
    projection = Row({field: file.get(field) for field in qr.ATTACHMENT_FIELDS})
    documents = {("Sales Invoice", invoice.name): invoice, ("Company", company.name): company,
        ("File", file.name): file}
    events, acl = [], []
    decisions = {}
    runtime = SimpleNamespace(session=SimpleNamespace(user=actor), PermissionError=Denied,
        db=SimpleNamespace(exists=Mock(return_value=True), set_value=Mock(), commit=Mock(), rollback=Mock()),
        get_all=Mock(return_value=[projection]), get_cached_doc=Mock(side_effect=AssertionError("No cached ACL subject")))
    def throw(message, exception=Denied):
        raise exception(message)
    runtime.throw = throw
    def load(doctype, name):
        events.append(("load", doctype, name))
        return documents[doctype, name]
    runtime.get_doc = Mock(side_effect=load)
    def decide(doctype, operation, doc, user, quiet):
        events.append(("acl", doctype, operation))
        acl.append((doctype, operation, doc, user, quiet))
        decision = decisions.get((doctype, operation), True)
        if isinstance(decision, Exception):
            raise decision
        return decision() if callable(decision) else decision
    def v15(doctype, operation, *, doc, user, raise_exception=True):
        return decide(doctype, operation, doc, user, raise_exception)
    def v16(doctype, operation, *, doc, user, print_logs=True):
        return decide(doctype, operation, doc, user, print_logs)
    monkeypatch.setattr(qr, "frappe", runtime)
    monkeypatch.setattr(qr, "has_permission", v15 if request.param == 15 else v16)
    monkeypatch.setattr(qr, "_", lambda text: text)
    monkeypatch.setattr(qr, "is_zatca_invoice_enabled", lambda doc: True)
    reader = Mock(side_effect=AssertionError("No real path or physical file read"))
    parser = Mock(side_effect=AssertionError("No real XML parse"))
    saver = Mock(side_effect=AssertionError("No physical file save"))
    generator = Mock(side_effect=AssertionError("No real QR generation"))
    opener = Mock(side_effect=AssertionError("No physical file open"))
    # Tripwires for the removed legacy paths; none may be called if reintroduced.
    monkeypatch.setattr(qr, "get_file_path", reader, raising=False)
    monkeypatch.setattr(qr, "_extract_qr_payload_from_xml", parser, raising=False)
    monkeypatch.setattr(qr, "save_file", saver, raising=False)
    monkeypatch.setattr(qr, "create_qr_code", generator, raising=False)
    monkeypatch.setattr(qr, "open", opener, raising=False)
    return SimpleNamespace(doc=invoice, request_name=invoice.name, company=company, file=file, row=projection, runtime=runtime,
        documents=documents, decisions=decisions, acl=acl, events=events, reader=reader, parser=parser,
        saver=saver, generator=generator, opener=opener, actor=actor)


def invoke(case, endpoint):
    # Execute the real endpoint body without Frappe's request-local typing
    # decorator. No site/request is initialized for a unit access test.
    return inspect.unwrap(getattr(qr, endpoint))(case.request_name)


def no_writes(case):
    case.runtime.db.set_value.assert_not_called()
    case.runtime.db.commit.assert_not_called()
    case.runtime.db.rollback.assert_not_called()
    case.file.save.assert_not_called()
    case.doc.save.assert_not_called()
    case.doc.check_permission.assert_not_called()
    case.generator.assert_not_called()
    case.saver.assert_not_called()


def denied(case, endpoint):
    with pytest.raises(Denied) as error:
        invoke(case, endpoint)
    assert str(error.value) == qr.DENIED_MESSAGE and error.value.__context__ is None
    no_writes(case)
    case.reader.assert_not_called()
    case.opener.assert_not_called()
    case.parser.assert_not_called()


ENDPOINTS = ("get_qr_regeneration_state", "regenerate_qr")


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("actor", ["Guest", "", None, " actor ", "x" * 141, "PRIVATE\x00USER", 7])
def test_invalid_or_guest_actor_stops_before_any_saved_row_load(access, endpoint, actor):
    access.runtime.session.user = actor
    denied(access, endpoint)
    access.runtime.get_doc.assert_not_called()
    access.runtime.get_all.assert_not_called()
    assert not access.acl


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("name", [None, "", {}, ["invoice"], "x" * 141, " invoice ", "PRIVATE\nNAME"])
def test_request_name_is_not_a_document_or_filter(access, endpoint, name):
    with pytest.raises(Denied) as error:
        inspect.unwrap(getattr(qr, endpoint))(name)
    assert str(error.value) == qr.DENIED_MESSAGE
    access.runtime.get_doc.assert_not_called()
    access.runtime.get_all.assert_not_called()
    no_writes(access)


@pytest.mark.parametrize("endpoint,subject,operation", [
    ("get_qr_regeneration_state", "Sales Invoice", "read"),
    ("regenerate_qr", "Sales Invoice", "read"),
    ("regenerate_qr", "Sales Invoice", "write"),
    ("get_qr_regeneration_state", "Company", "read"),
    ("regenerate_qr", "Company", "read"),
])
def test_source_and_company_acl_precede_all_attachment_queries(access, endpoint, subject, operation):
    access.decisions[subject, operation] = False
    denied(access, endpoint)
    access.runtime.get_all.assert_not_called()
    assert not any(event[:2] == ("load", "File") for event in access.events)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("value", [None, 1, "yes"])
def test_truthy_permission_result_cannot_bypass_document_flags(access, endpoint, value):
    access.decisions["Sales Invoice", "read"] = value
    denied(access, endpoint)
    access.runtime.get_all.assert_not_called()


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("error", [TypeError("PRIVATE ACL detail"), RuntimeError("PRIVATE credentials")])
def test_acl_fault_is_redacted_without_keyword_retry(access, endpoint, error):
    access.decisions["Sales Invoice", "read"] = error
    denied(access, endpoint)
    assert len(access.acl) == 1
    access.runtime.get_all.assert_not_called()


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_unknown_permission_engine_signature_fails_closed(access, monkeypatch, endpoint):
    engine = Mock()
    monkeypatch.setattr(qr, "has_permission", engine)
    denied(access, endpoint)
    engine.assert_not_called()


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("subject,field,value", [("doc", "name", "FOREIGN"), ("doc", "doctype", "POS Invoice"),
    ("company", "name", "FOREIGN"), ("company", "doctype", "Customer")])
def test_saved_identity_mismatch_cannot_authorize_a_different_row(access, endpoint, subject, field, value):
    setattr(getattr(access, subject), field, value)
    denied(access, endpoint)
    access.runtime.get_all.assert_not_called()


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_private_loader_exception_does_not_escape(access, endpoint):
    access.runtime.get_doc.side_effect = RuntimeError("PRIVATE database/credential detail")
    denied(access, endpoint)
    access.runtime.get_all.assert_not_called()


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_unreadable_file_blocks_inspection_without_silent_fallback(access, endpoint):
    access.decisions["File", "read"] = False
    denied(access, endpoint)
    assert access.acl[-1][:2] == ("File", "read")


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("field,value", [("attached_to_doctype", "POS Invoice"), ("attached_to_name", "FOREIGN"),
    ("file_url", "/private/files/FOREIGN.png"), ("file_name", "DIFFERENT.xml"),
    ("attached_to_field", "different_field"), ("name", "FOREIGN")])
def test_owned_file_and_projection_must_match_exactly(access, endpoint, field, value):
    setattr(access.file, field, value)
    denied(access, endpoint)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("shape", ["limit", "missing", "row_type", "collection_type"])
def test_file_projection_is_bounded_and_complete(access, endpoint, shape):
    if shape == "limit":
        access.runtime.get_all.return_value = [access.row] * (qr.MAX_FILE_OBSERVATIONS + 1)
    elif shape == "missing":
        access.runtime.get_all.return_value = [Row(name=access.file.name)]
    elif shape == "row_type":
        access.runtime.get_all.return_value = [None]
    else:
        access.runtime.get_all.return_value = None
    denied(access, endpoint)
    assert not any(event[:2] == ("load", "File") for event in access.events)


def test_preview_uses_read_acl_only_and_quiet_version_keyword(access):
    assert invoke(access, "get_qr_regeneration_state") == {
        "eligible": False, "action": "REVIEW", "reason": qr.REVIEW_MESSAGE}
    assert [(dt, op) for dt, op, *_ in access.acl] == [("Sales Invoice", "read"), ("Company", "read"), ("File", "read")]
    assert all(user == access.actor and quiet is False for _, _, _, user, quiet in access.acl)
    query = access.runtime.get_all.call_args.kwargs
    assert query["filters"] == {"attached_to_doctype": "Sales Invoice", "attached_to_name": access.doc.name}
    assert query["limit_page_length"] == qr.MAX_FILE_OBSERVATIONS + 1
    access.runtime.db.exists.assert_not_called()
    access.runtime.get_cached_doc.assert_not_called()
    no_writes(access)


def test_readable_file_without_write_acl_can_be_preserved_without_any_write(access):
    access.decisions["File", "write"] = False
    access.doc.ksa_einv_qr = access.file.file_url
    assert invoke(access, "regenerate_qr")["status"] == "preserved"
    assert ("File", "write") not in [(dt, op) for dt, op, *_ in access.acl]
    no_writes(access)


def test_file_write_privilege_does_not_authorize_implicit_relink(access):
    access.decisions["File", "write"] = True
    with pytest.raises(Denied, match=qr.REVIEW_MESSAGE):
        invoke(access, "regenerate_qr")
    assert ("File", "write") not in [(dt, op) for dt, op, *_ in access.acl]
    no_writes(access)


def test_owned_current_reference_is_preserved_without_legacy_commit(access):
    access.doc.ksa_einv_qr = access.file.file_url
    result = invoke(access, "regenerate_qr")
    assert result["status"] == "preserved" and result["file_url"] == access.file.file_url
    assert [(dt, op) for dt, op, *_ in access.acl][:3] == [
        ("Sales Invoice", "read"), ("Sales Invoice", "write"), ("Company", "read")]
    assert access.events.count(("load", "Sales Invoice", access.doc.name)) == 1
    no_writes(access)
    access.reader.assert_not_called()


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_actor_change_during_acl_stops_before_next_row_or_side_effect(access, endpoint):
    def change_actor():
        access.runtime.session.user = "OTHER-USER"
        return True
    access.decisions["Sales Invoice", "read"] = change_actor
    denied(access, endpoint)
    assert len(access.acl) == 1
    access.runtime.get_all.assert_not_called()


def configure_xml(case, monkeypatch):
    case.file.file_name = case.row["file_name"] = "SYNTHETIC-REPORTED.xml"
    case.company.custom_zatca_phase = "Phase-2"


def test_phase2_file_denial_stops_without_xml_parser_fallback(access, monkeypatch):
    configure_xml(access, monkeypatch)
    access.decisions["File", "read"] = False
    denied(access, "get_qr_regeneration_state")


def test_phase2_preview_does_not_read_xml_even_with_saved_file_acl(access, monkeypatch):
    configure_xml(access, monkeypatch)
    assert invoke(access, "get_qr_regeneration_state")["action"] == "REVIEW"
    access.opener.assert_not_called()
    access.reader.assert_not_called()
    access.parser.assert_not_called()
    assert [op for dt, op, *_ in access.acl if dt == "File"] == ["read"]
    no_writes(access)


@pytest.mark.parametrize("status", ["REPORTED", "Phase-1 QR Generated"])
def test_status_hint_does_not_authorize_xml_reconstruction(access, monkeypatch, status):
    configure_xml(access, monkeypatch)
    access.doc.custom_zatca_status = status
    with pytest.raises(Denied) as error:
        invoke(access, "regenerate_qr")
    assert str(error.value) == qr.REVIEW_MESSAGE and error.value.__context__ is None
    access.opener.assert_not_called()
    access.parser.assert_not_called()
    no_writes(access)


def test_mutation_is_registered_for_post_only_and_neither_endpoint_allows_guest():
    import frappe
    assert frappe.allowed_http_methods_for_whitelisted_func[qr.regenerate_qr] == ["POST"]
    assert qr.regenerate_qr not in frappe.guest_methods
    assert qr.get_qr_regeneration_state not in frappe.guest_methods


def test_global_file_url_presence_does_not_authorize_preview(access, monkeypatch):
    access.doc.ksa_einv_qr = "/files/FOREIGN.png"
    access.runtime.get_all.return_value = []
    assert invoke(access, "get_qr_regeneration_state")["eligible"] is False
    access.runtime.db.exists.assert_not_called()
    no_writes(access)


def test_denial_is_translated_without_private_error_context(access, monkeypatch):
    with (Path(__file__).resolve().parents[2] / "translations/ar.csv").open() as stream:
        entries = dict(csv.reader(stream))
    translation = entries[qr.DENIED_MESSAGE]
    assert translation != qr.DENIED_MESSAGE
    monkeypatch.setattr(qr, "_", lambda message: entries[message])
    access.decisions["Sales Invoice", "read"] = RuntimeError("PRIVATE secret")
    with pytest.raises(Denied) as error:
        invoke(access, "get_qr_regeneration_state")
    assert str(error.value) == translation and error.value.__context__ is None
    no_writes(access)


@pytest.mark.parametrize("filename", ["DEBUG-NEW.xml", "QR-Phase2-CLEARED-NEW.png", "ordinary.pdf"])
@pytest.mark.parametrize("status", ["Not Submitted", "REPORTED", "Phase-1 QR Generated"])
def test_current_owned_qr_wins_without_newest_file_or_status_ranking(access, filename, status):
    access.doc.ksa_einv_qr, access.doc.custom_zatca_status = access.file.file_url, status
    newer = Document(**vars(access.file))
    newer.name, newer.file_name, newer.file_url = "NEWER", filename, "/files/NEWER"
    access.documents["File", newer.name] = newer
    projection = Row({field: newer.get(field) for field in qr.ATTACHMENT_FIELDS})
    for rows in ([projection, access.row], [access.row, projection]):
        access.runtime.get_all.return_value = rows
        assert invoke(access, "regenerate_qr")["file_url"] == access.file.file_url
    no_writes(access)
    access.reader.assert_not_called()


@pytest.mark.parametrize("clock", [None, timedelta(0), "INVALID-PRIVATE-TIME"])
def test_preservation_does_not_reinterpret_current_time_or_company_tax_id(access, clock):
    access.doc.ksa_einv_qr, access.doc.posting_time = access.file.file_url, clock
    access.doc.posting_date, access.company.tax_id = None, None
    assert invoke(access, "regenerate_qr")["status"] == "preserved"
    no_writes(access)


@pytest.mark.parametrize("filename", [None, "DEBUG.xml", "REPORTED.xml", "CLEARED.xml", "QR-ONLY.png"])
def test_absent_original_never_falls_back_to_invoice_values_or_xml_filename(access, filename):
    if filename is None:
        access.runtime.get_all.return_value = []
    else:
        access.file.file_name = access.row["file_name"] = filename
    current = access.doc.ksa_einv_qr
    with pytest.raises(Denied) as error:
        invoke(access, "regenerate_qr")
    assert str(error.value) == qr.REVIEW_MESSAGE and error.value.__context__ is None
    assert access.doc.ksa_einv_qr == current
    no_writes(access)
    access.reader.assert_not_called()
    access.parser.assert_not_called()
    access.opener.assert_not_called()


@pytest.mark.parametrize("gate", ["draft", "cancelled", "disabled"])
def test_unavailable_paths_do_not_inspect_or_change_attachments(access, monkeypatch, gate):
    if gate == "disabled":
        monkeypatch.setattr(qr, "is_zatca_invoice_enabled", lambda doc: False)
    else:
        access.doc.docstatus = 0 if gate == "draft" else 2
    assert invoke(access, "get_qr_regeneration_state")["action"] == "UNAVAILABLE"
    access.runtime.get_all.assert_not_called()
    no_writes(access)


def test_review_and_preservation_messages_are_arabic_when_selected(access, monkeypatch):
    with (Path(__file__).resolve().parents[2] / "translations/ar.csv").open() as stream:
        translations = dict(csv.reader(stream))
    for key in (qr.REVIEW_MESSAGE, qr.PRESERVED_MESSAGE, "Review QR Code"):
        assert translations[key] != key
    monkeypatch.setattr(qr, "_", lambda message: translations[message])
    assert invoke(access, "get_qr_regeneration_state")["reason"] == translations[qr.REVIEW_MESSAGE]
    access.doc.ksa_einv_qr = access.file.file_url
    assert invoke(access, "regenerate_qr")["message"] == translations[qr.PRESERVED_MESSAGE]
    no_writes(access)


def test_recovery_module_has_no_content_io_mutation_or_transaction_calls():
    tree = ast.parse(inspect.getsource(qr))
    forbidden = {"set_value", "db_set", "save", "commit", "rollback", "delete_doc",
        "get_file_path", "save_file", "create_qr_code", "open", "_extract_qr_payload_from_xml"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else (
                node.func.id if isinstance(node.func, ast.Name) else None)
            assert name not in forbidden
    js = (Path(__file__).resolve().parents[2] / "public/js/our_sales_invoice.js").read_text()
    assert 'state.message.action === "REVIEW"' in js
    assert '__("Review QR Code")' in js
    assert "qr_regeneration.regenerate_qr" not in js
