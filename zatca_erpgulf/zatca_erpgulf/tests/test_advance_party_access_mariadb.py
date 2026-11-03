"""Same-owned party fallback on NEW guard-owned TCP-disabled SQL only."""
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial
from zatca_erpgulf.zatca_erpgulf import calculated_totals as totals
from zatca_erpgulf.zatca_erpgulf.tests import test_calculation_precision as primary
from zatca_erpgulf.zatca_erpgulf.tests.test_field_rounding import framework
from zatca_erpgulf.zatca_erpgulf.tests.test_calculated_totals import controller
from frappe.utils import cstr
import frappe
from zatca_erpgulf.zatca_erpgulf.source_metadata import ADVANCE_PARTY_PROFILE, OWNER_CURRENCY_PROFILE
from zatca_erpgulf.zatca_erpgulf.metadata_source import SelectedMetadataRows
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_advance_rounding_mariadb import native_case as previous_case
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_advance_rounding import capture
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta
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
    reason="NEW temporary TCP-disabled synthetic SQL only; no tenant or authority access")


def observation(raw, profile, suffix):
    initial = observed_metadata(raw, profile=profile)
    body = json.loads(initial._payload)
    for row in body["docfields"]: row["name"] += suffix
    return SelectedMetadataRows(initial.applied, financial._canonical(body))


def native_case(operator, connections, *, values=None, **options):
    case = previous_case(operator, connections, party_option=True, **options)
    raw = AppliedMeta("Sales Invoice Advance", ("party_account_currency",) if values is not None else ())
    if values is not None: raw.definitions["party_account_currency"].values.update(fieldtype="Link", options="Currency")
    case.party_observation = observation(raw, ADVANCE_PARTY_PROFILE, "-ADVANCE-PARTY")
    meta = case.normal_metas[raw.name]
    meta.istable, meta.issingle = 1, 0
    case.party_df = Document(fieldname="party_account_currency", fieldtype="Link", options="Currency", permlevel=0)
    if values is not None: case.field_overrides[raw.name, "party_account_currency"] = case.party_df
    for i, row in enumerate(case.refs["advances"]):
        value = None if values is None else values[i]
        if values is not None:
            row.party_account_currency = value
            case.saved["advances", row.name].party_account_currency = value
    root = AppliedMeta(case.invoice.doctype, ("party_account_currency",))
    root.definitions["party_account_currency"].values.update(fieldtype="Link", options="Currency")
    case.owner_observation = observation(root, OWNER_CURRENCY_PROFILE, "-OWNER-PARTY")
    case.field_overrides[case.invoice.doctype, "party_account_currency"] = case.owner_observation.applied.get_field("party_account_currency")
    case.invoice.party_account_currency = "SAR"
    case.invoice.currency = case.data.records["header"][0]["currency"] = "USD"
    case.party_metadata = Mock(side_effect=lambda *args: {raw.name: case.party_observation.applied})
    case.owner_metadata = Mock(side_effect=lambda *args: {root.name: case.owner_observation.applied})
    case.service = access.SavedCalculationDefaultsService(case.scope, case.factory, case.cache,
        applied_metadata_reader=case.metadata_provider, rounding_metadata_reader=case.round_metadata,
        rounding_cache_reader=case.round_cache, child_metadata_reader=case.child_metadata,
        format_metadata_reader=case.format_metadata, format_cache_reader=case.format_cache,
        owner_currency_metadata_reader=case.owner_metadata, advance_party_metadata_reader=case.party_metadata)
    setup = connections()
    with setup.cursor() as cursor:
        cursor.execute("ALTER TABLE `tab" + root.name + "` ADD COLUMN IF NOT EXISTS party_account_currency VARCHAR(140)")
        cursor.execute("UPDATE `tab" + root.name + "` SET currency='USD',party_account_currency='SAR'")
        cursor.execute("ALTER TABLE `tabSales Invoice Advance` DROP COLUMN IF EXISTS party_account_currency")
        if values is not None:
            cursor.execute("ALTER TABLE `tabSales Invoice Advance` ADD COLUMN party_account_currency VARCHAR(140)")
            for index, value in enumerate(values, 1):
                cursor.execute("UPDATE `tabSales Invoice Advance` SET party_account_currency=%s WHERE name=%s", (value, "advances-" + str(index)))
    seed_metadata(setup, case.owner_observation, groups=("docfields",))
    seed_metadata(setup, case.party_observation, groups=("docfields",))
    setup.commit()  # NEW synthetic fixture setup only.
    setup.close()
    return case


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("values,expected", [(None,(8,8,8)),((None,"","SAR"),(8,8,8)),(("USD",)*3,(3,3,3)),(("USD",None,"SAR"),(3,8,8))])
def test_standard_party_option_uses_actual_own_or_parent_party(defaults_operator, connections, doctype, values, expected):
    case = native_case(defaults_operator, connections, doctype=doctype, values=values)
    result = capture(case)
    assert tuple(precision for name, precision in result.row_precisions) == expected
    assert result.party is not None and result.fields == ()
    if values == ("USD",)*3:
        assert result.party.parent is None
        case.owner_metadata.assert_not_called()
    else:
        assert result.party.parent.currency == "SAR"
    assert len(case.opened) == 1
    untouched(defaults_operator, case)


@pytest.mark.parametrize("values", [None, ("USD",None,"SAR")])
def test_primary_v16_currency_and_precision_helpers_match_the_bound_source(defaults_operator, connections, monkeypatch, values):
    case = native_case(defaults_operator, connections, values=values)
    result = capture(case)
    # The precision oracle replaces its currency dependency. Keep its globals
    # local to this test instead of mutating the module-scoped excerpt fixture.
    upstream16 = primary.upstream16.__wrapped__()
    actual_currency = upstream16["get_field_currency"]
    amounts = (1.23456, 1.123456789, None)
    for index, (name, precision) in enumerate(result.row_precisions):
        parent_read = Mock(return_value="SAR")
        runtime = SimpleNamespace(local=SimpleNamespace(field_currency={}), _dict=frappe._dict,
            db=SimpleNamespace(get_value=parent_read), get_meta=lambda dt: SimpleNamespace(has_field=lambda field: field=="party_account_currency"))
        upstream16["frappe"], upstream16["cstr"] = runtime, cstr
        doc = frappe._dict(doctype="Sales Invoice Advance", name=name, parent=case.invoice.name,
            parenttype=case.invoice.doctype, parentfield="advances", party_account_currency=None if values is None else values[index])
        df = frappe._dict(fieldname="allocated_amount", fieldtype="Currency", options="party_account_currency", precision=None)
        currency = actual_currency(df, doc)
        context = result.party.formats[index][1].context
        assert currency == context.currency
        assert primary.oracle(16, upstream16, monkeypatch, df, {"currency_precision":""}, context) == precision
        if values is None or not values[index]: parent_read.assert_called_once_with(case.invoice.doctype, case.invoice.name, "party_account_currency")
        else: parent_read.assert_not_called()
    rows = totals.CalculationRows(result.stage.numeric.view.financial,"advances","CALCULATED",
        tuple((name,value) for (name,p),value in zip(result.row_precisions,amounts)))
    calculated = totals.AdvanceAggregateCalculation(result.stage,rows,result)
    probe = framework(16,upstream16,monkeypatch,setting="Commercial Rounding")
    traces, seen = [], []
    class Checkpoint(Exception): pass
    class Root:
        def __setattr__(self,name,value):
            if name=="total_advance":seen.append(value);raise Checkpoint
            object.__setattr__(self,name,value)
        def get(self,name):return getattr(self,name,None)
        def precision(self,name):traces.append((case.invoice.name,name,3));return 3
    doc=Root();doc.docstatus=SimpleNamespace(is_cancelled=lambda:False);doc.advances=[]
    for (name,digits),amount in zip(result.row_precisions,amounts):
        def precision(field,name=name,digits=digits):traces.append((name,field,digits));return digits
        doc.advances.append(SimpleNamespace(allocated_amount=amount,precision=precision))
    with pytest.raises(Checkpoint):controller("calculate_total_advance",16,{"flt":probe.flt})(SimpleNamespace(doc=doc))
    calculated.require_match(total_advance=seen[0],
        setting_trace=tuple((call.args[0],"Commercial Rounding") for call in probe.runtime.get_system_settings.call_args_list),
        precision_trace=tuple(traces))
    untouched(defaults_operator, case)


@pytest.mark.parametrize("denied", ["row_field","parent_field","USD","SAR"])
def test_party_and_related_permissions_precede_new_providers(defaults_operator, connections, denied):
    case = native_case(defaults_operator, connections, values=("USD",None,"SAR"))
    if denied == "row_field": case.party_df.permlevel = 1
    elif denied == "parent_field":
        case.field_overrides[case.invoice.doctype,"party_account_currency"] = Document(fieldname="party_account_currency",fieldtype="Link",options="Currency",permlevel=1)
    else: defaults_operator.denied.add(("Currency",denied))
    with pytest.raises(PermissionDenied): capture(case)
    for callback in (case.party_metadata,case.owner_metadata,case.format_metadata): callback.assert_not_called()
    one_failure(defaults_operator,access.FINANCIAL_DENIED_MESSAGE)
    untouched(defaults_operator,case)


@pytest.mark.parametrize("changed", ["parent","child","amount","format","metadata"])
def test_same_owned_native_party_drift_is_refused_and_rolled_back(defaults_operator, connections, changed):
    case = native_case(defaults_operator,connections,values=("USD",None,"SAR"))
    old=case.format_cache.side_effect
    edits=[]
    def read(*args):
        result=old(*args)
        if not edits:
            with case.opened[0].cursor() as cursor:
                if changed=="parent":cursor.execute("UPDATE `tabSales Invoice` SET party_account_currency='USD'")
                elif changed=="child":cursor.execute("UPDATE `tabSales Invoice Advance` SET party_account_currency='USD' WHERE name='advances-2'")
                elif changed=="amount":cursor.execute("UPDATE `tabSales Invoice Advance` SET allocated_amount=2")
                elif changed=="format":cursor.execute("UPDATE `tabCurrency` SET number_format='#.###' WHERE name='SAR'")
                else:cursor.execute("UPDATE `tabDocField` SET options='Company' WHERE parent='Sales Invoice Advance' AND fieldname='party_account_currency'")
            edits.append(changed)
        return result
    case.format_cache.side_effect=read
    with pytest.raises(InspectionFailed):capture(case)
    assert edits==[changed]
    one_failure(defaults_operator,access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator,case)
    observer=connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT party_account_currency FROM `tabSales Invoice` WHERE name=%s",(case.invoice.name,))
        assert cursor.fetchone()==("SAR",)
        cursor.execute("SELECT party_account_currency,allocated_amount FROM `tabSales Invoice Advance` WHERE name='advances-2'")
        party,amount=cursor.fetchone()
        assert party is None and amount==1
    observer.close()


@pytest.mark.parametrize("changed", ["row","parent","precision","currency_cache"])
def test_close_cannot_hide_original_saved_or_cache_drift(defaults_operator,connections,changed):
    case=native_case(defaults_operator,connections,values=("USD",None,"SAR"))
    factory=case.factory.side_effect
    def acquire(*args):
        connection=factory(*args)
        close=connection.close.side_effect
        def finish():
            result=close()
            if changed=="row":case.refs["advances"][0].party_account_currency="SAR"
            elif changed=="parent":case.invoice.party_account_currency="USD"
            elif changed=="precision":case.saved["advances","advances-1"]._precision={"main":{"allocated_amount":3}}
            else:defaults_operator.runtime.local.field_currency={("Sales Invoice Advance","advances-1"):{"allocated_amount":"USD"}}
            return result
        connection.close.side_effect=finish
        return connection
    case.factory.side_effect=acquire
    with pytest.raises(InspectionFailed):capture(case)
    one_failure(defaults_operator,access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator,case)


def test_undeclared_physical_party_column_is_refused(defaults_operator,connections):
    case=native_case(defaults_operator,connections)
    setup=connections()
    with setup.cursor() as cursor:cursor.execute("ALTER TABLE `tabSales Invoice Advance` ADD COLUMN party_account_currency VARCHAR(140)")
    setup.commit();setup.close()  # NEW synthetic fixture only.
    with pytest.raises(InspectionFailed):capture(case)
    untouched(defaults_operator,case)


def test_blank_parent_party_is_not_replaced_with_transaction_currency(defaults_operator,connections):
    case=native_case(defaults_operator,connections)
    case.invoice.party_account_currency=""
    with pytest.raises(InspectionFailed):capture(case)
    for callback in (case.party_metadata,case.owner_metadata,case.format_metadata):callback.assert_not_called()
    untouched(defaults_operator,case)
