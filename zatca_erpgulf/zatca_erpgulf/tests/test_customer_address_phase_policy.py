"""Current-baseline hotfix and DEV address preflight with synthetic inputs only."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf.zatca_runtime import (
    PHASE_1_VALUE, is_zatca_invoice_enabled, resolve_zatca_phase,
)


class ValidationFailure(Exception):
    pass


@pytest.fixture
def policy():
    root = Path(__file__).resolve().parents[3]
    source = root / "zatca_erpgulf/zatca_erpgulf/customer_address.py"
    tree = ast.parse(source.read_text())
    selected = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef)
        and node.name in ("_value", "validate_customer_address_for_zatca")], type_ignores=[])
    def throw(message):
        raise ValidationFailure(message)
    runtime = SimpleNamespace(get_cached_doc=Mock(), get_doc=Mock(), throw=Mock(side_effect=throw))
    resolver = Mock(return_value=(None, None))
    namespace = dict(frappe=runtime, PHASE_1_VALUE=PHASE_1_VALUE, is_zatca_invoice_enabled=is_zatca_invoice_enabled,
        resolve_zatca_phase=resolve_zatca_phase, resolve_customer_address=resolver,
        cint=lambda value: int(value or 0), get_alias_value=lambda key, doc, default: getattr(doc, "b2c", default),
        _=lambda text: text, Any=object)
    exec(compile(selected, str(source), "exec"), namespace)
    return SimpleNamespace(runtime=runtime, resolver=resolver, validate=namespace["validate_customer_address_for_zatca"])


def company(phase, *, enabled=1, legacy=None, primary_present=True):
    values = dict(custom_zatca_invoice_enabled=enabled, phase_1_or_2=legacy)
    if primary_present: values["custom_phase_1_or_2"] = phase
    return SimpleNamespace(**values, meta=SimpleNamespace(has_field=lambda name: name in values))


def invoice(doctype="Sales Invoice"):
    return SimpleNamespace(doctype=doctype, company="SYNTHETIC-CO", customer="SYNTHETIC-CUSTOMER")


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("phase", ["Phase-1", " Phase-1 "])
def test_phase1_does_not_load_customer_or_resolve_address(policy, doctype, phase):
    policy.runtime.get_cached_doc.return_value = company(phase)
    assert policy.validate(invoice(doctype), "before_submit") is None
    policy.runtime.get_doc.assert_not_called()
    policy.resolver.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
def test_phase2_non_b2c_missing_address_still_blocks(policy, doctype):
    policy.runtime.get_cached_doc.return_value = company("Phase-2")
    policy.runtime.get_doc.return_value = SimpleNamespace(b2c=0)
    with pytest.raises(ValidationFailure, match="Customer address is mandatory"):
        policy.validate(invoice(doctype), "before_submit")
    policy.resolver.assert_called_once()


@pytest.mark.parametrize("phase", [None, "", "unknown"])
def test_unknown_phase_retains_existing_validation(policy, phase):
    policy.runtime.get_cached_doc.return_value = company(phase)
    policy.runtime.get_doc.return_value = SimpleNamespace(b2c=0)
    with pytest.raises(ValidationFailure): policy.validate(invoice())


def test_legacy_phase_field_still_resolves_phase1(policy):
    policy.runtime.get_cached_doc.return_value = company(None, primary_present=False, legacy="Phase-1")
    assert policy.validate(invoice()) is None
    policy.runtime.get_doc.assert_not_called()


def test_primary_phase2_wins_over_legacy_phase1(policy):
    policy.runtime.get_cached_doc.return_value = company("Phase-2", legacy="Phase-1")
    policy.runtime.get_doc.return_value = SimpleNamespace(b2c=0)
    with pytest.raises(ValidationFailure): policy.validate(invoice())


def test_disabled_company_never_loads_customer(policy):
    policy.runtime.get_cached_doc.return_value = company("Phase-2", enabled=0)
    assert policy.validate(invoice()) is None
    policy.runtime.get_doc.assert_not_called()


def test_phase2_b2c_keeps_existing_exemption(policy):
    policy.runtime.get_cached_doc.return_value = company("Phase-2")
    policy.runtime.get_doc.return_value = SimpleNamespace(b2c=1)
    assert policy.validate(invoice()) is None
    policy.resolver.assert_not_called()


def test_phase2_address_result_is_returned_without_mutation(policy):
    policy.runtime.get_cached_doc.return_value = company("Phase-2")
    policy.runtime.get_doc.return_value = SimpleNamespace(b2c=0)
    address = SimpleNamespace(name="SYNTHETIC-ADDRESS")
    policy.resolver.return_value = (address, "Customer.customer_primary_address")
    assert policy.validate(invoice()) == (address, "Customer.customer_primary_address")
