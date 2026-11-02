"""Advance formats on a NEW guard-owned TCP-disabled SQL fixture only."""

import json
import os
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from copy import deepcopy

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial
from zatca_erpgulf.zatca_erpgulf.calculation_precision import CurrencyFormatContext
from zatca_erpgulf.zatca_erpgulf.metadata_source import SelectedMetadataRows
from zatca_erpgulf.zatca_erpgulf.source_metadata import CHILD_CURRENCY_PROFILE
from zatca_erpgulf.zatca_erpgulf import calculated_totals as totals
from zatca_erpgulf.zatca_erpgulf import calculation_advance_rounding as advance
from zatca_erpgulf.zatca_erpgulf.tests.test_calculated_totals import controller
from zatca_erpgulf.zatca_erpgulf.tests.test_field_rounding import framework
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_advance_rounding import capture, guard_precision
from zatca_erpgulf.zatca_erpgulf.tests.test_calculated_totals_mariadb import native_case as previous_case
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_numeric_access import bind_numeric
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_format_access import bind_formats
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta, project
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access_mariadb import (
    combined_schema, defaults_schema, financial_schema, metadata_schema, isolated_server, connections, untouched,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_format_source_mariadb import format_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_field_currency_access_mariadb import field_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_format_access_mariadb import empty_sources
from zatca_erpgulf.zatca_erpgulf.tests.test_rounding_stage_mariadb import selected_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_format_access_mariadb import seed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, one_failure, InspectionFailed, PermissionDenied,
)

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW guard-owned temporary SQL only; never a tenant or authority connection")


def native_case(operator, connections, *, currencies=("USD", "SAR", "USD"), default="",
        own_company=False, company_option=False, use_currency_format=True, party_option=False, **options):
    case = previous_case(operator, connections, advance_rows=len(currencies), advance_root_precision=3, **options)
    system = case.round_doc
    bind_formats(case, operator)
    flag = case.related["System Settings"].get("use_number_format_from_currency")
    system.use_number_format_from_currency = flag
    system.use_number_format_from_currency = int(use_currency_format)
    case.format_data.records["System Settings"] = [
        (dt, name, str(int(use_currency_format))) for dt, name, value in case.format_data.records["System Settings"]]
    old_get = system.meta.get_field
    system.meta.get_field = lambda name: Document(fieldtype="Check", permlevel=0) if name == "use_number_format_from_currency" else old_get(name)
    case.related["System Settings"] = system
    operator.documents[system.doctype, system.name] = system
    for dt in ("Currency", "Language"):
        case.related[dt].meta = SimpleNamespace(get_field=lambda name: Document(permlevel=0),
            get_permlevel_access=Mock(return_value=[0]))
    usd = Document(doctype="Currency", name="USD", modified=case.related["Currency"].modified, number_format="#,###.###")
    usd.meta = case.related["Currency"].meta
    usd.save, usd.db_set = Mock(), Mock()
    operator.documents["Currency", "USD"] = usd
    case.format_data.records["Currency"].append((usd.name, usd.modified, usd.number_format))
    raw = case.data.raw_metas["Sales Invoice Advance"]
    raw.definitions["allocated_amount"].values["options"] = "Company:company:default_currency" if company_option else "currency"
    if party_option: raw.definitions["allocated_amount"].values["options"] = "party_account_currency"
    case.data.metas[raw.name] = case.applied[raw.name] = project(raw)
    case.observations[raw.name] = observed_metadata(raw)
    own = AppliedMeta(raw.name, ("currency", "company"))
    own.definitions["currency"].values.update(fieldtype="Link", options="Currency")
    own.definitions["company"].values.update(fieldtype="Link", options="Company")
    case.own_observation = observed_metadata(own, profile=CHILD_CURRENCY_PROFILE)
    body = json.loads(case.own_observation._payload)
    for row in body["docfields"]: row["name"] += "-LINK"
    case.own_observation = SelectedMetadataRows(case.own_observation.applied, financial._canonical(body))
    case.child_metadata = Mock(side_effect=lambda scope, names: {raw.name: case.own_observation.applied})
    for record, currency in zip(case.data.records["advances"], currencies):
        record.update(currency=currency, company=case.company.name if own_company else None)
    bind_numeric(case, operator)
    for name in ("currency", "company"):
        case.field_overrides[raw.name, name] = own.definitions[name]
    guard_precision(case)
    company_meta = AppliedMeta("Company", ("default_currency",))
    company_meta.definitions["default_currency"].values.update(fieldtype="Link", options="Currency")
    case.observations["Company"] = observed_metadata(company_meta)
    case.applied["Company"] = case.observations["Company"].applied
    case.company.default_currency = "SAR"
    company_df = Document(fieldtype="Link", options="Currency", permlevel=0)
    case.company.meta = SimpleNamespace(get_field=lambda name: company_df if name == "default_currency" else None,
        get_permlevel_access=Mock(return_value=[0]))
    case.format_metadata.side_effect = lambda scope, names: {name: case.format_data.metas[name] for name in names}
    case.cache.return_value = {"currency_precision": default}
    case.database.defaults = [(*row[:-1], default) for row in case.database.defaults]
    def format_context(scope, language, currency):
        doc = operator.documents["Currency", currency] if currency else None
        return CurrencyFormatContext(language, case.related["Language"].number_format,
            bool(system.use_number_format_from_currency), currency, None if doc is None else doc.number_format)
    case.format_cache.side_effect = format_context
    case.service = access.SavedCalculationDefaultsService(case.scope, case.factory, case.cache,
        applied_metadata_reader=case.metadata_provider, rounding_metadata_reader=case.round_metadata,
        rounding_cache_reader=case.round_cache, child_metadata_reader=case.child_metadata,
        format_metadata_reader=case.format_metadata, format_cache_reader=case.format_cache)
    setup = connections()
    changed = ("Company", case.invoice.doctype, "Sales Invoice Advance")
    with setup.cursor() as cursor:
        for name in ("currency", "company"):
            cursor.execute("ALTER TABLE `tabSales Invoice Advance` ADD COLUMN IF NOT EXISTS `" + name + "` VARCHAR(140)")
        for dt in changed: cursor.execute("DELETE FROM `tabDocField` WHERE parent=%s", (dt,))
        cursor.execute("UPDATE `tabDefaultValue` SET defvalue=%s", (default,))
        cursor.execute("UPDATE `tabCompany` SET default_currency='SAR'")
        for record in case.data.records["advances"]:
            cursor.execute("UPDATE `tabSales Invoice Advance` SET currency=%s,company=%s WHERE name=%s",
                (record["currency"], record["company"], record["name"]))
    for dt in changed: seed_metadata(setup, case.observations[dt], groups=("docfields",))
    seed_metadata(setup, case.own_observation, groups=("docfields",))
    for dt, observation in case.format_data.observations.items():
        if dt == "System Settings":
            body = json.loads(observation._payload)
            for row in body["docfields"]: row["name"] += "-FORMAT"
            observation = SelectedMetadataRows(observation.applied, financial._canonical(body))
            seed_metadata(setup, observation, groups=("docfields",))
        else: seed_metadata(setup, observation)
    with setup.cursor() as cursor:
        for dt in ("Currency", "Language", "System Settings"):
            for row in case.format_data.records[dt]:
                cursor.execute("INSERT INTO `tab" + ("Singles" if dt == "System Settings" else dt) + "` VALUES (%s,%s,%s)", row)
    setup.commit()  # NEW synthetic fixture setup only.
    setup.close()
    return case


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
def test_distinct_direct_row_currencies_use_one_owned_context(defaults_operator, connections, doctype, isolation):
    case = native_case(defaults_operator, connections, doctype=doctype, isolation=isolation)
    result = capture(case)
    assert result.row_precisions == (("advances-1", 3), ("advances-2", 8), ("advances-3", 3))
    assert result.fields[0].field.formats == result.fields[2].field.formats
    assert result.fields[0].field.formats != result.fields[1].field.formats
    assert len(case.opened) == 1 and case.opened[0].rollback.call_count == 2
    for doc in case.saved.values(): doc.precision.assert_not_called()
    untouched(defaults_operator, case)


@pytest.mark.parametrize("major", [15, 16])
def test_bound_aggregate_matches_actual_controller_prefix(defaults_operator, connections, monkeypatch, upstream16, major):
    case = native_case(defaults_operator, connections)
    result = capture(case, major)
    amounts = (1.23456, 1.123456789, None)
    rows = totals.CalculationRows(result.stage.numeric.view.financial, "advances", "CALCULATED",
        tuple((name, amount) for (name, precision), amount in zip(result.row_precisions, amounts)))
    calculated = totals.AdvanceAggregateCalculation(result.stage, rows, result)
    probe = framework(major, upstream16, monkeypatch, setting="Commercial Rounding")
    traces, seen = [], []
    class Checkpoint(Exception): pass
    class Root:
        def __setattr__(self, name, value):
            if name == "total_advance": seen.append(value); raise Checkpoint
            object.__setattr__(self, name, value)
        def get(self, name): return getattr(self, name, None)
        def precision(self, name): traces.append((case.invoice.name, name, 3)); return 3
    doc = Root()
    doc.docstatus = SimpleNamespace(is_cancelled=lambda: False)
    doc.advances = []
    for (name, digits), amount in zip(result.row_precisions, amounts):
        def precision(field, name=name, digits=digits): traces.append((name, field, digits)); return digits
        doc.advances.append(SimpleNamespace(allocated_amount=amount, precision=precision))
    with pytest.raises(Checkpoint): controller("calculate_total_advance", major, {"flt": probe.flt})(SimpleNamespace(doc=doc))
    settings = tuple((call.args[0], "Commercial Rounding") for call in probe.runtime.get_system_settings.call_args_list)
    calculated.require_match(total_advance=seen[0], setting_trace=settings, precision_trace=tuple(traces))
    if major == 16:
        assert calculated.row_precision is None and calculated.total_advance == 2.358
        with pytest.raises(totals.CalculatedTotalsError): totals.AdvanceAggregateCalculation(result.stage, rows)
    else:
        assert result.fields == () and calculated.row_precision == 2
        case.child_metadata.assert_not_called()
        case.format_metadata.assert_not_called()
    untouched(defaults_operator, case)


@pytest.mark.parametrize("empty", [None, ""])
def test_missing_own_row_currency_uses_saved_parent_currency(defaults_operator, connections, empty):
    case = native_case(defaults_operator, connections, currencies=(empty,) * 3)
    result = capture(case)
    assert result.row_precisions == tuple(("advances-" + str(i + 1), 8) for i in range(3))
    assert all(row.field.resolve_currency().origin == "PARENT_CURRENCY" for row in result.fields)
    assert len({row.field.formats.sha256 for row in result.fields}) == 1
    untouched(defaults_operator, case)


@pytest.mark.parametrize("own", [False, True])
def test_company_option_uses_only_own_company_or_disabled_locale(defaults_operator, connections, own):
    case = native_case(defaults_operator, connections, company_option=True, own_company=own,
        use_currency_format=own)
    result = capture(case)
    assert all(precision == (8 if own else 2) for name, precision in result.row_precisions)
    assert all(row.field.resolve_currency().currency == ("SAR" if own else None) for row in result.fields)
    assert all((row.field.company is not None) is own for row in result.fields)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("source", ["USD", "SAR", "language", "format_field"])
def test_all_related_access_precedes_child_and_format_callbacks(defaults_operator, connections, source):
    case = native_case(defaults_operator, connections)
    if source == "format_field":
        defaults_operator.documents["Currency", "SAR"].meta.get_field = lambda name: Document(permlevel=1)
    else:
        defaults_operator.denied.add(("Language", "ar") if source == "language" else ("Currency", source))
    with pytest.raises(PermissionDenied): capture(case)
    case.child_metadata.assert_not_called()
    case.format_metadata.assert_not_called()
    case.format_cache.assert_not_called()
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("boundary", ["format_metadata", "format_cache", "close"])
@pytest.mark.parametrize("changed", ["currency", "precision"])
def test_callback_or_close_cannot_warm_a_later_rows_cache(defaults_operator, connections, boundary, changed):
    case = native_case(defaults_operator, connections)
    callback = case.opened if boundary == "close" else getattr(case, boundary)
    def change():
        if changed == "precision": case.saved["advances", "advances-3"]._precision = {"main": {"allocated_amount": 3}}
        else: defaults_operator.runtime.local.field_currency = {("Sales Invoice Advance", "advances-3"): {"allocated_amount": "USD"}}
    if boundary == "close":
        original_factory = case.factory.side_effect
        def acquire(*args):
            connection = original_factory(*args)
            old_close = connection.close.side_effect
            def close():
                result = old_close(); change(); return result
            connection.close.side_effect = close
            return connection
        case.factory.side_effect = acquire
    else:
        old = callback.side_effect
        def read(*args):
            result = old(*args); change(); return result
        callback.side_effect = read
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("changed", ["link", "format", "allocated", "default", "method"])
def test_same_owned_native_changes_without_timestamp_are_refused_and_rolled_back(defaults_operator, connections, changed):
    case = native_case(defaults_operator, connections)
    old = case.format_cache.side_effect
    edits = []
    def read(*args):
        result = old(*args)
        if not edits:
            with case.opened[0].cursor() as cursor:
                if changed == "link": cursor.execute("UPDATE `tabSales Invoice Advance` SET currency='SAR' WHERE name='advances-1'")
                elif changed == "format": cursor.execute("UPDATE `tabCurrency` SET number_format='#.###' WHERE name='USD'")
                elif changed == "allocated": cursor.execute("UPDATE `tabSales Invoice Advance` SET allocated_amount=2")
                elif changed == "default": cursor.execute("UPDATE `tabDefaultValue` SET defvalue='4'")
                else: cursor.execute("UPDATE `tabSingles` SET value='Banker''s Rounding' WHERE field='rounding_method'")
            edits.append(changed)
        return result
    case.format_cache.side_effect = read
    with pytest.raises(InspectionFailed): capture(case)
    assert edits == [changed]
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator, case)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT currency,allocated_amount FROM `tabSales Invoice Advance` WHERE name='advances-1'")
        assert cursor.fetchone() == ("USD", Decimal("1.000000000"))
        cursor.execute("SELECT number_format FROM `tabCurrency` WHERE name='USD'")
        assert cursor.fetchone() == ("#,###.###",)
        cursor.execute("SELECT defvalue FROM `tabDefaultValue`")
        assert cursor.fetchone() == ("",)
        cursor.execute("SELECT value FROM `tabSingles` WHERE field='rounding_method'")
        assert cursor.fetchone() == ("Commercial Rounding",)
    observer.close()


@pytest.mark.parametrize("major,default,empty", [(15,"",False),(16,"2",False),(16,"",True)])
def test_unused_direct_currency_dependencies_are_not_acquired(defaults_operator, connections, major, default, empty):
    case = native_case(defaults_operator, connections, default=default, currencies=() if empty else ("USD","SAR","USD"))
    defaults_operator.runtime.local.field_currency = "MALFORMED-UNUSED"
    result = capture(case, major)
    assert result.fields == ()
    assert result.row_precisions == (() if empty else (("advances-1",2),("advances-2",2),("advances-3",2)))
    case.child_metadata.assert_not_called()
    case.format_metadata.assert_not_called()
    case.format_cache.assert_not_called()
    assert defaults_operator.runtime.local.field_currency == "MALFORMED-UNUSED"
    untouched(defaults_operator, case)


@pytest.mark.parametrize("currencies,expected", [(("USD",) * 3, ["USD"]), (("USD","SAR","USD"), ["USD","SAR"])])
def test_each_distinct_currency_has_one_initial_format_source(defaults_operator, connections, monkeypatch, currencies, expected):
    case = native_case(defaults_operator, connections, currencies=currencies)
    calls = []
    original = advance.FormatAcquisition.load_for_update
    def load(source, connection):
        calls.append(source.currency)
        return original(source, connection)
    monkeypatch.setattr(advance.FormatAcquisition, "load_for_update", load)
    result = capture(case)
    assert calls == expected and len(result.fields) == 3
    untouched(defaults_operator, case)


def test_missing_own_company_does_not_inherit_the_invoice_company(defaults_operator, connections):
    case = native_case(defaults_operator, connections, company_option=True)
    with pytest.raises(InspectionFailed): capture(case)
    case.child_metadata.assert_not_called()
    case.format_metadata.assert_not_called()
    untouched(defaults_operator, case)


def test_existing_row_caches_are_compared_without_refresh(defaults_operator, connections):
    case = native_case(defaults_operator, connections)
    currencies = {}
    for index, (currency, precision) in enumerate((("USD",3),("SAR",8),("USD",3)), 1):
        name = "advances-" + str(index)
        currencies["Sales Invoice Advance", name] = {"allocated_amount": currency}
        case.saved["advances", name]._precision = {"main": {"allocated_amount": precision}}
        case.refs["advances"][index - 1]._precision = {"main": {"allocated_amount": precision}}
    defaults_operator.runtime.local.field_currency = currencies
    before = deepcopy(currencies)
    result = capture(case)
    assert result.row_precisions == (("advances-1",3),("advances-2",8),("advances-3",3))
    assert defaults_operator.runtime.local.field_currency == before
    for doc in case.saved.values(): doc.precision.assert_not_called()
    untouched(defaults_operator, case)


@pytest.mark.parametrize("major,default,success", [(15,"",True),(16,"2",True),(16,"",False)])
def test_standard_party_option_never_substitutes_invoice_currency(defaults_operator, connections, major, default, success):
    case = native_case(defaults_operator, connections, party_option=True, default=default)
    if success:
        result = capture(case, major)
        assert result.row_precisions == (("advances-1",2),("advances-2",2),("advances-3",2))
    else:
        with pytest.raises(InspectionFailed): capture(case, major)
        one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)
    case.child_metadata.assert_not_called()
    case.format_metadata.assert_not_called()
    case.format_cache.assert_not_called()
    untouched(defaults_operator, case)
