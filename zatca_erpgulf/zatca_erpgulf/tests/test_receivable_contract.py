"""Pinned controller inventory and the conversion prefix for suffix inputs."""
import ast
from types import SimpleNamespace
import pytest

from zatca_erpgulf.zatca_erpgulf.tests.test_calculated_totals import controller,controller_text
from zatca_erpgulf.zatca_erpgulf.tests.test_field_rounding import framework
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16


@pytest.mark.parametrize("name",["calculate_outstanding_amount","calculate_write_off_amount","_set_in_company_currency","is_internal_invoice"])
def test_primary_inventory_preserves_both_versions_and_explicit_stage_gates(name):
    assert ast.dump(ast.parse(controller_text(name,15)))==ast.dump(ast.parse(controller_text(name,16)))


@pytest.mark.parametrize("major",[15,16])
@pytest.mark.parametrize("amount,expected",[(2.675,8.4195),(-2.675,-8.3881),(None,0.0)])
def test_company_conversion_rounds_source_before_fx_and_retains_original_amount(monkeypatch,upstream16,major,amount,expected):
    probe=framework(major,upstream16,monkeypatch,setting=None)
    traces=[]
    doc=SimpleNamespace(write_off_amount=amount,conversion_rate=3.1415926)
    doc.get=lambda name:getattr(doc,name,None)
    doc.set=lambda name,value:setattr(doc,name,value)
    def precision(name):
        traces.append(name)
        return 2 if name=="write_off_amount" else 4
    doc.precision=precision
    controller("_set_in_company_currency",major,{"flt":probe.flt})(SimpleNamespace(doc=doc),doc,["write_off_amount"])
    assert doc.write_off_amount is amount
    assert doc.base_write_off_amount==expected
    assert traces==["write_off_amount","base_write_off_amount"]
    assert probe.runtime.get_system_settings.call_count==(1 if amount is None else 2)
