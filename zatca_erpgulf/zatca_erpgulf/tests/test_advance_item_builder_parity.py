"""Frozen advance wrappers against shared regular-line emission, offline only."""

from decimal import Decimal
import hashlib
from pathlib import Path
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from zatca_erpgulf.zatca_erpgulf import create_xml_final_part as core
from zatca_erpgulf.zatca_erpgulf.tests.test_sales_item_builder_parity import (
    TrackedDocument, invoice, source as sales_source,
)


REFERENCE = Path(__file__).parent / "fixtures" / "advance_item_builders_03b4982.py"
REFERENCE_SHA256 = "2fab4743ddd59103e86e50b2198453d16dab6d5698870a20e05c27eac7772814"
WATCHED = {"currency", "items", "idx", "uom", "qty", "taxes", "tax_rate",
           "custom_zatca_tax_category", "custom_advances_copy", "custom_item"}


class AttributeDocument(TrackedDocument):
    def __getattribute__(self, name):
        if name in WATCHED:
            trace = object.__getattribute__(self, "trace")
            trace.append((object.__getattribute__(self, "role"), "attribute:" + name))
            if name == "currency":
                fault_at = object.__getattribute__(self, "__dict__").get("currency_fault_at")
                if fault_at:
                    count = object.__getattribute__(self, "__dict__").get("currency_reads", 0) + 1
                    self.currency_reads = count
                    if count == fault_at:
                        raise ValueError("synthetic-currency-read-failure")
        return super().__getattribute__(name)


@pytest.fixture
def advance_source(sales_source):
    s = sales_source
    s.document = lambda role, **values: AttributeDocument(role=role, trace=s.trace, **values)
    def convert(role, old):
        return s.document(role, **{key: value for key, value in vars(old).items() if key not in ("role", "trace")})
    s.template = convert("template", s.template)
    s.template.taxes = [s.document("template-rate", tax_rate=15)]
    s.advance = convert("advance", s.advance)
    s.last_template = s.document("last-template", custom_zatca_tax_category="Exempted", taxes=[s.document("last-rate", tax_rate=5)])
    s.legacy = s.document("legacy", custom_item=[
        s.document("legacy-row-1", uom="PCE", amount=-50, item_code="OLD-1", item_name="Old first"),
        s.document("legacy-row-2", uom="PCE", amount=20.15, item_code="OLD-2", item_name="Old second"),
    ])
    s.records = {("Item Tax Template", "ITEM-VAT"): s.template,
                 ("Item Tax Template", "LAST-VAT"): s.last_template,
                 ("Sales Invoice", s.advance.name): s.advance,
                 ("Advance Sales Invoice", "LEGACY-2020"): s.legacy}
    s.runtime.get_doc.side_effect = lambda dt, name: s.records[dt, name]
    s.apps = []
    s.runtime.get_installed_apps = Mock(side_effect=lambda: list(s.apps))
    content = REFERENCE.read_bytes()
    assert hashlib.sha256(content).hexdigest() == REFERENCE_SHA256
    s.advance_reference = dict(vars(core))
    exec(compile(content, str(REFERENCE), "exec"), s.advance_reference)
    return s


def prepare(s, *, route="none", mixed=False, **kwargs):
    doc = invoice(s, direct=route in ("direct", "both"), **kwargs)
    if mixed:
        doc.items[-1].item_tax_template = "LAST-VAT"
        doc.items[-1].item_tax_rate = '{"VAT":5}'
        if hasattr(doc, "item_wise_tax_details"):
            doc.item_wise_tax_details[-1].rate = 5
    s.apps = ["claudion4saudi"] if route in ("legacy", "both") else []
    if route in ("legacy", "both"):
        doc.custom_advances_copy = [
            s.document("copy", reference_name="LEGACY-2020", uuid="legacy-uuid",
                       difference_posting_date="2020-01-01", posting_time="9:05:42"),
            s.document("unused-copy", reference_name="MUST-NOT-LOAD"),
        ]
    return doc


def compare(s, doc, has_template, *, ordinary=False):
    name = ("item_data_with_template" if has_template else "item_data") if ordinary else (
        "item_data_with_template_advance_invoice" if has_template else "item_data_advance_invoice")
    reference = s.reference if ordinary else s.advance_reference
    outcomes = []
    for operation in (reference[name], getattr(core, name)):
        root = ET.Element("Invoice")
        s.trace.clear()
        s.runtime.get_doc.reset_mock()
        s.runtime.get_installed_apps.reset_mock()
        doc.currency_reads = 0
        try:
            result = operation(root, doc)
        except Exception as error:
            outcome = type(error), str(error)
        else:
            assert result is root
            outcome = None
        outcomes.append((outcome, ET.tostring(root), s.trace[:],
                         s.runtime.get_doc.call_args_list[:], s.runtime.get_installed_apps.call_args_list[:]))
    if outcomes[0][2] != outcomes[1][2]:
        before, after = outcomes[0][2], outcomes[1][2]
        first = next((i for i, pair in enumerate(zip(before, after)) if pair[0] != pair[1]), min(len(before), len(after)))
        pytest.fail("Synthetic read-order mismatch at {0}: {1!r} versus {2!r}".format(
            first, before[max(0, first - 2):first + 3], after[max(0, first - 2):first + 3]))
    assert outcomes[0] == outcomes[1]
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()
    s.runtime.db.commit.assert_not_called()
    s.runtime.db.set_value.assert_not_called()
    s.runtime.log_error.assert_not_called()
    s.runtime.msgprint.assert_not_called()
    return outcomes[-1]


@pytest.mark.parametrize("has_template", [False, True])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("erp_major", [15, 16])
@pytest.mark.parametrize("quantity", [0, 3, -3])
@pytest.mark.parametrize("route", ["none", "direct", "legacy", "both"])
@pytest.mark.parametrize("company_field", [False, True])
@pytest.mark.parametrize("mixed", [False, True])
def test_advance_wrapper_bytes_reads_and_direct_legacy_priority_match_frozen_code(
    advance_source, has_template, currency, erp_major, quantity, route, company_field, mixed,
):
    s = advance_source
    doc = prepare(s, route=route, mixed=mixed, currency=currency, erp_major=erp_major,
                  quantity=quantity, company_field=company_field)
    before = [(item.qty, item.net_amount, item.base_net_amount) for item in doc.items]
    outcome, xml, _reads, masters, apps = compare(s, doc, has_template)
    assert outcome is None
    # Resolve the literal prefixes only for inspection; byte comparison above
    # remains against the exact original unformatted output.
    root = ET.fromstring(xml.replace(b"<Invoice>", b'<Invoice xmlns:cac="urn:cac" xmlns:cbc="urn:cbc">', 1))
    lines = root.findall("{urn:cac}InvoiceLine")
    ids = [line.find("{urn:cbc}ID").text for line in lines]
    assert ids == (["2", "7", "8"] if route in ("direct", "both") else ["2", "7", "3", "4"] if route == "legacy" else ["2", "7"])
    assert len(apps) == (0 if route in ("direct", "both") else 1)
    assert all(call.args != ("Advance Sales Invoice", "MUST-NOT-LOAD") for call in masters)
    if route == "both":
        assert all(call.args[0] != "Advance Sales Invoice" for call in masters)
    if route == "legacy":
        assert lines[-1].find("{urn:cac}DocumentReference").find("{urn:cbc}IssueDate").text == "2020-01-01"
    assert before == [(item.qty, item.net_amount, item.base_net_amount) for item in doc.items]


@pytest.mark.parametrize("has_template", [False, True])
@pytest.mark.parametrize("clock", [None, "", "9:05:42", "invalid-time"])
def test_legacy_time_fallback_and_failure_behavior_is_not_silently_unified(advance_source, has_template, clock):
    s = advance_source
    doc = prepare(s, route="legacy")
    doc.custom_advances_copy[0].posting_time = clock
    compare(s, doc, has_template)


@pytest.mark.parametrize("has_template", [False, True])
@pytest.mark.parametrize("case", ["empty-items", "empty-copy", "blank-reference", "empty-legacy-items"])
def test_legacy_last_loop_and_short_circuit_edge_behavior_is_preserved(advance_source, has_template, case):
    s = advance_source
    doc = prepare(s, route="legacy")
    if case == "empty-items":
        doc.items = []
    elif case == "empty-copy":
        doc.custom_advances_copy = []
    elif case == "blank-reference":
        doc.custom_advances_copy[0].reference_name = ""
    else:
        s.legacy.custom_item = []
    compare(s, doc, has_template)


@pytest.mark.parametrize("ordinary,has_template", [(True, False), (True, True), (False, False), (False, True)])
@pytest.mark.parametrize("fault", ["unit", "currency-first", "currency-last", "name", "price", "percent"])
def test_layout_read_timing_exception_and_partial_xml_match_old_code(advance_source, monkeypatch, ordinary, has_template, fault):
    s = advance_source
    doc = prepare(s)
    if fault == "unit":
        del doc.items[0].uom
    else:
        # Isolate emission timing from earlier acquisition/arithmetic so the
        # same targeted failure reaches the old and new XML construction site.
        patches = {"_line_net_amount": lambda *args: Decimal("1.01"),
                   "_line_net_rate": lambda *args: Decimal("0.336666666667"),
                   "_line_tax_amount_from_net": lambda *args: Decimal("0.15"),
                   "get_tax_wise_detail": lambda *args: "{}"}
        if fault.startswith("currency"):
            doc.currency_fault_at = 1 if fault.endswith("first") else 4
            patches["get_item_tax_detail"] = lambda *args: (0, 15)
        elif fault in ("name", "price"):
            patches["_line_name" if fault == "name" else "_format_price_amount"] = Mock(side_effect=ValueError("synthetic-" + fault + "-failure"))
        else:
            class BrokenRate:
                def __float__(self):
                    raise ValueError("synthetic-rate-failure")
            s.template.taxes[0].tax_rate = BrokenRate()
            patches["get_item_tax_detail"] = lambda *args: (0, s.template.taxes[0].tax_rate)
        for name, value in patches.items():
            monkeypatch.setattr(core, name, value)
            s.reference[name] = s.advance_reference[name] = value
    outcome, *_ = compare(s, doc, has_template, ordinary=ordinary)
    assert outcome is not None


def test_unknown_internal_layout_fails_before_appending_any_line():
    root = ET.Element("Invoice")
    with pytest.raises(ValueError, match="^sales_item_layout$"):
        core._append_sales_invoice_line(root, object(), object(), 0, 0, 0, 0, layout="invalid")
    assert not list(root)
