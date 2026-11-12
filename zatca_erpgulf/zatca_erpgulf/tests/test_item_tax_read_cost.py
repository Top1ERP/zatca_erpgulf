"""Parent reader parity and deliberate unused-JSON retirement, without site I/O."""

from decimal import Decimal
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock, call
import xml.etree.ElementTree as ET

import pytest

from zatca_erpgulf.zatca_erpgulf import create_xml_final_part as core
from zatca_erpgulf.zatca_erpgulf.tests.test_sales_item_builder_parity import source as sales_source
from zatca_erpgulf.zatca_erpgulf.tests.test_advance_item_builder_parity import (
    advance_source, prepare, run_builder,
)


REFERENCE = Path(__file__).parent / "fixtures" / "item_tax_reads_11a429d.py"
REFERENCE_SHA256 = "219ab1bba51abb5dc36535e1cb2bafb6a6378d33e3015dfd8c9d7626f7aeac4f"


def parent_builders():
    content = REFERENCE.read_bytes()
    assert hashlib.sha256(content).hexdigest() == REFERENCE_SHA256
    namespace = dict(vars(core))
    # Unlike the older remaining-read oracles, this exact parent executes the
    # real public JSON helper and both real adapter calls for each plain item.
    exec(compile(content, str(REFERENCE), "exec"), namespace)
    return namespace


def builder_name(advance):
    return "item_data_advance_invoice" if advance else "item_data"


@pytest.mark.parametrize("advance", [False, True])
@pytest.mark.parametrize("erp_major", [15, 16])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("route", ["none", "direct", "legacy", "both"])
@pytest.mark.parametrize("quantity", [3, -3])
def test_parent_xml_and_master_reads_match_with_half_the_tax_calls(
    advance_source, monkeypatch, advance, erp_major, currency, route, quantity,
):
    s = advance_source
    doc = prepare(s, route=route, erp_major=erp_major, currency=currency, quantity=quantity)
    reader = Mock(wraps=core.get_item_tax_detail)
    monkeypatch.setattr(core, "get_item_tax_detail", reader)
    rate_reader = Mock(wraps=core.get_item_tax_rate)
    monkeypatch.setattr(core, "get_item_tax_rate", rate_reader)
    parent = parent_builders()
    name = builder_name(advance)
    expected = run_builder(s, doc, parent[name])
    assert reader.call_args_list == [entry for item in doc.items for entry in [call(doc, item)] * 2]
    reader.reset_mock()
    actual = run_builder(s, doc, getattr(core, name))
    reader.assert_not_called()
    assert rate_reader.call_args_list == [call(doc, item) for item in doc.items]
    assert expected[:2] == actual[:2] and actual[0] is None
    assert expected[3:] == actual[3:]


@pytest.mark.parametrize("advance", [False, True])
@pytest.mark.parametrize("erp_major", [15, 16])
@pytest.mark.parametrize("failing_item", [0, 1])
def test_remaining_tax_read_faults_keep_error_and_partial_xml(
    advance_source, monkeypatch, advance, erp_major, failing_item,
):
    s = advance_source
    doc = prepare(s, erp_major=erp_major)
    original = core.get_item_tax_detail
    def tax_reader(document, item):
        if item is doc.items[failing_item]:
            raise ValueError("synthetic-required-tax-read-failure")
        return original(document, item)
    reader = Mock(side_effect=tax_reader)
    monkeypatch.setattr(core, "get_item_tax_detail", reader)
    rate_reader = Mock(side_effect=lambda document, item: tax_reader(document, item)[1])
    monkeypatch.setattr(core, "get_item_tax_rate", rate_reader)
    parent = parent_builders()
    name = builder_name(advance)
    expected = run_builder(s, doc, parent[name])
    assert reader.call_count == failing_item * 2 + 1
    reader.reset_mock()
    actual = run_builder(s, doc, getattr(core, name))
    reader.assert_not_called()
    assert rate_reader.call_count == failing_item + 1
    assert expected[:2] == actual[:2] and actual[0] is not None
    assert "synthetic-required-tax-read-failure" in actual[0][1]
    assert expected[3:] == actual[3:]


@pytest.mark.parametrize("advance", [False, True])
@pytest.mark.parametrize("erp_major", [15, 16])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
def test_unused_json_no_longer_rejects_valid_native_decimal_tax_tuple(
    advance_source, monkeypatch, advance, erp_major, currency,
):
    s = advance_source
    doc = prepare(s, erp_major=erp_major, currency=currency)
    original = core.get_item_tax_detail
    def decimal_details(document, item):
        amount, rate = original(document, item)
        return Decimal(str(amount)), Decimal(str(rate))
    reader = Mock(side_effect=decimal_details)
    monkeypatch.setattr(core, "get_item_tax_detail", reader)
    rate_reader = Mock(side_effect=lambda document, item: decimal_details(document, item)[1])
    monkeypatch.setattr(core, "get_item_tax_rate", rate_reader)
    parent = parent_builders()
    name = builder_name(advance)
    old = run_builder(s, doc, parent[name])
    assert old[0] is not None and "not JSON serializable" in old[0][1]
    reader.reset_mock()
    actual = run_builder(s, doc, getattr(core, name))
    assert actual[0] is None and rate_reader.call_count == len(doc.items)
    reader.assert_not_called()
    # An independent native-float parent run supplies the unchanged XML bytes.
    monkeypatch.setattr(core, "get_item_tax_detail", original)
    expected = run_builder(s, doc, parent_builders()[name])
    assert actual[:2] == expected[:2] and actual[3:] == expected[3:]


@pytest.mark.parametrize("advance", [False, True])
@pytest.mark.parametrize("erp_major", [15, 16])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
def test_unused_json_no_longer_requires_item_code_when_description_and_tax_exist(
    advance_source, advance, erp_major, currency,
):
    s = advance_source
    doc = prepare(s, erp_major=erp_major, currency=currency)
    del doc.items[0].item_code
    name = builder_name(advance)
    old = run_builder(s, doc, parent_builders()[name])
    assert old[0] is not None and "item_code" in old[0][1]
    actual = run_builder(s, doc, getattr(core, name))
    assert actual[0] is None
    # Supplying a code only for the parent's unused serializer leaves the
    # tax rate and description-based XML name unchanged in these fixtures.
    doc.items[0].item_code = "ITEM"
    expected = run_builder(s, doc, parent_builders()[name])
    assert actual[:2] == expected[:2] and actual[3:] == expected[3:]


@pytest.mark.parametrize("advance", [False, True])
@pytest.mark.parametrize("erp_major", [15, 16])
def test_each_row_uses_one_fresh_result_without_cross_row_cache(
    advance_source, monkeypatch, advance, erp_major,
):
    s = advance_source
    doc = prepare(s, erp_major=erp_major)
    calls = []
    def read_once(document, item):
        assert all(item is not previous for previous in calls), "A row must not be acquired twice"
        calls.append(item)
        return 5.0 if item is doc.items[0] else 15.0
    monkeypatch.setattr(core, "get_item_tax_rate", read_once)
    root = ET.Element("Invoice")
    getattr(core, builder_name(advance))(root, doc)
    rates = [line.find("cac:Item").find("cac:ClassifiedTaxCategory").find("cbc:Percent").text
             for line in root.findall("cac:InvoiceLine")]
    assert rates == ["5.00", "15.00"] and calls == doc.items


@pytest.mark.parametrize("code", ["ITEM", "", "خدمة"])
def test_public_legacy_json_helper_still_returns_original_wire_contract(advance_source, monkeypatch, code):
    s = advance_source
    doc = prepare(s)
    doc.items[0].item_code = code
    reader = Mock(return_value=(1.5, 15.0))
    monkeypatch.setattr(core, "get_item_tax_detail", reader)
    content = core.get_tax_wise_detail(doc, doc.items[0])
    assert content == json.dumps({str(code): [15.0, 1.5]})
    reader.assert_called_once_with(doc, doc.items[0])


def test_public_legacy_json_helper_keeps_its_existing_decimal_error(advance_source, monkeypatch):
    s = advance_source
    doc = prepare(s)
    monkeypatch.setattr(core, "get_item_tax_detail", lambda *args: (Decimal("1.5"), Decimal("15")))
    with pytest.raises(TypeError, match="not JSON serializable"):
        core.get_tax_wise_detail(doc, doc.items[0])
