"""Account classification parity, fallback isolation and native-tax boundaries."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from zatca_erpgulf.ksa_compliance.tax_account_policy import is_reconciliation_tax_account
from zatca_erpgulf.ksa_compliance.tax_details import get_item_tax_detail, get_item_tax_rate
from zatca_erpgulf.zatca_erpgulf import tax_error as checks
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document

REFERENCE = Path(__file__).parent / "fixtures" / "tax_account_7906adf.py"
REFERENCE_SHA256 = "54b29b55c42c1a039e1a2fc3b45a8cfc305a1cc881c2c8420e3e673c0a414785"
METADATA = [
    ({"account_type": "Tax", "root_type": "Expense"}, True),
    ({"account_type": " tAx ", "root_type": "Asset"}, True),
    ({"account_type": "Expense", "root_type": "Liability"}, False),
    ({"account_type": "Receivable", "root_type": "Asset"}, False),
    ({"account_type": "", "root_type": " Liability "}, True),
    ({"account_type": None, "root_type": "liability"}, True),
    ({"account_type": "", "root_type": "Asset"}, False),
    ({"account_type": None, "root_type": None}, False),
    ({"root_type": "Liability"}, True),
    ({"account_type": "Tax"}, True),
]
UNKNOWN = [None, {}, False, "", RuntimeError("synthetic unreadable account")]


def parent_classifier():
    content = REFERENCE.read_bytes()
    assert hashlib.sha256(content).hexdigest() == REFERENCE_SHA256
    namespace = dict(vars(checks))
    exec(compile(content, str(REFERENCE), "exec"), namespace)
    return namespace["_is_tax_account"]


def install_reader(monkeypatch, metadata):
    reader = Mock(side_effect=metadata) if isinstance(metadata, Exception) else Mock(return_value=metadata)
    monkeypatch.setattr(checks, "frappe", SimpleNamespace(db=SimpleNamespace(get_value=reader)))
    return reader


def account_call(name="ACCOUNT"):
    return call("Account", name, ["account_type", "root_type"], as_dict=True)


@pytest.mark.parametrize("metadata,expected", METADATA)
@pytest.mark.parametrize("default", [True, False, None, "caller-fallback"])
@pytest.mark.parametrize("cached", [False, True])
def test_known_metadata_matches_frozen_parent_and_reuses_lookup(monkeypatch, metadata, expected, default, cached):
    reader = install_reader(monkeypatch, metadata)
    old_cache, new_cache = ({}, {}) if cached else (None, None)
    old = parent_classifier()
    for _ in range(2):
        assert old(" ACCOUNT ", old_cache, default) is expected
        assert checks._is_tax_account(" ACCOUNT ", new_cache, default) is expected
    assert old_cache == new_cache == ({"ACCOUNT": expected} if cached else None)
    assert reader.call_args_list == [account_call()] * (2 if cached else 4)


@pytest.mark.parametrize("metadata", UNKNOWN)
@pytest.mark.parametrize("default", [True, False, None, "caller-fallback"])
def test_unknown_fresh_call_retains_parent_return_and_query(monkeypatch, metadata, default):
    reader = install_reader(monkeypatch, metadata)
    assert parent_classifier()("ACCOUNT", default=default) is default
    assert checks._is_tax_account("ACCOUNT", default=default) is default
    assert reader.call_args_list == [account_call(), account_call()]


@pytest.mark.parametrize("metadata", UNKNOWN)
@pytest.mark.parametrize("defaults", [(True, False), (False, True), (None, True), (True, None), ([], {}), ({}, [])])
def test_unknown_cache_keeps_observation_not_first_call_fallback(monkeypatch, metadata, defaults):
    reader = install_reader(monkeypatch, metadata)
    first, second = defaults
    old_cache, new_cache = {}, {}
    old = parent_classifier()
    assert old("ACCOUNT", old_cache, first) is first
    assert old("ACCOUNT", old_cache, second) is first  # Frozen-parent defect.
    assert checks._is_tax_account("ACCOUNT", new_cache, first) is first
    assert checks._is_tax_account("ACCOUNT", new_cache, second) is second
    assert reader.call_args_list == [account_call(), account_call()]
    assert set(new_cache) == {"ACCOUNT"}


@pytest.mark.parametrize("cached_value", [True, False, None, "", "prepopulated"])
def test_prepopulated_legacy_cache_values_remain_authoritative(monkeypatch, cached_value):
    reader = install_reader(monkeypatch, RuntimeError("must not read"))
    cache = {"ACCOUNT": cached_value}
    assert parent_classifier()(" ACCOUNT ", cache, True) is cached_value
    assert checks._is_tax_account(" ACCOUNT ", cache, False) is cached_value
    reader.assert_not_called()


@pytest.mark.parametrize("name", [None, "", " ", "\t\n"])
def test_empty_account_never_reads_or_caches(monkeypatch, name):
    reader = install_reader(monkeypatch, RuntimeError("must not read"))
    cache = {}
    assert parent_classifier()(name, cache) is False
    assert checks._is_tax_account(name, cache) is False
    assert cache == {}
    reader.assert_not_called()


@pytest.mark.parametrize("metadata", [True, 1, ["malformed"], "malformed"])
def test_truthy_malformed_metadata_retains_access_failure(monkeypatch, metadata):
    reader = install_reader(monkeypatch, metadata)
    for classifier in (parent_classifier(), checks._is_tax_account):
        cache = {}
        with pytest.raises(AttributeError):
            classifier("ACCOUNT", cache)
        assert cache == {}
    assert reader.call_args_list == [account_call(), account_call()]


def test_shared_policy_is_pure_and_cache_is_request_owned():
    reader = Mock(return_value=None)
    first, second = {}, {}
    assert is_reconciliation_tax_account(" ACCOUNT ", read_account=reader, cache=first) is True
    assert is_reconciliation_tax_account("ACCOUNT", read_account=reader, cache=first, default=False) is False
    assert is_reconciliation_tax_account("ACCOUNT", read_account=reader, cache=second, default=None) is None
    assert reader.call_args_list == [call("ACCOUNT"), call("ACCOUNT")]


@pytest.mark.parametrize("metadata,expected", METADATA)
@pytest.mark.parametrize("field", ["base_tax_amount_after_discount_amount", "base_tax_amount",
                                   "tax_amount_after_discount_amount", "tax_amount"])
def test_actual_preflight_uses_shared_policy_and_local_cache(monkeypatch, metadata, expected, field):
    reader = install_reader(monkeypatch, metadata)
    policy = Mock(wraps=is_reconciliation_tax_account)
    monkeypatch.setattr(checks, "is_reconciliation_tax_account", policy)
    doc = Document(taxes=[Document(account_head="ACCOUNT", **{field: 0}),
                          Document(account_head="ACCOUNT", **{field: 2})],
                   total_taxes_and_charges=999, save=Mock(), db_set=Mock())
    assert checks._invoice_has_tax_amount(doc) is expected
    reader.assert_called_once_with("Account", "ACCOUNT", ["account_type", "root_type"], as_dict=True)
    assert policy.call_count == 2
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()


@pytest.mark.parametrize("metadata", UNKNOWN)
def test_actual_preflight_retains_unknown_account_conservative_fallback(monkeypatch, metadata):
    reader = install_reader(monkeypatch, metadata)
    doc = Document(taxes=[Document(account_head="ACCOUNT", tax_amount=0),
                          Document(account_head="ACCOUNT", tax_amount=2)])
    assert checks._invoice_has_tax_amount(doc) is True
    assert reader.call_args_list == [account_call()]


@pytest.mark.parametrize("other_type,other_root,other_rate,other_amount,eligible", [
    ("Expense", "Expense", 100, 100, False),
    ("Tax", "Liability", 3, -3, True),
    ("", "Liability", 3, -3, True),
])
def test_v16_all_matched_rates_still_include_other_charge_rows(
    monkeypatch, other_type, other_root, other_rate, other_amount, eligible,
):
    # Characterization, not the desired VAT-only selection or fiscal approval.
    metadata = {"VAT": {"account_type": "Tax", "root_type": "Liability"},
                "OTHER": {"account_type": other_type, "root_type": other_root}}
    reader = Mock(side_effect=lambda doctype, name, fields, **kwargs: metadata[name])
    monkeypatch.setattr(checks, "frappe", SimpleNamespace(db=SimpleNamespace(get_value=reader)))
    item = Document(name="ITEM-ROW", item_code="ITEM", net_amount=100, base_net_amount=100)
    doc = Document(currency="SAR", taxes=[
        Document(name="VAT-ROW", account_head="VAT", rate=15),
        Document(name="OTHER-ROW", account_head="OTHER", rate=other_rate)],
        item_wise_tax_details=[
            Document(item_row="ITEM-ROW", tax_row="VAT-ROW", rate=15, amount=15),
            Document(item_row="ITEM-ROW", tax_row="OTHER-ROW", rate=other_rate, amount=other_amount),
            Document(item_row="UNRELATED-ITEM", tax_row="OTHER-ROW", rate=80, amount=80)])
    assert checks._is_tax_account("OTHER") is eligible
    reader.reset_mock()
    assert get_item_tax_rate(doc, item) == 15 + other_rate
    assert get_item_tax_detail(doc, item) == (15 + other_rate, 15 + other_rate)
    reader.assert_not_called()  # Native adapter has no account ownership reader.


@pytest.mark.parametrize("vat_first", [False, True])
@pytest.mark.parametrize("item_override", [False, True])
def test_v15_first_rate_and_explicit_item_override_remain_characterized(vat_first, item_override):
    item = Document(name="ITEM-ROW", item_code="ITEM", net_amount=100, base_net_amount=100,
                    item_tax_rate=json.dumps({"VAT": 15}) if item_override else None)
    vat = Document(account_head="VAT", rate=15, item_wise_tax_detail=json.dumps({"ITEM": [15, 15]}))
    other = Document(account_head="FREIGHT", rate=7, item_wise_tax_detail=json.dumps({"ITEM": [7, 7]}))
    doc = Document(currency="SAR", taxes=[vat, other] if vat_first else [other, vat])
    expected = 15 if vat_first or item_override else 7
    assert get_item_tax_rate(doc, item) == expected
    assert get_item_tax_detail(doc, item) == (expected, expected)
