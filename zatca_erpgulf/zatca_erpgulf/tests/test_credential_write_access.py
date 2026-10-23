"""Actual credential writers with synthetic ACL/keys/saves/HTTP, never a site."""

import base64
import csv
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from zatca_erpgulf.zatca_erpgulf import sign_invoice_first as client
from zatca_erpgulf.zatca_erpgulf.credential_write_access import ACCESS_DENIED, ACCESS_UNCONFIRMED
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import (
    boundary as saved_boundary, materials, ValidationError,
)


class PermissionDenied(Exception):
    pass


MODES = ("key", "csr", "compliance", "production")
FIELDS = ("custom_private_key", "custom_csr_data", "custom_certificate", "custom_certficate",
          "custom_basic_auth_from_csid", "custom_basic_auth_from_production", "custom_final_auth_csid")


@pytest.fixture
def boundary(saved_boundary, monkeypatch):
    b = saved_boundary
    b.lang = "en"
    with (Path(__file__).parents[2] / "translations/ar.csv").open(encoding="utf-8", newline="") as source:
        b.catalog = dict(csv.reader(source))
    for name in ("create_csr", "create_csid", "production_csid"):
        monkeypatch.setattr(client, name, inspect.unwrap(getattr(client, name)))
    monkeypatch.setattr(client, "_", lambda text: b.catalog.get(text, text) if b.lang == "ar" else text)
    b.visible = []
    b.frappe.PermissionError = PermissionDenied
    def msgprint(value, **kwargs):
        if not b.frappe.flags.get("mute_messages"):
            b.visible.append({"value": value, **kwargs})
    def throw(message, exc=ValidationError, **kwargs):
        msgprint(message, **kwargs)
        raise exc(message)
    b.frappe.msgprint, b.frappe.throw = msgprint, throw
    b.frappe.publish_realtime = Mock()
    b.frappe.db.rollback = Mock()
    b.frappe.delete_doc = Mock()
    b.acl = []
    def permission(doctype, ptype, *, doc, user, raise_exception=True):
        b.acl.append((doctype, ptype, doc, user, raise_exception))
        assert raise_exception is False
        return True
    monkeypatch.setattr(client, "has_permission", permission)
    b.keygen = Mock(side_effect=AssertionError("Test key generation must be explicitly configured"))
    monkeypatch.setattr(client.ec, "generate_private_key", b.keygen)
    b.post = Mock(side_effect=AssertionError("Test HTTP response must be explicitly configured"))
    monkeypatch.setattr(client.requests, "post", b.post)
    b.route = Mock(return_value=SimpleNamespace(environment="Production", url="https://example.invalid/compliance"))
    monkeypatch.setattr(client, "get_company_api_route", b.route)
    monkeypatch.setattr(client, "get_compliance_api_url", lambda *args, **kwargs: "https://example.invalid/production/csids")
    for doc in (b.company, b.device):
        doc.custom_csr_data = "SAVED-CSR"
        doc.custom_otp = "SAVED-OTP"
        doc.custom_compliance_request_id_ = "SAVED-REQUEST"
        doc.custom_csr_config = (
            "csr.common.name=TEST ONLY\ncsr.serial.number=TEST-SERIAL\n"
            "csr.organization.identifier=TEST-VAT\ncsr.organization.unit.name=TEST UNIT\n"
            "csr.organization.name=TEST ORGANIZATION\ncsr.country.name=SA\ncsr.invoice.type=1100\n"
            "csr.location.address=TEST CITY\ncsr.industry.business.category=TEST CATEGORY")
    b.before = {doc.name: {field: getattr(doc, field, None) for field in FIELDS} for doc in (b.company, b.device)}
    b.invoke = lambda mode, source="company", identity=None, abbr="TC": invoke(b, mode, source, identity, abbr)
    return b


def invoke(b, mode, source, identity, abbr):
    doc = getattr(b, source)
    identity = {"doctype": doc.doctype, "name": doc.name} if identity is None else identity
    if mode == "key":
        return client.create_private_keys(abbr, identity)
    if mode == "csr":
        return client.create_csr(identity, "Production", abbr)
    if mode == "compliance":
        return client.create_csid(identity, abbr)
    return client.production_csid(identity, abbr)


def enable(b, materials, mode):
    if mode in ("key", "csr"):
        b.keygen.side_effect = None
        b.keygen.return_value = serialization.load_pem_private_key(materials[0].pem.encode(), password=None)
    else:
        data = {"binarySecurityToken": base64.b64encode(materials[0].text.encode()).decode(),
                "secret": "TEST-SECRET", "requestID": "TEST-REQUEST"}
        b.post.side_effect = None
        b.post.return_value = SimpleNamespace(status_code=200, text=json.dumps(data), json=lambda: data)


def no_effects(b):
    b.keygen.assert_not_called()
    b.post.assert_not_called()
    b.route.assert_not_called()
    b.frappe.publish_realtime.assert_not_called()
    for doc in (b.company, b.device):
        doc.save.assert_not_called()
        assert {field: getattr(doc, field, None) for field in FIELDS} == b.before[doc.name]
    b.frappe.db.commit.assert_not_called()
    b.frappe.db.rollback.assert_not_called()
    b.frappe.delete_doc.assert_not_called()


SCOPES = [(source, doctype, operation) for source, doctype, operation in (
    ("company", "Company", "read"), ("company", "Company", "write"),
    ("device", "ZATCA Multiple Setting", "read"), ("device", "ZATCA Multiple Setting", "write"),
    ("device", "Company", "read"))]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("source,doctype,operation", SCOPES)
@pytest.mark.parametrize("allowed", [False, None, 1, "yes"])
def test_public_and_private_writers_reject_missing_row_permissions_before_any_effect(boundary, monkeypatch, mode, source, doctype, operation, allowed):
    b = boundary
    def permission(kind, ptype, *, doc, user, raise_exception=True):
        assert raise_exception is False
        return allowed if (kind, ptype) == (doctype, operation) else True
    monkeypatch.setattr(client, "has_permission", permission)
    with pytest.raises(PermissionDenied) as raised:
        b.invoke(mode, source)
    assert str(raised.value) == ACCESS_DENIED
    assert raised.value.__context__ is None and len(b.visible) == 1
    assert b.frappe.flags == {}
    no_effects(b)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("engine", ["v15", "v16"])
def test_authorized_exact_sources_use_normal_saves_and_preserve_return_contracts(boundary, materials, monkeypatch, mode, source, engine):
    b = boundary
    doc = getattr(b, source)
    if engine == "v16":
        def permission(doctype, ptype, *, doc, user, print_logs=True):
            b.acl.append((doctype, ptype, doc, user, print_logs))
            return True
        monkeypatch.setattr(client, "has_permission", permission)
    enable(b, materials, mode)
    forged = {"doctype": doc.doctype, "name": doc.name, "custom_private_key": "FORGED-KEY",
              "custom_csr_data": "FORGED-CSR", "custom_basic_auth_from_csid": "FORGED-AUTH",
              "custom_linked_doctype": "FORGED-COMPANY", "flags": {"ignore_permissions": True}}
    result = b.invoke(mode, source, json.dumps(forged))
    assert all(call.kwargs == {} for call in doc.save.call_args_list)
    assert doc.save.call_count == (2 if mode == "csr" else 1)
    assert all(row[3] == b.frappe.session.user and row[4] is False for row in b.acl)
    assert (doc.doctype, "write") in [(row[0], row[1]) for row in b.acl]
    if source == "device":
        assert ("Company", "write") not in [(row[0], row[1]) for row in b.acl]
        b.company.save.assert_not_called()
    else:
        b.device.save.assert_not_called()
    b.frappe.db.get_value.assert_not_called()
    b.frappe.db.commit.assert_not_called()
    if mode == "csr":
        assert isinstance(result, str) and result == doc.custom_csr_data
        csr = x509.load_pem_x509_csr(base64.b64decode(result))
        assert "TEST ONLY" in csr.subject.rfc4514_string()
    elif mode == "key":
        assert isinstance(result, bytes) and result.decode() == doc.custom_private_key
    else:
        assert json.loads(result)["purpose"] == mode and "TEST-SECRET" not in result
        kwargs = b.post.call_args.kwargs
        assert "FORGED" not in repr(kwargs)
        if mode == "compliance":
            assert json.loads(kwargs["data"]) == {"csr": "SAVED-CSR"}
    assert b.keygen.call_count == (1 if mode in ("key", "csr") else 0)
    assert b.post.call_count == (1 if mode in ("compliance", "production") else 0)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("source", ["company", "device"])
def test_dict_subclass_identity_remains_compatible_without_trusting_its_flags(boundary, materials, mode, source):
    # Frappe-style dict subclasses are valid internal callers; never use them
    # to construct a credential-bearing Document or to bypass row permissions.
    class Identity(dict):
        pass
    b = boundary
    doc = getattr(b, source)
    enable(b, materials, mode)
    b.invoke(mode, source, Identity(doctype=doc.doctype, name=doc.name, flags={"ignore_permissions": True}))
    assert all(call.kwargs == {} for call in doc.save.call_args_list)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("identity", [{}, {"doctype": "User", "name": "Administrator"}, {"doctype": "Sales Invoice", "name": "SI"},
    {"doctype": "Company", "name": ""}, {"doctype": "Company", "name": " A"}, "PRIVATE invalid JSON", [], "x" * 16385])
def test_invalid_identity_cannot_reach_saved_rows_or_effects(boundary, mode, identity):
    with pytest.raises(ValidationError):
        boundary.invoke(mode, identity=identity)
    boundary.frappe.get_doc.assert_not_called()
    no_effects(boundary)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("source", ["company", "device"])
def test_company_abbreviation_cannot_redirect_a_permitted_target(boundary, mode, source):
    with pytest.raises(ValidationError):
        boundary.invoke(mode, source, abbr="OTHER")
    boundary.frappe.db.get_value.assert_not_called()
    no_effects(boundary)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("scope", ["company-target", "device-target", "device-company"])
def test_loader_returned_identity_cannot_redirect_the_write(boundary, mode, scope):
    b = boundary
    read = b.frappe.get_doc.side_effect
    def redirected(doctype, name):
        if scope == "company-target" and doctype == "Company":
            return b.linked
        if scope == "device-target" and doctype == "ZATCA Multiple Setting":
            return b.company
        if scope == "device-company" and doctype == "Company":
            return b.linked
        return read(doctype, name)
    b.frappe.get_doc.side_effect = redirected
    with pytest.raises(ValidationError):
        b.invoke(mode, "company" if scope == "company-target" else "device")
    no_effects(b)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("link", [None, "", {}, "MISSING COMPANY"])
def test_device_cannot_fall_back_when_linked_company_is_missing(boundary, mode, link):
    boundary.device.custom_linked_doctype = link
    with pytest.raises(ValidationError):
        boundary.invoke(mode, "device")
    no_effects(boundary)


@pytest.mark.parametrize("mode", MODES)
def test_unknown_acl_signature_has_no_permission_fallback(boundary, monkeypatch, mode):
    engine = Mock(return_value=True)
    monkeypatch.setattr(client, "has_permission", engine)
    with pytest.raises(ValidationError):
        boundary.invoke(mode)
    engine.assert_not_called()
    no_effects(boundary)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("user", [None, "", "Guest"])
def test_guest_or_missing_actor_is_rejected_before_document_loading(boundary, mode, user):
    boundary.frappe.session.user = user
    with pytest.raises(PermissionDenied):
        boundary.invoke(mode)
    boundary.frappe.get_doc.assert_not_called()
    no_effects(boundary)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("lang", ["en", "ar"])
def test_permission_errors_are_translated_only_for_display(boundary, monkeypatch, mode, lang):
    b = boundary
    b.lang = lang
    def permission(doctype, ptype, *, doc, user, raise_exception=True):
        return False
    monkeypatch.setattr(client, "has_permission", permission)
    with pytest.raises(PermissionDenied) as raised:
        b.invoke(mode)
    assert str(raised.value) == (b.catalog[ACCESS_DENIED] if lang == "ar" else ACCESS_DENIED)
    assert b.visible[0]["value"] == str(raised.value)
    no_effects(b)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("flags", [{}, {"mute_messages": False}, {"mute_messages": True}, {"mute_messages": "parent"}])
def test_unknown_acl_failures_are_not_stringified_and_restore_parent_flags(boundary, monkeypatch, mode, flags):
    b = boundary
    b.frappe.flags = dict(flags)
    class PrivateError(Exception):
        def __str__(self):
            raise AssertionError("Never stringify private permission error")
    def permission(doctype, ptype, *, doc, user, raise_exception=True):
        b.frappe.msgprint("PRIVATE-CHILD")
        raise PrivateError()
    monkeypatch.setattr(client, "has_permission", permission)
    with pytest.raises(ValidationError) as raised:
        b.invoke(mode)
    assert raised.value.__context__ is None and "PRIVATE" not in str(raised.value)
    assert b.frappe.flags == flags
    assert len(b.visible) == (0 if flags.get("mute_messages") else 1)
    no_effects(b)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("stop", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_cancellation_restores_child_state_without_effects(boundary, monkeypatch, mode, stop):
    def permission(doctype, ptype, *, doc, user, raise_exception=True):
        raise stop("PRIVATE-STOP")
    monkeypatch.setattr(client, "has_permission", permission)
    with pytest.raises(stop):
        boundary.invoke(mode)
    assert boundary.frappe.flags == {} and boundary.visible == []
    no_effects(boundary)


@pytest.mark.parametrize("source", ["company", "device"])
def test_csr_rechecks_access_after_key_save_without_generating_another_key(boundary, materials, monkeypatch, source):
    b = boundary
    doc = getattr(b, source)
    enable(b, materials, "csr")
    previous = doc.custom_private_key
    revoked = False
    def save():
        nonlocal revoked
        revoked = True
    doc.save.side_effect = save
    def permission(doctype, ptype, *, doc, user, raise_exception=True):
        return not (revoked and ptype == "write")
    monkeypatch.setattr(client, "has_permission", permission)
    with pytest.raises(PermissionDenied):
        b.invoke("csr", source)
    assert doc.custom_private_key != previous
    assert doc.custom_csr_data == "SAVED-CSR"
    assert doc.save.call_count == 1 and doc.save.call_args.kwargs == {}
    assert b.keygen.call_count == 1 and len(b.visible) == 1
    b.post.assert_not_called()
    b.frappe.db.rollback.assert_not_called()
    b.frappe.db.commit.assert_not_called()


@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("mode", ["compliance", "production"])
def test_ordinary_save_permission_failure_after_reply_is_uncertain_not_a_retry(boundary, materials, source, mode):
    b = boundary
    doc = getattr(b, source)
    enable(b, materials, mode)
    def denied_save(**kwargs):
        assert kwargs == {}
        b.frappe.throw("PRIVATE-SAVE-PERMISSION", exc=PermissionDenied)
    doc.save.side_effect = denied_save
    with pytest.raises(ValidationError) as raised:
        b.invoke(mode, source)
    assert "CSID storage could not be confirmed" in str(raised.value)
    assert "PRIVATE" not in str(raised.value) + repr(b.visible)
    assert raised.value.__context__ is None and len(b.visible) == 1
    assert b.post.call_count == 1 and doc.save.call_count == 1
    b.keygen.assert_not_called()
    b.frappe.db.commit.assert_not_called()
    b.frappe.db.rollback.assert_not_called()


def test_access_display_keys_have_actual_arabic_translations(boundary):
    assert boundary.catalog[ACCESS_DENIED] != ACCESS_DENIED
    assert boundary.catalog[ACCESS_UNCONFIRMED] != ACCESS_UNCONFIRMED
