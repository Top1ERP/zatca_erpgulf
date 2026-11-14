"""Strict account-scoped native observations; no fiscal-role inference or I/O."""

import ast
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import textwrap

import pytest

from zatca_erpgulf.ksa_compliance.account_tax_rates import (
    AccountTaxRateError, index_item_account_rates,
)
from zatca_erpgulf.ksa_compliance.tax_details import get_item_tax_rate
from zatca_erpgulf.zatca_erpgulf.tests.test_baseline_tax_compatibility import input_snapshot
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16
from zatca_erpgulf.zatca_erpgulf.tests.test_distributed_invoice_discount import SOURCES, SOURCE_HASHES
from zatca_erpgulf.zatca_erpgulf.tests.test_field_rounding import framework
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document


def model(major):
    rows = [Document(name="TAX-15", account_head="ACCOUNT-15", rate=0),
            Document(name="TAX-5", account_head="ACCOUNT-5", rate=0)]
    items = [Document(name="ITEM-ROW-1", item_code="DUPLICATE", idx=1,
                      item_tax_rate='{"ACCOUNT-15":15}'),
             Document(name="ITEM-ROW-2", item_code="DUPLICATE", idx=2,
                      item_tax_rate='{"ACCOUNT-5":5}')]
    doc = Document(items=items, taxes=rows)
    if major == 16:
        doc.item_wise_tax_details = [Document(item_row=item.name, tax_row=row.name,
            rate=15 if i == j == 0 else 5 if i == j == 1 else 0, amount="UNUSED")
            for i, item in enumerate(items) for j, row in enumerate(rows)]
    return doc


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("order", [False, True])
def test_exact_account_pairs_preserve_zero_and_ignore_codes_and_amounts(major, order):
    doc = model(major)
    if order:
        doc.taxes.reverse()
        if major == 16:
            doc.item_wise_tax_details.reverse()
    before = input_snapshot(doc)
    observed = index_item_account_rates(doc)
    assert observed.rate(doc.items[0], "ACCOUNT-15") == Decimal("15")
    assert observed.rate(doc.items[0], "ACCOUNT-5") == 0
    assert observed.rate(doc.items[1], "ACCOUNT-15") == 0
    assert observed.rate(doc.items[1], "ACCOUNT-5") == Decimal("5")
    assert input_snapshot(doc) == before
    with pytest.raises(TypeError):
        observed._rates[doc.items[0].name]["ACCOUNT-5"] = 10


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("item_override", [0, 5, 15])
@pytest.mark.parametrize("invoice_rate", [0, 5, 15])
def test_numeric_account_map_selection_agrees_with_pinned_native_controller(
    monkeypatch, upstream16, major, item_override, invoice_rate,
):
    probe = framework(major, upstream16, monkeypatch, setting="Commercial Rounding")
    content = SOURCES[major].read_bytes()
    assert hashlib.sha256(content).hexdigest() == json.loads(SOURCE_HASHES.read_text())[str(major)]["file_sha256"]
    cls = next(node for node in ast.parse(content).body if isinstance(node, ast.ClassDef)
               and node.name == "calculate_taxes_and_totals")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "_get_tax_rate")
    namespace = dict(flt=probe.flt, NOT_APPLICABLE_TAX=object())
    exec(compile(textwrap.dedent(ast.get_source_segment(content.decode(), method)),
                 "pinned-numeric-account-selection", "exec"), namespace)
    doc = model(15)
    doc.taxes[0].rate = invoice_rate
    doc.items[0].item_tax_rate = json.dumps({"ACCOUNT-15": item_override})
    calculation = Document(doc=Document(precision=lambda *args: 2))
    native = namespace["_get_tax_rate"]
    for row in doc.taxes:
        expected = native(calculation, row, {"ACCOUNT-15": item_override})
        assert index_item_account_rates(doc).rate(doc.items[0], row.account_head) == Decimal(str(expected))


@pytest.mark.parametrize("fault,code", [
    ("empty-v16", "account_rate_v16_empty"),
    ("partial-v16", "account_rate_missing_pair"),
    ("unknown-item", "account_rate_dangling_reference"),
    ("code-alias", "account_rate_dangling_reference"),
    ("index-alias", "account_rate_identity"),
    ("account-alias", "account_rate_dangling_reference"),
    ("unknown-tax", "account_rate_dangling_reference"),
    ("duplicate-pair", "account_rate_duplicate_pair"),
    ("missing-rate", "account_rate_value"),
    ("nan-rate", "account_rate_value"),
    ("inf-rate", "account_rate_value"),
    ("negative-rate", "account_rate_value"),
    ("bool-rate", "account_rate_value"),
    ("not-applicable", "account_rate_value"),
    ("bad-shape", "account_rate_shape"),
])
def test_v16_bad_or_partial_identity_never_falls_back_to_v15_maps(fault, code):
    doc = model(16)
    if fault == "empty-v16": doc.item_wise_tax_details = []
    elif fault == "partial-v16": doc.item_wise_tax_details.pop()
    elif fault == "unknown-item": doc.item_wise_tax_details[0].item_row = "FOREIGN-ROW"
    elif fault == "code-alias": doc.item_wise_tax_details[0].item_row = "DUPLICATE"
    elif fault == "index-alias": doc.item_wise_tax_details[0].item_row = 1
    elif fault == "account-alias": doc.item_wise_tax_details[0].tax_row = "ACCOUNT-15"
    elif fault == "unknown-tax": doc.item_wise_tax_details[0].tax_row = "FOREIGN-TAX"
    elif fault == "duplicate-pair": doc.item_wise_tax_details.append(doc.item_wise_tax_details[0])
    elif fault == "bad-shape": doc.item_wise_tax_details[0] = None
    else:
        doc.item_wise_tax_details[0].rate = {"missing-rate": None, "nan-rate": "NaN",
            "inf-rate": "Infinity", "negative-rate": -1, "bool-rate": True,
            "not-applicable": "NA"}[fault]
    before = input_snapshot(doc)
    with pytest.raises(AccountTaxRateError, match="^" + code + "$"):
        index_item_account_rates(doc)
    assert input_snapshot(doc) == before


@pytest.mark.parametrize("raw,code", [
    ('{"ACCOUNT-15":15,"ACCOUNT-15":0}', "account_rate_duplicate_key"),
    ("[]", "account_rate_item_map"), ("not-json", "account_rate_item_map"),
    (True, "account_rate_item_map"), ('{"ACCOUNT-15":null}', "account_rate_value"),
    ('{"ACCOUNT-15":true}', "account_rate_value"), ('{"ACCOUNT-15":"NaN"}', "account_rate_value"),
])
def test_v15_malformed_selected_sources_are_not_coerced_to_zero(raw, code):
    doc = model(15)
    doc.items[0].item_tax_rate = raw
    with pytest.raises(AccountTaxRateError, match="^" + code + "$"):
        index_item_account_rates(doc)


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("fault", ["duplicate-item", "duplicate-tax-name", "duplicate-account", "missing-item-name", "missing-tax-name"])
def test_scope_identities_are_unambiguous(major, fault):
    doc = model(major)
    if fault == "duplicate-item": doc.items[1].name = doc.items[0].name
    elif fault == "duplicate-tax-name": doc.taxes[1].name = doc.taxes[0].name
    elif fault == "duplicate-account": doc.taxes[1].account_head = doc.taxes[0].account_head
    elif fault == "missing-item-name": doc.items[0].name = None
    elif fault == "missing-tax-name": doc.taxes[0].name = None
    with pytest.raises(AccountTaxRateError):
        index_item_account_rates(doc)


def test_legacy_public_rate_api_keeps_its_existing_unscoped_result():
    doc = model(16)
    doc.item_wise_tax_details[1].rate = 100
    doc.item_wise_tax_details[0].amount = doc.item_wise_tax_details[1].amount = 0
    assert get_item_tax_rate(doc, doc.items[0]) == 115
    observed = index_item_account_rates(doc)
    assert observed.rate(doc.items[0], "ACCOUNT-15") == 15
    assert observed.rate(doc.items[0], "ACCOUNT-5") == 100


def test_v16_detail_rows_are_indexed_once_without_reading_amounts():
    reads = []
    class Observed(dict):
        def get(self, key, default=None):
            reads.append(key)
            assert key != "amount", "Account selection must not calculate or interpret money"
            return super().get(key, default)
    doc = model(16)
    doc.items = [Document(name="ROW-" + str(i), item_tax_rate="STALE INVALID JSON") for i in range(100)]
    doc.item_wise_tax_details = [Observed(item_row=item.name, tax_row=tax.name, rate=15 if j == 0 else 0)
        for item in doc.items for j, tax in enumerate(doc.taxes)]
    observed = index_item_account_rates(doc)
    assert len(reads) == 100 * 2 * 3
    for item in doc.items:
        assert observed.rate(item, "ACCOUNT-15") == 15
        assert observed.rate(item, "ACCOUNT-5") == 0
    assert len(reads) == 600, "Pair lookups must not rescan the native detail table"


@pytest.mark.parametrize("major", [15, 16])
def test_new_preparations_observe_changes_without_cross_request_cache(major):
    doc = model(major)
    before = index_item_account_rates(doc)
    if major == 15:
        doc.items[0].item_tax_rate = '{"ACCOUNT-15":5}'
    else:
        doc.item_wise_tax_details[0].rate = 5
    after = index_item_account_rates(doc)
    assert before.rate(doc.items[0], "ACCOUNT-15") == 15
    assert after.rate(doc.items[0], "ACCOUNT-15") == 5
