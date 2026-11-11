"""Discount/tax selection parity with real builders and synthetic saved inputs.

Preserving the existing per-adapter bytes is not fiscal/SDK acceptance. The
fixture owns mocked master reads and observes no allocated advances or GL work.
"""

from dataclasses import FrozenInstanceError
import json
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from zatca_erpgulf.zatca_erpgulf import (
    advance_deduction, createxml, create_xml_final_part, posxml, pos_final,
    sign_invoice, pos_sign, xml_tax_data,
)
from zatca_erpgulf.zatca_erpgulf.document_tax_xml import DocumentTaxTools, populate_document_tax
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document, fail


def previous_sequence(root, doc, namespace, has_template, mode):
    """Freeze prior selection independently of the new tools factory."""
    cached = getattr(doc, "custom_zatca_nominal_invoice", 0) == 1 if mode == "debug" else None
    nominal = cached if mode == "debug" else doc.custom_zatca_nominal_invoice == 1 if mode == "sales" else False
    if nominal:
        root = namespace["add_nominal_discount_tax"](root, doc)
    elif not has_template:
        root = namespace["add_document_level_discount_with_tax"](root, doc)
    else:
        root = namespace["add_document_level_discount_with_tax_template"](root, doc)
    nominal = cached if mode == "debug" else doc.custom_zatca_nominal_invoice == 1 if mode == "sales" else False
    if nominal:
        if not has_template:
            root = namespace["tax_data_nominal"](root, doc)
        else:
            root = namespace["tax_data_with_template_nominal"](root, doc)
    elif not has_template:
        root = namespace["tax_data"](root, doc)
    else:
        root = namespace["tax_data_with_template"](root, doc)
    return root


def run_shared(root, doc, namespace, has_template, mode):
    if mode == "debug":
        cached = getattr(doc, "custom_zatca_nominal_invoice", 0) == 1
        reader = lambda: cached
    elif mode == "sales":
        reader = lambda: doc.custom_zatca_nominal_invoice == 1
    else:
        reader = None
    tools = DocumentTaxTools.from_namespace(namespace, has_template=has_template, include_nominal=mode != "pos")
    return populate_document_tax(root, doc, tools=tools, is_nominal=reader)


@pytest.fixture
def tax_source(monkeypatch):
    templates = {
        ("Item Tax Template", "ITEM-VAT"): Document(custom_zatca_tax_category="Standard",
            custom_exemption_reason_code=None, taxes=[Document(tax_rate=15)]),
        ("POS Profile", "POS"): Document(taxes_and_charges="INVOICE-VAT"),
        ("Sales Taxes and Charges Template", "INVOICE-VAT"): Document(custom_zatca_tax_category="Standard",
            custom_exemption_reason_code=None, taxes=[Document(rate=15, included_in_print_rate=0)]),
    }
    runtime = SimpleNamespace(get_doc=Mock(side_effect=lambda dt, name: templates[dt, name]),
        throw=fail, DoesNotExistError=ValueError, db=SimpleNamespace(commit=Mock(), set_value=Mock()),
        log_error=Mock(), msgprint=Mock())
    for module in (createxml, create_xml_final_part, posxml, pos_final, xml_tax_data):
        monkeypatch.setattr(module, "frappe", runtime)
        monkeypatch.setattr(module, "_", lambda message, *args: message)
    monkeypatch.setattr(advance_deduction, "supports_advance_deduction_schema", lambda doc: False)
    return templates, runtime


@pytest.mark.parametrize("family,nominal", [("sales", 0), ("sales", 1), ("pos", 1)])
@pytest.mark.parametrize("has_template", [False, True])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("discount_kind", ["none", "document", "distributed"])
@pytest.mark.parametrize("negative", [False, True])
@pytest.mark.parametrize("erp_major", [15, 16])
@pytest.mark.parametrize("inclusive", [0, 1])
def test_real_discount_tax_bytes_reads_and_numeric_inputs_match_previous_sequence(
    tax_source, family, nominal, has_template, currency, discount_kind, negative, erp_major, inclusive,
):
    templates, runtime = tax_source
    sign, fx = (-1 if negative else 1), (1 if currency == "SAR" else 3.75)
    discount = 0 if discount_kind == "none" else 10
    net = 90 if discount_kind == "distributed" else 100
    item = Document(name="ROW", idx=1, item_code="ITEM", item_name="Synthetic Item", qty=sign,
        amount=100 * sign, base_amount=100 * fx * sign, net_amount=net * sign,
        base_net_amount=net * fx * sign, item_tax_template="ITEM-VAT" if has_template else "",
        item_tax_rate=json.dumps({"VAT": 15}), distributed_discount_amount=10 if discount_kind == "distributed" else 0)
    tax = Document(name="TAX", rate=15, included_in_print_rate=inclusive, account_head="VAT",
        item_wise_tax_detail=json.dumps({"ITEM": [15, net * .15]}))
    doc = Document(doctype="Sales Invoice" if family == "sales" else "POS Invoice", company="SYNTHETIC",
        currency=currency, conversion_rate=fx, pos_profile="POS", taxes_and_charges="INVOICE-VAT",
        custom_zatca_nominal_invoice=nominal, custom_zatca_tax_category="Standard",
        custom_zatca_discount_reason="Discount", custom_exemption_reason_code=None,
        total=100 * sign, net_total=net * sign, base_total=100 * fx * sign, base_net_total=net * fx * sign,
        discount_amount=discount, base_discount_amount=discount * fx,
        total_taxes_and_charges=net * .15 * sign, base_total_taxes_and_charges=net * .15 * fx * sign,
        is_return=int(negative), is_debit_note=0, disable_rounded_total=1,
        items=[item], taxes=[tax], save=Mock(), db_set=Mock())
    if erp_major == 16:
        doc.item_wise_tax_details = [Document(item_row="ROW", tax_row="TAX", rate=15, amount=net * .15)]
    templates["Sales Taxes and Charges Template", "INVOICE-VAT"].taxes[0].included_in_print_rate = inclusive
    namespace = vars(sign_invoice if family == "sales" else pos_sign)
    numeric_before = (doc.total, doc.net_total, doc.base_total, doc.base_net_total,
                      doc.discount_amount, doc.base_discount_amount, item.net_amount, item.base_net_amount)
    expected = previous_sequence(ET.Element("Invoice"), doc, namespace, has_template, family)
    reads = runtime.get_doc.call_args_list[:]
    runtime.get_doc.reset_mock()
    actual = run_shared(ET.Element("Invoice"), doc, namespace, has_template, family)
    assert ET.tostring(actual) == ET.tostring(expected)
    assert runtime.get_doc.call_args_list == reads
    assert actual.find("cac:TaxTotal") is not None and actual.find("cac:LegalMonetaryTotal") is not None
    assert numeric_before == (doc.total, doc.net_total, doc.base_total, doc.base_net_total,
                              doc.discount_amount, doc.base_discount_amount, item.net_amount, item.base_net_amount)
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()
    runtime.db.commit.assert_not_called()
    runtime.db.set_value.assert_not_called()
    runtime.log_error.assert_not_called()
    runtime.msgprint.assert_not_called()


def trace_namespace(*, change_to=None, failure=None, clone=False):
    calls, roots = [], []
    sentinel = RuntimeError("synthetic-tax-stage-failure")
    names = ("add_document_level_discount_with_tax", "add_document_level_discount_with_tax_template",
             "tax_data", "tax_data_with_template", "add_nominal_discount_tax",
             "tax_data_nominal", "tax_data_with_template_nominal")
    def step(name):
        def invoke(root, doc):
            calls.append((name, root, doc))
            if failure and ((failure == "discount" and name.startswith("add_")) or
                            (failure == "tax" and name.startswith("tax_"))):
                raise sentinel
            if change_to is not None and name.startswith("add_"):
                doc.custom_zatca_nominal_invoice = change_to
            result = object() if clone else root
            roots.append(result)
            return result
        return invoke
    return {name: step(name) for name in names}, calls, roots, sentinel


@pytest.mark.parametrize("mode", ["sales", "debug", "pos"])
@pytest.mark.parametrize("has_template", [False, True])
@pytest.mark.parametrize("initial,changed", [(0, 1), (1, 0)])
def test_mutated_nominal_flag_preserves_two_reads_sales_one_read_debug_and_no_pos_policy(mode, has_template, initial, changed):
    old_namespace, old_calls, _, _ = trace_namespace(change_to=changed)
    new_namespace, calls, _, _ = trace_namespace(change_to=changed)
    doc, old_doc = Document(custom_zatca_nominal_invoice=initial), Document(custom_zatca_nominal_invoice=initial)
    previous_sequence(object(), old_doc, old_namespace, has_template, mode)
    run_shared(object(), doc, new_namespace, has_template, mode)
    assert [call[0] for call in calls] == [call[0] for call in old_calls]
    assert doc.custom_zatca_nominal_invoice == old_doc.custom_zatca_nominal_invoice == changed


@pytest.mark.parametrize("mode,expected", [("sales", 2), ("debug", 1), ("pos", 0)])
@pytest.mark.parametrize("has_template", [False, True])
def test_nominal_source_is_read_at_the_original_frequency(mode, expected, has_template):
    class ObservedDocument:
        reads = 0

        @property
        def custom_zatca_nominal_invoice(self):
            self.reads += 1
            return 1

    doc = ObservedDocument()
    namespace, _, _, _ = trace_namespace()
    run_shared(object(), doc, namespace, has_template, mode)
    assert doc.reads == expected


@pytest.mark.parametrize("nominal", [False, True])
@pytest.mark.parametrize("failed_read", [1, 2])
def test_nominal_read_failure_stops_at_its_original_stage(nominal, failed_read):
    namespace, calls, _, _ = trace_namespace()
    tools = DocumentTaxTools.from_namespace(namespace, has_template=False, include_nominal=True)
    sentinel = AttributeError("synthetic-field-read-failure")
    reader = Mock(side_effect=[sentinel] if failed_read == 1 else [nominal, sentinel])
    with pytest.raises(AttributeError) as raised:
        populate_document_tax(object(), object(), tools=tools, is_nominal=reader)
    assert raised.value is sentinel
    assert len(calls) == failed_read - 1
    assert reader.call_count == failed_read


@pytest.mark.parametrize("has_template", [False, True])
@pytest.mark.parametrize("nominal", [0, 1])
@pytest.mark.parametrize("failure", ["discount", "tax"])
def test_stage_failure_preserves_exception_and_prevents_later_work(has_template, nominal, failure):
    namespace, calls, _, sentinel = trace_namespace(failure=failure)
    with pytest.raises(RuntimeError) as raised:
        run_shared(object(), Document(custom_zatca_nominal_invoice=nominal), namespace, has_template, "sales")
    assert raised.value is sentinel
    assert len(calls) == (1 if failure == "discount" else 2)


@pytest.mark.parametrize("has_template", [False, True, None, 0, 1, "0", "1"])
def test_existing_flag_truthiness_root_replacement_and_minimal_pos_dependencies(has_template):
    namespace, calls, roots, _ = trace_namespace(clone=True)
    for name in ("add_nominal_discount_tax", "tax_data_nominal", "tax_data_with_template_nominal"):
        del namespace[name]
    root = object()
    result = run_shared(root, object(), namespace, has_template, "pos")
    assert [call[0] for call in calls] == (["add_document_level_discount_with_tax_template", "tax_data_with_template"] if has_template else ["add_document_level_discount_with_tax", "tax_data"])
    assert calls[0][1] is root and calls[1][1] is roots[0] and result is roots[1]


def test_debug_optional_field_remains_optional_and_sales_required_field_remains_required():
    namespace, calls, _, _ = trace_namespace()
    run_shared(object(), Document(), namespace, False, "debug")
    assert [call[0] for call in calls] == ["add_document_level_discount_with_tax", "tax_data"]
    calls.clear()
    with pytest.raises(AttributeError):
        run_shared(object(), Document(), namespace, False, "sales")
    assert not calls


def test_missing_nominal_tools_and_invalid_reader_fail_without_disclosing_inputs():
    tools = DocumentTaxTools(Mock(), Mock())
    for reader, error, message in ((True, TypeError, "document_tax_nominal_reader"),
                                    (lambda: True, ValueError, "document_tax_nominal_tools")):
        with pytest.raises(error, match="^" + message + "$"):
            populate_document_tax(object(), object(), tools=tools, is_nominal=reader)
    tools.discount.assert_not_called()
    tools.tax.assert_not_called()


@pytest.mark.parametrize("inputs", [(None, Mock(), None, None), (Mock(), None, None, None),
                                  (Mock(), Mock(), Mock(), None), (Mock(), Mock(), None, Mock())])
def test_incomplete_tool_bindings_are_rejected(inputs):
    with pytest.raises(TypeError, match="^document_tax_tools$"):
        DocumentTaxTools(*inputs)


def test_binding_is_frozen_and_does_not_copy_namespace_or_source_values():
    namespace, _, _, _ = trace_namespace()
    secret = object()
    namespace.update(private_key=secret, document=secret)
    first = DocumentTaxTools.from_namespace(namespace, has_template=False)
    old = first.discount
    namespace["add_document_level_discount_with_tax"] = Mock()
    second = DocumentTaxTools.from_namespace(namespace, has_template=False)
    assert first.discount is old and second.discount is not old
    assert all(value is not secret for value in vars(first).values())
    with pytest.raises(FrozenInstanceError):
        first.tax = Mock()
