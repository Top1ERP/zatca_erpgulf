"""Explicit invoice/Company currency and parent-document child precision."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_format_access as formats
from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import company_currency_source as company_source
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_format_access import scenario as previous_case
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, one_failure, untouched, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta, Definition, project
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata


def bind_fields(case, operator, *, scope="company"):
    case.currency_scope = scope
    case.invoice.currency = "USD"
    case.company.default_currency = "SAR"
    case.data.records["header"][0]["currency"] = "USD"
    case.format_data.records["Company"] = [(case.company.name, case.company.modified, "SAR")]
    company = AppliedMeta("Company", ("default_currency",))
    company.definitions["default_currency"].values.update(fieldtype="Link", options="Currency")
    case.company_meta = company
    case.applied["Company"] = project(company)
    case.observations["Company"] = observed_metadata(company)
    root = case.data.raw_metas[case.invoice.doctype]
    root.definitions["base_grand_total"] = Definition("base_grand_total", fieldtype="Currency", options="Company:company:default_currency")
    case.data.records["header"][0]["base_grand_total"] = case.data.records["header"][0]["grand_total"]
    if hasattr(case.data.connection, "signatures"):
        case.data.connection.signatures["header", "base_grand_total"] = list(case.data.connection.signatures["header", "grand_total"])
    child_name = "Sales Invoice Item" if case.invoice.doctype == "Sales Invoice" else "POS Invoice Item"
    child = case.data.raw_metas[child_name]
    child.definitions["amount"].values["options"] = "currency"
    child.definitions["base_amount"] = Definition("base_amount", fieldtype="Currency", options="Company:company:default_currency")
    case.data.records["items"][0]["base_amount"] = case.data.records["items"][0]["amount"]
    if hasattr(case.data.connection, "signatures"):
        case.data.connection.signatures["items", "base_amount"] = list(case.data.connection.signatures["items", "amount"])
    for raw in (root, child):
        case.data.metas[raw.name] = project(raw)
        case.applied[raw.name] = case.data.metas[raw.name]
        case.observations[raw.name] = observed_metadata(raw)
    target, number_format = ("SAR", "#.########") if scope == "company" else ("USD", "#,###.###")
    old = case.related["Currency"]
    operator.documents.pop((old.doctype, old.name))
    old.name, old.number_format = target, number_format
    operator.documents[old.doctype, old.name] = old
    case.format_data.records["Currency"] = [(target, old.modified, number_format)]
    case.format_cache.side_effect = lambda *args: formats.CurrencyFormatContext("ar", case.related["Language"].number_format,
        bool(case.related["System Settings"].get("use_number_format_from_currency")), target, case.related["Currency"].number_format)
    return case


def scenario(operator, monkeypatch, *, doctype="Sales Invoice", scope="company"):
    case = previous_case(operator, monkeypatch, doctype=doctype)
    bind_fields(case, operator, scope=scope)
    old_cursor, text_cursor = case.database.cursor, case.format_data.connection.cursor
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=()):
            self.current = text_cursor() if "FROM `tabCompany`" in sql and "OCTET_LENGTH(" in sql else old_cursor()
            self.current.execute(sql, params)
        def fetchone(self): return self.current.fetchone()
        def fetchall(self): return self.current.fetchall()
        @property
        def description(self): return self.current.description
    case.database.cursor = Mock(side_effect=Cursor)
    monkeypatch.setattr(company_source, "MariaDBMetadataSourceReader", access.MariaDBMetadataSourceReader)
    case.database.defaults = [(*row[:-1], "") for row in case.database.defaults]
    case.cache.return_value = {"currency_precision": ""}
    return case


def capture(case):
    method = case.service.capture_base_currency_context if case.currency_scope == "company" else case.service.capture_currency_context
    return method(case.invoice.name, doctype=case.invoice.doctype)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("scope", ["invoice", "company"])
def test_scope_selects_the_correct_currency_for_root_and_parent_child_fields(defaults_operator, monkeypatch, doctype, scope):
    case = scenario(defaults_operator, monkeypatch, doctype=doctype, scope=scope)
    result = capture(case)
    root, child, wrong, currency, precision = ("base_grand_total", "base_amount", "grand_total", "SAR", 8) if scope == "company" else ("grand_total", "amount", "base_grand_total", "USD", 3)
    assert result.resolve_precision(root).precision == result.resolve_precision(child, parentfield="items").precision == precision
    result.require_field_currency_match(child, currency, parentfield="items")
    with pytest.raises(formats.CalculationFormatAccessError): result.resolve_precision(wrong)
    assert result.formats.currency == currency
    assert (result.company_currency is not None) is (scope == "company")
    assert case.factory.call_count == 1 and case.database.close.call_count == 1
    untouched(defaults_operator, case)


@pytest.mark.parametrize("boundary", ["metadata_first", "metadata_second", "cache_first", "cache_second", "close"])
def test_saved_company_currency_changes_without_revision_never_disclose(defaults_operator, monkeypatch, boundary):
    case = scenario(defaults_operator, monkeypatch)
    def mutate(): case.company.default_currency = "EUR"
    if boundary == "close": case.database.close.side_effect = mutate
    else:
        callback = case.format_metadata if boundary.startswith("metadata") else case.format_cache
        original = callback.side_effect
        def change(*args):
            result = original(*args)
            if callback.call_count == (1 if boundary.endswith("first") else 2): mutate()
            return result
        callback.side_effect = change
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)


@pytest.mark.parametrize("changed", ["link", "revision"])
def test_native_company_drift_is_checked_after_the_last_cache_callback(defaults_operator, monkeypatch, changed):
    case = scenario(defaults_operator, monkeypatch)
    original = case.format_cache.side_effect
    def cached(*args):
        result = original(*args)
        if case.format_cache.call_count == 2:
            case.format_data.records["Company"] = [(case.company.name, case.company.modified + timedelta(seconds=1) if changed == "revision" else case.company.modified,
                "EUR" if changed == "link" else "SAR")]
        return result
    case.format_cache.side_effect = cached
    with pytest.raises(InspectionFailed): capture(case)


@pytest.mark.parametrize("denied", ["Company", "Currency"])
def test_normal_company_and_selected_currency_read_are_mandatory(defaults_operator, monkeypatch, denied):
    case = scenario(defaults_operator, monkeypatch)
    doc = case.company if denied == "Company" else case.related["Currency"]
    defaults_operator.denied.add((doc.doctype, doc.name))
    with pytest.raises(PermissionDenied): capture(case)
    case.factory.assert_not_called()
    case.format_metadata.assert_not_called()
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE)


@pytest.mark.parametrize("cached", ["USD", None, "", False, ["SAR"]])
def test_field_currency_cache_mismatch_is_not_repaired_or_silently_accepted(defaults_operator, monkeypatch, cached):
    result = capture(scenario(defaults_operator, monkeypatch))
    with pytest.raises(formats.CalculationFormatAccessError) as caught:
        result.require_field_currency_match("base_amount", cached, parentfield="items")
    assert str(caught.value) == "calculation_field_currency_cache_mismatch"


@pytest.mark.parametrize("fault", ["missing", "derived", "company", "revision"])
def test_company_proof_cannot_be_removed_or_rebound_on_result_reconstruction(defaults_operator, monkeypatch, fault):
    result = capture(scenario(defaults_operator, monkeypatch))
    changes = {}
    if fault == "missing": changes["company_currency"] = None
    elif fault == "derived": object.__setattr__(result.company_currency, "currency", "EUR")
    elif fault == "company":
        from zatca_erpgulf.zatca_erpgulf.financial_source_observation import _canonical
        import json
        body = json.loads(result.company_currency._payload)
        body["record"]["name"] = "OTHER"
        changes["company_currency"] = replace(result.company_currency, name="OTHER", _payload=_canonical(body))
    else:
        from zatca_erpgulf.zatca_erpgulf.financial_source_observation import _canonical
        import json
        body = json.loads(result.company_currency._payload)
        body["record"]["modified"] = ["datetime", "2026-10-27T19:00:00.000000"]
        changes["company_currency"] = replace(result.company_currency, _payload=_canonical(body))
    with pytest.raises(formats.CalculationFormatAccessError): replace(result, **changes)


def test_unknown_parent_or_direct_child_currency_option_is_refused(defaults_operator, monkeypatch):
    result = capture(scenario(defaults_operator, monkeypatch))
    for parentfield in ("missing", "company", None):
        with pytest.raises(formats.CalculationFormatAccessError): result.resolve_precision("base_amount", parentfield=parentfield)
