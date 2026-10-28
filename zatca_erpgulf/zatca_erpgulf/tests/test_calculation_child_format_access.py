"""Selected child Company/formats on the shared service; synthetic sources."""

from dataclasses import replace
from copy import deepcopy
from datetime import timedelta
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import calculation_child_format_access as child_formats
from zatca_erpgulf.zatca_erpgulf import calculation_format_access as formats
from zatca_erpgulf.zatca_erpgulf import company_currency_source as company_sql
from zatca_erpgulf.zatca_erpgulf import currency_format_source as format_sql
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_access import scenario as child_case, saved_graph
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, one_failure, untouched, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_format_source import scenario as format_case, NOW
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta, project
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import Document


def bind_sources(case, operator, *, scope="company", row_currency="USD"):
    dt = case.data.own.applied.name
    raw = case.data.raw_metas[dt]
    raw.definitions["amount"].values["options"] = "Company:company:default_currency" if scope == "company" else "currency"
    case.data.metas[dt] = project(raw)
    case.observations[dt] = observed_metadata(raw)
    case.applied[dt] = case.data.metas[dt]
    raw_company = AppliedMeta("Company", ("default_currency",))
    raw_company.definitions["default_currency"].values.update(fieldtype="Link", options="Currency")
    case.observations["Company"] = observed_metadata(raw_company)
    case.applied["Company"] = case.observations["Company"].applied
    case.data.observations = case.observations
    case.data.records["items"][0]["currency"] = row_currency
    case.invoice.currency = case.data.records["header"][0]["currency"]
    saved_graph(operator, case)
    operator.runtime.local.lang = "ar"
    case.own_company = Document(doctype="Company", name="SYNTHETIC-CHILD-CO", modified=case.invoice.modified, default_currency="EUR")
    case.own_company.save, case.own_company.db_set, case.own_company.check_permission = Mock(), Mock(), Mock()
    company_df = Document(fieldtype="Link", options="Currency", permlevel=0)
    case.own_company.meta = SimpleNamespace(get_field=lambda name: company_df if name == "default_currency" else None,
        get_permlevel_access=Mock(return_value=[0]))
    case.company_df = company_df
    operator.documents["Company", case.own_company.name] = case.own_company
    case.expected_currency = "EUR" if scope == "company" else row_currency or case.invoice.currency
    case.expected_precision = 3 if case.expected_currency == "USD" else 8
    case.format_data = format_case(currency=case.expected_currency,
        currency_format="#,###.###" if case.expected_precision == 3 else "#.########")
    case.format_data.records["Company"] = [(case.own_company.name, case.own_company.modified, "EUR")]
    case.related, case.format_fields = {}, {}
    for dt, name, value in (("Currency", case.expected_currency, case.format_data.records["Currency"][0][2]),
            ("Language", "ar", "#,###.##"), ("System Settings", "System Settings", 1)):
        fieldname = format_sql.FLAG if dt == "System Settings" else "number_format"
        doc = Document(doctype=dt, name=name, modified=NOW, **{fieldname: value})
        doc.save, doc.db_set, doc.check_permission = Mock(), Mock(), Mock()
        df = Document(permlevel=0)
        doc.meta = SimpleNamespace(get_field=lambda name, df=df, fieldname=fieldname: df if name == fieldname else None,
            get_permlevel_access=Mock(return_value=[0]))
        case.related[dt], case.format_fields[dt] = doc, df
        operator.documents[dt, name] = doc
    case.format_metadata = Mock(side_effect=lambda *args: dict(case.format_data.metas))
    case.format_cache = Mock(side_effect=lambda *args: formats.CurrencyFormatContext("ar",
        case.related["Language"].number_format, bool(case.related["System Settings"].get(format_sql.FLAG)),
        case.expected_currency, case.related["Currency"].number_format))
    case.service = access.SavedCalculationDefaultsService(case.scope, case.factory, case.cache,
        applied_metadata_reader=case.metadata_provider, child_metadata_reader=case.child_metadata,
        format_metadata_reader=case.format_metadata, format_cache_reader=case.format_cache)
    return case


def scenario(operator, monkeypatch, **options):
    case = child_case(operator, monkeypatch, doctype=options.pop("doctype", "Sales Invoice"),
        present=options.pop("present", ("currency", "company")))
    bind_sources(case, operator, **options)
    native_cursor, format_cursor = case.database.cursor, case.format_data.connection.cursor
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=()):
            selected = any("FROM `tab" + dt + "`" in sql for dt in ("Currency", "Language", "Singles")) or ("FROM `tabCompany`" in sql and "OCTET_LENGTH(" in sql)
            self.current = format_cursor() if selected else native_cursor()
            self.current.execute(sql, params)
        def fetchone(self): return self.current.fetchone()
        def fetchall(self): return self.current.fetchall()
        @property
        def description(self): return self.current.description
    case.database.cursor = Mock(side_effect=Cursor)
    provider = Mock()
    provider.load_for_update.side_effect = lambda meta: case.format_data.observations[meta.name]
    provider.require_unchanged.return_value = None
    monkeypatch.setattr(format_sql, "MariaDBMetadataSourceReader", Mock(return_value=provider))
    monkeypatch.setattr(company_sql, "MariaDBMetadataSourceReader", Mock(return_value=case.data.metadata_reader))
    return case


def capture(case, *, major=16, row="items-1", field="amount"):
    return case.service.capture_child_field_context(case.invoice.name, "items", row, field,
        doctype=case.invoice.doctype, erp_major=major)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("scope", ["invoice", "company"])
@pytest.mark.parametrize("major", [15, 16])
def test_row_or_own_company_currency_and_versioned_precision_are_bound(defaults_operator, monkeypatch, doctype, scope, major):
    case = scenario(defaults_operator, monkeypatch, doctype=doctype, scope=scope)
    if major == 16:
        case.database.defaults = [(*row[:-1], "") for row in case.database.defaults]
        case.cache.return_value = {"currency_precision": ""}
    result = capture(case, major=major)
    assert type(result) is child_formats.SavedChildFieldRead
    assert result.resolve_currency().currency == case.expected_currency
    assert result.resolve_precision().precision == (2 if major == 15 else case.expected_precision)
    assert (result.company is not None) is (scope == "company")
    if scope == "company": assert result.company.name != case.company.name
    assert (result.formats is not None) is (major == 16)
    assert case.format_metadata.call_count == case.format_cache.call_count == (2 if major == 16 else 0)
    result.require_field_currency_match(row_entry=("str", case.expected_currency))
    result.require_cached_precision_match(result.resolve_precision().precision)
    assert case.factory.call_count == 1 and case.database.close.call_count == 1
    untouched(defaults_operator, case)


@pytest.mark.parametrize("denied", ["Company", "company_field", "Currency", "currency_field", "Language", "System Settings"])
def test_related_read_and_field_denials_precede_all_metadata_cache_and_sql(defaults_operator, monkeypatch, denied):
    case = scenario(defaults_operator, monkeypatch)
    if denied.endswith("field"):
        (case.company_df if denied == "company_field" else case.format_fields["Currency"]).permlevel = 1
    else:
        doc = case.own_company if denied == "Company" else case.related[denied]
        defaults_operator.denied.add((doc.doctype, doc.name))
    with pytest.raises(PermissionDenied): capture(case)
    for provider in (case.child_metadata, case.metadata_provider, case.format_metadata, case.format_cache, case.factory): provider.assert_not_called()
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE)


@pytest.mark.parametrize("boundary", ["format_first", "format_second", "cache_first", "cache_second", "close"])
@pytest.mark.parametrize("changed", ["company_currency", "company_permission", "format_permission", "company_field", "locale"])
def test_callbacks_and_cleanup_recheck_selected_company_formats_and_locale(defaults_operator, monkeypatch, boundary, changed):
    case = scenario(defaults_operator, monkeypatch)
    def mutate():
        if changed == "company_currency": case.own_company.default_currency = "SAR"
        elif changed == "company_permission": defaults_operator.denied.add(("Company", case.own_company.name))
        elif changed == "format_permission": defaults_operator.denied.add(("Currency", case.expected_currency))
        elif changed == "company_field": case.company_df.permlevel = 1
        else: defaults_operator.runtime.local.lang = "en"
    if boundary == "close": case.database.close.side_effect = mutate
    else:
        provider = case.format_metadata if boundary.startswith("format") else case.format_cache
        original = provider.side_effect
        def read(*args):
            result = original(*args)
            if provider.call_count == (1 if boundary.endswith("first") else 2): mutate()
            return result
        provider.side_effect = read
    denied = changed in ("company_permission", "format_permission", "company_field")
    with pytest.raises(PermissionDenied if denied else InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE if denied else access.FINANCIAL_FAILED_MESSAGE)


@pytest.mark.parametrize("fault", ["row", "field", "unreviewed_options"])
def test_unbound_field_selection_never_guesses_a_parent_company(defaults_operator, monkeypatch, fault):
    case = scenario(defaults_operator, monkeypatch)
    if fault == "unreviewed_options":
        case.field_overrides[case.data.own.applied.name, "amount"] = Document(fieldtype="Currency", options="unknown_currency", precision=None)
    with pytest.raises(InspectionFailed): capture(case, row="OTHER" if fault == "row" else "items-1", field="unselected" if fault == "field" else "amount")
    case.factory.assert_not_called()
    case.child_metadata.assert_not_called()


def unresolved_sources(case, *, company=None, flag=0):
    """Keep native/saved child links empty; prove locale without Currency rows."""
    case.refs["items"][0].company = case.saved["items", "items-1"].company = company
    case.data.records["items"][0]["company"] = company
    case.expected_currency = None
    case.format_data.records["Language"] = [("ar", NOW, "#,###.###")]
    case.format_data.records["System Settings"] = [("System Settings", format_sql.FLAG, str(flag))]
    case.related["Language"].number_format = "#,###.###"
    setattr(case.related["System Settings"], format_sql.FLAG, flag)
    case.format_metadata.side_effect = lambda *args: {name: meta for name, meta in case.format_data.metas.items() if name != "Currency"}
    case.format_cache.side_effect = lambda *args: formats.CurrencyFormatContext("ar",
        case.related["Language"].number_format, bool(case.related["System Settings"].get(format_sql.FLAG)), None, None)
    return case


def selected_capture(case, *, major, cached=False):
    method = case.service.capture_child_cached_context if cached else case.service.capture_child_field_context
    return method(case.invoice.name, "items", "items-1", "amount", doctype=case.invoice.doctype, erp_major=major)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("company", [None, ""])
@pytest.mark.parametrize("cached", [False, True])
def test_unresolved_own_company_uses_versioned_precision_without_guessing_a_currency(defaults_operator, monkeypatch, doctype, major, company, cached):
    case = unresolved_sources(scenario(defaults_operator, monkeypatch, doctype=doctype), company=company)
    if major == 16:
        case.database.defaults = [(*row[:-1], "") for row in case.database.defaults]
        case.cache.return_value = {"currency_precision": ""}
    result = selected_capture(case, major=major, cached=cached)
    bound = result.field if cached else result
    assert result.resolve_currency().currency is None and result.resolve_currency().origin == "UNRESOLVED"
    assert result.resolve_precision().precision == (2 if major == 15 else 3)
    assert bound.company is None and bound.company_rows == ()
    if major == 16:
        assert tuple(row.doctype for row in bound.related) == ("Language", "System Settings")
        assert bound.formats.context.currency is None
        assert case.format_metadata.call_args.args[1] == ("Language", "System Settings")
        assert case.format_cache.call_args.args[-1] is None
    else:
        assert bound.formats is None and bound.related == ()
        case.format_metadata.assert_not_called()
        case.format_cache.assert_not_called()
    assert not any(call.args[0] == "Currency" or call.args == ("Company", case.own_company.name)
        for call in defaults_operator.runtime.get_doc.call_args_list)
    assert not any("FROM `tabCurrency`" in sql for sql, _ in case.format_data.connection.queries)
    assert not hasattr(defaults_operator.runtime.local, "field_currency")
    assert all("_precision" not in vars(doc) for doc in (case.refs["items"][0], case.saved["items", "items-1"]))
    untouched(defaults_operator, case)


def test_unresolved_currency_override_is_refused_before_providers_or_sql(defaults_operator, monkeypatch):
    case = unresolved_sources(scenario(defaults_operator, monkeypatch), flag=1)
    with pytest.raises(InspectionFailed): capture(case)
    for provider in (case.child_metadata, case.metadata_provider, case.format_metadata, case.format_cache, case.factory):
        provider.assert_not_called()
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)


@pytest.mark.parametrize("major", [15, 16])
def test_absent_child_company_field_is_proved_absent_in_metadata_and_storage(defaults_operator, monkeypatch, major):
    case = unresolved_sources(scenario(defaults_operator, monkeypatch, present=("currency",)))
    result = selected_capture(case, major=major, cached=True)
    assert result.resolve_currency().inputs.row_company == ("absent",)
    assert result.resolve_currency().currency is None
    assert result.resolve_precision().precision == 2
    untouched(defaults_operator, case)


@pytest.mark.parametrize("slot", [None, ""])
def test_unresolved_parent_cache_null_and_blank_keep_framework_presence_semantics(defaults_operator, monkeypatch, slot):
    case = unresolved_sources(scenario(defaults_operator, monkeypatch))
    values = {(case.data.own.applied.name, case.invoice.name): {"amount": slot}}
    defaults_operator.runtime.local.field_currency = values
    before = deepcopy(values)
    if slot is None:
        for doc in (case.refs["items"][0], case.saved["items", "items-1"]): doc._precision = {"main": {"amount": 2}}
        assert selected_capture(case, major=16, cached=True).resolve_currency().currency is None
    else:
        with pytest.raises(InspectionFailed): selected_capture(case, major=16, cached=True)
        one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)
    assert defaults_operator.runtime.local.field_currency == before
    untouched(defaults_operator, case)


@pytest.mark.parametrize("changed", ["flag", "language_permission", "language_field", "close_locale", "stale_cache"])
def test_locale_only_scope_rejects_setting_permission_cleanup_and_cache_drift(defaults_operator, monkeypatch, changed):
    case = unresolved_sources(scenario(defaults_operator, monkeypatch))
    if changed == "stale_cache":
        defaults_operator.runtime.local.field_currency = {(case.data.own.applied.name, "items-1"): {"amount": "SAR"}}
    elif changed == "close_locale":
        case.database.close.side_effect = lambda: setattr(defaults_operator.runtime.local, "lang", "en")
    else:
        original = case.format_cache.side_effect
        def read(*args):
            result = original(*args)
            if changed == "flag": setattr(case.related["System Settings"], format_sql.FLAG, 1)
            elif changed == "language_permission": defaults_operator.denied.add(("Language", "ar"))
            else: case.format_fields["Language"].permlevel = 1
            return result
        case.format_cache.side_effect = read
    denied = changed in ("language_permission", "language_field")
    with pytest.raises(PermissionDenied if denied else InspectionFailed): selected_capture(case, major=16, cached=True)
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE if denied else access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("fault", ["company", "formats", "related"])
def test_unresolved_result_cannot_acquire_an_unrelated_company_or_currency(defaults_operator, monkeypatch, fault):
    resolved = capture(scenario(defaults_operator, monkeypatch))
    # Use a fresh synthetic graph so the first result is not the selected source.
    defaults_operator.runtime.get_doc.reset_mock()
    result = capture(unresolved_sources(scenario(defaults_operator, monkeypatch)))
    changes = {"company": resolved.company, "company_rows": resolved.company_rows} if fault == "company" else {fault: getattr(resolved, fault)}
    with pytest.raises(child_formats.CalculationChildAccessError, match="calculation_child_field_result"):
        replace(result, **changes)


@pytest.mark.parametrize("fault", ["company", "company_rows", "formats", "related", "row", "field"])
def test_protected_field_result_cannot_lose_or_rebind_selected_evidence(defaults_operator, monkeypatch, fault):
    result = capture(scenario(defaults_operator, monkeypatch))
    changes = {fault: None if fault in ("company", "formats") else () if fault in ("company_rows", "related") else "OTHER"}
    if fault == "row": changes = {"row_name": "OTHER"}
    if fault == "field": changes = {"fieldname": "OTHER"}
    with pytest.raises(child_formats.CalculationChildAccessError, match="calculation_child_field_result"): replace(result, **changes)
    assert "SYNTHETIC" not in repr(result)
    with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(result)


@pytest.mark.parametrize("value", [None, ""])
def test_empty_own_currency_uses_native_parent_currency_without_company_lookup(defaults_operator, monkeypatch, value):
    case = scenario(defaults_operator, monkeypatch, scope="invoice", row_currency=value)
    result = capture(case)
    assert result.resolve_currency().currency == case.invoice.currency == "SAR"
    assert result.company is None
    assert not any(call.args == ("Company", case.own_company.name) for call in defaults_operator.runtime.get_doc.call_args_list)


def test_normal_and_applied_field_definition_must_match_before_sql(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    raw = deepcopy(case.data.raw_metas[case.data.own.applied.name])
    raw.definitions["amount"].values["options"] = "currency"
    wrong = project(raw)
    original = case.metadata_provider.side_effect
    def supplied(*args):
        values = original(*args)
        if wrong.name in values: values[wrong.name] = wrong
        return values
    case.metadata_provider.side_effect = supplied
    with pytest.raises(InspectionFailed): capture(case)
    case.factory.assert_not_called()


def test_equal_numeric_precision_does_not_authorize_a_different_cached_currency(defaults_operator, monkeypatch):
    from zatca_erpgulf.zatca_erpgulf.child_field_currency import ChildFieldCurrencyError
    from zatca_erpgulf.zatca_erpgulf.calculation_precision import FieldPrecisionError
    result = capture(scenario(defaults_operator, monkeypatch))
    result.require_cached_precision_match(2)
    with pytest.raises(ChildFieldCurrencyError): result.require_field_currency_match(row_entry=("str", "SAR"))
    with pytest.raises(FieldPrecisionError): result.require_cached_precision_match(3)


@pytest.mark.parametrize("scope", ["global", "user"])
@pytest.mark.parametrize("major", [15, 16])
def test_field_precision_acquisition_never_silently_uses_non_site_default_scope(defaults_operator, monkeypatch, scope, major):
    case = scenario(defaults_operator, monkeypatch)
    case.service = access.SavedCalculationDefaultsService(case.scope, case.factory, case.cache,
        parent_kind=scope, applied_metadata_reader=case.metadata_provider, child_metadata_reader=case.child_metadata,
        format_metadata_reader=case.format_metadata, format_cache_reader=case.format_cache)
    with pytest.raises(InspectionFailed): capture(case, major=major)
    case.factory.assert_not_called()
    case.child_metadata.assert_not_called()


def test_currency_format_disabled_uses_captured_locale_without_changing_currency(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    case.database.defaults = [(*row[:-1], "") for row in case.database.defaults]
    case.cache.return_value = {"currency_precision": ""}
    setattr(case.related["System Settings"], format_sql.FLAG, 0)
    case.format_data.records["System Settings"] = [("System Settings", format_sql.FLAG, "0")]
    result = capture(case)
    assert result.resolve_currency().currency == "EUR"
    assert result.resolve_precision().precision == 2
