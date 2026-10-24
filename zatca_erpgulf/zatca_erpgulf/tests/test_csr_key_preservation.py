"""Synthetic shared-key preservation; no site, tenant credentials or HTTP.

Presence is a conservative stop, never a validity/activation/rotation claim.
All crypto material belongs to the imported ephemeral test-only fixtures.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import sign_invoice_first as client
from zatca_erpgulf.ksa_compliance.field_compat import get_alias_group
from zatca_erpgulf.zatca_erpgulf.csr_key_preservation import (
    PROTECTED_CREDENTIAL_FIELDS, KEY_PRESERVATION_REQUIRED,
    CREDENTIAL_STATE_UNCONFIRMED, CSRKeyPreservationError, require_unissued_key_target,
)
from zatca_erpgulf.zatca_erpgulf.operation_messages import CSRProgress, csr_local_failure
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_write_access import (
    boundary, saved_boundary, materials, enable, no_effects, FIELDS, ValidationError,
)


class PrivateValue:
    def __str__(self):
        raise AssertionError("Do not stringify private credential values")

    def __bool__(self):
        raise AssertionError("Do not truth-test private credential values")


class PrivateFailure(Exception):
    def __str__(self):
        raise AssertionError("Do not stringify private credential read errors")


def empty_projection():
    return dict.fromkeys(PROTECTED_CREDENTIAL_FIELDS)


def remember(b):
    b.before = {doc.name: {field: getattr(doc, field, None) for field in FIELDS}
                for doc in (b.company, b.device)}


def no_transport_or_transaction(b):
    b.post.assert_not_called()
    b.route.assert_not_called()
    b.frappe.publish_realtime.assert_not_called()
    b.frappe.db.commit.assert_not_called()
    b.frappe.db.rollback.assert_not_called()
    b.frappe.delete_doc.assert_not_called()


def display(b, text):
    return b.catalog[text] if b.lang == "ar" else text


@pytest.mark.parametrize("field", PROTECTED_CREDENTIAL_FIELDS)
@pytest.mark.parametrize("value", ["TEST-ONLY-OPAQUE", " ", "********", "INVALID-OR-EXPIRED-MATERIAL"])
def test_presence_never_parses_normalizes_or_discards_legacy_material(field, value):
    values = empty_projection()
    values[field] = value
    before = dict(values)
    with pytest.raises(CSRKeyPreservationError) as raised:
        require_unissued_key_target(values)
    assert raised.value.code == "CSR_KEY_PRESERVATION_REQUIRED"
    assert raised.value.message == KEY_PRESERVATION_REQUIRED
    assert values == before and raised.value.args == ("CSR_KEY_PRESERVATION_REQUIRED",)


@pytest.mark.parametrize("field", PROTECTED_CREDENTIAL_FIELDS)
@pytest.mark.parametrize("value", [False, True, 0, 1, b"", b"TEST", [], {}, pytest.param(PrivateValue(), id="private-object")])
def test_unknown_types_are_not_coerced_into_absent_or_valid_material(field, value):
    values = empty_projection()
    values[field] = value
    with pytest.raises(CSRKeyPreservationError) as raised:
        require_unissued_key_target(values)
    assert raised.value.code == "CSR_CREDENTIAL_STATE_UNCONFIRMED"
    assert raised.value.message == CREDENTIAL_STATE_UNCONFIRMED
    assert values[field] is value


@pytest.mark.parametrize("values", [None, [], {}, {"extra": None}, {name: None for name in PROTECTED_CREDENTIAL_FIELDS[:-1]}])
def test_projection_requires_exact_app_owned_shape(values):
    with pytest.raises(CSRKeyPreservationError) as raised:
        require_unissued_key_target(values)
    assert raised.value.code == "CSR_CREDENTIAL_STATE_UNCONFIRMED"


@pytest.mark.parametrize("value", [None, ""])
def test_only_exact_empty_text_or_none_is_absent(value):
    values = dict.fromkeys(PROTECTED_CREDENTIAL_FIELDS, value)
    assert require_unissued_key_target(values) is None


@pytest.mark.parametrize("mode", ["key", "csr"])
@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("lang", ["en", "ar"])
@pytest.mark.parametrize("field", PROTECTED_CREDENTIAL_FIELDS)
def test_saved_issued_material_blocks_both_real_entry_bodies_before_crypto_or_saves(boundary, materials, monkeypatch, mode, source, lang, field):
    b = boundary
    enable(b, materials, mode)
    b.lang = lang
    setattr(getattr(b, source), field, "TEST-ONLY-SAVED-MATERIAL")
    remember(b)
    loader = Mock(side_effect=AssertionError("Preservation must not decode/parse private material"))
    monkeypatch.setattr(client.serialization, "load_pem_private_key", loader)
    with pytest.raises(ValidationError) as raised:
        b.invoke(mode, source)
    assert str(raised.value) == display(b, KEY_PRESERVATION_REQUIRED)
    assert raised.value.__context__ is None and raised.value.__cause__ is None
    assert b.visible == [{"value": str(raised.value)}]
    assert b.frappe.flags == {}
    loader.assert_not_called()
    no_effects(b)


@pytest.mark.parametrize("mode", ["key", "csr"])
@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("field", PROTECTED_CREDENTIAL_FIELDS)
def test_unknown_saved_state_fails_closed_without_secret_coercion(boundary, materials, mode, source, field):
    b = boundary
    enable(b, materials, mode)
    setattr(getattr(b, source), field, PrivateValue())
    remember(b)
    with pytest.raises(ValidationError) as raised:
        b.invoke(mode, source)
    assert str(raised.value) == CREDENTIAL_STATE_UNCONFIRMED
    assert raised.value.__context__ is None and len(b.visible) == 1
    no_effects(b)


@pytest.mark.parametrize("mode", ["key", "csr"])
@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("flags", [{}, {"mute_messages": False}, {"mute_messages": True}])
def test_read_faults_restore_parent_state_without_diagnostics_or_cleanup(boundary, materials, monkeypatch, mode, source, flags):
    b = boundary
    enable(b, materials, mode)
    b.frappe.flags = dict(flags)
    doc = getattr(b, source)
    read = doc.get
    def get(field, *args):
        if field in PROTECTED_CREDENTIAL_FIELDS:
            b.frappe.msgprint("PRIVATE-READ-DIAGNOSTIC")
            raise PrivateFailure()
        return read(field, *args)
    monkeypatch.setattr(doc, "get", get)
    with pytest.raises(ValidationError) as raised:
        b.invoke(mode, source)
    assert str(raised.value) == CREDENTIAL_STATE_UNCONFIRMED
    assert raised.value.__context__ is None and b.frappe.flags == flags
    assert len(b.visible) == (0 if flags.get("mute_messages") else 1)
    b.keygen.assert_not_called()
    doc.save.assert_not_called()
    no_transport_or_transaction(b)


@pytest.mark.parametrize("mode", ["key", "csr"])
@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("stop", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_read_cancellation_propagates_without_a_new_popup(boundary, materials, monkeypatch, mode, source, stop):
    b = boundary
    enable(b, materials, mode)
    b.frappe.flags = {"mute_messages": False}
    doc = getattr(b, source)
    read = doc.get
    def get(field, *args):
        if field in PROTECTED_CREDENTIAL_FIELDS:
            raise stop()
        return read(field, *args)
    monkeypatch.setattr(doc, "get", get)
    with pytest.raises(stop):
        b.invoke(mode, source)
    assert b.frappe.flags == {"mute_messages": False} and b.visible == []
    b.keygen.assert_not_called()
    doc.save.assert_not_called()
    no_transport_or_transaction(b)


@pytest.mark.parametrize("mode", ["key", "csr"])
@pytest.mark.parametrize("source", ["company", "device"])
def test_caller_empty_fields_and_force_flags_cannot_override_saved_material(boundary, materials, mode, source):
    b = boundary
    enable(b, materials, mode)
    doc = getattr(b, source)
    doc.custom_final_auth_csid = "TEST-ONLY-SAVED-AUTH"
    remember(b)
    identity = {"doctype": doc.doctype, "name": doc.name,
                **empty_projection(), "force": True, "allow_rotation": True,
                "flags": {"ignore_permissions": True}, "custom_private_key": None}
    with pytest.raises(ValidationError) as raised:
        b.invoke(mode, source, identity)
    assert str(raised.value) == KEY_PRESERVATION_REQUIRED
    no_effects(b)


@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("portal", ["Sandbox", "Simulation", "Production"])
def test_environment_switch_does_not_authorize_replacing_a_shared_key(boundary, materials, source, portal):
    b = boundary
    enable(b, materials, "csr")
    doc = getattr(b, source)
    doc.custom_certficate = "TEST-ONLY-OTHER-ENVIRONMENT-CERT"
    remember(b)
    with pytest.raises(ValidationError) as raised:
        client.create_csr({"doctype": doc.doctype, "name": doc.name}, portal, "TC")
    assert str(raised.value) == KEY_PRESERVATION_REQUIRED
    no_effects(b)


@pytest.mark.parametrize("mode", ["key", "csr"])
@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("field", PROTECTED_CREDENTIAL_FIELDS)
@pytest.mark.parametrize("stage", ["generation", "serialization"])
def test_changed_loaded_record_after_crypto_stops_before_key_assignment(boundary, materials, mode, source, field, stage):
    b = boundary
    enable(b, materials, mode)
    doc = getattr(b, source)
    before_key, before_csr = doc.custom_private_key, doc.custom_csr_data
    key = b.keygen.return_value
    if stage == "generation":
        def generate(*args, **kwargs):
            setattr(doc, field, "TEST-ONLY-OBSERVED-ISSUANCE")
            return key
        b.keygen.side_effect = generate
    else:
        def private_bytes(**kwargs):
            setattr(doc, field, "TEST-ONLY-OBSERVED-ISSUANCE")
            return materials[0].pem.encode()
        b.keygen.return_value = SimpleNamespace(private_bytes=private_bytes)
    with pytest.raises(ValidationError) as raised:
        b.invoke(mode, source)
    assert str(raised.value) == KEY_PRESERVATION_REQUIRED and raised.value.__context__ is None
    assert doc.custom_private_key == before_key and doc.custom_csr_data == before_csr
    assert getattr(doc, field) == "TEST-ONLY-OBSERVED-ISSUANCE"  # No speculative undo.
    assert b.keygen.call_count == 1 and len(b.visible) == 1
    doc.save.assert_not_called()
    no_transport_or_transaction(b)


@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("lang", ["en", "ar"])
@pytest.mark.parametrize("field", PROTECTED_CREDENTIAL_FIELDS)
def test_material_appearing_after_key_save_retains_one_partial_review_not_csr_overwrite(boundary, materials, source, lang, field):
    b = boundary
    enable(b, materials, "csr")
    b.lang = lang
    doc = getattr(b, source)
    before_key, before_csr = doc.custom_private_key, doc.custom_csr_data
    doc.save.side_effect = lambda: setattr(doc, field, "TEST-ONLY-LATE-MATERIAL")
    with pytest.raises(ValidationError) as raised:
        b.invoke("csr", source)
    partial = csr_local_failure("csr", CSRProgress(True, True))
    assert str(raised.value) == display(b, partial["message"]) + "\n\n" + display(b, KEY_PRESERVATION_REQUIRED)
    assert raised.value.__context__ is None and len(b.visible) == 1
    assert doc.custom_private_key != before_key and doc.custom_csr_data == before_csr
    assert getattr(doc, field) == "TEST-ONLY-LATE-MATERIAL"
    assert b.keygen.call_count == 1 and doc.save.call_count == 1
    assert doc.save.call_args.kwargs == {}
    no_transport_or_transaction(b)


@pytest.mark.parametrize("source", ["company", "device"])
def test_second_source_load_is_checked_before_generation(boundary, materials, source):
    b = boundary
    enable(b, materials, "csr")
    doc = getattr(b, source)
    read = b.frappe.get_doc.side_effect
    seen = 0
    def load(doctype, name):
        nonlocal seen
        result = read(doctype, name)
        if result is doc:
            seen += 1
            if seen == 2:
                doc.custom_compliance_request_id_ = "TEST-ONLY-NEW-REFERENCE"
        return result
    b.frappe.get_doc.side_effect = load
    with pytest.raises(ValidationError) as raised:
        b.invoke("csr", source)
    assert str(raised.value) == KEY_PRESERVATION_REQUIRED and seen == 2
    b.keygen.assert_not_called()
    doc.save.assert_not_called()
    no_transport_or_transaction(b)


@pytest.mark.parametrize("linked", [0, 1])
def test_device_guard_does_not_write_or_select_its_company_credentials(boundary, materials, linked):
    b = boundary
    enable(b, materials, "csr")
    b.device.custom__use_company_certificate__keys = linked
    b.company.custom_certificate = "TEST-ONLY-COMPANY-CERT"
    b.company.custom_basic_auth_from_production = "TEST-ONLY-COMPANY-AUTH"
    before = {field: getattr(b.company, field, None) for field in FIELDS}
    result = b.invoke("csr", "device")
    assert result == b.device.custom_csr_data
    assert {field: getattr(b.company, field, None) for field in FIELDS} == before
    b.company.save.assert_not_called()
    assert b.device.save.call_count == 2 and b.visible == []
    no_transport_or_transaction(b)


@pytest.mark.parametrize("source", ["company", "device"])
def test_issued_material_stops_before_reading_or_parsing_invalid_csr_config(boundary, monkeypatch, source):
    b = boundary  # This fixture deliberately retains issued material.
    getattr(b, source).custom_csr_config = "MALFORMED-TEST-CONFIG"
    parser = Mock(side_effect=AssertionError("Issued target must stop before CSR parsing"))
    monkeypatch.setattr(client, "parse_csr_config", parser)
    with pytest.raises(ValidationError) as raised:
        b.invoke("csr", source)
    assert str(raised.value) == KEY_PRESERVATION_REQUIRED
    parser.assert_not_called()
    no_effects(b)


def test_static_messages_have_actual_arabic_translations(boundary):
    for text in (KEY_PRESERVATION_REQUIRED, CREDENTIAL_STATE_UNCONFIRMED):
        assert boundary.catalog[text] != text


def test_registered_certificate_aliases_cannot_drift_outside_the_guard():
    assert set(get_alias_group("multiple_setting_certificate")["aliases"]) <= set(PROTECTED_CREDENTIAL_FIELDS)
