"""Raw guard Checks/Links on the shared bounded native root-control reader."""
import pickle
import pytest
from pymysql.constants import FIELD_TYPE as FT

from zatca_erpgulf.zatca_erpgulf.outstanding_guard_source import LockedOutstandingGuardsRead,MariaDBOutstandingGuardsReader
from zatca_erpgulf.zatca_erpgulf.source_metadata import OUTSTANDING_GUARDS_PROFILE
from zatca_erpgulf.zatca_erpgulf.financial_source_sql import MariaDBInvoiceFinancialReader
from zatca_erpgulf.zatca_erpgulf.invoice_rounding_source import InvoiceRoundingSourceError
from zatca_erpgulf.zatca_erpgulf.tests.test_invoice_rounding_source import scenario as previous
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta,project
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata


def scenario(monkeypatch,doctype="Sales Invoice",present=LockedOutstandingGuardsRead.FIELDS,flag=0):
    case=previous(monkeypatch,doctype=doctype)
    raw=AppliedMeta(doctype,present);links=dict(LockedOutstandingGuardsRead.LINKS)
    for name,df in raw.definitions.items():
        df.values.update(fieldtype="Link" if name in links else "Check",options=(links[name] or doctype) if name in links else None)
        case.connection.signatures["header",name]=[FT.VAR_STRING,140,0,True] if name in links else [FT.LONG,20,0,True]
    root=case.raw_metas[doctype]
    for name in LockedOutstandingGuardsRead.OVERLAP:
        if name in present:root.definitions[name]=raw.definitions[name]
        else:root.definitions.pop(name,None)
    case.metas[doctype]=project(root);case.observations[doctype]=observed_metadata(root)
    values=dict(company=case.records["header"][0]["company"],return_against="ORIGINAL",represents_company=None,
        **{name:flag for name in LockedOutstandingGuardsRead.CHECKS})
    case.records["header"][0].update({name:values[name] for name in present})
    case.guard_metadata=observed_metadata(raw,profile=OUTSTANDING_GUARDS_PROFILE)
    old=case.metadata_reader.load_for_update.side_effect
    case.metadata_reader.load_for_update.side_effect=lambda meta:case.guard_metadata if meta.profile==OUTSTANDING_GUARDS_PROFILE else old(meta)
    case.connection.columns=set(present)
    case.financial=MariaDBInvoiceFinancialReader(case.connection).load_for_update(doctype,case.name,erp_major=16,applied_metadata=case.metas)
    case.guard_reader=MariaDBOutstandingGuardsReader(case.connection)
    return case


@pytest.mark.parametrize("doctype",["Sales Invoice","POS Invoice"])
@pytest.mark.parametrize("present",[("company","is_return"),LockedOutstandingGuardsRead.OVERLAP,LockedOutstandingGuardsRead.FIELDS])
@pytest.mark.parametrize("flag",[None,0,1])
def test_raw_links_nulls_and_check_projection_leave_financial_bytes_intact(monkeypatch,doctype,present,flag):
    case=scenario(monkeypatch,doctype,present,flag)
    before=case.financial._payload,case.financial.sha256,case.financial.financial._payload
    native=case.guard_reader.load_for_update(case.financial,applied_metadata=case.guard_metadata.applied)
    assert native.normalized_checks==tuple((name,(flag or 0) if name in present else None) for name in native.CHECKS)
    case.guard_reader.require_unchanged(native)
    assert (native.financial._payload,native.financial.sha256,native.financial.financial._payload)==before
    assert "ORIGINAL" not in repr(native)
    with pytest.raises(TypeError):pickle.dumps(native)


@pytest.mark.parametrize("name",LockedOutstandingGuardsRead.FIELDS)
def test_native_values_cannot_change_without_revision(monkeypatch,name):
    case=scenario(monkeypatch)
    native=case.guard_reader.load_for_update(case.financial,applied_metadata=case.guard_metadata.applied)
    case.records["header"][0][name]=1 if name in native.CHECKS else "CHANGED"
    with pytest.raises(InvoiceRoundingSourceError):case.guard_reader.require_unchanged(native)


@pytest.mark.parametrize("field",["company","return_against","represents_company"])
def test_link_target_metadata_is_not_interchangeable(monkeypatch,field):
    case=scenario(monkeypatch)
    raw=AppliedMeta(case.doctype,LockedOutstandingGuardsRead.FIELDS)
    for name,df in raw.definitions.items():
        links=dict(LockedOutstandingGuardsRead.LINKS)
        df.values.update(fieldtype="Link" if name in links else "Check",options=(links[name] or case.doctype) if name in links else None)
    raw.definitions[field].values["options"]="Customer"
    wrong=observed_metadata(raw,profile=OUTSTANDING_GUARDS_PROFILE)
    with pytest.raises(InvoiceRoundingSourceError):case.guard_reader.load_for_update(case.financial,applied_metadata=wrong.applied)


@pytest.mark.parametrize("doctype",["Sales Invoice","POS Invoice"])
def test_return_link_cannot_target_the_other_invoice_type(monkeypatch,doctype):
    case=scenario(monkeypatch,doctype=doctype)
    raw=AppliedMeta(doctype,LockedOutstandingGuardsRead.FIELDS)
    links=dict(LockedOutstandingGuardsRead.LINKS)
    for name,df in raw.definitions.items():
        df.values.update(fieldtype="Link" if name in links else "Check",options=(links[name] or doctype) if name in links else None)
    raw.definitions["return_against"].values["options"]="POS Invoice" if doctype=="Sales Invoice" else "Sales Invoice"
    wrong=observed_metadata(raw,profile=OUTSTANDING_GUARDS_PROFILE)
    with pytest.raises(InvoiceRoundingSourceError):case.guard_reader.load_for_update(case.financial,applied_metadata=wrong.applied)
