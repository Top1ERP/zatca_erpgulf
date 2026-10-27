"""Permissioned native financial/default composition; synthetic sources only."""

import csv
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
import json
from pathlib import Path
import pickle
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import financial_source_sql as sql_source
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, scenario as defaults_case, one_failure, untouched,
    PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import (
    scenario as financial_case, observed_metadata,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta, project


def bind(case, data, operator):
    """Align minimal authorized document identity with the native source fixture."""
    operator.documents.pop((case.invoice.doctype, case.invoice.name))
    operator.documents.pop((case.company.doctype, case.company.name))
    case.invoice.name = data.name
    case.company.name = data.records["header"][0]["company"]
    case.invoice.company = case.company.name
    data.records["header"][0].update(modified=case.invoice.modified, docstatus=case.invoice.docstatus)
    operator.documents[case.invoice.doctype, case.invoice.name] = case.invoice
    operator.documents[case.company.doctype, case.company.name] = case.company
    case.data = data
    company = observed_metadata(AppliedMeta("Company", ()))
    case.observations = {**data.observations, "Company": company}
    case.applied = {name: row.applied for name, row in case.observations.items()}
    case.metadata_provider = Mock(side_effect=lambda scope, types: {name: case.applied[name] for name in types})
    case.service = access.SavedCalculationDefaultsService(case.scope, case.factory, case.cache,
        parent_kind=getattr(case, "parent_kind", "site"), applied_metadata_reader=case.metadata_provider)
    return case


def scenario(operator, monkeypatch, *, doctype="Sales Invoice", optional=True, parent_kind="site", docstatus=1):
    case = defaults_case(operator, doctype=doctype, parent_kind=parent_kind, docstatus=docstatus)
    case.parent_kind = parent_kind
    data = financial_case(doctype, optional=optional)
    bind(case, data, operator)
    default_cursor, financial_cursor = case.database.cursor, data.connection.cursor

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, statement, params=()):
            native = "OCTET_LENGTH(" in statement
            self.current = financial_cursor() if native else default_cursor()
            self.current.execute(statement, params)
        def fetchone(self): return self.current.fetchone()
        def fetchall(self): return self.current.fetchall()
        @property
        def description(self): return self.current.description

    case.database.cursor = Mock(side_effect=Cursor)
    provider = Mock()
    provider.load_for_update.side_effect = lambda meta: case.observations[meta.name]
    provider.require_unchanged.return_value = None
    monkeypatch.setattr(access, "MariaDBMetadataSourceReader", Mock(return_value=provider))
    monkeypatch.setattr(sql_source, "MariaDBMetadataSourceReader", Mock(return_value=provider))
    return case


def capture(case, major=15):
    return case.service.capture_financial_context(case.invoice.name, doctype=case.invoice.doctype, erp_major=major)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("optional", [True, False])
@pytest.mark.parametrize("parent_kind", access.PARENT_KINDS)
def test_same_owned_pipeline_binds_exact_financial_metadata_and_defaults(defaults_operator, monkeypatch, doctype, major, optional, parent_kind):
    case = scenario(defaults_operator, monkeypatch, doctype=doctype, optional=optional, parent_kind=parent_kind)
    result = capture(case, major)
    assert type(result) is access.SavedCalculationFinancialRead
    assert result.context.settings.defaults.parent == case.parent
    assert result.financial.financial.erp_major == major
    header = dict(json.loads(result.financial.financial._payload)["header"])
    assert header["grand_total"] == ["decimal", "8.700000000"]
    assert tuple(row.applied.name for row in result.context.metadata) == ("Company", doctype)
    minimal = ("Company", doctype)
    extended = (*minimal, *sorted(name for name in case.applied if name not in minimal))
    assert case.metadata_provider.call_args_list == [((case.scope, types),) for types in (minimal, extended, minimal, extended)]
    case.factory.assert_called_once_with(case.scope)
    assert case.database.rollback.call_count == 2 and case.database.close.call_count == 1
    assert result.context is not None and "PARTIAL" in repr(result) and case.invoice.name not in repr(result)
    with pytest.raises(FrozenInstanceError): result.context = None
    with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(result)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("denial", ["role", "invoice", "company"])
def test_acl_precedes_every_financial_metadata_factory_or_cache_read(defaults_operator, monkeypatch, denial):
    case = scenario(defaults_operator, monkeypatch)
    if denial == "role": defaults_operator.runtime.get_roles.return_value = []
    else:
        doc = case.invoice if denial == "invoice" else case.company
        defaults_operator.denied.add((doc.doctype, doc.name))
    with pytest.raises(PermissionDenied): capture(case)
    case.metadata_provider.assert_not_called()
    case.factory.assert_not_called()
    case.cache.assert_not_called()
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE)


@pytest.mark.parametrize("major", [None, True, "15", 14, 17])
def test_explicit_version_is_required_before_source_dependencies(defaults_operator, monkeypatch, major):
    case = scenario(defaults_operator, monkeypatch)
    with pytest.raises(InspectionFailed): capture(case, major)
    case.metadata_provider.assert_not_called()
    case.factory.assert_not_called()
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)


@pytest.mark.parametrize("boundary", [1, 2, 3, 4])
@pytest.mark.parametrize("change", ["permission", "actor", "revision", "error", "interrupt"])
def test_metadata_callbacks_are_followed_by_guards_and_one_safe_display(defaults_operator, monkeypatch, boundary, change):
    case = scenario(defaults_operator, monkeypatch)
    def supplied(scope, types):
        if case.metadata_provider.call_count == boundary:
            if change == "permission": defaults_operator.denied.add((case.invoice.doctype, case.invoice.name))
            elif change == "actor": defaults_operator.runtime.session.user = "other@example.invalid"
            elif change == "revision": case.invoice.modified += timedelta(seconds=1)
            elif change == "error": defaults_operator.runtime.throw("PRIVATE-METADATA", InspectionFailed)
            else: raise KeyboardInterrupt()
        return {name: case.applied[name] for name in types}
    case.metadata_provider.side_effect = supplied
    denied = change in ("permission", "actor")
    with pytest.raises(KeyboardInterrupt if change == "interrupt" else PermissionDenied if denied else InspectionFailed): capture(case)
    assert case.database.close.call_count == (0 if boundary <= 2 else 1)
    if change == "interrupt": assert defaults_operator.runtime.message_log == ["EXISTING-PARENT-MESSAGE"]
    else: one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE if denied else access.FINANCIAL_FAILED_MESSAGE)


@pytest.mark.parametrize("boundary", [1, 2])
@pytest.mark.parametrize("changed", ["header", "child_value", "child_revision", "child_insert", "child_delete", "child_order"])
def test_cache_cannot_hide_financial_changes_without_parent_revision(defaults_operator, monkeypatch, boundary, changed):
    case = scenario(defaults_operator, monkeypatch)
    def cached(*args):
        if case.cache.call_count == boundary:
            item = case.data.records["items"][0]
            if changed == "header": case.data.records["header"][0]["grand_total"] = None
            elif changed == "child_value": item["amount"] = None
            elif changed == "child_revision": item["modified"] += timedelta(seconds=1)
            elif changed == "child_insert": case.data.records["items"].append(dict(item, name="items-2", idx=2))
            elif changed == "child_delete": case.data.records["items"] = []
            else: item["idx"] = 2
        return {"currency_precision": "2"}
    case.cache.side_effect = cached
    with pytest.raises(InspectionFailed): capture(case)
    case.database.close.assert_called_once()
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)


@pytest.mark.parametrize("changed", ["root", "child", "extra", "missing", "financial"])
def test_extended_manifest_and_last_provider_callback_cannot_replace_bound_sources(defaults_operator, monkeypatch, changed):
    case = scenario(defaults_operator, monkeypatch)
    def supplied(scope, types):
        result = {name: case.applied[name] for name in types}
        if case.metadata_provider.call_count == 4:
            if changed == "extra": result["Customer"] = project(AppliedMeta("Customer", ()))
            elif changed == "missing": result.pop(types[-1])
            elif changed == "financial": case.data.records["items"][0]["amount"] = None
            else:
                name = case.invoice.doctype if changed == "root" else types[-1]
                raw = case.data.raw_metas[name]
                # A selected supported property changes the applied declaration.
                next(iter(raw.definitions.values())).values["options"] = "CHANGED"
                result[name] = project(raw)
        return result
    case.metadata_provider.side_effect = supplied
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)


@pytest.mark.parametrize("fault", ["context_type", "financial_type", "company", "status", "name", "revision", "metadata", "hash"])
def test_protected_result_reconstruction_rejects_cross_source_mismatch(defaults_operator, monkeypatch, fault):
    case = scenario(defaults_operator, monkeypatch)
    result = capture(case)
    changes = {}
    if fault == "context_type": changes["context"] = "PRIVATE"
    elif fault == "financial_type": changes["financial"] = "PRIVATE"
    elif fault == "hash": object.__setattr__(result.financial, "sha256", "f" * 64)
    else:
        settings = result.context.settings
        company, invoice = settings.sources
        if fault == "company":
            company = replace(company, name="OTHER")
            invoice = replace(invoice, values=("OTHER", invoice.values[1]))
        elif fault == "status": invoice = replace(invoice, values=(company.name, 2))
        elif fault == "name": invoice = replace(invoice, name="OTHER")
        elif fault == "revision": invoice = replace(invoice, revision=invoice.revision.replace("12:00", "13:00"))
        elif fault == "metadata":
            raw = case.data.raw_metas[case.invoice.doctype]
            raw.definitions["company"].values["options"] = "Company"
            changes["context"] = replace(result.context, metadata=(result.context.metadata[0], observed_metadata(raw)))
        if fault != "metadata": changes["context"] = replace(result.context, settings=replace(settings, sources=(company, invoice)))
    with pytest.raises(access.CalculationDefaultsAccessError) as caught: replace(result, **changes)
    assert str(caught.value) == "calculation_financial_access_result" and caught.value.__context__ is None


@pytest.mark.parametrize("denied", [False, True])
def test_single_arabic_failure_and_late_close_denial(defaults_operator, monkeypatch, denied):
    case = scenario(defaults_operator, monkeypatch)
    with (Path(__file__).resolve().parents[2] / "translations/ar.csv").open() as stream:
        translated = {row[0]: row[1] for row in csv.reader(stream) if len(row) >= 2}
    monkeypatch.setattr(access, "_", lambda message: translated[message])
    def close():
        if denied: defaults_operator.denied.add((case.invoice.doctype, case.invoice.name))
        else: defaults_operator.runtime.throw("PRIVATE-CLOSE", InspectionFailed)
    case.database.close.side_effect = close
    with pytest.raises(PermissionDenied if denied else InspectionFailed): capture(case)
    one_failure(defaults_operator, translated[access.FINANCIAL_DENIED_MESSAGE if denied else access.FINANCIAL_FAILED_MESSAGE])
    untouched(defaults_operator, case)


@pytest.mark.parametrize("docstatus", [0, 1, 2])
def test_saved_status_is_observed_without_phase2_or_previous_invoice_requirements(defaults_operator, monkeypatch, docstatus):
    case = scenario(defaults_operator, monkeypatch, docstatus=docstatus)
    result = capture(case)
    assert result.context.settings.sources[1].values[1] == docstatus
    assert dict(json.loads(result.financial.financial._payload)["header"])["docstatus"] == ["int", str(docstatus)]


def test_minimal_to_extended_root_metadata_drift_fails_before_sql(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    def supplied(scope, types):
        result = {name: case.applied[name] for name in types}
        if case.metadata_provider.call_count == 2:
            raw = case.data.raw_metas[case.invoice.doctype]
            raw.definitions["company"].values["options"] = "Company"
            result[case.invoice.doctype] = project(raw)
        return result
    case.metadata_provider.side_effect = supplied
    with pytest.raises(InspectionFailed): capture(case)
    case.factory.assert_not_called()
    case.cache.assert_not_called()
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
def test_captured_native_precision_uses_exact_metadata_and_defaults_without_io(defaults_operator, monkeypatch, major, doctype):
    case = scenario(defaults_operator, monkeypatch, doctype=doctype)
    result = capture(case, major)
    queries = tuple(defaults_operator.sql), tuple(case.data.connection.queries)
    reads = case.cache.call_count, case.metadata_provider.call_count
    header = result.resolve_precision(case.invoice.doctype, "grand_total")
    tax = result.resolve_precision("Sales Taxes and Charges", "tax_amount")
    assert header.precision == tax.precision == 2
    assert header.defaults == result.context.settings.defaults
    assert queries == (tuple(defaults_operator.sql), tuple(case.data.connection.queries))
    assert reads == (case.cache.call_count, case.metadata_provider.call_count)


@pytest.mark.parametrize("fault", ["unrelated", "field", "scope", "corrupt"])
def test_captured_precision_never_uses_an_unbound_type_or_default_scope(defaults_operator, monkeypatch, fault):
    case = scenario(defaults_operator, monkeypatch, parent_kind="global" if fault == "scope" else "site")
    result = capture(case)
    if fault == "corrupt": object.__setattr__(result.financial, "sha256", "f" * 64)
    with pytest.raises(access.CalculationDefaultsAccessError) as caught:
        result.resolve_precision("Company" if fault == "unrelated" else case.invoice.doctype,
            "PRIVATE" if fault == "field" else "grand_total")
    assert str(caught.value) == "calculation_financial_precision" and caught.value.__context__ is None
