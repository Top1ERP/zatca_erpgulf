"""Party-currency aliases, Company API witnesses and pinned schema inventory."""

from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import hashlib
import importlib.util
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import calculation_owner_currency_access as owner
from zatca_erpgulf.zatca_erpgulf import company_currency_source as company_sql
from zatca_erpgulf.zatca_erpgulf import calculation_field_rounding_access as rounding
from zatca_erpgulf.zatca_erpgulf import calculation_format_access as formats
from zatca_erpgulf.zatca_erpgulf.source_metadata import OWNER_CURRENCY_PROFILE
from zatca_erpgulf.zatca_erpgulf.financial_source_observation import _canonical
from zatca_erpgulf.zatca_erpgulf.metadata_source import SelectedMetadataRows
from zatca_erpgulf.zatca_erpgulf.tests.test_field_rounding_formats import scenario as previous_case
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_field_rounding_access import capture
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_numeric_access import bind_numeric
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta, project
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, one_failure, untouched, PermissionDenied, InspectionFailed,
)


def configure(case, operator):
    dt = case.invoice.doctype
    raw = AppliedMeta(dt,("party_account_currency",))
    raw.definitions["party_account_currency"].values.update(fieldtype="Link",options="Currency")
    observation = observed_metadata(raw,profile=OWNER_CURRENCY_PROFILE)
    body = json.loads(observation._payload)
    for row in body["docfields"]: row["name"] += "-PARTY"
    case.owner_observation = SelectedMetadataRows(observation.applied,_canonical(body))
    case.owner_metadata = Mock(side_effect=lambda *args:{dt:case.owner_observation.applied})
    case.invoice.party_account_currency = "EUR"
    # Both main and parent-owned child numeric fields use this source alias.
    for name,field in ((dt,"grand_total"),("Sales Invoice Advance","allocated_amount")):
        selected = case.data.raw_metas[name]
        selected.definitions[field].values["options"] = "party_account_currency"
        case.data.metas[name] = case.applied[name] = project(selected)
        case.observations[name] = observed_metadata(selected)
    currency = case.related["Currency"]
    operator.documents.pop((currency.doctype,currency.name))
    currency.name,currency.number_format = "EUR","#.########"
    operator.documents[currency.doctype,currency.name] = currency
    case.format_data.records["Currency"] = [("EUR",currency.modified,currency.number_format)]
    case.format_data.records[dt] = [(case.invoice.name,case.invoice.modified,"EUR")]
    case.format_cache.side_effect = lambda *args: formats.CurrencyFormatContext("ar",
        case.related["Language"].number_format,True,"EUR",case.related["Currency"].number_format)
    bind_numeric(case,operator)
    case.field_overrides[dt,"party_account_currency"] = case.owner_observation.applied.get_field("party_account_currency")
    case.service = access.SavedCalculationDefaultsService(case.scope,case.factory,case.cache,
        applied_metadata_reader=case.metadata_provider,rounding_metadata_reader=case.round_metadata,
        rounding_cache_reader=case.round_cache,format_metadata_reader=case.format_metadata,
        format_cache_reader=case.format_cache,owner_currency_metadata_reader=case.owner_metadata,
        company_currency_cache_reader=case.company_api_cache)
    return case


def scenario(operator,monkeypatch,**options):
    case = previous_case(operator,monkeypatch,**options)
    cursor = case.database.cursor
    configure(case,operator)
    class Cursor:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,sql,params=()):
            self.current = case.format_data.connection.cursor() if "OCTET_LENGTH(`party_account_currency`)" in sql else cursor()
            self.current.execute(sql,params)
        def fetchone(self):return self.current.fetchone()
        def fetchall(self):return self.current.fetchall()
        @property
        def description(self):return self.current.description
    case.database.cursor = Mock(side_effect=Cursor)
    provider = Mock()
    provider.load_for_update.side_effect = lambda meta: case.owner_observation if meta.profile == OWNER_CURRENCY_PROFILE else case.observations[meta.name]
    monkeypatch.setattr(owner,"MariaDBMetadataSourceReader",Mock(return_value=provider))
    monkeypatch.setattr(company_sql,"MariaDBMetadataSourceReader",Mock(return_value=provider))
    return case


@pytest.mark.parametrize("doctype",["Sales Invoice","POS Invoice"])
@pytest.mark.parametrize("major",[15,16])
def test_root_party_currency_is_independent_of_invoice_and_company(defaults_operator,monkeypatch,doctype,major):
    case = scenario(defaults_operator,monkeypatch,doctype=doctype)
    result = capture(case,major)
    if major == 16:
        assert result.formats.formats.currency == "EUR"
        assert result.formats.owner_currency.currency == "EUR"
        assert result.precision.precision == 8
        assert result.numeric.financial.financial.financial.erp_major == 16
        case.company_api_cache.assert_not_called()
    else:
        assert result.formats is None
        case.owner_metadata.assert_not_called()
    result.require_result_match(8.7)
    assert case.factory.call_count == 1
    untouched(defaults_operator,case)


@pytest.mark.parametrize("boundary",["owner_metadata","format_cache","close"])
@pytest.mark.parametrize("changed",["value","permission","currency_cache"])
def test_party_source_and_cache_drift_never_disclose(defaults_operator,monkeypatch,boundary,changed):
    case = scenario(defaults_operator,monkeypatch)
    def mutate():
        if changed == "value":case.invoice.party_account_currency = "GBP"
        elif changed == "permission":
            case.field_overrides[case.invoice.doctype,"party_account_currency"] = type(case.round_df)(fieldtype="Link",options="Currency",permlevel=1)
        else:defaults_operator.runtime.local.field_currency = {}
    if boundary == "close":case.database.close.side_effect=mutate
    else:
        callback=getattr(case,boundary);old=callback.side_effect
        def call(*args):
            value=old(*args)
            if callback.call_count==2:mutate()
            return value
        callback.side_effect=call
    with pytest.raises(PermissionDenied if changed=="permission" else InspectionFailed):capture(case)


def test_party_field_read_precedes_its_metadata_provider(defaults_operator,monkeypatch):
    case=scenario(defaults_operator,monkeypatch)
    case.field_overrides[case.invoice.doctype,"party_account_currency"]=type(case.round_df)(fieldtype="Link",options="Currency",permlevel=1)
    with pytest.raises(PermissionDenied):capture(case)
    case.owner_metadata.assert_not_called()
    one_failure(defaults_operator,access.FINANCIAL_DENIED_MESSAGE)


@pytest.mark.parametrize("value",[None,"","EUR",1,False])
def test_company_api_projection_must_match_native_currency(defaults_operator,monkeypatch,value):
    case=previous_case(defaults_operator,monkeypatch,scope="company")
    case.company_cache_value=value
    with pytest.raises(InspectionFailed):capture(case,target=(None,None,"base_grand_total"))
    assert case.company_api_cache.called


def test_valid_local_company_currency_skips_unused_company_api(defaults_operator,monkeypatch):
    case=previous_case(defaults_operator,monkeypatch,scope="company")
    defaults_operator.runtime.local.field_currency={(case.invoice.doctype,case.invoice.name):{"base_grand_total":"SAR"}}
    case.company_cache_value="WRONG"
    result=capture(case,target=(None,None,"base_grand_total"))
    assert result.company_cache is None
    case.company_api_cache.assert_not_called()


def test_company_api_evidence_is_reconstructed_and_checked_after_cleanup(defaults_operator,monkeypatch):
    case=previous_case(defaults_operator,monkeypatch,scope="company")
    result=capture(case,target=(None,None,"base_grand_total"))
    assert result.company_cache==("str","SAR")
    with pytest.raises(rounding.FieldRoundingAccessError):replace(result,company_cache=None)
    case.database.close.side_effect=lambda:setattr(case,"company_cache_value","EUR")
    with pytest.raises(InspectionFailed):capture(case,target=(None,None,"base_grand_total"))


def test_pinned_standard_currency_inventory_exposes_all_three_source_families():
    data=json.loads(Path(__file__).with_name("erpnext_currency_fields_oracle.json").read_text())
    for major in (15,16):
        rows=[row for row in data["sources"] if row["erp_major"]==major]
        assert len(rows)==7 and len({row["commit"] for row in rows})==1
        counts=Counter(df.get("options") for row in rows for df in row["fields"])
        assert counts=={"currency":36,"Company:company:default_currency":32,"party_account_currency":6}
        aliases={(row["doctype"],df["fieldname"]) for row in rows for df in row["fields"] if df.get("options")=="party_account_currency"}
        assert ("Sales Invoice Advance","allocated_amount") in aliases
        assert ("Sales Invoice","outstanding_amount") in aliases


@pytest.mark.parametrize("value",[None,"","X"*4097])
def test_missing_or_oversized_native_party_link_is_never_guessed(defaults_operator,monkeypatch,value):
    case=scenario(defaults_operator,monkeypatch)
    case.format_data.records[case.invoice.doctype]=[(case.invoice.name,case.invoice.modified,value)]
    with pytest.raises(InspectionFailed):capture(case)
    one_failure(defaults_operator,access.FINANCIAL_FAILED_MESSAGE)


@pytest.mark.parametrize("fault",["scope","profile","definition"])
def test_party_metadata_provider_cannot_replace_its_bound_field(defaults_operator,monkeypatch,fault):
    case=scenario(defaults_operator,monkeypatch)
    if fault=="scope":case.owner_metadata.side_effect=lambda *args:{"Company":case.owner_observation.applied}
    elif fault=="profile":case.owner_metadata.side_effect=lambda *args:{case.invoice.doctype:case.applied[case.invoice.doctype]}
    else:
        bad=AppliedMeta(case.invoice.doctype,("party_account_currency",))
        bad.definitions["party_account_currency"].values.update(fieldtype="Link",options="Account")
        case.owner_metadata.side_effect=lambda *args:{case.invoice.doctype:observed_metadata(bad,profile=OWNER_CURRENCY_PROFILE).applied}
    with pytest.raises(InspectionFailed):capture(case)


def test_required_company_api_dependency_is_not_invented(defaults_operator,monkeypatch):
    case=previous_case(defaults_operator,monkeypatch,scope="company")
    case.service._company_currency_cache=None
    with pytest.raises(InspectionFailed):capture(case,target=(None,None,"base_grand_total"))


@pytest.mark.parametrize("major,default",[(15,""),(16,"2")])
def test_unused_party_provider_and_company_api_are_skipped(defaults_operator,monkeypatch,major,default):
    case=scenario(defaults_operator,monkeypatch,default=default)
    case.service._owner_currency_metadata=None
    case.service._company_currency_cache=None
    assert capture(case,major).formats is None
    case.owner_metadata.assert_not_called()
    case.company_api_cache.assert_not_called()


def test_inventory_tool_checks_hashes_and_reconstructs_selected_fields(tmp_path,monkeypatch):
    path=Path(__file__).resolve().parents[3]/"tools/audit_financial_currency_fields.py"
    spec=importlib.util.spec_from_file_location("currency_audit_test",path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    data=json.loads(Path(__file__).with_name("erpnext_currency_fields_oracle.json").read_text())
    data["sources"]=[row for row in data["sources"] if row["erp_major"]==15]
    for row in data["sources"]:
        fields=row["fields"]+([row["owner_link"]] if "owner_link" in row else [])
        raw=json.dumps(dict(name=row["doctype"],fields=fields)).encode()
        row["sha256"]=hashlib.sha256(raw).hexdigest()
        target=tmp_path/row["path"];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    oracle=tmp_path/"fixture.json";oracle.write_text(json.dumps(data))
    monkeypatch.setattr(module,"ORACLE",oracle)
    report=module.audit(tmp_path,15)
    assert report["currency_fields"]==74 and report["unsupported_options"]==[]
    (tmp_path/data["sources"][0]["path"]).write_bytes(b"changed")
    with pytest.raises(ValueError,match="currency_inventory_source_mismatch"):module.audit(tmp_path,15)
