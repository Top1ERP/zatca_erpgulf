"""One permissioned transaction for defaults and exact invoice/Company metadata."""

from dataclasses import FrozenInstanceError, replace
import csv
from datetime import timedelta
from pathlib import Path
import pickle
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import calculation_defaults as defaults
from zatca_erpgulf.zatca_erpgulf import metadata_source as metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, scenario as defaults_case, capture as capture_defaults,
    one_failure, untouched, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_metadata_source import scenario as metadata_case
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import Definition, project


def declarations(doctype):
    """Include the exact columns used by the minimal saved source projection."""
    case = metadata_case(doctype)
    for name in access.FIELDS.get(doctype, ()):
        if name not in metadata.BASE_TYPES and name not in case.meta.definitions:
            values = {prop: None for prop in metadata.EDITABLE}
            values["fieldtype"] = "Data"
            case.meta.definitions[name] = Definition(name, **values)
            case.records["docfields"].append(dict(case.records["docfields"][0],
                fieldname=name, idx=len(case.records["docfields"]) + 1, **values))
    # Names are global primary keys within each metadata table, not just a type.
    for group, rows in case.records.items():
        if group == "doctype": continue
        for index, row in enumerate(rows): row["name"] = f"{doctype}-{group}-{index:03}"
        rows.sort(key=lambda row: row["name"])
    case.applied = project(case.meta)
    return case


def scenario(operator, *, doctype="Sales Invoice", parent_kind="site", docstatus=0):
    case = defaults_case(operator, doctype=doctype, parent_kind=parent_kind, docstatus=docstatus)
    case.metadata_cases = {name: declarations(name) for name in ("Company", doctype)}
    case.applied = {name: item.applied for name, item in case.metadata_cases.items()}
    case.metadata_provider = Mock(side_effect=lambda scope, types: dict(case.applied))

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=()):
            operator.sql.append((sql, params))
            if sql == "SELECT @@session.autocommit": self.result = (0,)
            elif sql == defaults.READ_SQL: self.records = case.database.defaults
            else:
                table = sql.split("FROM `tab", 1)[1].split("`", 1)[0]
                if table in ("Company", "Sales Invoice", "POS Invoice"):
                    doc = operator.documents[table, params[-1]]
                    selected = access.CalculationDefaultsSourceRow.from_document(doc)
                    self.result = (selected.name, doc.modified, *selected.values)
                else:
                    group = next(key for key, (name, _) in metadata.SPECS.items() if name == table)
                    preflight = group != "doctype" and "CASE WHEN" not in sql
                    fields = metadata.PREFLIGHT[group] if preflight else metadata.SPECS[group][1]
                    self.records = tuple((row["name"], row["modified"], *(row.get(name) for name in fields))
                        for row in case.metadata_cases[params[0]].records[group])
            if case.database.on_execute: case.database.on_execute(sql, params)
        def fetchone(self): return self.result
        def fetchall(self): return self.records

    case.database.cursor = Mock(side_effect=Cursor)
    case.service = access.SavedCalculationDefaultsService(case.scope, case.factory, case.cache,
        parent_kind=parent_kind, applied_metadata_reader=case.metadata_provider)
    return case


def capture(case):
    return case.service.capture_context(case.invoice.name, doctype=case.invoice.doctype)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("parent_kind", access.PARENT_KINDS)
@pytest.mark.parametrize("docstatus", [0, 1, 2])
def test_context_shares_one_owned_transaction_and_exact_metadata_types(defaults_operator, doctype, parent_kind, docstatus):
    case = scenario(defaults_operator, doctype=doctype, parent_kind=parent_kind, docstatus=docstatus)
    result = capture(case)
    assert type(result) is access.SavedCalculationContextRead
    assert result.settings.actor == defaults_operator.runtime.session.user
    assert tuple(row.applied.name for row in result.metadata) == ("Company", doctype)
    assert case.metadata_provider.call_args_list == [((case.scope, ("Company", doctype)),)] * 2
    case.factory.assert_called_once_with(case.scope)
    assert case.cache.call_count == 2 and case.database.rollback.call_count == 2
    case.database.close.assert_called_once()
    result.settings.defaults.require_cache_match(case.parent, {"currency_precision": "2"})
    assert "SYNTHETIC" not in repr(result) and "NOT verified" in repr(result)
    with pytest.raises(FrozenInstanceError): result.metadata = ()
    with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(result)
    untouched(defaults_operator, case)


def test_defaults_only_path_does_not_read_or_require_metadata(defaults_operator):
    case = scenario(defaults_operator)
    case.metadata_provider.side_effect = AssertionError("Legacy path must not acquire metadata")
    assert type(capture_defaults(case)) is access.SavedCalculationDefaultsRead
    case.metadata_provider.assert_not_called()
    assert not any("FROM `tabDocType`" in sql for sql, _ in defaults_operator.sql)


@pytest.mark.parametrize("denial", ["role", "invoice", "company"])
def test_authorization_precedes_metadata_cache_and_sql_dependencies(defaults_operator, denial):
    case = scenario(defaults_operator)
    if denial == "role": defaults_operator.runtime.get_roles.return_value = []
    else:
        doc = case.invoice if denial == "invoice" else case.company
        defaults_operator.denied.add((doc.doctype, doc.name))
    with pytest.raises(PermissionDenied): capture(case)
    case.metadata_provider.assert_not_called()
    case.factory.assert_not_called()
    case.cache.assert_not_called()
    one_failure(defaults_operator, access.DENIED_MESSAGE)


@pytest.mark.parametrize("fault", ["missing", "extra", "wrong_type", "wrong_name", "missing_company_field", "no_provider"])
def test_incomplete_or_unrelated_metadata_is_rejected_before_owned_acquisition(defaults_operator, fault):
    case = scenario(defaults_operator)
    if fault == "missing": case.applied.pop("Company")
    elif fault == "extra": case.applied["Customer"] = declarations("Customer").applied
    elif fault == "wrong_type": case.applied[case.invoice.doctype] = "PRIVATE"
    elif fault == "wrong_name": case.applied[case.invoice.doctype] = case.applied["Company"]
    elif fault == "no_provider": case.service._metadata = None
    else:
        selected = case.metadata_cases[case.invoice.doctype]
        selected.meta.definitions.pop("company")
        case.applied[case.invoice.doctype] = project(selected.meta)
    with pytest.raises(InspectionFailed): capture(case)
    case.factory.assert_not_called()
    one_failure(defaults_operator, access.FAILED_MESSAGE)


@pytest.mark.parametrize("boundary", ["metadata_first", "metadata_second", "defaults_first", "defaults_second", "close"])
@pytest.mark.parametrize("change", ["permission", "actor", "invoice_revision"])
def test_callback_drift_and_late_denial_never_disclose_the_context(defaults_operator, boundary, change):
    case = scenario(defaults_operator)
    def mutate():
        if change == "permission": defaults_operator.denied.add((case.invoice.doctype, case.invoice.name))
        elif change == "actor": defaults_operator.runtime.session.user = "other@example.invalid"
        else: case.invoice.modified += timedelta(seconds=1)
    if boundary == "close": case.database.close.side_effect = mutate
    elif boundary.startswith("metadata"):
        def supplied(*args):
            if case.metadata_provider.call_count == (1 if boundary == "metadata_first" else 2): mutate()
            return dict(case.applied)
        case.metadata_provider.side_effect = supplied
    else:
        def cached(*args):
            if case.cache.call_count == (1 if boundary == "defaults_first" else 2): mutate()
            return {"currency_precision": "2"}
        case.cache.side_effect = cached
    with pytest.raises(InspectionFailed if change == "invoice_revision" else PermissionDenied): capture(case)
    assert case.database.close.call_count == (0 if boundary == "metadata_first" else 1)
    one_failure(defaults_operator, access.FAILED_MESSAGE if change == "invoice_revision" else access.DENIED_MESSAGE)


@pytest.mark.parametrize("changed", ["applied", "sql_revision", "sql_value", "defaults"])
def test_final_metadata_callback_is_followed_by_all_sql_source_rechecks(defaults_operator, changed):
    case = scenario(defaults_operator)
    def supplied(*args):
        if case.metadata_provider.call_count == 2:
            if changed == "defaults": case.database.defaults = [(*case.database.defaults[0][:-1], "3")]
            else:
                selected = case.metadata_cases[case.invoice.doctype]
                if changed == "applied":
                    selected.meta.definitions[selected.ordinary[0]].values["options"] = "CHANGED"
                    case.applied[case.invoice.doctype] = project(selected.meta)
                elif changed == "sql_revision": selected.records["docfields"][0]["modified"] += timedelta(seconds=1)
                else: selected.records["property_setters"][0]["value"] = "3"
        return dict(case.applied)
    case.metadata_provider.side_effect = supplied
    with pytest.raises(InspectionFailed): capture(case)
    case.database.close.assert_called_once()
    one_failure(defaults_operator, access.FAILED_MESSAGE)


@pytest.mark.parametrize("boundary", ["first", "second"])
@pytest.mark.parametrize("interrupt", [False, True])
def test_metadata_provider_failure_is_single_redacted_and_owned_cleanup_is_exact(defaults_operator, boundary, interrupt):
    case = scenario(defaults_operator)
    def supplied(*args):
        if case.metadata_provider.call_count == (1 if boundary == "first" else 2):
            if interrupt: raise KeyboardInterrupt()
            defaults_operator.runtime.throw("PRIVATE-METADATA-MESSAGE", InspectionFailed)
        return dict(case.applied)
    case.metadata_provider.side_effect = supplied
    with pytest.raises(KeyboardInterrupt if interrupt else InspectionFailed): capture(case)
    assert case.database.close.call_count == (0 if boundary == "first" else 1)
    if not interrupt: one_failure(defaults_operator, access.FAILED_MESSAGE)
    else: assert defaults_operator.runtime.message_log == ["EXISTING-PARENT-MESSAGE"]
    assert "mute_messages" not in defaults_operator.runtime.flags


@pytest.mark.parametrize("fault", ["missing", "extra", "order", "corrupt", "wrong_settings"])
def test_protected_context_reconstruction_binds_exact_independent_parents(defaults_operator, fault):
    case = scenario(defaults_operator)
    result = capture(case)
    changes = {}
    if fault == "missing": changes["metadata"] = result.metadata[:1]
    elif fault == "extra": changes["metadata"] = (*result.metadata, result.metadata[0])
    elif fault == "order": changes["metadata"] = tuple(reversed(result.metadata))
    elif fault == "corrupt": object.__setattr__(result.metadata[0], "sha256", "f" * 64)
    else: changes["settings"] = "PRIVATE"
    with pytest.raises(access.CalculationDefaultsAccessError) as caught: replace(result, **changes)
    assert str(caught.value) == "calculation_context_access_result" and caught.value.__context__ is None


def test_combined_metadata_failure_displays_one_arabic_summary_without_raw_details(defaults_operator, monkeypatch):
    case = scenario(defaults_operator)
    path = Path(__file__).resolve().parents[2] / "translations/ar.csv"
    with path.open() as stream:
        translations = {line[0]: line[1] for line in csv.reader(stream) if len(line) >= 2}
    monkeypatch.setattr(access, "_", lambda message: translations[message])
    case.metadata_provider.side_effect = lambda *args: defaults_operator.runtime.throw("PRIVATE-METADATA", InspectionFailed)
    with pytest.raises(InspectionFailed) as caught: capture(case)
    assert str(caught.value) == translations[access.FAILED_MESSAGE]
    one_failure(defaults_operator, translations[access.FAILED_MESSAGE])
    case.factory.assert_not_called()
    assert access.FAILED_MESSAGE.startswith("ZATCA")
