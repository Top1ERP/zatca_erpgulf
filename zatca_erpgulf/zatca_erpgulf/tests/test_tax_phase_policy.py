"""Phase-aware canonical tax hooks with exact parent order and no site I/O."""

import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.ksa_compliance import field_compat
from zatca_erpgulf.zatca_erpgulf import tax_error as checks
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document, ValidationError, fail

REFERENCE = Path(__file__).parent / "fixtures" / "tax_hooks_30570cf.py"
REFERENCE_SHA256 = "8ef703f7aa2021fd68c01ab1514d4abb153bca44cf7f8c109aae932caed5494c"
CHECKS = (
    "validate_positive_item_values_for_zatca",
    "validate_advance_payment_invoice_tax_structure",
    "validate_zatca_tax_source_presence",
    "validate_zatca_tax_category_and_exemption_reason",
    "validate_zatca_zero_rate_categories",
    "validate_zatca_tax_table",
)
# Schema absence and blank values are deliberately different cases.
PHASES = [
    (True, "Phase-1", True, "Phase-2", True),
    (True, " Phase-1 ", False, None, True),
    (False, None, True, "Phase-1", True),
    (True, "Phase-2", True, "Phase-1", False),
    (False, None, True, "Phase-2", False),
    (True, "", True, "Phase-1", False),
    (True, None, True, "Phase-1", False),
    (True, "unknown", True, "Phase-1", False),
    (False, None, False, None, False),
]


class Meta:
    def __init__(self, fields):
        self.fields = set(fields)
    def has_field(self, name):
        return name in self.fields
    def get_field(self, name):
        return SimpleNamespace(fieldname=name) if name in self.fields else None


@pytest.fixture
def environment(monkeypatch):
    company = Document(doctype="Company", name="SYNTHETIC-COMPANY", custom_zatca_invoice_enabled=1,
                       custom_zatca_negative_line_validation_mode="Strict")
    customer = Document(name="SYNTHETIC-CUSTOMER")
    item = Document(idx=1, item_code="ITEM", qty=1, rate=100, amount=100, net_amount=100,
                    base_amount=100, base_net_amount=100)
    doc = Document(doctype="Sales Invoice", name="SYNTHETIC-INVOICE", company=company.name,
        customer=customer.name, items=[item], taxes=[Document(rate=15)], save=Mock(), db_set=Mock())
    records = {("Company", company.name): company, ("Customer", customer.name): customer}
    events = []
    company_fields = {"custom_zatca_negative_line_validation_mode"}
    company_meta = Meta(company_fields)
    invoice_meta = Meta(())
    def get_doc(doctype, name):
        events.append(("load", doctype, name))
        return records[doctype, name]
    runtime = SimpleNamespace(get_doc=Mock(side_effect=get_doc),
        get_meta=Mock(side_effect=lambda doctype: company_meta if doctype == "Company" else invoice_meta),
        get_installed_apps=Mock(return_value=[]), throw=Mock(side_effect=fail),
        msgprint=Mock(), log_error=Mock(), DoesNotExistError=KeyError,
        db=SimpleNamespace(exists=Mock(return_value=False), commit=Mock(), set_value=Mock()))
    monkeypatch.setattr(checks, "frappe", runtime)
    monkeypatch.setattr(field_compat, "frappe", runtime)
    monkeypatch.setattr(checks, "_", lambda text, *args, **kwargs: text)
    monkeypatch.setattr(checks, "_zt", lambda text: text)
    return SimpleNamespace(company=company, customer=customer, doc=doc, item=item, records=records,
                           events=events, runtime=runtime, company_meta=company_meta)


def configure(env, phase, enabled=1, doctype="Sales Invoice"):
    primary_present, primary, legacy_present, legacy, _skip = phase
    for name in ("custom_phase_1_or_2", "phase_1_or_2"):
        env.company.__dict__.pop(name, None)
        env.company_meta.fields.discard(name)
    if primary_present:
        env.company.custom_phase_1_or_2 = primary
        env.company_meta.fields.add("custom_phase_1_or_2")
    if legacy_present:
        env.company.phase_1_or_2 = legacy
        env.company_meta.fields.add("phase_1_or_2")
    env.company.custom_zatca_invoice_enabled = enabled
    env.doc.doctype = doctype


def parent_hooks():
    content = REFERENCE.read_bytes()
    assert hashlib.sha256(content).hexdigest() == REFERENCE_SHA256
    namespace = dict(vars(checks))
    exec(compile(content, str(REFERENCE), "exec"), namespace)
    return namespace


def install_check_probes(env, monkeypatch, fault=None):
    probes = {}
    for name in CHECKS:
        def probe(*args, _name=name, **kwargs):
            env.events.append(("check", _name, args, kwargs))
            if _name == fault:
                raise ValueError("synthetic-" + _name)
        probes[name] = Mock(side_effect=probe)
        monkeypatch.setattr(checks, name, probes[name])
    return probes


def invoke(env, operation, event):
    env.events.clear()
    env.runtime.get_doc.reset_mock()
    env.runtime.get_meta.reset_mock()
    env.runtime.get_installed_apps.reset_mock()
    try:
        result = operation(env.doc, event)
    except Exception as error:
        outcome = type(error), str(error)
    else:
        assert result is None
        outcome = None
    return outcome, env.events[:], env.runtime.get_doc.call_args_list[:], env.runtime.get_installed_apps.call_args_list[:]


def no_writes(env):
    env.doc.save.assert_not_called()
    env.doc.db_set.assert_not_called()
    env.runtime.db.commit.assert_not_called()
    env.runtime.db.set_value.assert_not_called()


@pytest.mark.parametrize("hook", ["validate_negative_item_values_on_save", "validate_sales_invoice_taxes"])
@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("event", [None, "synthetic-event"])
@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("enabled", [0, 1])
def test_exact_parent_sequence_is_retained_except_explicit_phase1_metadata(
    environment, monkeypatch, hook, doctype, event, phase, enabled,
):
    env = environment
    configure(env, phase, enabled, doctype)
    install_check_probes(env, monkeypatch)
    old = invoke(env, parent_hooks()[hook], event)
    new = invoke(env, getattr(checks, hook), event)
    if enabled and phase[-1]:
        expected_events = [entry for entry in old[1] if entry[0] != "check" or entry[1] == CHECKS[0]]
        assert new == (old[0], expected_events, old[2], old[3])
    else:
        assert new == old
    if not enabled:
        assert env.runtime.get_meta.call_count == 0
    no_writes(env)
    env.runtime.msgprint.assert_not_called()
    env.runtime.log_error.assert_not_called()


@pytest.mark.parametrize("hook", ["validate_negative_item_values_on_save", "validate_sales_invoice_taxes"])
@pytest.mark.parametrize("phase", [PHASES[0], PHASES[3], PHASES[5], PHASES[8]])
@pytest.mark.parametrize("fault", CHECKS)
def test_validation_failures_preserve_order_and_phase1_still_checks_values(
    environment, monkeypatch, hook, phase, fault,
):
    env = environment
    configure(env, phase)
    install_check_probes(env, monkeypatch, fault)
    old = invoke(env, parent_hooks()[hook], "event")
    new = invoke(env, getattr(checks, hook), "event")
    if phase[-1] and fault != CHECKS[0]:
        assert old[0] is not None and new[0] is None
        assert [entry[1] for entry in new[1] if entry[0] == "check"] == [CHECKS[0]]
    else:
        assert new == old and new[0] is not None
    no_writes(env)


@pytest.mark.parametrize("hook", ["validate_negative_item_values_on_save", "validate_sales_invoice_taxes"])
@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("phase", PHASES[:3])
@pytest.mark.parametrize("item_template", [False, True])
def test_real_phase1_hook_does_not_require_phase2_source_or_category_metadata(
    environment, hook, doctype, phase, item_template,
):
    env = environment
    configure(env, phase, doctype=doctype)
    if item_template:
        env.item.item_tax_template = "LEGACY-VAT"
        env.records[("Item Tax Template", "LEGACY-VAT")] = Document(name="LEGACY-VAT", taxes=[Document(tax_rate=15)])
    # No taxes_and_charges or custom ZATCA category/reason is supplied. ERP tax
    # rows remain present so unrelated submit-tail requirements still apply.
    old = invoke(env, parent_hooks()[hook], "event")
    assert old[0] is not None
    env.runtime.throw.reset_mock()
    new = invoke(env, getattr(checks, hook), "event")
    assert new[0] is None
    assert all(entry[0] == "load" for entry in new[1])
    env.runtime.throw.assert_not_called()
    no_writes(env)


@pytest.mark.parametrize("hook", ["validate_negative_item_values_on_save", "validate_sales_invoice_taxes"])
@pytest.mark.parametrize("phase", [PHASES[3], PHASES[5], PHASES[8]])
def test_real_phase2_and_unknown_phase_keep_rejecting_missing_source(environment, hook, phase):
    env = environment
    configure(env, phase)
    old = invoke(env, parent_hooks()[hook], "event")
    new = invoke(env, getattr(checks, hook), "event")
    assert new == old and new[0] is not None
    assert "taxes_and_charges" in new[0][1] or "tax sources" in new[0][1]
    no_writes(env)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("hook", ["validate_negative_item_values_on_save", "validate_sales_invoice_taxes"])
def test_phase1_negative_item_values_still_fail_with_real_item_validator(environment, doctype, hook):
    env = environment
    configure(env, PHASES[0], doctype=doctype)
    env.item.qty = -1
    old = invoke(env, parent_hooks()[hook], None)
    new = invoke(env, getattr(checks, hook), None)
    assert new == old and new[0] is not None
    assert "quantity" in new[0][1].lower() or "Quantity" in new[0][1]
    no_writes(env)


@pytest.mark.parametrize("hook", ["validate_negative_item_values_on_save", "validate_sales_invoice_taxes"])
def test_phase_read_failure_does_not_silently_skip_metadata(environment, monkeypatch, hook):
    env = environment
    configure(env, PHASES[0])
    probes = install_check_probes(env, monkeypatch)
    monkeypatch.setattr(checks, "resolve_zatca_phase", Mock(side_effect=ValueError("synthetic-phase-read-failure")))
    outcome = invoke(env, getattr(checks, hook), None)
    assert outcome[0] == (ValueError, "synthetic-phase-read-failure")
    probes[CHECKS[0]].assert_called_once_with(env.doc, env.company)
    assert all(not probes[name].called for name in CHECKS[1:])
    no_writes(env)


def test_phase1_submit_keeps_unrelated_cost_center_requirement(environment, monkeypatch):
    env = environment
    configure(env, PHASES[0])
    env.company.custom_costcenter = 1
    install_check_probes(env, monkeypatch)
    old = invoke(env, parent_hooks()["validate_sales_invoice_taxes"], None)
    new = invoke(env, checks.validate_sales_invoice_taxes, None)
    assert old[0] == new[0] and "requires a Cost Center" in new[0][1]
    assert env.runtime.throw.call_count == 2
    no_writes(env)


@pytest.mark.parametrize("company_name", [None, ""])
def test_save_without_company_still_exits_before_phase_resolution(environment, monkeypatch, company_name):
    env = environment
    env.doc.company = company_name
    install_check_probes(env, monkeypatch)
    old = invoke(env, parent_hooks()["validate_negative_item_values_on_save"], None)
    new = invoke(env, checks.validate_negative_item_values_on_save, None)
    assert new == old and new == (None, [], [], [])
    env.runtime.get_meta.assert_not_called()
    no_writes(env)


def test_unsupported_save_doctype_keeps_original_early_exit(environment, monkeypatch):
    env = environment
    env.doc.doctype = "Purchase Invoice"
    install_check_probes(env, monkeypatch)
    old = invoke(env, parent_hooks()["validate_negative_item_values_on_save"], None)
    new = invoke(env, checks.validate_negative_item_values_on_save, None)
    assert new == old and new == (None, [], [], [])
    no_writes(env)


def test_phase1_submit_still_keeps_the_existing_tax_information_requirement(environment, monkeypatch):
    env = environment
    configure(env, PHASES[0])
    env.doc.taxes = []
    install_check_probes(env, monkeypatch)
    old = invoke(env, parent_hooks()["validate_sales_invoice_taxes"], None)
    new = invoke(env, checks.validate_sales_invoice_taxes, None)
    assert old[0] == new[0] and "tax information is missing" in new[0][1]
    no_writes(env)


@pytest.mark.parametrize("hook", ["validate_negative_item_values_on_save", "validate_sales_invoice_taxes"])
@pytest.mark.parametrize("phase", PHASES[:3])
@pytest.mark.parametrize("item_template", [False, True])
def test_real_phase1_advance_marker_does_not_impose_phase2_tax_metadata(
    environment, hook, phase, item_template,
):
    env = environment
    configure(env, phase)
    env.doc.is_advance_payment = 1
    if item_template:
        env.item.item_tax_template = "LEGACY-VAT"
        env.records[("Item Tax Template", "LEGACY-VAT")] = Document(name="LEGACY-VAT", taxes=[Document(tax_rate=15)])
    old = invoke(env, parent_hooks()[hook], None)
    assert old[0] is not None
    env.runtime.throw.reset_mock()
    new = invoke(env, getattr(checks, hook), None)
    assert new[0] is None
    env.runtime.throw.assert_not_called()
    no_writes(env)
