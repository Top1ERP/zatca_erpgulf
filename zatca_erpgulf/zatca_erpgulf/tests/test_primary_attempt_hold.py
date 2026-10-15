"""Logical-invoice hold tests; all identities/material/SQL are synthetic."""

from dataclasses import FrozenInstanceError, replace
import inspect
import json
import pickle
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from lxml import etree
import pytest

from zatca_erpgulf.zatca_erpgulf import primary_attempt_hold as holds
from zatca_erpgulf.zatca_erpgulf.api_routing import ENVIRONMENT_FIELDS, resolve_api_route
from zatca_erpgulf.zatca_erpgulf.artifact_evidence import NS
from zatca_erpgulf.zatca_erpgulf.dispatch_journal import DispatchJournal, append_dispatch_event
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_dispatch_journal import event, start
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository import NAMESPACE, prepared
from zatca_erpgulf.zatca_erpgulf.tests.test_issuance_candidate import candidate


def variant(prepared, certificates, change):
    """Valid local declarations, never evidence of a genuine signing/epoch flow."""
    context = prepared.context
    if change == "certificate":
        return candidate(certificates[1])
    if change == "indicator":
        return candidate(certificates[0], indicator="0100000")
    if change == "environment":
        return candidate(certificates[0], selected_scope=replace(context.scope, environment="Simulation"))
    if change in ("uuid", "icv"):
        root = etree.fromstring(prepared.xml_bytes)
        if change == "uuid":
            root.find("cbc:UUID", namespaces=NS).text = str(uuid4())
        else:
            root.xpath("./cac:AdditionalDocumentReference[cbc:ID='ICV']/cbc:UUID", namespaces=NS)[0].text = "78"
        return replace(prepared, xml_bytes=etree.tostring(root, encoding="UTF-8", xml_declaration=True))
    if change == "version":
        context = replace(context, scope=replace(context.scope, issuance_version=2))
    elif change == "chain":
        context = replace(context, scope=replace(context.scope, chain_id=str(uuid4())))
    elif change == "unit":
        context = replace(context, scope=replace(context.scope, legacy_issuing_unit="another-unit"))
    elif change == "epoch":
        context = replace(context, credential_epoch=replace(context.credential_epoch, version_id=str(uuid4())))
    elif change == "owner":
        context = replace(context, credential_epoch=replace(context.credential_epoch, owner_name="OTHER"))
    elif change == "source":
        context = replace(context, source_snapshot_sha256="0" * 64)
    elif change == "route":
        route = resolve_api_route({"custom_select": context.scope.environment,
            ENVIRONMENT_FIELDS[context.scope.environment]: "https://changed.invalid/phase2"}, context.route.endpoint)
        context = replace(context, route=route)
    else:
        raise AssertionError("Unreviewed synthetic change")
    return replace(prepared, context=context)


def scenario(monkeypatch, started):
    expected = holds._declaration(NAMESPACE, started)
    cursor = Mock()
    cursor.__enter__, cursor.__exit__ = Mock(return_value=cursor), Mock(return_value=False)
    connection = SimpleNamespace(cursor=Mock(return_value=cursor), commit=Mock(), rollback=Mock(), close=Mock())
    case = SimpleNamespace(started=started, expected=expected, cursor=cursor, connection=connection,
        current=DispatchJournal(started.candidate), autocommit=(0,), row=expected)
    def execute(sql, values=None):
        if sql == "SELECT @@session.autocommit":
            cursor.fetchone.return_value = case.autocommit
        elif sql.startswith("INSERT INTO zatca_primary_attempt_hold_v1"):
            assert "ON DUPLICATE" not in sql and values == tuple(vars(expected).values())
        elif sql.startswith("SELECT candidate_sha256"):
            assert "FOR UPDATE" in sql and values == (NAMESPACE, expected.source_sha256)
            cursor.fetchone.return_value = None if case.row is None else tuple(getattr(case.row, name) for name in
                ("candidate_sha256", "manifest_sha256", "attempt_id", "started_journal_sha256"))
        else:
            raise AssertionError("Unreviewed SQL")
    cursor.execute.side_effect = execute
    case.journal = Mock()
    case.journal.load.side_effect = lambda key: case.current
    def append(key, supplied, *, expected_journal_sha256):
        assert key == started.candidate.key_sha256 and supplied == started.events[0]
        assert expected_journal_sha256 == DispatchJournal(started.candidate).journal_sha256
        case.current = started
        return started
    case.journal.append.side_effect = append
    case.journal_factory = Mock(return_value=case.journal)
    monkeypatch.setattr(holds, "MariaDBJournalRepository", case.journal_factory)
    case.repository = holds.MariaDBPrimaryAttemptHoldRepository(connection, NAMESPACE)
    return case


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("code", ["388", "381", "383", "386"])
def test_explicit_start_and_hold_share_exact_transaction_without_authorizing_dispatch(certificates, monkeypatch, doctype, indicator, code):
    from zatca_erpgulf.zatca_erpgulf.tests.test_issuance_candidate import scope
    selected = candidate(certificates[0], selected_scope=scope(doctype=doctype), indicator=indicator, code=code)
    case = scenario(monkeypatch, start(selected))
    result = case.repository.reserve(case.started)
    assert result == case.expected and case.current == case.started
    case.journal_factory.assert_called_once_with(case.connection, NAMESPACE)
    assert case.repository.load(case.started) == result
    report = result.diagnostic_projection()
    assert all(value is False for key, value in report.items() if key.endswith(("_verified", "_authorized")))
    assert "INV-TEST" not in json.dumps(report) and NAMESPACE not in repr(result)
    for method in (case.connection.commit, case.connection.rollback, case.connection.close):
        method.assert_not_called()


@pytest.mark.parametrize("change", ["version", "chain", "unit", "epoch", "owner", "source", "route", "uuid", "icv",
    "certificate", "environment", "indicator"])
def test_logical_source_key_cannot_be_reset_by_new_preparation(prepared, certificates, change):
    other = variant(prepared, certificates, change)
    assert holds._started_journal(start(other)) == start(other)
    assert other != prepared
    assert holds._source_sha256(other) == holds._source_sha256(prepared)


@pytest.mark.parametrize("code", ["381", "383", "386"])
def test_classification_change_cannot_reset_the_logical_document_hold(prepared, certificates, code):
    changed = candidate(certificates[0], code=code)
    assert changed.invoice_type_code == code
    assert holds._source_sha256(changed) == holds._source_sha256(prepared)


@pytest.mark.parametrize("changed", ["company", "doctype", "invoice"])
def test_different_saved_source_has_different_logical_key(prepared, certificates, changed):
    context = prepared.context
    changes = {"company": {"company_name": "ANOTHER"}, "doctype": {"doctype": "POS Invoice"},
        "invoice": {"invoice_name": "INV-OTHER"}}[changed]
    other = candidate(certificates[0], selected_scope=replace(context.scope, **changes))
    assert holds._source_sha256(other) != holds._source_sha256(prepared)


@pytest.mark.parametrize("unknown", [False, True])
@pytest.mark.parametrize("status", [200, 202, 400, 401, 403, 406, 409, 500, 599])
def test_later_http_or_unknown_never_releases_original_hold(prepared, monkeypatch, unknown, status):
    started = start(prepared)
    case = scenario(monkeypatch, started)
    case.repository.reserve(started)
    if unknown:
        case.current = append_dispatch_event(case.current, event(prepared, "TRANSPORT_UNKNOWN", 2))
    case.current = append_dispatch_event(case.current, event(prepared, "HTTP_RESPONSE", len(case.current.events) + 1,
        http_status=status, response_bytes=b"SYNTHETIC ONLY"))
    assert case.repository.load(started) == case.expected
    with pytest.raises(holds.PrimaryAttemptHoldError, match="primary_hold_journal_not_empty"):
        case.repository.reserve(started)
    assert case.journal.append.call_count == 1


@pytest.mark.parametrize("invalid", [None, {}, True, "PRIVATE"])
@pytest.mark.parametrize("operation", ["reserve", "load"])
def test_bad_input_never_reaches_sql(prepared, monkeypatch, invalid, operation):
    case = scenario(monkeypatch, start(prepared))
    with pytest.raises(holds.PrimaryAttemptHoldError, match="primary_hold_input") as error:
        getattr(case.repository, operation)(invalid)
    assert error.value.__context__ is None
    case.connection.cursor.assert_not_called()
    case.journal_factory.assert_not_called()


@pytest.mark.parametrize("fault", ["empty", "unknown", "response", "hash", "state", "event", "candidate"])
def test_changed_or_nonstart_journal_cannot_reserve(prepared, monkeypatch, fault):
    started = start(replace(prepared))
    case = scenario(monkeypatch, started)
    if fault == "empty":
        supplied = DispatchJournal(prepared)
    elif fault in ("unknown", "response"):
        supplied = append_dispatch_event(started, event(prepared,
            "TRANSPORT_UNKNOWN" if fault == "unknown" else "HTTP_RESPONSE", 2))
    else:
        supplied = started
        if fault == "hash":
            object.__setattr__(supplied, "journal_sha256", "0" * 64)
        elif fault == "state":
            object.__setattr__(supplied, "state", "PREPARED_CANDIDATE")
        elif fault == "event":
            object.__setattr__(supplied.events[0], "sequence", 2)
        else:
            object.__setattr__(supplied.candidate, "manifest_sha256", "0" * 64)
    with pytest.raises(holds.PrimaryAttemptHoldError, match="primary_hold_input"):
        case.repository.reserve(supplied)
    case.connection.cursor.assert_not_called()


@pytest.mark.parametrize("fault", ["autocommit", "bool-autocommit", "existing-start", "append", "missing", "conflict", "sql", "interrupt"])
def test_any_failure_poisoned_transaction_requires_caller_rollback_without_retry(prepared, monkeypatch, fault):
    case = scenario(monkeypatch, start(prepared))
    exception = holds.PrimaryAttemptHoldError
    if fault in ("autocommit", "bool-autocommit"):
        case.autocommit = (1,) if fault == "autocommit" else (False,)
    elif fault == "existing-start":
        case.current = case.started
    elif fault == "append":
        case.journal.append.side_effect = lambda *args, **kwargs: DispatchJournal(prepared)
    elif fault == "missing":
        case.row = None
    elif fault == "conflict":
        case.row = replace(case.expected, attempt_id=str(uuid4()))
    else:
        exception = KeyboardInterrupt if fault == "interrupt" else holds.PrimaryAttemptHoldError
        case.cursor.execute.side_effect = KeyboardInterrupt() if fault == "interrupt" else RuntimeError("PRIVATE SQL")
    with pytest.raises(exception) as error:
        case.repository.reserve(case.started)
    if fault != "interrupt":
        assert error.value.__context__ is None and "PRIVATE" not in str(error.value)
    before = case.cursor.execute.call_count
    with pytest.raises(holds.PrimaryAttemptHoldError, match="primary_hold_transaction_unusable"):
        case.repository.load(case.started)
    assert case.cursor.execute.call_count == before
    for method in (case.connection.commit, case.connection.rollback, case.connection.close):
        method.assert_not_called()


@pytest.mark.parametrize("fault", ["missing-start", "different-start", "different-candidate", "missing-hold", "conflicting-hold"])
def test_inspection_never_adopts_or_repairs_a_different_journal(prepared, monkeypatch, certificates, fault):
    case = scenario(monkeypatch, start(prepared))
    case.current = case.started
    if fault == "missing-start":
        case.current = DispatchJournal(prepared)
    elif fault == "different-start":
        case.current = replace(case.started, events=(replace(case.started.events[0], event_id=str(uuid4())),))
    elif fault == "different-candidate":
        case.current = start(variant(prepared, certificates, "version"))
    elif fault == "missing-hold":
        case.row = None
    else:
        case.row = replace(case.expected, started_journal_sha256="0" * 64)
    with pytest.raises(holds.PrimaryAttemptHoldError) as error:
        case.repository.load(case.started)
    assert error.value.__context__ is None
    case.journal.append.assert_not_called()
    assert not any(call.args[0].startswith("INSERT") for call in case.cursor.execute.call_args_list)


@pytest.mark.parametrize("invalid", [None, {}, NAMESPACE.upper(), "00000000-0000-0000-0000-000000000000"])
def test_namespace_is_explicit_and_canonical(invalid):
    connection = Mock()
    with pytest.raises(holds.PrimaryAttemptHoldError, match="primary_hold_namespace"):
        holds.MariaDBPrimaryAttemptHoldRepository(connection, invalid)
    connection.cursor.assert_not_called()


def test_objects_are_hidden_frozen_and_nonpickleable(prepared, monkeypatch):
    case = scenario(monkeypatch, start(prepared))
    for value in (case.expected, case.repository):
        assert "INV-TEST" not in repr(value) and NAMESPACE not in repr(value)
        with pytest.raises(holds.PrimaryAttemptHoldError, match="not_pickleable"):
            pickle.dumps(value)
    with pytest.raises(FrozenInstanceError):
        case.expected.attempt_id = str(uuid4())


def test_no_dispatch_or_activation_transaction_ownership_release_or_current_config_discovery():
    source = inspect.getsource(holds)
    for forbidden in ("import frappe", "import requests", "@frappe.whitelist", "CREATE TABLE", "DELETE FROM",
        "ON DUPLICATE", ".commit(", ".rollback(", ".close(", "get_doc(", "utcnow(", "get_password("):
        assert forbidden not in source
