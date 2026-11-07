"""Ordered same-owner substages preserve the existing rounding contracts."""

import pickle

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_rounding_stage as stage
from zatca_erpgulf.zatca_erpgulf.tests.test_rounding_stage import scenario, capture
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import defaults_operator, operator, untouched


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("names", [("grand_total",), ("net_total",), ("grand_total", "net_total")])
def test_project_stage_keeps_exact_numeric_method_owner_and_proofs(defaults_operator, monkeypatch, major, names):
    case = scenario(defaults_operator, monkeypatch)
    source = capture(case, major)
    selected = stage.project_stage(source, names)
    assert selected.numeric == source.numeric and selected.method == source.method
    assert selected.owner_document == source.owner_document == id(case.invoice)
    assert selected.targets == tuple(target for target in source.targets if target[2] in names)
    assert selected.fields == tuple(proof for proof in source.fields if proof.target[2] in names)
    assert case.factory.call_count == 1
    untouched(defaults_operator, case)
    with pytest.raises(TypeError): pickle.dumps(selected)


@pytest.mark.parametrize("names", [(), ("net_total", "grand_total"), ("grand_total", "grand_total"),
    ("unknown",), ["grand_total"], (True,)])
def test_project_stage_refuses_missing_reordered_or_untyped_subsets(defaults_operator, monkeypatch, names):
    source = capture(scenario(defaults_operator, monkeypatch))
    with pytest.raises(stage.RoundingStageError) as caught: stage.project_stage(source, names)
    assert str(caught.value) == "rounding_stage_projection" and caught.value.__context__ is None


def test_projection_cannot_erase_a_skip_declaration(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    source = capture(case, 16, skips=("net_total",))
    with pytest.raises(stage.RoundingStageError): stage.project_stage(source, ("grand_total",))


def test_projection_revalidates_mutated_precision_proof(defaults_operator, monkeypatch):
    source = capture(scenario(defaults_operator, monkeypatch))
    proof = source.fields[0]
    object.__setattr__(proof, "target", ("header", "OTHER", "grand_total"))
    with pytest.raises(stage.RoundingStageError): stage.project_stage(source, ("grand_total",))
