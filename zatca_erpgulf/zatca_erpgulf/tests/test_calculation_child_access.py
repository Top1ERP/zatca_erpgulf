"""Shared saved child/table READ and owned native acquisition; synthetic only."""

from dataclasses import replace
import ast
import csv
from datetime import timedelta
import json
from pathlib import Path
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import calculation_child_access as children
from zatca_erpgulf.zatca_erpgulf.tests.test_child_currency_source import scenario as child_case
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access import bind
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, scenario as defaults_case, one_failure, untouched,
    PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import Document
from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial


def saved_graph(operator, case):
    """Independent root-child and direct saved-child views, not ORM integration."""
    root = case.data.metas[case.invoice.doctype]
    case.definitions, case.refs, case.saved = {}, {}, {}
    for table in financial.TABLE_FIELDS:
        definition = root.get_field(table)
        if definition is None: continue
        case.definitions[table] = Document(fieldtype="Table", options=definition.options, permlevel=0)
        refs = []
        for raw in case.data.records[table]:
            values = dict(doctype=definition.options, **raw)
            saved = Document(**values)
            saved.save, saved.db_set, saved.check_permission = Mock(), Mock(), Mock()
            operator.documents[saved.doctype, saved.name] = saved
            case.saved[table, saved.name] = saved
            refs.append(Document(**values))
        case.refs[table] = refs
        setattr(case.invoice, table, refs)
    case.field_overrides, case.normal_metas = {}, {}
    for dt, meta in case.data.metas.items():
        def get(name, dt=dt, meta=meta):
            if (dt, name) in case.field_overrides: return case.field_overrides[dt, name]
            if dt == case.invoice.doctype and name in financial.TABLE_FIELDS: return case.definitions.get(name)
            if dt == case.data.own.applied.name and name in ("currency", "company"): return case.data.own.applied.get_field(name)
            return meta.get_field(name)
        case.normal_metas[dt] = SimpleNamespace(get_field=get, get_permlevel_access=Mock(return_value=[0]))
    case.invoice.meta = case.normal_metas[case.invoice.doctype]
    operator.runtime.get_meta = Mock(side_effect=lambda dt: case.normal_metas[dt])


def configure(case):
    case.child_metadata = Mock(side_effect=lambda scope, types: {case.data.own.applied.name: case.data.own.applied})
    case.service = access.SavedCalculationDefaultsService(case.scope, case.factory, case.cache,
        parent_kind=case.parent_kind, applied_metadata_reader=case.metadata_provider,
        child_metadata_reader=case.child_metadata)
    return case


def scenario(operator, monkeypatch, *, doctype="Sales Invoice", present=("currency", "company"), parent_kind="site"):
    case = defaults_case(operator, doctype=doctype, docstatus=1, parent_kind=parent_kind)
    case.parent_kind = parent_kind
    data = child_case(monkeypatch, doctype=doctype, present=present)
    bind(case, data, operator)
    data.observations = case.observations
    saved_graph(operator, case)
    default_cursor, native_cursor = case.database.cursor, data.connection.cursor
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=()):
            native = any(marker in sql for marker in ("OCTET_LENGTH(", "information_schema.COLUMNS", "SUBSTRING(`parenttype`,1,141)"))
            self.current = native_cursor() if native else default_cursor()
            self.current.execute(sql, params)
        def fetchone(self): return self.current.fetchone()
        def fetchall(self): return self.current.fetchall()
        @property
        def description(self): return self.current.description
    case.database.cursor = Mock(side_effect=Cursor)
    monkeypatch.setattr(access, "MariaDBMetadataSourceReader", Mock(return_value=data.metadata_reader))
    return configure(case)


def capture(case, *, major=16, table="items"):
    return case.service.capture_child_context(case.invoice.name, table, erp_major=major, doctype=case.invoice.doctype)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("present", [(), ("currency", "company")])
def test_saved_child_graph_links_defaults_and_precision_share_one_owned_boundary(defaults_operator, monkeypatch, doctype, major, present):
    case = scenario(defaults_operator, monkeypatch, doctype=doctype, present=present)
    result = capture(case, major=major)
    assert type(result) is children.SavedChildCalculationRead
    assert result.resolve_currency("items-1", "amount").currency == ("USD" if present else "SAR")
    assert result.resolve_precision("items-1", "amount").precision == 2
    result.require_field_currency_match("items-1", "amount", parent_entry=("str", "USD" if present else "SAR"))
    assert tuple(name for name, _ in result.tables) == tuple(case.refs)
    assert result.sources[0].name == "items-1" and result.child.financial == result.financial.financial
    assert case.factory.call_count == 1 and case.database.rollback.call_count == 2 and case.database.close.call_count == 1
    assert case.child_metadata.call_count == 2
    untouched(defaults_operator, case)


@pytest.mark.parametrize("denial", ["invoice", "company", "table", "child", "other_table", "other_child", "role"])
def test_all_financial_tables_and_rows_require_read_before_any_provider_or_sql(defaults_operator, monkeypatch, denial):
    case = scenario(defaults_operator, monkeypatch)
    if denial == "role": defaults_operator.runtime.get_roles.return_value = []
    else:
        dt, name = {
            "invoice": (case.invoice.doctype, case.invoice.name), "company": ("Company", case.company.name),
            "table": ("Sales Invoice Item", None), "child": ("Sales Invoice Item", "items-1"),
            "other_table": ("Sales Taxes and Charges", None), "other_child": ("Sales Taxes and Charges", "taxes-1"),
        }[denial]
        defaults_operator.denied.add((dt, name))
    with pytest.raises(PermissionDenied): capture(case)
    for provider in (case.factory, case.cache, case.metadata_provider, case.child_metadata): provider.assert_not_called()
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE)


@pytest.mark.parametrize("value", [None, "", "company", False, 1, [], "__dict__"])
def test_invalid_table_never_falls_back_to_financial_only_capture(defaults_operator, monkeypatch, value):
    case = scenario(defaults_operator, monkeypatch)
    with pytest.raises(InspectionFailed): capture(case, table=value)
    case.factory.assert_not_called()
    case.child_metadata.assert_not_called()


@pytest.mark.parametrize("boundary", ["child_first", "child_second", "cache_first", "cache_second", "factory", "close"])
@pytest.mark.parametrize("change", ["permission", "membership", "links", "permlevel", "other_child", "actor"])
def test_callbacks_and_cleanup_cannot_hide_late_child_graph_drift(defaults_operator, monkeypatch, boundary, change):
    case = scenario(defaults_operator, monkeypatch)
    def mutate():
        if change == "permission": defaults_operator.denied.add(("Sales Invoice Item", "items-1"))
        elif change == "membership": case.refs["items"].clear()
        elif change == "links": case.saved["items", "items-1"].currency = "EUR"
        elif change == "permlevel": case.definitions["items"].permlevel = 1
        elif change == "other_child": defaults_operator.denied.add(("Sales Taxes and Charges", "taxes-1"))
        else: defaults_operator.runtime.session.user = "other@example.invalid"
    if boundary == "close": case.database.close.side_effect = mutate
    elif boundary == "factory": case.factory.side_effect = lambda *args: (mutate(), case.database)[1]
    else:
        provider = case.child_metadata if boundary.startswith("child") else case.cache
        old = provider.side_effect or (lambda *args: provider.return_value)
        def read(*args):
            result = old(*args)
            if provider.call_count == (1 if boundary.endswith("first") else 2): mutate()
            return result
        provider.side_effect = read
    denied = change in ("permission", "other_child", "actor")
    with pytest.raises(PermissionDenied if denied else InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE if denied else access.FINANCIAL_FAILED_MESSAGE)
    assert case.database.close.call_count == (0 if boundary == "child_first" else 1)


@pytest.mark.parametrize("fault", ["currency", "company", "revision", "idx", "parent", "parentfield"])
def test_saved_and_native_child_views_must_agree_without_parent_timestamp_changes(defaults_operator, monkeypatch, fault):
    case = scenario(defaults_operator, monkeypatch)
    for doc in (case.refs["items"][0], case.saved["items", "items-1"]):
        setattr(doc, fault if fault != "revision" else "modified",
            doc.modified + timedelta(seconds=1) if fault == "revision" else 2 if fault == "idx" else "OTHER")
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)


def test_empty_other_table_still_requires_table_read(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    assert case.refs["payments"] == []
    defaults_operator.denied.add(("Sales Invoice Payment", None))
    with pytest.raises(PermissionDenied): capture(case)
    case.factory.assert_not_called()
    case.child_metadata.assert_not_called()


@pytest.mark.parametrize("boundary", ["first", "second"])
@pytest.mark.parametrize("fault", ["extra", "missing", "wrong_profile", "nested", "interrupt"])
def test_child_metadata_callbacks_are_exact_and_use_the_shared_message_boundary(defaults_operator, monkeypatch, boundary, fault):
    case = scenario(defaults_operator, monkeypatch)
    old = case.child_metadata.side_effect
    def supplied(*args):
        result = old(*args)
        if case.child_metadata.call_count == (1 if boundary == "first" else 2):
            if fault == "extra": result["PRIVATE"] = case.data.own.applied
            elif fault == "missing": result = {}
            elif fault == "wrong_profile": result = {case.data.own.applied.name: case.data.metas[case.data.own.applied.name]}
            elif fault == "nested": defaults_operator.runtime.throw("PRIVATE-CALLBACK", InspectionFailed)
            else: raise KeyboardInterrupt()
        return result
    case.child_metadata.side_effect = supplied
    with pytest.raises(KeyboardInterrupt if fault == "interrupt" else InspectionFailed): capture(case)
    if fault == "interrupt": assert defaults_operator.runtime.message_log == ["EXISTING-PARENT-MESSAGE"]
    else: one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)


@pytest.mark.parametrize("fault", ["graph", "row", "revision", "derived"])
def test_protected_result_reconstruction_keeps_saved_graph_bound_to_native_parent(defaults_operator, monkeypatch, fault):
    case = scenario(defaults_operator, monkeypatch)
    result = capture(case)
    if fault == "derived":
        object.__setattr__(result, "sources", ())
        with pytest.raises(children.CalculationChildAccessError): result.resolve_currency("items-1", "amount")
        return
    tables = list(result.tables)
    if fault == "graph": tables.pop()
    else:
        row = tables[0][1][0]
        if fault == "row": row = replace(row, name="OTHER")
        else: row = replace(row, revision="2026-10-28T12:00:00.000000")
        tables[0] = (tables[0][0], (row,))
    with pytest.raises(children.CalculationChildAccessError): replace(result, tables=tuple(tables))


def test_read_never_uses_ignore_permission_shortcuts_or_exports_protected_data(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    doc = case.saved["items", "items-1"]
    doc.flags = {"ignore_permissions": True}
    result = capture(case)
    assert "SYNTHETIC" not in repr(result)
    with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(result)
    untouched(defaults_operator, case)
    defaults_operator.denied.add((doc.doctype, doc.name))
    with pytest.raises(PermissionDenied): capture(case)


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("level,accessible,parentfield,parent_allowed,expected", [
    (0, [0], "items", True, True), (1, [0], "items", True, False),
    (1, [0, 1], "items", True, True), (0, [0], "other", True, False),
    (0, [0], "items", False, False),
])
def test_framework_table_probe_checks_permlevel_and_saved_parent(monkeypatch, major, level, accessible, parentfield, parent_allowed, expected):
    import frappe
    from frappe import permissions
    field = frappe._dict(fieldname="items", options="Sales Invoice Item", permlevel=level)
    meta = SimpleNamespace(istable=False, get_table_fields=Mock(return_value=[field]),
        get_field=lambda name: field, get_permlevel_access=Mock(return_value=accessible))
    parent = Document(doctype="Sales Invoice", name="SYNTHETIC-INVOICE")
    probe = SimpleNamespace(doctype="Sales Invoice Item", name=None, parent=parent.name,
        parenttype=parent.doctype, parentfield=parentfield, parent_doc=parent)
    parent_acl = Mock(return_value=parent_allowed)
    monkeypatch.setattr(frappe, "get_meta", Mock(return_value=meta))
    monkeypatch.setattr(frappe, "bold", str)
    if major == 15:
        monkeypatch.setattr(permissions, "has_permission", parent_acl)
        monkeypatch.setattr(permissions, "push_perm_check_log", Mock())
        monkeypatch.setattr(permissions, "_", lambda text: text)
        helper, quiet = permissions.has_child_permission, {"raise_exception": False}
    else:
        record = json.loads(Path(__file__).with_name("frappe16_precision_oracle.json").read_text())
        assert record["commit"] == "e8d41dd0061a32ee781caefe5d0b0d2bb7c15362" and "The MIT License" in record["license"]
        source = record["files"]["permissions.py"]
        assert source["sha256"] == "ae3c1285b87094fef39c27c4a5f73c258da11f955ce45169ca6b4996558f6bd8"
        namespace = dict(frappe=frappe, has_permission=parent_acl, push_perm_check_log=Mock(), _=lambda text: text)
        exec(compile(ast.parse(source["excerpts"]["has_child_permission"]), "pinned-frappe16/permissions.py", "exec"), namespace)
        helper, quiet = namespace["has_child_permission"], {"print_logs": False}
    assert helper("Sales Invoice Item", "read", child_doc=probe, user="manager@example.test", **quiet) is expected
    meta.get_table_fields.assert_called_once_with(**({"include_computed": True} if major == 16 else {}))
    if parent_acl.called:
        assert parent_acl.call_args.kwargs["doc"] is parent
        assert parent_acl.call_args.kwargs[next(iter(quiet))] is False


def test_child_denial_uses_existing_arabic_display_translation_once(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    with (Path(__file__).resolve().parents[2] / "translations/ar.csv").open() as stream:
        translations = {row[0]: row[1] for row in csv.reader(stream) if len(row) >= 2}
    monkeypatch.setattr(access, "_", lambda text: translations[text])
    defaults_operator.denied.add(("Sales Invoice Item", "items-1"))
    with pytest.raises(PermissionDenied): capture(case)
    one_failure(defaults_operator, translations[access.FINANCIAL_DENIED_MESSAGE])


def test_requested_empty_table_is_permissioned_and_never_invents_a_row(defaults_operator, monkeypatch):
    from zatca_erpgulf.zatca_erpgulf.source_metadata import CHILD_CURRENCY_PROFILE
    from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
    from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta
    case = scenario(defaults_operator, monkeypatch, present=())
    case.data.records["taxes"].clear()
    case.data.own = observed_metadata(AppliedMeta("Sales Taxes and Charges", ()), profile=CHILD_CURRENCY_PROFILE)
    case.data.metadata_reader.load_for_update.side_effect = lambda meta: case.data.own if meta.profile == CHILD_CURRENCY_PROFILE else case.data.observations[meta.name]
    saved_graph(defaults_operator, case)
    result = capture(case, table="taxes")
    assert result.sources == () and dict(result.tables)["taxes"] == ()
    defaults_operator.denied.add(("Sales Taxes and Charges", None))
    with pytest.raises(PermissionDenied): capture(case, table="taxes")


def test_applied_financial_table_not_in_saved_permission_graph_never_reaches_sql(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    case.definitions.pop("taxes")
    with pytest.raises(InspectionFailed): capture(case)
    case.factory.assert_not_called()
    case.cache.assert_not_called()


@pytest.mark.parametrize("dt,field", [("Sales Invoice", "grand_total"), ("Sales Invoice Item", "amount"), ("Sales Invoice Item", "currency"), ("Sales Taxes and Charges", "tax_amount")])
@pytest.mark.parametrize("allowed", [False, True])
def test_higher_field_levels_require_the_parents_field_read_access(defaults_operator, monkeypatch, dt, field, allowed):
    case = scenario(defaults_operator, monkeypatch)
    case.field_overrides[dt, field] = Document(permlevel=1)
    if allowed: case.invoice.meta.get_permlevel_access.return_value = [0, 1]
    if allowed:
        assert capture(case).sources[0].name == "items-1"
    else:
        with pytest.raises(PermissionDenied): capture(case)
        case.factory.assert_not_called()
        case.child_metadata.assert_not_called()
        one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE)


@pytest.mark.parametrize("boundary", ["cache", "close"])
def test_late_field_read_revocation_prevents_disclosure(defaults_operator, monkeypatch, boundary):
    case = scenario(defaults_operator, monkeypatch)
    def revoke(): case.field_overrides["Sales Invoice Item", "currency"] = Document(permlevel=1)
    if boundary == "close": case.database.close.side_effect = revoke
    else: case.cache.side_effect = lambda *args: (revoke(), {"currency_precision": "2"})[1]
    with pytest.raises(PermissionDenied): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE)
