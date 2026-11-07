"""Permissioned consumed POS sources; synthetic saved ACLs/native rows only."""

import copy
from dataclasses import replace
from datetime import timedelta
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import calculation_pos_profile_access as pos
from zatca_erpgulf.zatca_erpgulf.source_metadata import PROPERTIES
from zatca_erpgulf.zatca_erpgulf.tests.test_pos_profile_source import scenario as source_case
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access import bind
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_access import saved_graph
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, scenario as defaults_case, one_failure, untouched, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import Document


def configure(case):
    case.pos_metadata = Mock(side_effect=lambda scope, kind, types: {
        name: case.data.applied_pos[name] for name in types})
    case.service = access.SavedCalculationDefaultsService(case.scope, case.factory, case.cache,
        parent_kind=case.parent_kind, applied_metadata_reader=case.metadata_provider,
        pos_profile_metadata_reader=case.pos_metadata)
    return case


def normal_pos(case, operator):
    """Independent normal views; never substitute ORM payment/limit values."""
    case.data.own = SimpleNamespace(applied=case.data.metas[case.data.metas[case.invoice.doctype].get_field("items").options])
    saved_graph(operator, case)
    root = case.invoice.doctype
    for name in ("company", "pos_profile"):
        definition = case.data.metas[root].get_field(name)
        case.field_overrides[root, name] = Document(fieldname=name, permlevel=0,
            **{prop: definition.get(prop) for prop in PROPERTIES})
    normal = case.normal_metas[root]
    normal.name, normal.issingle, normal.istable = root, 0, 0
    normal.has_field = lambda name: normal.get_field(name) is not None
    case.invoice.pos_profile = "SYNTHETIC-POS"
    case.pos_definitions = {}
    for dt, raw in case.data.raw_pos.items():
        definitions = {name: Document(permlevel=0, **definition.values) for name, definition in raw.definitions.items()}
        case.pos_definitions[dt] = definitions
        meta = Document(name=dt, issingle=0, istable=int(dt == "POS Payment Method"),
            get_field=lambda name, definitions=definitions: definitions.get(name),
            has_field=lambda name, definitions=definitions: name in definitions,
            get_permlevel_access=Mock(return_value=[0]))
        case.normal_metas[dt] = meta
    def doc(dt, raw):
        values = {name: value for name, value in raw.items() if name not in ("write_off_limit", "mode_of_payment", "default", "allow_in_returns")}
        result = Document(doctype=dt, **values, meta=case.normal_metas[dt], save=Mock(), db_set=Mock(), check_permission=Mock())
        getter = result.get
        def get(name, *args):
            if name in ("write_off_limit", "mode_of_payment", "default", "allow_in_returns"):
                raise AssertionError("Normal getters must not replace native consumed values")
            return getter(name, *args)
        result.get = get
        return result
    case.master = doc("POS Profile", case.data.master_rows[0])
    operator.documents[case.master.doctype, case.master.name] = case.master
    case.pos_refs, case.pos_saved = [], []
    if case.data.kind == "default":
        for row in case.data.payment_rows:
            saved, ref = doc("POS Payment Method", row), doc("POS Payment Method", row)
            case.pos_saved.append(saved);case.pos_refs.append(ref)
            operator.documents[saved.doctype, saved.name] = saved
        case.master.payments = case.pos_refs
    return configure(case)


def scenario(operator, monkeypatch, *, parent_kind="site", **options):
    data = source_case(monkeypatch, **options)
    case = defaults_case(operator, doctype=data.doctype, parent_kind=parent_kind, docstatus=1)
    case.parent_kind = parent_kind
    bind(case, data, operator)
    data.observations = case.observations
    normal_pos(case, operator)
    default_cursor, native_cursor = case.database.cursor, data.connection.cursor
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=()):
            native = any(marker in sql for marker in (
                "OCTET_LENGTH(", "FROM `tabPOS Profile`", "FROM `tabPOS Payment Method`"))
            self.current = native_cursor() if native else default_cursor()
            self.current.execute(sql, params)
        def fetchone(self): return self.current.fetchone()
        def fetchall(self): return self.current.fetchall()
        @property
        def description(self): return self.current.description
    case.database.cursor = Mock(side_effect=Cursor)
    monkeypatch.setattr(access, "MariaDBMetadataSourceReader", Mock(return_value=data.provider))
    return case


def capture(case, *, kind=None, major=16):
    return case.service.capture_pos_profile_context(case.invoice.name,
        kind=case.data.kind if kind is None else kind, erp_major=major, doctype=case.invoice.doctype)


@pytest.mark.parametrize("kind", ["limit", "default"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
def test_consumed_pos_uses_one_owned_graph_and_no_orm_amount_getter(defaults_operator, monkeypatch, kind, major, doctype):
    case = scenario(defaults_operator, monkeypatch, kind=kind, doctype=doctype)
    defaults_operator.denied.add(("System Settings", None))
    if kind == "limit": defaults_operator.denied.add(("POS Payment Method", None))
    result = capture(case, major=major)
    assert type(result) is pos.SavedPosProfileContext and result.lookup.kind == kind
    assert result.financial.financial == result.lookup.financial and result.owner_document == id(case.invoice)
    assert result.master.name == case.master.name and result.master.revision == case.master.modified.isoformat(timespec="microseconds")
    assert len(result.payments) == (0 if kind == "limit" else 1)
    assert case.factory.call_count == 1 and case.database.rollback.call_count == 2 and case.database.close.call_count == 1
    assert case.pos_metadata.call_count == 2
    expected_types = ("POS Profile",) if kind == "limit" else ("POS Payment Method", "POS Profile")
    assert all(call.args == (case.scope, kind, expected_types) for call in case.pos_metadata.call_args_list)
    assert result.pin() == result
    untouched(defaults_operator, case)


@pytest.mark.parametrize("denial", ["role", "invoice", "company", "financial_table", "financial_child", "profile", "pos_table", "pos_child",
    "root_field", "master_field", "table_field", "child_field"])
def test_all_reads_precede_every_callback_and_sql(defaults_operator, monkeypatch, denial):
    case = scenario(defaults_operator, monkeypatch)
    if denial == "role": defaults_operator.runtime.get_roles.return_value = []
    elif denial == "root_field": case.field_overrides[case.invoice.doctype, "pos_profile"].permlevel = 2
    elif denial in ("master_field", "table_field"):
        case.pos_definitions["POS Profile"]["company" if denial == "master_field" else "payments"].permlevel = 2
    elif denial == "child_field": case.pos_definitions["POS Payment Method"]["mode_of_payment"].permlevel = 2
    else:
        identity = {"invoice": (case.invoice.doctype, case.invoice.name), "company": ("Company", case.company.name),
            "financial_table": ("Sales Invoice Item", None), "financial_child": ("Sales Taxes and Charges", "taxes-1"),
            "profile": ("POS Profile", case.master.name), "pos_table": ("POS Payment Method", None),
            "pos_child": ("POS Payment Method", "PAY-1")}[denial]
        defaults_operator.denied.add(identity)
    with pytest.raises(PermissionDenied): capture(case)
    for callback in (case.factory, case.cache, case.metadata_provider, case.pos_metadata): callback.assert_not_called()
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE)


@pytest.mark.parametrize("boundary", ["pos_first", "pos_last", "root_last", "defaults_last", "close"])
@pytest.mark.parametrize("changed", ["permission", "child_field", "link", "company", "membership", "revision"])
def test_access_or_source_drift_at_callbacks_and_close_prevents_disclosure(defaults_operator, monkeypatch, boundary, changed):
    case = scenario(defaults_operator, monkeypatch)
    def mutate():
        if changed == "permission": defaults_operator.denied.add(("POS Profile", case.master.name))
        elif changed == "child_field": case.pos_definitions["POS Payment Method"]["default"].permlevel = 2
        elif changed == "link": case.invoice.pos_profile = "OTHER"
        elif changed == "company": case.master.company = "OTHER"
        elif changed == "membership": case.master.payments = []
        else: case.master.modified += timedelta(seconds=1)
    if boundary == "close": case.database.close.side_effect = mutate
    else:
        callback = case.pos_metadata if boundary.startswith("pos") else case.cache if boundary == "defaults_last" else case.metadata_provider
        original = callback.side_effect or (lambda *args: callback.return_value)
        when = 1 if boundary == "pos_first" else 4 if boundary == "root_last" else 2
        def supply(*args):
            value = original(*args)
            if callback.call_count == when: mutate()
            return value
        callback.side_effect = supply
    denied = changed in ("permission", "child_field")
    with pytest.raises(PermissionDenied if denied else InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE if denied else access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("target", ["root", "master", "child", "reference"])
def test_equal_fresh_saved_objects_do_not_hide_original_object_drift(defaults_operator, monkeypatch, target):
    case = scenario(defaults_operator, monkeypatch)
    original = case.invoice if target == "root" else case.master if target == "master" else case.pos_saved[0] if target == "child" else case.pos_refs[0]
    def close():
        fresh = copy.copy(original)
        fresh.get = Document.get.__get__(fresh, Document)
        if target == "reference":
            case.master.payments = [fresh]
        else:
            defaults_operator.documents[original.doctype, original.name] = fresh
        if target == "root": original.pos_profile = "OTHER"
        elif target == "master": original.company = "OTHER"
        else: original.idx = 2
    case.database.close.side_effect = close
    with pytest.raises(InspectionFailed): capture(case)


def test_child_field_levels_are_checked_on_authorized_saved_parent(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    case.pos_definitions["POS Payment Method"]["mode_of_payment"].permlevel = 2
    case.master.meta.get_permlevel_access.return_value = [0, 2]
    case.normal_metas["POS Payment Method"].get_permlevel_access.return_value = []
    assert capture(case).lookup.default_observation().mode_of_payment == "Cash"


@pytest.mark.parametrize("fault", ["lookup", "tables", "master", "payments", "owner", "financial"])
def test_result_refuses_dropped_or_rebound_sources(defaults_operator, monkeypatch, fault):
    result = capture(scenario(defaults_operator, monkeypatch))
    fieldname = "owner_document" if fault == "owner" else fault
    value = 0 if fault == "owner" else () if fault in ("payments", "tables") else None
    with pytest.raises(pos.CalculationFormatAccessError): replace(result, **{fieldname: value})
    assert "SYNTHETIC" not in repr(result)
    with pytest.raises(TypeError): pickle.dumps(result)


@pytest.mark.parametrize("kind,major,parent_kind", [(True,16,"site"), ("other",16,"site"), ("limit",True,"site"),
    ("limit",17,"site"), ("default",16,"global"), ("default",15,"user")])
def test_invalid_scope_version_and_kind_fail_with_one_display_error(defaults_operator, monkeypatch, kind, major, parent_kind):
    case = scenario(defaults_operator, monkeypatch, parent_kind=parent_kind)
    with pytest.raises(InspectionFailed): capture(case, kind=kind, major=major)
    for callback in (case.factory, case.cache, case.metadata_provider, case.pos_metadata): callback.assert_not_called()
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)


def test_old_financial_capture_has_no_new_pos_dependency(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    assert type(case.service.capture_financial_context(case.invoice.name, erp_major=15)) is access.SavedCalculationFinancialRead
    case.pos_metadata.assert_not_called()


def detach_child_metadata(doc, *, denied=False):
    original = doc.meta
    replacement = copy.copy(original.get_field("default"))
    if denied: replacement.permlevel = 2
    else: replacement.default = "1"
    meta = copy.copy(original)
    meta.get_field = lambda name: replacement if name == "default" else original.get_field(name)
    doc.meta = meta


@pytest.mark.parametrize("target", ["reference", "saved"])
@pytest.mark.parametrize("denied", [False, True])
def test_child_own_metadata_drift_is_not_hidden_by_equal_global_meta(defaults_operator, monkeypatch, target, denied):
    case = scenario(defaults_operator, monkeypatch)
    child = case.pos_refs[0] if target == "reference" else case.pos_saved[0]
    case.database.close.side_effect = lambda: detach_child_metadata(child, denied=denied)
    with pytest.raises(PermissionDenied if denied else InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE if denied else access.FINANCIAL_FAILED_MESSAGE)


def test_arabic_display_is_one_summary_and_internal_keys_remain_english(defaults_operator, monkeypatch):
    import csv
    from pathlib import Path
    case = scenario(defaults_operator, monkeypatch)
    translations = dict(csv.reader((Path(__file__).parents[2] / "translations/ar.csv").open()))
    original = access.FINANCIAL_DENIED_MESSAGE
    translated = translations[original]
    defaults_operator.denied.add(("POS Profile", case.master.name))
    monkeypatch.setattr(access, "_", lambda text: translations.get(text, text))
    with pytest.raises(PermissionDenied) as caught: capture(case)
    assert str(caught.value) == translated and caught.value.__context__ is None
    one_failure(defaults_operator, translated)
    assert access.FINANCIAL_DENIED_MESSAGE == original and original != translated


@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit])
def test_interruptions_keep_priority_and_owned_cleanup(defaults_operator, monkeypatch, error):
    case = scenario(defaults_operator, monkeypatch)
    original = case.pos_metadata.side_effect
    def supply(*args):
        result = original(*args)
        if case.pos_metadata.call_count == 2: raise error("synthetic interruption")
        return result
    case.pos_metadata.side_effect = supply
    with pytest.raises(error): capture(case)
    assert case.database.rollback.call_count == 2 and case.database.close.call_count == 1
    assert defaults_operator.runtime.message_log == ["EXISTING-PARENT-MESSAGE"]
    untouched(defaults_operator, case)
