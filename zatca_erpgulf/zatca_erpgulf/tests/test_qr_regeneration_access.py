"""Saved-row QR endpoint access with synthetic ERP/File/IO only.

Signature-shaped v15/v16 ACL engines are not installed v16 acceptance. Authorized
legacy selection/commits are characterized, not endorsed as a repair contract.
"""

import csv
import inspect
import io
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
    monkeypatch.setattr(qr, "resolve_zatca_phase", lambda doc: "Phase-1")
    reader = Mock(side_effect=AssertionError("No real path or physical file read"))
    parser = Mock(side_effect=AssertionError("No real XML parse"))
    saver = Mock(side_effect=AssertionError("No physical file save"))
    generator = Mock(side_effect=AssertionError("No real QR generation"))
    opener = Mock(side_effect=AssertionError("No physical file open"))
    monkeypatch.setattr(qr, "get_file_path", reader)
    monkeypatch.setattr(qr, "_extract_qr_payload_from_xml", parser)
    monkeypatch.setattr(qr, "save_file", saver)
    monkeypatch.setattr(qr, "create_qr_code", generator)
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
    ("attached_to_field", "different_field"), ("creation", "2020-01-01")])
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
    assert invoke(access, "get_qr_regeneration_state") == {"eligible": True}
    assert [(dt, op) for dt, op, *_ in access.acl] == [("Sales Invoice", "read"), ("Company", "read"), ("File", "read")]
    assert all(user == access.actor and quiet is False for _, _, _, user, quiet in access.acl)
    query = access.runtime.get_all.call_args.kwargs
    assert query["filters"] == {"attached_to_doctype": "Sales Invoice", "attached_to_name": access.doc.name}
    assert query["limit_page_length"] == qr.MAX_FILE_OBSERVATIONS + 1
    access.runtime.db.exists.assert_not_called()
    access.runtime.get_cached_doc.assert_not_called()
    no_writes(access)


def test_readable_file_without_write_acl_cannot_be_relinked(access):
    access.decisions["File", "write"] = False
    denied(access, "regenerate_qr")
    assert access.acl[-1][:2] == ("File", "write")


def test_selected_file_write_permission_is_rechecked_before_save(access):
    decisions = iter((True, False))
    access.decisions["File", "write"] = lambda: next(decisions)
    denied(access, "regenerate_qr")
    assert [op for dt, op, *_ in access.acl if dt == "File"].count("write") == 2


def test_authorized_legacy_relink_checks_saved_file_write_but_still_commits(access):
    # Characterize, not endorse, the legacy selector and explicit commit. The
    # next bounded change must replace those policies; this is NOT adoption.
    result = invoke(access, "regenerate_qr")
    assert result["status"] == "relinked" and result["file_url"] == access.file.file_url
    assert [(dt, op) for dt, op, *_ in access.acl][:3] == [
        ("Sales Invoice", "read"), ("Sales Invoice", "write"), ("Company", "read")]
    assert ("File", "write") in [(dt, op) for dt, op, *_ in access.acl]
    assert access.events.count(("load", "Sales Invoice", access.doc.name)) == 1
    access.file.save.assert_called_once_with(ignore_permissions=True)
    access.runtime.db.commit.assert_called_once()
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
    monkeypatch.setattr(qr, "resolve_zatca_phase", lambda doc: qr.PHASE_2_VALUE)


def test_phase2_recheck_denial_is_not_swallowed_by_parser_fallback(access, monkeypatch):
    configure_xml(access, monkeypatch)
    reads = iter((True, False))
    access.decisions["File", "read"] = lambda: next(reads)
    denied(access, "get_qr_regeneration_state")


def test_phase2_preview_reads_synthetic_memory_only_after_saved_file_acl(access, monkeypatch):
    configure_xml(access, monkeypatch)
    access.reader.side_effect, access.reader.return_value = None, "SYNTHETIC-PATH-NEVER-OPENED"
    access.opener.side_effect, access.opener.return_value = None, io.BytesIO(b"SYNTHETIC XML")
    access.parser.side_effect, access.parser.return_value = None, "SYNTHETIC-PAYLOAD"
    assert invoke(access, "get_qr_regeneration_state") == {"eligible": True}
    access.opener.assert_called_once_with("SYNTHETIC-PATH-NEVER-OPENED", "rb")
    assert [op for dt, op, *_ in access.acl if dt == "File"] == ["read", "read", "read"]
    no_writes(access)


@pytest.mark.parametrize("parser_raises", [False, True])
def test_phase2_actor_change_during_parser_cannot_be_swallowed(access, monkeypatch, parser_raises):
    configure_xml(access, monkeypatch)
    access.reader.side_effect, access.reader.return_value = None, "SYNTHETIC-MEMORY-PATH"
    access.opener.side_effect, access.opener.return_value = None, io.BytesIO(b"SYNTHETIC XML")
    def parse(content):
        access.runtime.session.user = "OTHER-USER"
        if parser_raises:
            raise RuntimeError("PRIVATE parser detail")
        return "SYNTHETIC-PAYLOAD"
    access.parser.side_effect = parse
    with pytest.raises(Denied) as error:
        invoke(access, "get_qr_regeneration_state")
    assert str(error.value) == qr.DENIED_MESSAGE and error.value.__context__ is None
    no_writes(access)


def test_mutation_is_registered_for_post_only_and_neither_endpoint_allows_guest():
    import frappe
    assert frappe.allowed_http_methods_for_whitelisted_func[qr.regenerate_qr] == ["POST"]
    assert qr.regenerate_qr not in frappe.guest_methods
    assert qr.get_qr_regeneration_state not in frappe.guest_methods


def test_global_file_url_presence_does_not_authorize_preview(access, monkeypatch):
    access.doc.ksa_einv_qr = "/files/FOREIGN.png"
    access.runtime.get_all.return_value = []
    monkeypatch.setattr(qr, "resolve_zatca_phase", lambda doc: qr.PHASE_2_VALUE)
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
