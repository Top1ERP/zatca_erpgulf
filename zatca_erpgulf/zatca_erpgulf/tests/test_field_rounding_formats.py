"""Lazy v16 owner-field formats on the same numeric/default/method pipeline."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import frappe
from frappe.model import meta as framework_meta
from frappe.utils import cstr

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import calculation_field_rounding_access as rounding
from zatca_erpgulf.zatca_erpgulf import currency_format_source as sql
from zatca_erpgulf.zatca_erpgulf import company_currency_source as company_sql
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_field_rounding_access import scenario as previous_case, capture
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_numeric_access import bind_numeric
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_format_access import bind_formats
from zatca_erpgulf.zatca_erpgulf.tests.test_field_currency_access import bind_fields
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, one_failure, untouched, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16


def configure(case, operator, *, scope="invoice", default=""):
    original_system = case.round_doc
    bind_formats(case, operator)
    bind_fields(case, operator, scope=scope)
    # One saved Singleton exposes both independently captured selected fields.
    flag = case.related["System Settings"].get(sql.FLAG)
    setattr(original_system, sql.FLAG, flag)
    original_get = original_system.meta.get_field
    flag_df = Document(fieldtype="Check", permlevel=0)
    original_system.meta.get_field = lambda name: flag_df if name == sql.FLAG else original_get(name)
    case.related["System Settings"] = original_system
    operator.documents[original_system.doctype, original_system.name] = original_system
    case.format_fields = {}
    for dt in ("Currency", "Language"):
        definition = Document(fieldtype="Select", permlevel=0)
        case.format_fields[dt] = definition
        case.related[dt].meta = SimpleNamespace(get_field=lambda name, df=definition: df,
            get_permlevel_access=Mock(return_value=[0]))
    company_df = Document(fieldtype="Link", options="Currency", permlevel=0)
    case.format_fields["Company"] = company_df
    case.company.meta = SimpleNamespace(get_field=lambda name: company_df, get_permlevel_access=Mock(return_value=[0]))
    case.format_fields["System Settings"] = flag_df
    # Rebind the saved numeric graph after adding the base Currency fields.
    bind_numeric(case, operator)
    case.database.defaults = [(*row[:-1], default) for row in case.database.defaults]
    case.cache.return_value = {"currency_precision": default}
    case.company_cache_value = "SAR"
    case.company_api_cache = Mock(side_effect=lambda *args: case.company_cache_value)
    case.service = access.SavedCalculationDefaultsService(case.scope, case.factory, case.cache,
        applied_metadata_reader=case.metadata_provider, rounding_metadata_reader=case.round_metadata,
        rounding_cache_reader=case.round_cache, format_metadata_reader=case.format_metadata,
        format_cache_reader=case.format_cache, company_currency_cache_reader=case.company_api_cache)
    return case


def scenario(operator, monkeypatch, *, scope="invoice", default="", **options):
    case = previous_case(operator, monkeypatch, **options)
    previous_cursor = case.database.cursor
    configure(case, operator, scope=scope, default=default)
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, statement, params=()):
            selected = any("FROM `tab"+dt+"`" in statement for dt in ("Currency", "Language"))
            selected = selected or "FROM `tabCompany`" in statement and "OCTET_LENGTH(" in statement
            selected = selected or "FROM `tabSingles`" in statement and len(params) > 1 and params[1] == sql.FLAG
            self.current = case.format_data.connection.cursor() if selected else previous_cursor()
            self.current.execute(statement, params)
        def fetchone(self): return self.current.fetchone()
        def fetchall(self): return self.current.fetchall()
        @property
        def description(self): return self.current.description
    case.database.cursor = Mock(side_effect=Cursor)
    provider = Mock()
    provider.load_for_update.side_effect = lambda meta: case.format_data.observations[meta.name]
    monkeypatch.setattr(sql, "MariaDBMetadataSourceReader", Mock(return_value=provider))
    monkeypatch.setattr(company_sql, "MariaDBMetadataSourceReader", access.MariaDBMetadataSourceReader)
    return case


def target(scope, child):
    field = ("base_amount" if child else "base_grand_total") if scope == "company" else ("amount" if child else "grand_total")
    return ("items", "items-1", field) if child else (None, None, field)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("scope,expected", [("invoice", 3), ("company", 8)])
@pytest.mark.parametrize("child", [False, True])
@pytest.mark.parametrize("cached", [False, True])
def test_selected_owner_field_resolves_exact_formats_on_one_handle(defaults_operator, monkeypatch, doctype, scope, expected, child, cached):
    case = scenario(defaults_operator, monkeypatch, doctype=doctype, scope=scope)
    selected = target(scope, child)
    if cached:
        defaults_operator.runtime.local.field_currency = {(doctype, case.invoice.name): {selected[2]: "SAR" if scope == "company" else "USD"}}
    result = capture(case, target=selected)
    assert result.precision.precision == expected
    assert result.formats.formats.currency == ("SAR" if scope == "company" else "USD")
    assert result.formats.financial == result.numeric.financial
    result.require_result_match(1.0 if child else 8.7)
    assert case.factory.call_count == 1 and case.database.rollback.call_count == 2
    assert ("_precision" in vars(case.invoice)) is False
    untouched(defaults_operator, case)


@pytest.mark.parametrize("major,default", [(15,""),(16,"0"),(16,"2"),(16,"bad")])
def test_unused_format_sources_are_not_authorized_or_called(defaults_operator, monkeypatch, major, default):
    case = scenario(defaults_operator, monkeypatch, default=default)
    defaults_operator.denied.add(("Currency", "USD"))
    defaults_operator.runtime.local.field_currency = object()
    result = capture(case, major)
    assert result.formats is None and result.currency_cache is None
    case.format_metadata.assert_not_called()
    case.format_cache.assert_not_called()


@pytest.mark.parametrize("denied", ["Currency", "Language", "System Settings", "Company"])
def test_format_field_read_precedes_its_providers(defaults_operator, monkeypatch, denied):
    case = scenario(defaults_operator, monkeypatch, scope="company")
    case.format_fields[denied].permlevel = 1
    with pytest.raises(PermissionDenied): capture(case, target=target("company", False))
    case.format_metadata.assert_not_called()
    case.format_cache.assert_not_called()
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE)


@pytest.mark.parametrize("value", [None, "", "SAR", 1, False])
def test_blocked_or_stale_owner_currency_cache_is_not_repaired(defaults_operator, monkeypatch, value):
    case = scenario(defaults_operator, monkeypatch)
    cache = {(case.invoice.doctype,case.invoice.name): {"grand_total": value}}
    defaults_operator.runtime.local.field_currency = cache
    with pytest.raises(InspectionFailed): capture(case)
    assert cache[case.invoice.doctype,case.invoice.name]["grand_total"] is value


@pytest.mark.parametrize("boundary", ["format_metadata", "format_cache", "close"])
@pytest.mark.parametrize("changed", ["currency_cache", "locale", "currency", "field_acl", "precision_cache"])
def test_late_format_callbacks_and_cleanup_cannot_hide_drift(defaults_operator, monkeypatch, boundary, changed):
    case = scenario(defaults_operator, monkeypatch)
    def mutate():
        if changed == "currency_cache": defaults_operator.runtime.local.field_currency = {(case.invoice.doctype,case.invoice.name): {"grand_total":"USD"}}
        elif changed == "locale": defaults_operator.runtime.local.lang = "en"
        elif changed == "currency": case.invoice.currency = "EUR"
        elif changed == "field_acl": case.format_fields["Currency"].permlevel = 1
        else: case.invoice._precision = {"main": {"grand_total": 3}}
    if boundary == "close": case.database.close.side_effect = mutate
    else:
        callback = case.format_metadata if boundary == "format_metadata" else case.format_cache
        old = callback.side_effect
        def call(*args):
            value = old(*args)
            if callback.call_count == 2: mutate()
            return value
        callback.side_effect = call
    with pytest.raises(PermissionDenied if changed == "field_acl" else InspectionFailed): capture(case)


def test_result_reconstruction_refuses_missing_or_cross_field_formats(defaults_operator, monkeypatch):
    result = capture(scenario(defaults_operator, monkeypatch))
    for changes in (dict(formats=None),dict(currency_cache=None),dict(target=("header",result.target[1],"base_grand_total"))):
        with pytest.raises(rounding.FieldRoundingAccessError): replace(result, **changes)


@pytest.mark.parametrize("scope,precision", [("invoice",3),("company",8)])
@pytest.mark.parametrize("child", [False,True])
def test_existing_owner_precision_must_match_format_resolution(defaults_operator, monkeypatch, scope, precision, child):
    case = scenario(defaults_operator, monkeypatch, scope=scope)
    selected = target(scope, child)
    case.invoice._precision = {selected[0] or "main": {selected[2]: precision}}
    capture(case,target=selected).require_result_match(1.0 if child else 8.7)


def test_child_currency_cache_is_not_the_parent_owner_cache(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    defaults_operator.runtime.local.field_currency = {("Sales Invoice Item","items-1"): {"amount":"WRONG"}}
    capture(case,target=target("invoice",True)).require_result_match(1.0)


@pytest.mark.parametrize("boundary", ["format_metadata","format_cache"])
@pytest.mark.parametrize("interrupt", [KeyboardInterrupt,SystemExit])
def test_deferred_format_interrupts_propagate_after_owned_cleanup(defaults_operator, monkeypatch, boundary, interrupt):
    case = scenario(defaults_operator, monkeypatch)
    getattr(case,boundary).side_effect = interrupt
    with pytest.raises(interrupt): capture(case)
    case.database.close.assert_called_once()
    assert defaults_operator.runtime.message_log == ["EXISTING-PARENT-MESSAGE"]


@pytest.mark.parametrize("major", [15,16])
@pytest.mark.parametrize("options,expected", [("currency","USD"),("Company:company:default_currency","SAR")])
def test_real_helpers_key_child_field_currency_by_the_passed_parent_owner(upstream16,monkeypatch,major,options,expected):
    owner = frappe._dict(doctype="Sales Invoice",name="SYNTHETIC-OWNER",currency="USD",company="SYNTHETIC-CO")
    definition = frappe._dict(fieldname="amount",options=options)
    cache = {("Sales Invoice Item","SYNTHETIC-ROW"): {"amount":"WRONG"}}
    runtime = SimpleNamespace(local=SimpleNamespace(field_currency=cache),_dict=frappe._dict,
        get_cached_value=Mock(return_value="SAR"))
    if major == 15:
        monkeypatch.setattr(framework_meta,"frappe",runtime)
        actual = framework_meta.get_field_currency(definition,owner)
    else:
        monkeypatch.setitem(upstream16,"frappe",runtime)
        monkeypatch.setitem(upstream16,"cstr",cstr)
        actual = upstream16["get_field_currency"](definition,owner)
    assert actual == expected
    assert cache[owner.doctype,owner.name]["amount"] == expected
    assert cache["Sales Invoice Item","SYNTHETIC-ROW"]["amount"] == "WRONG"


@pytest.mark.parametrize("mode", ["disabled","null_format","blank_format"])
def test_locale_precision_is_used_when_currency_format_is_unavailable_or_disabled(defaults_operator,monkeypatch,mode):
    case = scenario(defaults_operator,monkeypatch)
    if mode == "disabled":
        setattr(case.related["System Settings"],sql.FLAG,0)
        case.format_data.records["System Settings"] = [("System Settings",sql.FLAG,"0")]
    else:
        value = None if mode == "null_format" else ""
        case.related["Currency"].number_format = value
        first,modified,_ = case.format_data.records["Currency"][0]
        case.format_data.records["Currency"] = [(first,modified,value)]
    result = capture(case)
    assert result.precision.precision == 2
    result.require_result_match(8.7)
