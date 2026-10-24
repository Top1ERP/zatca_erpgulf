"""Actual CSID boundaries with synthetic Final-auth changes; no real transport."""

import json
from types import SimpleNamespace

import pytest

from zatca_erpgulf.zatca_erpgulf import sign_invoice_first as client
from zatca_erpgulf.zatca_erpgulf.csid_preservation import (
    FINAL_AUTH_FIELDS, FINAL_AUTH_PRESERVATION_REQUIRED, FINAL_AUTH_STATE_UNCONFIRMED,
    CSIDPreservationError, require_no_saved_final_auth,
)
from zatca_erpgulf.zatca_erpgulf.credential_material import CredentialOwner, authorization_field_for_owner
from zatca_erpgulf.zatca_erpgulf.credential_write_access import ACCESS_DENIED
from zatca_erpgulf.zatca_erpgulf.operation_messages import CSIDProgress, CSID_PROGRESS_REVIEW, csid_local_failure
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_write_access import (
    boundary, saved_boundary, materials, enable, no_effects, FIELDS,
    ValidationError, PermissionDenied,
)


class PrivateValue:
    def __str__(self):
        raise AssertionError("Never stringify private saved auth")

    def __bool__(self):
        raise AssertionError("Never truth-test private saved auth")


class PrivateFailure(Exception):
    def __str__(self):
        raise AssertionError("Never stringify private read/cleanup errors")


def remember(b):
    b.before = {doc.name: {field: getattr(doc, field, None) for field in FIELDS}
                for doc in (b.company, b.device)}


def prepare(b, material, purpose):
    enable(b, material, purpose)
    remember(b)


def text(b, value):
    return b.catalog[value] if b.lang == "ar" else value


def no_transaction_or_generation(b):
    b.keygen.assert_not_called()
    b.frappe.db.commit.assert_not_called()
    b.frappe.db.rollback.assert_not_called()
    b.frappe.delete_doc.assert_not_called()


@pytest.mark.parametrize("field", FINAL_AUTH_FIELDS)
@pytest.mark.parametrize("value", ["TEST-ONLY-AUTH", " ", "********", "INVALID-OLD-AUTH"])
def test_either_populated_auth_spelling_is_protected_without_decoding(field, value):
    values = dict.fromkeys(FINAL_AUTH_FIELDS)
    values[field] = value
    with pytest.raises(CSIDPreservationError) as raised:
        require_no_saved_final_auth(values)
    assert raised.value.code == "CSID_FINAL_AUTH_PRESERVATION_REQUIRED"
    assert raised.value.message == FINAL_AUTH_PRESERVATION_REQUIRED
    assert raised.value.args == (raised.value.code,)


@pytest.mark.parametrize("purpose", ["compliance", "production"])
@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("lang", ["en", "ar"])
@pytest.mark.parametrize("field", FINAL_AUTH_FIELDS)
@pytest.mark.parametrize("value", ["TEST-ONLY-AUTH", " ", "********", "INVALID-OLD-AUTH"])
def test_saved_final_auth_stops_before_route_overlay_http_or_assignment(boundary, materials, purpose, source, lang, field, value):
    b = boundary
    prepare(b, materials, purpose)
    b.lang = lang
    setattr(getattr(b, source), field, value)
    remember(b)
    with pytest.raises(ValidationError) as raised:
        b.invoke(purpose, source)
    assert str(raised.value) == text(b, FINAL_AUTH_PRESERVATION_REQUIRED)
    assert raised.value.__context__ is None and raised.value.__cause__ is None
    assert b.visible == [{"value": str(raised.value), "title": text(b, "CSID Generation Failed")}]
    assert b.frappe.flags == {}
    no_effects(b)


@pytest.mark.parametrize("purpose", ["compliance", "production"])
@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("field", FINAL_AUTH_FIELDS)
@pytest.mark.parametrize("value", [False, 0, b"TEST", pytest.param(PrivateValue(), id="opaque")])
def test_unknown_final_auth_state_is_not_coerced_to_empty(boundary, materials, purpose, source, field, value):
    b = boundary
    prepare(b, materials, purpose)
    setattr(getattr(b, source), field, value)
    remember(b)
    with pytest.raises(ValidationError) as raised:
        b.invoke(purpose, source)
    assert str(raised.value) == FINAL_AUTH_STATE_UNCONFIRMED
    assert raised.value.__context__ is None and len(b.visible) == 1
    no_effects(b)


@pytest.mark.parametrize("purpose", ["compliance", "production"])
@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("flags", [{}, {"mute_messages": False}, {"mute_messages": True}])
def test_private_read_failure_restores_parent_state_and_one_static_notice(boundary, materials, monkeypatch, purpose, source, flags):
    b = boundary
    prepare(b, materials, purpose)
    b.frappe.flags = dict(flags)
    doc = getattr(b, source)
    read = doc.get
    def get(field, *args):
        if field in FINAL_AUTH_FIELDS:
            b.frappe.msgprint("PRIVATE-READ")
            raise PrivateFailure()
        return read(field, *args)
    monkeypatch.setattr(doc, "get", get)
    with pytest.raises(ValidationError) as raised:
        b.invoke(purpose, source)
    assert str(raised.value) == FINAL_AUTH_STATE_UNCONFIRMED
    assert raised.value.__context__ is None and b.frappe.flags == flags
    assert len(b.visible) == (0 if flags.get("mute_messages") else 1)
    no_effects(b)


@pytest.mark.parametrize("purpose", ["compliance", "production"])
@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("stop", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_read_cancellation_is_not_a_normal_failure_or_retry(boundary, materials, monkeypatch, purpose, source, stop):
    b = boundary
    prepare(b, materials, purpose)
    read = getattr(b, source).get
    def get(field, *args):
        if field in FINAL_AUTH_FIELDS:
            raise stop()
        return read(field, *args)
    monkeypatch.setattr(getattr(b, source), "get", get)
    with pytest.raises(stop):
        b.invoke(purpose, source)
    assert b.visible == [] and b.frappe.flags == {}
    no_effects(b)


@pytest.mark.parametrize("purpose", ["compliance", "production"])
@pytest.mark.parametrize("source", ["company", "device"])
def test_untrusted_force_flags_and_empty_fields_do_not_override_saved_final_auth(boundary, materials, purpose, source):
    b = boundary
    prepare(b, materials, purpose)
    doc = getattr(b, source)
    doc.custom_final_auth_csid = "TEST-ONLY-EXISTING"
    remember(b)
    identity = {"doctype": doc.doctype, "name": doc.name, **dict.fromkeys(FINAL_AUTH_FIELDS),
                "force": True, "allow_rotation": True, "flags": {"ignore_permissions": True}}
    with pytest.raises(ValidationError) as raised:
        b.invoke(purpose, source, identity)
    assert str(raised.value) == FINAL_AUTH_PRESERVATION_REQUIRED
    no_effects(b)


@pytest.mark.parametrize("purpose", ["compliance", "production"])
@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("engine", ["v15", "v16"])
def test_source_acl_denial_precedes_final_auth_disclosure(boundary, monkeypatch, purpose, source, engine):
    b = boundary  # Retain populated Final auth in this denied fixture.
    if engine == "v15":
        def permission(doctype, ptype, *, doc, user, raise_exception=True):
            assert raise_exception is False
            return False
    else:
        def permission(doctype, ptype, *, doc, user, print_logs=True):
            assert print_logs is False
            return False
    monkeypatch.setattr(client, "has_permission", permission)
    with pytest.raises(PermissionDenied) as raised:
        b.invoke(purpose, source)
    assert str(raised.value) == ACCESS_DENIED and raised.value.__context__ is None
    no_effects(b)


@pytest.mark.parametrize("purpose", ["compliance", "production"])
@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("portal", ["Sandbox", "Simulation", "Production"])
def test_environment_selection_cannot_override_saved_final_auth(boundary, materials, purpose, source, portal):
    b = boundary
    prepare(b, materials, purpose)
    doc = getattr(b, source)
    doc.custom_basic_auth_from_production = "TEST-ONLY-OTHER-ENVIRONMENT"
    remember(b)
    with pytest.raises(ValidationError) as raised:
        if purpose == "compliance":
            client.create_csid({"doctype": doc.doctype, "name": doc.name}, "TC", portal_type=portal)
        else:
            b.company.custom_select = portal
            b.invoke(purpose, source)
    assert str(raised.value) == FINAL_AUTH_PRESERVATION_REQUIRED
    no_effects(b)


def inject_change(b, monkeypatch, doc, purpose, stage, field, cleanup_failure=False):
    def change():
        setattr(doc, field, "TEST-ONLY-OBSERVED-FINAL-AUTH")
    if stage == "route":
        def route(*args, **kwargs):
            change()
            return SimpleNamespace(environment="Production", url="https://example.invalid/compliance")
        def final_route(*args, **kwargs):
            change()
            return "https://example.invalid/production/csids"
        monkeypatch.setattr(client, "get_company_api_route", route)
        monkeypatch.setattr(client, "get_compliance_api_url", final_route)
    if stage == "response":
        reply = b.post.return_value
        def post(*args, **kwargs):
            change()
            return reply
        b.post.side_effect = post
    def publish(event, *args, **kwargs):
        if event == "show_gif" and stage == "show":
            change()
        if event == "hide_gif" and cleanup_failure:
            b.frappe.msgprint("PRIVATE-CLEANUP")
            raise PrivateFailure()
    b.frappe.publish_realtime.side_effect = publish


@pytest.mark.parametrize("purpose", ["compliance", "production"])
@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("lang", ["en", "ar"])
@pytest.mark.parametrize("field", FINAL_AUTH_FIELDS)
@pytest.mark.parametrize("stage", ["route", "show", "response"])
def test_observed_final_auth_change_prevents_transport_or_response_assignment(boundary, materials, monkeypatch, purpose, source, lang, field, stage):
    b = boundary
    prepare(b, materials, purpose)
    b.lang = lang
    doc = getattr(b, source)
    inject_change(b, monkeypatch, doc, purpose, stage, field)
    with pytest.raises(ValidationError) as raised:
        b.invoke(purpose, source)
    expected = text(b, FINAL_AUTH_PRESERVATION_REQUIRED)
    if stage == "response":
        partial = csid_local_failure(purpose, CSIDProgress(True, True))
        expected = text(b, partial["message"]) + "<br>" + expected
    assert str(raised.value) == expected and raised.value.__context__ is None
    assert len(b.visible) == 1 and b.frappe.flags == {}
    assert b.post.call_count == (1 if stage == "response" else 0)
    assert [call.args[0] for call in b.frappe.publish_realtime.call_args_list] == ["show_gif", "hide_gif"]
    assert getattr(doc, field) == "TEST-ONLY-OBSERVED-FINAL-AUTH"
    assert all(getattr(doc, name, None) == value for name, value in b.before[doc.name].items() if name != field)
    doc.save.assert_not_called()
    no_transaction_or_generation(b)


@pytest.mark.parametrize("purpose", ["compliance", "production"])
@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("lang", ["en", "ar"])
def test_cleanup_failure_cannot_erase_a_late_preservation_notice(boundary, materials, monkeypatch, purpose, source, lang):
    b = boundary
    prepare(b, materials, purpose)
    b.lang = lang
    doc = getattr(b, source)
    inject_change(b, monkeypatch, doc, purpose, "response", FINAL_AUTH_FIELDS[0], cleanup_failure=True)
    with pytest.raises(ValidationError) as raised:
        b.invoke(purpose, source)
    partial = csid_local_failure(purpose, CSIDProgress(True, True))
    assert str(raised.value) == "<br>".join(text(b, key) for key in
        (partial["message"], FINAL_AUTH_PRESERVATION_REQUIRED, CSID_PROGRESS_REVIEW))
    assert len(b.visible) == 1 and "PRIVATE" not in str(raised.value)
    assert b.post.call_count == 1 and raised.value.__context__ is None
    doc.save.assert_not_called()
    no_transaction_or_generation(b)


@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("next_purpose", ["compliance", "production"])
@pytest.mark.parametrize("lang", ["en", "ar"])
def test_first_final_issuance_keeps_english_success_but_repeat_requires_review(boundary, materials, source, next_purpose, lang):
    b = boundary
    prepare(b, materials, "production")
    b.lang = lang
    doc = getattr(b, source)
    result = json.loads(b.invoke("production", source))
    assert result["status"] == "SUCCESS" and result["purpose"] == "production"
    assert result["message"].isascii()
    remember(b)
    b.visible.clear()  # Test observer only, not an application notification clear.
    with pytest.raises(ValidationError) as raised:
        b.invoke(next_purpose, source)
    assert str(raised.value) == text(b, FINAL_AUTH_PRESERVATION_REQUIRED)
    assert b.post.call_count == 1 and doc.save.call_count == 1
    assert {name: getattr(doc, name, None) for name in FIELDS} == b.before[doc.name]
    assert len(b.visible) == 1
    no_transaction_or_generation(b)


@pytest.mark.parametrize("purpose", ["compliance", "production"])
@pytest.mark.parametrize("linked", [0, 1])
def test_device_guard_does_not_rotate_or_inspect_linked_company_final_auth(boundary, materials, purpose, linked):
    b = boundary
    prepare(b, materials, purpose)
    b.device.custom__use_company_certificate__keys = linked
    b.company.custom_basic_auth_from_production = "TEST-ONLY-COMPANY-AUTH"
    remember(b)
    result = json.loads(b.invoke(purpose, "device"))
    assert result["status"] == "SUCCESS" and b.device.save.call_count == 1
    assert {name: getattr(b.company, name, None) for name in FIELDS} == b.before[b.company.name]
    b.company.save.assert_not_called()
    assert b.post.call_count == 1
    no_transaction_or_generation(b)


def test_auth_registry_and_arabic_display_keys_are_covered(boundary):
    for doctype in ("Company", "ZATCA Multiple Setting"):
        owner = CredentialOwner("A", doctype, "TEST-ONLY", "company" if doctype == "Company" else "multiple_setting", {})
        assert authorization_field_for_owner(owner, "production") in FINAL_AUTH_FIELDS
    for key in (FINAL_AUTH_PRESERVATION_REQUIRED, FINAL_AUTH_STATE_UNCONFIRMED):
        assert boundary.catalog[key] != key
