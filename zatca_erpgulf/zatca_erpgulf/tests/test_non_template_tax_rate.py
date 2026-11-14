"""Shared ordinary/nominal rate mechanics against complete frozen wrappers."""

from decimal import Decimal
import hashlib
from pathlib import Path
from unittest.mock import Mock

import pytest

from zatca_erpgulf.ksa_compliance import tax_details as native
from zatca_erpgulf.zatca_erpgulf import create_xml_final_part as sales, xml_tax_data as totals
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document

REFERENCE = Path(__file__).parent / "fixtures" / "non_template_rates_8861c2a.py"
REFERENCE_SHA256 = "c0badb61b7a95269084c179f4f5ae95400dff208d934ae6a8512ec5b9a55752e"
ROUTES = [
    (totals, "_get_item_tax_rate_without_template", "q2"),
    (sales, "_nominal_tax_rate_without_template", "_nominal_q2"),
]
SELECTED = [0, "0", Decimal("0.00"), 15, Decimal("1.005"), None, "", False,
            "malformed", float("nan"), float("inf"), ValueError("synthetic reader failure")]


class Observed(Document):
    def get(self, name, default=None):
        state = object.__getattribute__(self, "__dict__")
        state["trace"].append((state["role"], "get", name, default))
        if state.get("get_fault"):
            raise ValueError("synthetic " + state["role"] + " get failure")
        return getattr(self, name, default)

    def __getattribute__(self, name):
        if name in ("taxes", "rate"):
            state = object.__getattribute__(self, "__dict__")
            state["trace"].append((state["role"], "attribute", name))
        return super().__getattribute__(name)


def parent_wrapper(module, name):
    content = REFERENCE.read_bytes()
    assert hashlib.sha256(content).hexdigest() == REFERENCE_SHA256
    namespace = dict(vars(module))
    exec(compile(content, str(REFERENCE), "exec"), namespace)
    return namespace[name]


def outcome(operation, doc, item):
    try:
        result = operation(doc, item)
    except Exception as error:
        return "error", type(error), str(error)
    return "value", type(result), str(result)


def compare_wrappers(monkeypatch, route, *, selected=0, fallback=15, empty=False,
                     doc_fault=False, row_fault=False, quantize_fault=False):
    module, name, quantizer_name = route
    trace = []
    row = Observed(role="tax", trace=trace, get_fault=row_fault)
    if fallback != "missing":
        row.rate = fallback
    doc = Observed(role="invoice", trace=trace, taxes=[] if empty else [row],
                   get_fault=doc_fault, save=Mock(), db_set=Mock())
    item = Document(name="ROW", item_code="ITEM")
    original_quantizer = getattr(module, quantizer_name)
    def round_rate(value):
        trace.append(("round", type(value), str(value)))
        if quantize_fault:
            raise ArithmeticError("synthetic rounding failure")
        return original_quantizer(value)
    def read_rate(*args, **kwargs):
        trace.append(("native", kwargs))
        assert args == (doc, item) and kwargs == {"default": None}
        if isinstance(selected, Exception):
            raise selected
        return selected
    reader, quantizer = Mock(side_effect=read_rate), Mock(side_effect=round_rate)
    monkeypatch.setattr(module, "get_item_tax_rate", reader)
    monkeypatch.setattr(module, quantizer_name, quantizer)
    observations = []
    for operation in (parent_wrapper(module, name), getattr(module, name)):
        trace.clear()
        reader.reset_mock()
        quantizer.reset_mock()
        result = outcome(operation, doc, item)
        observations.append((result, trace[:], reader.call_count, quantizer.call_count))
    assert observations[0] == observations[1]
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()
    return observations[-1]


@pytest.mark.parametrize("route", ROUTES, ids=["ordinary", "nominal"])
@pytest.mark.parametrize("selected", SELECTED)
@pytest.mark.parametrize("fallback", [15, 0, None, "missing"])
def test_selected_presence_rounding_and_first_row_fallback_match_parent(monkeypatch, route, selected, fallback):
    compare_wrappers(monkeypatch, route, selected=selected, fallback=fallback)


@pytest.mark.parametrize("route", ROUTES, ids=["ordinary", "nominal"])
@pytest.mark.parametrize("case", ["empty", "document-get", "row-get", "native-then-row-get",
                                  "selected-rounding", "fallback-rounding", "empty-rounding"])
def test_exception_boundaries_and_empty_rounding_remain_distinct(monkeypatch, route, case):
    options = {
        "empty": {"empty": True},
        "document-get": {"doc_fault": True},
        "row-get": {"row_fault": True, "selected": None},
        "native-then-row-get": {"row_fault": True, "selected": ValueError("synthetic native")},
        "selected-rounding": {"quantize_fault": True},
        "fallback-rounding": {"quantize_fault": True, "selected": None},
        "empty-rounding": {"quantize_fault": True, "empty": True},
    }[case]
    result, trace, reads, rounds = compare_wrappers(monkeypatch, route, **options)
    if case in ("empty", "empty-rounding"):
        assert reads == 0
        assert rounds == (0 if route[0] is totals else 1)
        if case == "empty-rounding" and route[0] is sales:
            assert result[0] == "error"
        else:
            assert result == ("value", Decimal, "0.00")


NATIVE_CASES = ["v15-item-zero", "v15-invoice-zero", "v15-missing", "v15-other-first",
                "v16-zero", "v16-unmatched", "v16-empty", "v16-other-rate"]


@pytest.mark.parametrize("route", ROUTES, ids=["ordinary", "nominal"])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("case", NATIVE_CASES)
def test_actual_native_reader_preserves_zero_identity_and_other_charge_limits(monkeypatch, route, currency, case):
    module, name, _ = route
    item = Document(name="ROW", item_code="ITEM", net_amount=100, base_net_amount=375)
    taxes = [Document(name="VAT-ROW", account_head="VAT", rate=15)]
    doc = Document(currency=currency, taxes=taxes, save=Mock(), db_set=Mock())
    expected = 15
    if case == "v15-item-zero":
        item.item_tax_rate = '{"VAT":0}'
        expected = 0
    elif case == "v15-invoice-zero":
        taxes[0].rate = 0
        expected = 0
    elif case == "v15-missing":
        del taxes[0].rate
        expected = 0  # Native missing falls back to first-row default zero.
    elif case == "v15-other-first":
        taxes.insert(0, Document(name="OTHER-ROW", account_head="FREIGHT", rate=7))
        expected = 7
    else:
        doc.item_wise_tax_details = []
        if case != "v16-empty":
            doc.item_wise_tax_details = [Document(item_row="OTHER" if case == "v16-unmatched" else "ROW",
                tax_row="VAT-ROW", rate=0, amount=0)]
            expected = 0
        if case == "v16-other-rate":
            doc.item_wise_tax_details[0].rate = 15
            doc.item_wise_tax_details.append(Document(item_row="ROW", tax_row="OTHER-ROW", rate=3, amount=-3))
            expected = 18
    reader = Mock(wraps=native.get_item_tax_rate)
    monkeypatch.setattr(module, "get_item_tax_rate", reader)
    old = outcome(parent_wrapper(module, name), doc, item)
    new = outcome(getattr(module, name), doc, item)
    assert old == new == ("value", Decimal, f"{expected:.2f}")
    assert reader.call_count == 2
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()


@pytest.mark.parametrize("route", ROUTES, ids=["ordinary", "nominal"])
def test_existing_wrapper_aliases_delegate_to_shared_policy(monkeypatch, route):
    module, name, quantizer = route
    sentinel = object()
    resolver = Mock(return_value=(True, sentinel))
    reader, rounding = Mock(), Mock()
    monkeypatch.setattr(module, "resolve_non_template_tax_rate", resolver)
    monkeypatch.setattr(module, "get_item_tax_rate", reader)
    monkeypatch.setattr(module, quantizer, rounding)
    doc, item = Document(), Document()
    assert getattr(module, name)(doc, item) is sentinel
    resolver.assert_called_once_with(doc, item, read_rate=reader, quantize=rounding)
    reader.assert_not_called()
    rounding.assert_not_called()
