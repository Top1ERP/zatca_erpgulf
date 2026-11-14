"""Explicit VAT selection is opt-in, deterministic and independent of row order."""

import copy
from decimal import Decimal
import json
from pathlib import Path

import pytest

from zatca_erpgulf.ksa_compliance.item_vat_selection import (
    FIELD, VatSelectionError, select_declared_vat,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_baseline_tax_compatibility import input_snapshot


def template(rate=15, position=0):
    vat = Document(tax_type="VAT-ACCOUNT", tax_rate=rate)
    rows = [Document(tax_type="ZERO-A", tax_rate=0), Document(tax_type="ZERO-B", tax_rate="0")]
    rows.insert(position, vat)
    return Document(doctype="Item Tax Template", company="COMPANY", taxes=rows,
                    **{FIELD: "VAT-ACCOUNT"})


@pytest.mark.parametrize("position", [0, 1, 2])
@pytest.mark.parametrize("rate", [0, "0", Decimal("0.00"), 5, 15, Decimal("15.00")])
@pytest.mark.parametrize("as_dict", [False, True])
def test_selection_preserves_selected_zero_and_never_rewrites_rows(position, rate, as_dict):
    doc = template(rate, position)
    if as_dict:
        doc = dict(vars(doc), taxes=[vars(row).copy() for row in doc.taxes])
    before = input_snapshot(doc)
    selected = select_declared_vat(doc, company="COMPANY")
    assert selected.account == "VAT-ACCOUNT" and selected.rate == Decimal(str(rate))
    assert selected.excluded_accounts == ("ZERO-A", "ZERO-B")
    assert selected.row is (doc["taxes"] if as_dict else doc.taxes)[position]
    assert input_snapshot(doc) == before


@pytest.mark.parametrize("value", [None, "", "absent"])
def test_legacy_absence_does_not_touch_tax_rows_or_invent_an_account(value):
    class Legacy:
        @property
        def taxes(self): raise AssertionError("Legacy rows must remain owned by their caller")
    doc = Legacy()
    if value != "absent": setattr(doc, FIELD, value)
    assert select_declared_vat(doc) is None


@pytest.mark.parametrize("fault,code", [
    ("foreign-company", "declared_vat_company_mismatch"),
    ("missing-account", "declared_vat_account_not_in_template"),
    ("duplicate", "declared_vat_duplicate_or_missing_account"),
    ("blank-row-account", "declared_vat_duplicate_or_missing_account"),
    ("positive-other", "declared_vat_nonzero_other_row"),
    ("negative-other", "declared_vat_invalid_rate"),
    ("missing-rate", "declared_vat_invalid_rate"),
    ("nan-rate", "declared_vat_invalid_rate"),
    ("inf-rate", "declared_vat_invalid_rate"),
    ("boolean-rate", "declared_vat_invalid_rate"),
    ("whitespace", "declared_vat_invalid_account"),
    ("non-text", "declared_vat_invalid_account"),
])
def test_ambiguous_or_nonzero_other_taxes_are_rejected(fault, code):
    doc = template()
    if fault == "foreign-company": doc.company = "OTHER"
    elif fault == "missing-account":
        setattr(doc, FIELD, "NOT-IN-ROWS")
        doc.taxes[0].tax_rate = 0
    elif fault == "duplicate": doc.taxes.append(copy.deepcopy(doc.taxes[0]))
    elif fault == "blank-row-account": doc.taxes[1].tax_type = ""
    elif fault == "positive-other": doc.taxes[1].tax_rate = 5
    elif fault == "negative-other": doc.taxes[1].tax_rate = -1
    elif fault == "missing-rate": doc.taxes[1].tax_rate = None
    elif fault == "nan-rate": doc.taxes[0].tax_rate = "NaN"
    elif fault == "inf-rate": doc.taxes[0].tax_rate = "Infinity"
    elif fault == "boolean-rate": doc.taxes[0].tax_rate = True
    elif fault == "whitespace": setattr(doc, FIELD, " ")
    elif fault == "non-text": setattr(doc, FIELD, ["VAT-ACCOUNT"])
    before = input_snapshot(doc)
    with pytest.raises(VatSelectionError, match="^" + code + "$"):
        select_declared_vat(doc, company="COMPANY")
    assert input_snapshot(doc) == before


def test_new_fixture_is_optional_link_and_does_not_mutate_legacy_fields():
    rows = json.loads((Path(__file__).parents[2] / "fixtures/custom_field.json").read_text())
    matches = [row for row in rows if row.get("dt") == "Item Tax Template" and row.get("fieldname") == FIELD]
    assert len(matches) == 1
    row = matches[0]
    assert row["fieldtype"] == "Link" and row["options"] == "Account"
    assert row["reqd"] == row["translatable"] == row["allow_on_submit"] == 0
    assert row["fetch_from"] is None and row["default"] is None
