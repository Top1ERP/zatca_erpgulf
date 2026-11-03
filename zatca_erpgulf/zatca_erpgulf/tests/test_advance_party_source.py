"""Optional advance party columns and unchanged old child profiles."""
from dataclasses import replace
import pytest

from zatca_erpgulf.zatca_erpgulf import advance_party_source as party
from zatca_erpgulf.zatca_erpgulf.child_currency_source import ChildCurrencySourceError
from zatca_erpgulf.zatca_erpgulf.source_metadata import ADVANCE_PARTY_PROFILE
from zatca_erpgulf.zatca_erpgulf.tests.test_child_currency_source import scenario as previous
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata


def scenario(monkeypatch, present):
    case = previous(monkeypatch, parentfield="advances", present=())
    raw = AppliedMeta("Sales Invoice Advance", ("party_account_currency",) if present else ())
    if present: raw.definitions["party_account_currency"].values.update(fieldtype="Link", options="Currency")
    own = observed_metadata(raw, profile=ADVANCE_PARTY_PROFILE)
    case.connection.columns = {"party_account_currency"} if present else set()
    case.records["advances"][0]["party_account_currency"] = "USD" if present else None
    old = case.metadata_reader.load_for_update.side_effect
    case.metadata_reader.load_for_update.side_effect = lambda meta: own if meta.profile == ADVANCE_PARTY_PROFILE else old(meta)
    case.party_metadata = own
    case.party_reader = party.MariaDBAdvancePartyReader(case.connection)
    return case


@pytest.mark.parametrize("present", [False, True])
def test_optional_native_column_retains_absence_and_old_financial_bytes(monkeypatch, present):
    case = scenario(monkeypatch, present)
    original = case.financial._payload, case.financial.financial._payload, case.financial.sha256
    result = case.party_reader.load_for_update(case.financial, "advances", applied_metadata=case.party_metadata.applied)
    assert result.financial == case.financial
    assert (result.financial._payload, result.financial.financial._payload, result.financial.sha256) == original
    assert result.metadata.applied.has_field("party_account_currency") is present
    assert "USD" not in repr(result)
    case.party_reader.require_unchanged(result)
    with pytest.raises(ValueError): replace(result, parentfield="items")


def test_physical_column_without_applied_metadata_is_not_silently_absent(monkeypatch):
    case = scenario(monkeypatch, False)
    case.connection.columns.add("party_account_currency")
    with pytest.raises(ChildCurrencySourceError):
        case.party_reader.load_for_update(case.financial, "advances", applied_metadata=case.party_metadata.applied)


def test_native_change_without_modified_is_refused_and_poisoned(monkeypatch):
    case = scenario(monkeypatch, True)
    result = case.party_reader.load_for_update(case.financial, "advances", applied_metadata=case.party_metadata.applied)
    case.records["advances"][0]["party_account_currency"] = "SAR"
    with pytest.raises(ChildCurrencySourceError): case.party_reader.require_unchanged(result)
    with pytest.raises(ChildCurrencySourceError): case.party_reader.require_unchanged(result)
