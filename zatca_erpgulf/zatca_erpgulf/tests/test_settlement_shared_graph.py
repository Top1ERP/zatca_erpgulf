"""One authorized original object for consumed POS and rounding side reads."""

from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf.calculation_numeric_access import NumericAcquisition
from zatca_erpgulf.zatca_erpgulf.calculation_pos_profile_access import PosProfileAcquisition, PosProfileRequest
from zatca_erpgulf.zatca_erpgulf.calculation_invoice_rounding_access import InvoiceRoundingAcquisition
from zatca_erpgulf.zatca_erpgulf.calculation_child_access import CalculationChildAccessError
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_pos_profile_access import scenario
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import defaults_operator, operator, PermissionDenied


def numeric_root(case, policy, actor):
    for name, meta in case.normal_metas.items():
        meta.name = name
        meta.has_field = lambda field, meta=meta: meta.get_field(field) is not None
    return NumericAcquisition(policy, actor, case.invoice.name, case.invoice.doctype)


@pytest.mark.parametrize("kind", ["limit", "default"])
def test_shared_graph_keeps_the_exact_original_owner_and_membership(defaults_operator, monkeypatch, kind):
    case = scenario(defaults_operator, monkeypatch, kind=kind)
    policy = case.service._policy
    actor = policy._actor()
    root = numeric_root(case, policy, actor)
    pos = PosProfileAcquisition(policy, actor, case.invoice.name, case.invoice.doctype,
        PosProfileRequest(kind), case.pos_metadata, _shared_graph=root)
    rounding_metadata = Mock()
    controls = InvoiceRoundingAcquisition(policy, actor, case.invoice.name, case.invoice.doctype,
        rounding_metadata, _shared_graph=root)
    assert pos.document is controls.document is root.document is case.invoice
    assert pos._tables is controls._tables is root._tables
    assert pos.tables is controls.tables is root.tables
    case.factory.assert_not_called()
    case.pos_metadata.assert_not_called()
    rounding_metadata.assert_not_called()


@pytest.mark.parametrize("fault", ["policy", "name", "doctype", "type"])
def test_graph_cannot_be_rebound_to_another_owner_or_policy(defaults_operator, monkeypatch, fault):
    case = scenario(defaults_operator, monkeypatch)
    policy = case.service._policy;actor = policy._actor()
    root = numeric_root(case, policy, actor)
    args = dict(policy=policy, actor=actor, invoice_name=case.invoice.name, doctype=case.invoice.doctype,
        request=PosProfileRequest("default"), metadata_reader=case.pos_metadata, _shared_graph=root)
    if fault == "policy": args["policy"] = object()
    elif fault == "name": args["invoice_name"] = "OTHER"
    elif fault == "doctype": args["doctype"] = "POS Invoice"
    else: args["_shared_graph"] = object()
    with pytest.raises(CalculationChildAccessError): PosProfileAcquisition(**args)
    case.factory.assert_not_called()
    case.pos_metadata.assert_not_called()


@pytest.mark.parametrize("consumer", ["pos", "rounding"])
def test_shared_graph_cannot_borrow_a_different_actors_field_levels(defaults_operator, monkeypatch, consumer):
    case = scenario(defaults_operator, monkeypatch, kind="limit")
    policy = case.service._policy;actor = policy._actor()
    root = numeric_root(case, policy, actor)
    wrong_actor = actor[0], "other-manager@example.test"
    with pytest.raises(PermissionDenied):
        if consumer == "pos":
            PosProfileAcquisition(policy, wrong_actor, case.invoice.name, case.invoice.doctype,
                PosProfileRequest("limit"), case.pos_metadata, _shared_graph=root)
        else:
            InvoiceRoundingAcquisition(policy, wrong_actor, case.invoice.name, case.invoice.doctype,
                Mock(), _shared_graph=root)
    case.factory.assert_not_called()
    case.pos_metadata.assert_not_called()
