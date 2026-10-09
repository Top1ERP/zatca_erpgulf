"""Characterize legacy ICV identities before designing a continuity migration.

These are migration tripwires, not an endorsement of the legacy identity rules.
Do not change these expectations just to make a new resolver pass: an explicit
chain mapping and continuity test are required first. No counters are allocated.
"""

import hashlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import icv
from zatca_erpgulf.zatca_erpgulf.credential_material import CredentialOwner, authorization_for_owner


class Document(SimpleNamespace):
    def get(self, key, default=None):
        return getattr(self, key, default)


def fingerprint(kind, value):
    return kind + ":" + hashlib.sha256(value.encode()).hexdigest()[:24]


@pytest.fixture
def saved(monkeypatch):
    company = Document(doctype="Company", name="A", custom_basic_auth_from_production="P-TOKEN",
                       custom_basic_auth_from_csid="C-TOKEN")
    device = Document(doctype="ZATCA Multiple Setting", name="DEVICE", custom_final_auth_csid="DP-TOKEN",
                      custom_basic_auth_from_csid="DC-TOKEN", custom__use_company_certificate__keys=0,
                      custom_linked_doctype="A")
    invoice = Document(doctype="Sales Invoice", name="SI", company="A", custom_zatca_pos_name=None)

    def get_doc(doctype, name):
        return {("Company", "A"): company, ("ZATCA Multiple Setting", "DEVICE"): device}[doctype, name]

    fake = SimpleNamespace(get_doc=Mock(side_effect=get_doc))
    # There is intentionally no db or meta API. Any allocation/persistence is
    # an error rather than an accidentally successful mock call.
    monkeypatch.setattr(icv, "frappe", fake)
    return company, device, invoice


@pytest.mark.parametrize("environment, token", [("Production", "P-TOKEN"), ("Compliance", "C-TOKEN"),
                                               ("Debug", "C-TOKEN"), ("Simulation", "C-TOKEN"), ("Sandbox", "C-TOKEN")])
def test_legacy_company_selector_is_not_an_api_environment_resolver(saved, environment, token):
    _, _, invoice = saved
    assert icv._issuing_unit(invoice, environment) == fingerprint("company", token)


@pytest.mark.parametrize("environment", ["Production", "Compliance", "Debug", "Simulation", "Sandbox"])
def test_legacy_device_fingerprint_prefers_final_token_for_every_environment(saved, environment):
    _, _, invoice = saved
    invoice.custom_zatca_pos_name = "DEVICE"
    assert icv._issuing_unit(invoice, environment) == fingerprint("setting", "DP-TOKEN")


@pytest.mark.parametrize("mode", [0, 1, "0", "1"])
def test_linked_company_flag_does_not_change_legacy_device_identity(saved, mode):
    company, device, invoice = saved
    invoice.custom_zatca_pos_name = "DEVICE"
    device.custom__use_company_certificate__keys = mode
    company.custom_basic_auth_from_production = "ROTATED-COMPANY-TOKEN"
    assert icv._issuing_unit(invoice, "Production") == fingerprint("setting", "DP-TOKEN")


def test_equivalent_http_authorization_can_have_different_counter_identity(saved):
    company, _, invoice = saved
    identities, headers = [], []
    for value in ("P-TOKEN", "Basic P-TOKEN", " P-\nTOKEN "):
        company.custom_basic_auth_from_production = value
        identities.append(icv._issuing_unit(invoice, "Production"))
        owner = CredentialOwner("A", "Company", "A", "company", {"custom_basic_auth_from_production": value})
        headers.append(authorization_for_owner(owner, "production").header)
    assert len(set(headers)) == 1
    assert len(set(identities)) == 3


def test_credential_rotation_changes_legacy_identity(saved):
    company, _, invoice = saved
    previous = icv._issuing_unit(invoice, "Production")
    company.custom_basic_auth_from_production = "ROTATED"
    assert icv._issuing_unit(invoice, "Production") != previous


def test_missing_company_credential_falls_back_to_company_name(saved):
    company, _, invoice = saved
    company.custom_basic_auth_from_production = None
    assert icv._issuing_unit(invoice, "Production") == fingerprint("company", "A")


def test_missing_device_final_token_falls_back_to_compliance_then_name(saved):
    _, device, invoice = saved
    invoice.custom_zatca_pos_name = "DEVICE"
    device.custom_final_auth_csid = ""
    assert icv._issuing_unit(invoice, "Production") == fingerprint("setting", "DC-TOKEN")
    device.custom_basic_auth_from_csid = ""
    assert icv._issuing_unit(invoice, "Production") == fingerprint("setting", "DEVICE")


def test_equal_material_on_company_and_device_stays_in_distinct_legacy_namespaces(saved):
    company, device, invoice = saved
    device.custom_final_auth_csid = company.custom_basic_auth_from_production
    company_identity = icv._issuing_unit(invoice, "Production")
    invoice.custom_zatca_pos_name = "DEVICE"
    device_identity = icv._issuing_unit(invoice, "Production")
    assert company_identity != device_identity
    assert company_identity.split(":")[1] == device_identity.split(":")[1]


def test_short_legacy_keys_separate_purposes_and_company_names():
    assert icv._counter_key("A", "unit", "Production") == "A-unit-Production"
    assert icv._counter_key("A", "unit", "Compliance") != icv._counter_key("A", "unit", "Production")
    assert icv._counter_key("B", "unit", "Production") != icv._counter_key("A", "unit", "Production")


def test_legacy_slash_replacement_can_collapse_different_names():
    assert icv._counter_key("A/B", "unit", "Production") == icv._counter_key("A-B", "unit", "Production")


def test_legacy_length_truncation_can_drop_owner_and_purpose():
    company = "A" * 140
    assert icv._counter_key(company, "unit-one", "Production") == icv._counter_key(company, "unit-two", "Compliance")
