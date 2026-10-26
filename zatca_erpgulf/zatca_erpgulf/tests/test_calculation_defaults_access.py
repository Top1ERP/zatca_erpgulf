"""Permissioned protected defaults acquisition; synthetic saved ACL/SQL only."""

import csv
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta
from pathlib import Path
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import calculation_defaults as defaults
from zatca_erpgulf.zatca_erpgulf.tests.test_advance_source_access import operator, PermissionDenied, InspectionFailed
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults import row
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import Document

NOW = datetime(2026, 10, 27, 12, 0, 0)


@pytest.fixture(params=[15, 16])
def defaults_operator(operator, monkeypatch, request):
    def v15(dt, operation, *, doc, user, raise_exception=True):
        return operator.acl(dt, operation, doc=doc, user=user, raise_exception=raise_exception)
    def v16(dt, operation, *, doc, user, print_logs=True):
        return operator.acl(dt, operation, doc=doc, user=user, raise_exception=print_logs)
    monkeypatch.setattr(access, "frappe", operator.runtime)
    monkeypatch.setattr(access, "_", lambda text: text)
    monkeypatch.setattr(access, "has_permission", v15 if request.param == 15 else v16)
    operator.runtime.flags = {}
    operator.runtime.message_log = ["EXISTING-PARENT-MESSAGE"]
    def throw(message, exception=InspectionFailed):
        if not operator.runtime.flags.get("mute_messages"):
            operator.runtime.message_log.append(message)
        raise exception(message)
    operator.runtime.throw = Mock(side_effect=throw)
    return operator


def scenario(operator, *, doctype="Sales Invoice", parent_kind="site", docstatus=0):
    def document(dt, name, **values):
        doc = Document(doctype=dt, name=name, modified=NOW, **values)
        doc.save, doc.db_set, doc.check_permission = Mock(), Mock(), Mock()
        operator.documents[dt, name] = doc
        return doc

    company = document("Company", "SYNTHETIC-COMPANY")
    invoice = document(doctype, "SYNTHETIC-INVOICE", company=company.name, docstatus=docstatus)
    scope = access.CredentialStorageScope("private.test", "31234567-1234-4123-8123-123456789abc")
    parent = {"site": "__default", "global": "__global", "user": operator.runtime.session.user}[parent_kind]
    database = SimpleNamespace(rollback=Mock(), close=Mock(), commit=Mock(),
        defaults=[row(parent=parent)], on_execute=None)

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=()):
            operator.sql.append((sql, params))
            if sql == "SELECT @@session.autocommit": self.result = (0,)
            elif sql == defaults.READ_SQL:
                assert params == (parent, *defaults.KEYS, defaults.MAX_ROWS + 1)
                self.records = database.defaults
            else:
                assert "FOR UPDATE" in sql
                dt = sql.split("FROM `tab", 1)[1].split("`", 1)[0]
                doc = operator.documents[dt, params[-1]]
                selected = access.CalculationDefaultsSourceRow.from_document(doc)
                self.result = (selected.name, doc.modified, *selected.values)
            if database.on_execute: database.on_execute(sql, params)
        def fetchone(self): return self.result
        def fetchall(self): return self.records

    database.cursor = Mock(side_effect=Cursor)
    factory = Mock(return_value=database)
    cache = Mock(return_value={"currency_precision": "2"})
    service = access.SavedCalculationDefaultsService(scope, factory, cache, parent_kind=parent_kind)
    return SimpleNamespace(service=service, factory=factory, cache=cache, database=database,
        scope=scope, parent=parent, invoice=invoice, company=company)


def capture(case):
    return case.service.capture(case.invoice.name, doctype=case.invoice.doctype)


def untouched(operator, case):
    operator.runtime.db.commit.assert_not_called()
    operator.runtime.db.rollback.assert_not_called()
    case.database.commit.assert_not_called()
    for doc in operator.documents.values():
        doc.save.assert_not_called()
        doc.db_set.assert_not_called()
        doc.check_permission.assert_not_called()


def one_failure(operator, message):
    assert operator.runtime.message_log == ["EXISTING-PARENT-MESSAGE", message]
    assert "mute_messages" not in operator.runtime.flags


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("parent_kind", access.PARENT_KINDS)
@pytest.mark.parametrize("docstatus", [0, 1, 2])
def test_protected_saved_read_without_any_certificate_route_or_acceptance_fields(defaults_operator, doctype, parent_kind, docstatus):
    case = scenario(defaults_operator, doctype=doctype, parent_kind=parent_kind, docstatus=docstatus)
    result = capture(case)
    assert type(result) is access.SavedCalculationDefaultsRead
    assert result.actor == defaults_operator.runtime.session.user
    assert result.scope == case.scope and result.scope is not case.scope
    assert result.defaults.parent == case.parent
    result.defaults.require_cache_match(case.parent, {"currency_precision": "2"})
    assert [source.doctype for source in result.sources] == ["Company", doctype]
    case.factory.assert_called_once_with(case.scope)
    assert case.cache.call_args_list == [((case.scope, case.parent),)] * 2
    assert case.database.rollback.call_count == 2 and case.database.close.call_count == 1
    assert "SYNTHETIC" not in repr(result) and "NOT verified" in repr(result)
    with pytest.raises(FrozenInstanceError): result.actor = "other"
    for protected in (case.service, result):
        with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(protected)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("identity", [("Sales Invoice", "SYNTHETIC-INVOICE"), ("Company", "SYNTHETIC-COMPANY")])
def test_every_saved_read_acl_precedes_factory_and_cache_and_ignores_bypass_flags(defaults_operator, identity):
    case = scenario(defaults_operator)
    defaults_operator.denied.add(identity)
    defaults_operator.documents[identity].flags = SimpleNamespace(ignore_permissions=True)
    with pytest.raises(PermissionDenied) as caught: capture(case)
    assert str(caught.value) == access.DENIED_MESSAGE and caught.value.__context__ is None
    case.factory.assert_not_called()
    case.cache.assert_not_called()
    one_failure(defaults_operator, access.DENIED_MESSAGE)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("change", ["guest", "missing_actor", "role", "site"])
def test_actor_site_role_denial_before_any_source_or_dependency(defaults_operator, change):
    case = scenario(defaults_operator)
    if change == "guest": defaults_operator.runtime.session.user = "Guest"
    elif change == "missing_actor": defaults_operator.runtime.session.user = None
    elif change == "role": defaults_operator.runtime.get_roles.return_value = []
    else: defaults_operator.runtime.local.site = "other.test"
    with pytest.raises(PermissionDenied): capture(case)
    defaults_operator.runtime.get_doc.assert_not_called()
    case.factory.assert_not_called()
    case.cache.assert_not_called()
    one_failure(defaults_operator, access.DENIED_MESSAGE)


@pytest.mark.parametrize("boundary", ["factory", "cache_first", "cache_second", "close"])
@pytest.mark.parametrize("change", ["permission", "role", "actor", "site", "invoice_revision", "company_revision", "ownership"])
def test_late_drift_denies_protected_disclosure_after_owned_cleanup(defaults_operator, boundary, change):
    case = scenario(defaults_operator)
    def mutate():
        if change == "permission": defaults_operator.denied.add((case.invoice.doctype, case.invoice.name))
        elif change == "role": defaults_operator.runtime.get_roles.return_value = []
        elif change == "actor": defaults_operator.runtime.session.user = "other@example.invalid"
        elif change == "site": defaults_operator.runtime.local.site = "other.test"
        elif change == "invoice_revision": case.invoice.modified += timedelta(seconds=1)
        elif change == "company_revision": case.company.modified += timedelta(seconds=1)
        else: case.invoice.company = "OTHER-COMPANY"
    if boundary == "factory":
        def acquire(*args): mutate(); return case.database
        case.factory.side_effect = acquire
    elif boundary == "close": case.database.close.side_effect = mutate
    else:
        calls = []
        def read(*args):
            calls.append(args)
            if len(calls) == (1 if boundary == "cache_first" else 2): mutate()
            return {"currency_precision": "2"}
        case.cache.side_effect = read
    denied = change in ("permission", "role", "actor", "site")
    with pytest.raises(PermissionDenied if denied else InspectionFailed) as caught: capture(case)
    assert caught.value.__context__ is None
    one_failure(defaults_operator, access.DENIED_MESSAGE if denied else access.FAILED_MESSAGE)
    case.database.close.assert_called_once()
    untouched(defaults_operator, case)


@pytest.mark.parametrize("borrowed", ["db", "raw"])
def test_recognizable_parent_connection_is_never_rolled_back_or_closed(defaults_operator, borrowed):
    case = scenario(defaults_operator)
    defaults_operator.runtime.db._conn = case.database
    case.factory.return_value = defaults_operator.runtime.db if borrowed == "db" else case.database
    with pytest.raises(InspectionFailed): capture(case)
    case.database.rollback.assert_not_called()
    case.database.close.assert_not_called()
    case.cache.assert_not_called()
    untouched(defaults_operator, case)


@pytest.mark.parametrize("boundary", ["factory", "initial_rollback", "cache", "final_rollback", "close"])
@pytest.mark.parametrize("interrupt", [False, True])
def test_failures_are_single_redacted_messages_and_owned_cleanup_preserves_interrupt(defaults_operator, boundary, interrupt):
    case = scenario(defaults_operator)
    error = KeyboardInterrupt("PRIVATE") if interrupt else RuntimeError("PRIVATE DRIVER DETAILS")
    if boundary == "factory": case.factory.side_effect = error
    elif boundary == "cache": case.cache.side_effect = error
    elif boundary == "close": case.database.close.side_effect = error
    else: case.database.rollback.side_effect = [error, None] if boundary == "initial_rollback" else [None, error]
    with pytest.raises(KeyboardInterrupt if interrupt else InspectionFailed) as caught: capture(case)
    if not interrupt:
        assert str(caught.value) == access.FAILED_MESSAGE and caught.value.__context__ is None
        one_failure(defaults_operator, access.FAILED_MESSAGE)
    else: defaults_operator.runtime.throw.assert_not_called()
    assert case.database.close.call_count == (0 if boundary == "factory" else 1)
    assert case.factory.call_count == 1
    untouched(defaults_operator, case)


@pytest.mark.parametrize("boundary", [1, 2])
def test_cache_mismatch_or_missing_cache_does_not_trigger_refresh_retry_or_raw_export(defaults_operator, boundary):
    case = scenario(defaults_operator)
    case.cache.side_effect = [None] if boundary == 1 else [{"currency_precision": "2"}, {"currency_precision": "3"}]
    with pytest.raises(InspectionFailed) as caught: capture(case)
    assert str(caught.value) == access.FAILED_MESSAGE and case.cache.call_count == boundary
    one_failure(defaults_operator, access.FAILED_MESSAGE)
    untouched(defaults_operator, case)


def test_final_cache_callback_cannot_hide_changed_selected_sql_rows(defaults_operator):
    case = scenario(defaults_operator)
    def cached(*args):
        if case.cache.call_count == 2: case.database.defaults = [row(parent=case.parent, value="3")]
        return {"currency_precision": "2"}
    case.cache.side_effect = cached
    with pytest.raises(InspectionFailed): capture(case)
    assert case.cache.call_count == 2


@pytest.mark.parametrize("fault", ["actor", "scope", "source_order", "source_revision", "source_company", "source_fields", "defaults_hash", "parent"])
def test_direct_protected_result_rechecks_sources_scope_and_defaults(defaults_operator, fault):
    case = scenario(defaults_operator)
    result = capture(case)
    changes = {}
    if fault == "actor": changes["actor"] = "Guest"
    elif fault == "scope": changes["scope"] = "PRIVATE"
    elif fault == "source_order": changes["sources"] = tuple(reversed(result.sources))
    elif fault in ("source_revision", "source_company", "source_fields"):
        company, invoice = result.sources
        if fault == "source_revision": company = replace(company, revision="PRIVATE")
        elif fault == "source_company": invoice = replace(invoice, values=("OTHER", 0))
        else: invoice = replace(invoice, fields=("private_key", "docstatus"))
        changes["sources"] = (company, invoice)
    elif fault == "defaults_hash": object.__setattr__(result.defaults, "sha256", "f" * 64)
    else:
        from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults import load
        changes["defaults"] = load([row(parent="another@example.invalid")], "another@example.invalid")[0]
    with pytest.raises(access.CalculationDefaultsAccessError) as caught: replace(result, **changes)
    assert str(caught.value) == "calculation_defaults_access_result" and caught.value.__context__ is None


def test_one_arabic_display_error_preserves_english_internal_labels(defaults_operator, monkeypatch):
    case = scenario(defaults_operator)
    path = Path(__file__).resolve().parents[2] / "translations/ar.csv"
    with path.open() as stream:
        translations = {line[0]: line[1] for line in csv.reader(stream) if len(line) >= 2}
    monkeypatch.setattr(access, "_", lambda text: translations[text])
    defaults_operator.denied.add((case.invoice.doctype, case.invoice.name))
    with pytest.raises(PermissionDenied) as caught: capture(case)
    assert str(caught.value) == translations[access.DENIED_MESSAGE]
    one_failure(defaults_operator, translations[access.DENIED_MESSAGE])
    assert access.DENIED_MESSAGE.startswith("You do not")
    assert translations[access.FAILED_MESSAGE].startswith("تعذّر")


@pytest.mark.parametrize("boundary", ["source", "cache"])
def test_nested_producer_popup_is_muted_and_replaced_by_one_safe_summary(defaults_operator, boundary):
    case = scenario(defaults_operator)
    def producer(*args):
        assert defaults_operator.runtime.flags["mute_messages"] is True
        defaults_operator.runtime.throw("PRIVATE-PRODUCER-DETAIL", InspectionFailed)
    if boundary == "source": defaults_operator.runtime.get_doc.side_effect = producer
    else: case.cache.side_effect = producer
    with pytest.raises(InspectionFailed) as caught: capture(case)
    assert str(caught.value) == access.FAILED_MESSAGE and caught.value.__context__ is None
    one_failure(defaults_operator, access.FAILED_MESSAGE)
    if boundary == "source": case.factory.assert_not_called()


@pytest.mark.parametrize("previous", [None, False, True, "PARENT-VALUE"])
@pytest.mark.parametrize("outcome", ["success", "error", "interrupt"])
def test_parent_mute_flag_and_existing_messages_restore_exactly(defaults_operator, previous, outcome):
    case = scenario(defaults_operator)
    flags = {"unrelated": "KEEP"}
    if previous is not None: flags["mute_messages"] = previous
    defaults_operator.runtime.flags = dict(flags)
    if outcome == "error": case.cache.side_effect = RuntimeError("PRIVATE")
    elif outcome == "interrupt": case.cache.side_effect = KeyboardInterrupt()
    if outcome == "success": capture(case)
    else:
        with pytest.raises(KeyboardInterrupt if outcome == "interrupt" else InspectionFailed): capture(case)
    assert defaults_operator.runtime.flags == flags
    expected = ["EXISTING-PARENT-MESSAGE"]
    if outcome == "error" and not previous: expected.append(access.FAILED_MESSAGE)
    assert defaults_operator.runtime.message_log == expected


@pytest.mark.parametrize("doctype", [None, "Company", "Sales Order", "sales invoice"])
def test_unsupported_source_type_is_rejected_before_documents_or_sql(defaults_operator, doctype):
    case = scenario(defaults_operator)
    with pytest.raises(InspectionFailed): case.service.capture(case.invoice.name, doctype=doctype)
    defaults_operator.runtime.get_doc.assert_not_called()
    case.factory.assert_not_called()
    case.cache.assert_not_called()
    one_failure(defaults_operator, access.FAILED_MESSAGE)


@pytest.mark.parametrize("kind", [None, "__default", "another@example.invalid", {}, 0])
def test_parent_scope_is_a_fixed_server_constructor_choice(defaults_operator, kind):
    case = scenario(defaults_operator)
    with pytest.raises(access.CalculationDefaultsAccessError):
        access.SavedCalculationDefaultsService(case.scope, case.factory, case.cache, parent_kind=kind)
    case.factory.assert_not_called()
    case.cache.assert_not_called()
