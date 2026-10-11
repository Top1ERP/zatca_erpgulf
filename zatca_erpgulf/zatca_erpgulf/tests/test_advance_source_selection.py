"""Synthetic archive choice; observations are deliberately NOT authority proof."""

import base64
from dataclasses import FrozenInstanceError, replace
import json
from unittest.mock import Mock

from lxml import etree
import pytest

from zatca_erpgulf.zatca_erpgulf import advance_source_selection as selection
from zatca_erpgulf.zatca_erpgulf.dispatch_journal import DispatchJournal, append_dispatch_event
from zatca_erpgulf.zatca_erpgulf.artifact_evidence import NS
from zatca_erpgulf.zatca_erpgulf.tests.test_artifact_evidence import OTHER_UUID, node, xml_bytes
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_dispatch_journal import event, start
from zatca_erpgulf.zatca_erpgulf.tests.test_issuance_candidate import candidate, scope
from zatca_erpgulf.zatca_erpgulf.tests.test_response_assessment import assess, body


def advance(der, *, indicator="0200000", environment="Production", doctype="Sales Invoice",
            day="2026-09-27", clock="00:05:42+03:00", code="386"):
    prepared = candidate(der, selected_scope=scope(environment=environment, doctype=doctype),
                         code=code, indicator=indicator)
    root = etree.fromstring(prepared.xml_bytes)
    node(root, "cbc", "IssueDate", day)
    node(root, "cbc", "IssueTime", clock)
    return replace(prepared, xml_bytes=xml_bytes(root))


@pytest.fixture(scope="module")
def prepared(certificates):
    return advance(certificates[0])


def select(observed_journal, **changes):
    values = dict(journal=observed_journal, expected_context=observed_journal.candidate.context,
        expected_uuid=observed_journal.candidate.artifact.uuid, expected_icv=observed_journal.candidate.artifact.icv,
        expected_journal_sha256=observed_journal.journal_sha256)
    values.update(changes)
    return selection.ArchivedAdvanceSource(**values)


def receipt(prepared, **changes):
    return assess(prepared, **changes).journal


def changed_return(prepared, field="Note", value="PRIVATE-RETURNED-ONLY"):
    root = etree.fromstring(prepared.xml_bytes)
    root.find("cbc:" + field, NS).text = value
    return xml_bytes(root)


def response_with_xml(prepared, returned):
    field = "clearedInvoice" if prepared.invoice_type_indicator.startswith("01") else "reportedInvoice"
    return body(prepared, **{field: base64.b64encode(returned).decode()})


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("status", [200, 202])
def test_exact_declared_environment_endpoint_choice_and_warning_preservation(certificates, environment, indicator, status):
    original = advance(certificates[0], environment=environment, indicator=indicator)
    returned = changed_return(original)
    journal = receipt(original, status=status, response=response_with_xml(original, returned))
    selected = select(journal)
    is_clearance = indicator.startswith("01")
    assert selected.source_kind == ("CLEARANCE_RETURNED_XML" if is_clearance else "REPORTING_REQUEST_XML")
    assert selected.xml_bytes == (returned if is_clearance else original.xml_bytes)
    assert selected.has_warnings is (status == 202)
    assert selected.reference.issue_date == "2026-09-27"
    assert selected.reference.issue_time == "00:05:42+03:00"
    report = selected.diagnostic_projection()
    assert all(value is False for key, value in report.items() if key.endswith(("_verified", "_authorized")))
    assert "PRIVATE" not in repr(selected) and "PRIVATE" not in json.dumps(report)
    assert "gateway.invalid" not in repr(selected) and original.xml_bytes.decode() not in repr(selected)


def test_reporting_without_optional_returned_xml_always_uses_exact_request(prepared):
    selected = select(receipt(prepared))
    assert selected.xml_bytes is prepared.xml_bytes
    assert selected.reference.file_sha256 == prepared.artifact.file_sha256


@pytest.mark.parametrize("field", ["source_kind", "xml_bytes", "reference", "assessment_sha256", "has_warnings", "expected_context"])
def test_observation_frozen_and_derived_fields_not_caller_claims(prepared, field):
    selected = select(receipt(prepared))
    with pytest.raises(FrozenInstanceError):
        setattr(selected, field, None)
    if field != "expected_context":
        with pytest.raises(TypeError):
            select(receipt(prepared), **{field: None})


@pytest.mark.parametrize("field,value,code", [
    ("journal", None, "advance_source_journal"),
    ("journal", {"status": "REPORTED"}, "advance_source_journal"),
    ("expected_context", {}, "advance_source_context"),
    ("expected_uuid", None, "advance_source_uuid"),
    ("expected_uuid", "PRIVATE-UUID", "advance_source_uuid"),
    ("expected_uuid", OTHER_UUID, "advance_source_uuid_mismatch"),
    ("expected_icv", True, "advance_source_icv"),
    ("expected_icv", "77", "advance_source_icv"),
    ("expected_icv", 0, "advance_source_icv"),
    ("expected_icv", 10**64, "advance_source_icv"),
    ("expected_icv", 78, "advance_source_icv_mismatch"),
    ("expected_journal_sha256", None, "advance_source_revision"),
    ("expected_journal_sha256", "PRIVATE-HASH", "advance_source_revision"),
    ("expected_journal_sha256", "f" * 64, "advance_source_revision_mismatch"),
])
def test_exact_expected_input_no_defaults_or_success_dictionaries(prepared, field, value, code):
    with pytest.raises(selection.AdvanceSourceSelectionError) as error:
        select(receipt(prepared), **{field: value})
    assert str(error.value) == code and error.value.__context__ is None


@pytest.mark.parametrize("field,value", [("company_name", "OTHER"), ("invoice_name", "OTHER"),
    ("seller_tax_id", "300000000000013"), ("legacy_issuing_unit", "OTHER"),
    ("chain_id", "01234567-1234-4123-8123-123456789abc"), ("issuance_version", 2),
    ("doctype", "POS Invoice")])
def test_scope_drift_cannot_select_same_identity_from_wrong_archive_context(prepared, field, value):
    expected = replace(prepared.context, scope=replace(prepared.context.scope, **{field: value}))
    with pytest.raises(selection.AdvanceSourceSelectionError, match="advance_source_context_mismatch"):
        select(receipt(prepared), expected_context=expected)


@pytest.mark.parametrize("field", ["source_snapshot", "credential_version", "credential_owner", "route"])
def test_snapshot_credential_and_route_are_pinned_not_latest_settings(prepared, field):
    context = prepared.context
    if field == "source_snapshot":
        context = replace(context, source_snapshot_sha256="f" * 64)
    elif field == "credential_version":
        context = replace(context, credential_epoch=replace(context.credential_epoch,
            version_id="01234567-1234-4123-8123-123456789abc"))
    elif field == "credential_owner":
        context = replace(context, credential_epoch=replace(context.credential_epoch, owner_name="OTHER"))
    else:
        context = replace(context, route=replace(context.route, url="https://other.invalid/invoices/reporting/single"))
    with pytest.raises(selection.AdvanceSourceSelectionError, match="advance_source_context_mismatch"):
        select(receipt(prepared), expected_context=context)


@pytest.mark.parametrize("status", [201, 204, 303, 400, 401, 403, 406, 409, 500, 503])
def test_http_success_shaped_body_does_not_override_unconfirmed_attempt(prepared, status):
    with pytest.raises(selection.AdvanceSourceSelectionError, match="advance_source_response_unconfirmed"):
        select(receipt(prepared, status=status))


@pytest.mark.parametrize("state", ["empty", "started", "unknown", "bad_body", "rejected"])
def test_missing_unknown_malformed_rejected_receipts_do_not_select_request_as_accepted(prepared, state):
    if state == "empty":
        journal = DispatchJournal(prepared)
    elif state == "started":
        journal = start(prepared)
    elif state == "unknown":
        journal = append_dispatch_event(start(prepared), event(prepared, "TRANSPORT_UNKNOWN", 2))
    elif state == "bad_body":
        journal = receipt(prepared, raw=b"PRIVATE-RESPONSE")
    else:
        journal = receipt(prepared, status=400, response=body(prepared, reportingStatus="NOT_REPORTED",
            validationResults={"status": "ERROR", "errorMessages": [{}]}))
    with pytest.raises(selection.AdvanceSourceSelectionError) as error:
        select(journal)
    assert str(error.value) == "advance_source_response_unconfirmed" and error.value.__context__ is None


@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("field,value", [("IssueDate", "2026-09-28"), ("IssueTime", "00:05:43+03:00"),
    ("IssueTime", "21:05:42Z"), ("IssueTime", "00:05:42.000000+03:00")])
def test_returned_clock_drift_rejected_even_when_generic_assessment_acceptance_matches(certificates, indicator, field, value):
    original = advance(certificates[0], indicator=indicator)
    response = response_with_xml(original, changed_return(original, field, value))
    observed = assess(original, response=response)
    assert observed.outcome.endswith("ACCEPTANCE_MATCHED") and observed.issues == ()
    with pytest.raises(selection.AdvanceSourceSelectionError, match="advance_source_returned_clock_mismatch"):
        select(observed.journal)


@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("field", ["IssueDate", "IssueTime"])
def test_missing_duplicate_or_invalid_returned_clock_never_falls_back(certificates, indicator, field):
    original = advance(certificates[0], indicator=indicator)
    for mutation in ("missing", "duplicate", "invalid"):
        root = etree.fromstring(original.xml_bytes)
        item = root.find("cbc:" + field, NS)
        if mutation == "missing":
            root.remove(item)
        elif mutation == "duplicate":
            node(root, "cbc", field, item.text)
        else:
            item.text = "PRIVATE-INVALID-CLOCK"
        journal = receipt(original, response=response_with_xml(original, xml_bytes(root)))
        with pytest.raises(selection.AdvanceSourceSelectionError) as error:
            select(journal)
        assert error.value.code.startswith("reference_") and error.value.__context__ is None


def test_clearance_requires_returned_artifact_never_request_fallback(certificates):
    original = advance(certificates[0], indicator="0100000")
    response = body(original)
    del response["clearedInvoice"]
    with pytest.raises(selection.AdvanceSourceSelectionError, match="advance_source_response_unconfirmed"):
        select(receipt(original, response=response))


@pytest.mark.parametrize("code", ["388", "381", "383"])
def test_not_advance_original_rejected(certificates, code):
    with pytest.raises(selection.AdvanceSourceSelectionError, match="advance_source_type"):
        select(receipt(advance(certificates[0], code=code)))


def test_pos_advance_outside_current_sales_allocation_contract(certificates):
    with pytest.raises(selection.AdvanceSourceSelectionError, match="advance_source_doctype"):
        select(receipt(advance(certificates[0], doctype="POS Invoice")))


def test_late_response_requires_exact_later_journal_revision(prepared):
    started = start(prepared)
    unknown = append_dispatch_event(started, event(prepared, "TRANSPORT_UNKNOWN", 2))
    late = receipt(prepared, late=True)
    with pytest.raises(selection.AdvanceSourceSelectionError, match="advance_source_revision_mismatch"):
        select(late, expected_journal_sha256=unknown.journal_sha256)
    assert select(late).source_kind == "REPORTING_REQUEST_XML"


def test_recompute_assessment_no_file_or_site_discovery(prepared, monkeypatch):
    import frappe
    forbidden = Mock(side_effect=AssertionError("No current site/file/config/default lookup"))
    for name in ("get_doc", "get_all", "get_site_path", "get_system_settings", "init", "connect"):
        monkeypatch.setattr(frappe, name, forbidden)
    journal = receipt(prepared)
    selected = select(journal)
    report = selected.diagnostic_projection()
    report["settlement_authorized"] = True
    assert selected.diagnostic_projection()["settlement_authorized"] is False
    assert selected.journal is journal and selected.reference.issue_time == "00:05:42+03:00"
    forbidden.assert_not_called()
