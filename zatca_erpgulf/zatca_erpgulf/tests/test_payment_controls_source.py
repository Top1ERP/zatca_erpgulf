"""Native payment controls preserve raw values and existing financial payloads."""
from decimal import Decimal
import itertools
import pickle
import pytest
from pymysql.constants import FIELD_TYPE as FT

from zatca_erpgulf.zatca_erpgulf.payment_controls_source import LockedPaymentControlsRead, MariaDBPaymentControlsReader
from zatca_erpgulf.zatca_erpgulf.financial_source_sql import MariaDBInvoiceFinancialReader
from zatca_erpgulf.zatca_erpgulf.invoice_rounding_source import InvoiceRoundingSourceError
from zatca_erpgulf.zatca_erpgulf.source_metadata import PAYMENT_CONTROLS_PROFILE
from zatca_erpgulf.zatca_erpgulf.tests.test_invoice_rounding_source import scenario as previous
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta, project
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata


def scenario(monkeypatch, flags=(1,0,1)):
    case=previous(monkeypatch)
    raw=AppliedMeta(case.doctype,LockedPaymentControlsRead.FIELDS)
    for name in raw.definitions:
        raw.definitions[name].values["fieldtype"]="Check" if name in LockedPaymentControlsRead.CHECKS else "Currency"
        case.connection.signatures["header",name]=[FT.LONG,20,0,True] if name in LockedPaymentControlsRead.CHECKS else [FT.NEWDECIMAL,23,9,True]
    for name in LockedPaymentControlsRead.OVERLAP:
        case.raw_metas[case.doctype].definitions[name]=raw.definitions[name]
    case.metas[case.doctype]=project(case.raw_metas[case.doctype])
    case.observations[case.doctype]=observed_metadata(case.raw_metas[case.doctype])
    case.own_payment=observed_metadata(raw,profile=PAYMENT_CONTROLS_PROFILE)
    old=case.metadata_reader.load_for_update.side_effect
    case.metadata_reader.load_for_update.side_effect=lambda meta:case.own_payment if meta.profile==PAYMENT_CONTROLS_PROFILE else old(meta)
    case.records["header"][0].update(dict(zip(LockedPaymentControlsRead.CHECKS,flags)),loyalty_amount=Decimal("1.234500000"))
    case.connection.columns=set(LockedPaymentControlsRead.FIELDS)
    case.financial=MariaDBInvoiceFinancialReader(case.connection).load_for_update(case.doctype,case.name,erp_major=case.major,applied_metadata=case.metas)
    case.payment_reader=MariaDBPaymentControlsReader(case.connection)
    return case


@pytest.mark.parametrize("flags",tuple(itertools.product((None,0,1),repeat=3)))
def test_native_flags_and_loyalty_are_separate_from_normalized_checks(monkeypatch,flags):
    case=scenario(monkeypatch,flags)
    before=case.financial._payload,case.financial.sha256,case.financial.financial._payload
    result=case.payment_reader.load_for_update(case.financial,applied_metadata=case.own_payment.applied)
    assert result.normalized_checks==tuple((name,flag or 0) for name,flag in zip(result.CHECKS,flags))
    result.require_saved_check_match(dict(zip(result.CHECKS,flags)))
    case.payment_reader.require_unchanged(result)
    assert (result.financial._payload,result.financial.sha256,result.financial.financial._payload)==before
    assert "1.2345" not in repr(result)
    with pytest.raises(TypeError):pickle.dumps(result)


@pytest.mark.parametrize("name",LockedPaymentControlsRead.FIELDS)
def test_native_control_drift_without_revision_change_is_refused(monkeypatch,name):
    case=scenario(monkeypatch)
    result=case.payment_reader.load_for_update(case.financial,applied_metadata=case.own_payment.applied)
    case.records["header"][0][name]=Decimal("2.000000000") if name=="loyalty_amount" else 0 if name in ("is_pos","redeem_loyalty_points") else 1
    with pytest.raises(InvoiceRoundingSourceError):case.payment_reader.require_unchanged(result)
