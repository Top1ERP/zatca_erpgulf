"""Write-off side profile invariants; all records and SQL are synthetic."""
from decimal import Decimal
import pickle
from pymysql.constants import FIELD_TYPE as FT
import pytest

from zatca_erpgulf.zatca_erpgulf.write_off_source import MariaDBWriteOffReader, LockedWriteOffRead
from zatca_erpgulf.zatca_erpgulf.invoice_rounding_source import InvoiceRoundingSourceError
from zatca_erpgulf.zatca_erpgulf.source_metadata import WRITE_OFF_PROFILE
from zatca_erpgulf.zatca_erpgulf.tests.test_invoice_rounding_source import scenario as previous
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata


def scenario(monkeypatch,auto=0):
    case=previous(monkeypatch)
    raw=AppliedMeta(case.doctype,LockedWriteOffRead.FIELDS)
    for name in LockedWriteOffRead.FIELDS:
        raw.definitions[name].values["fieldtype"]="Check" if name in LockedWriteOffRead.CHECKS else "Currency"
        case.connection.signatures["header",name]=[FT.LONG,20,0,True] if name in LockedWriteOffRead.CHECKS else [FT.NEWDECIMAL,23,9,True]
    case.write_meta=observed_metadata(raw,profile=WRITE_OFF_PROFILE)
    case.connection.columns=set(LockedWriteOffRead.FIELDS)
    case.records["header"][0].update(write_off_amount=Decimal("1.234500000"),base_write_off_amount=Decimal("1.500000000"),
        write_off_outstanding_amount_automatically=auto)
    old=case.metadata_reader.load_for_update.side_effect
    case.metadata_reader.load_for_update.side_effect=lambda meta:case.write_meta if meta.profile==WRITE_OFF_PROFILE else old(meta)
    case.write_reader=MariaDBWriteOffReader(case.connection)
    return case


@pytest.mark.parametrize("auto",[None,0,1])
def test_raw_money_and_normalized_check_do_not_change_old_financial_bytes(monkeypatch,auto):
    case=scenario(monkeypatch,auto)
    before=case.financial._payload,case.financial.financial._payload,case.financial.sha256
    result=case.write_reader.load_for_update(case.financial,applied_metadata=case.write_meta.applied)
    assert result.normalized_checks==(("write_off_outstanding_amount_automatically",0 if auto is None else auto),)
    result.require_saved_check_match({"write_off_outstanding_amount_automatically":auto})
    case.write_reader.require_unchanged(result)
    assert (result.financial._payload,result.financial.financial._payload,result.financial.sha256)==before
    assert "1.2345" not in repr(result)
    with pytest.raises(TypeError):pickle.dumps(result)


def test_native_write_off_change_without_revision_is_refused(monkeypatch):
    case=scenario(monkeypatch)
    result=case.write_reader.load_for_update(case.financial,applied_metadata=case.write_meta.applied)
    case.records["header"][0]["write_off_amount"]=Decimal("2.000000000")
    with pytest.raises(InvoiceRoundingSourceError):case.write_reader.require_unchanged(result)
