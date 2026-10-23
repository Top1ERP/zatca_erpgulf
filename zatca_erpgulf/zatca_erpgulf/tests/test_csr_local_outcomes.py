"""Fixed synthetic key/CSR failures; no site, authority, file or active key.

The imported fixtures supply ephemeral test-only EC material and exact saved
row mocks. A save observation is never treated as a real database commit.
"""

import base64
import itertools
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID, ObjectIdentifier

from zatca_erpgulf.zatca_erpgulf import sign_invoice_first as client
from zatca_erpgulf.zatca_erpgulf.credential_write_access import ACCESS_DENIED, ACCESS_UNCONFIRMED
from zatca_erpgulf.zatca_erpgulf.operation_messages import CSRProgress, csr_local_failure
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_write_access import (
    boundary, saved_boundary, materials, enable, PermissionDenied, ValidationError,
)


class PrivateFailure(Exception):
    def __str__(self):
        raise AssertionError("Private crypto/ORM diagnostics must not be stringified")


STAGES = (
    ("key", "keygen", "CSR_PREPARATION_FAILED", 0),
    ("key", "serialization", "CSR_PREPARATION_FAILED", 0),
    ("key", "key-save", "CSR_KEY_STORAGE_UNCONFIRMED", 1),
    ("csr", "config", "CSR_PREPARATION_FAILED", 0),
    ("csr", "keygen", "CSR_PREPARATION_FAILED", 0),
    ("csr", "serialization", "CSR_PREPARATION_FAILED", 0),
    ("csr", "key-save", "CSR_KEY_STORAGE_UNCONFIRMED", 1),
    ("csr", "key-load", "CSR_BUILD_UNCONFIRMED", 1),
    ("csr", "build", "CSR_BUILD_UNCONFIRMED", 1),
    ("csr", "csr-save", "CSR_STORAGE_UNCONFIRMED", 2),
)


def progress_for(stage):
    return CSRProgress(key_save_started=stage in ("key-save", "key-load", "build", "csr-save"),
                       key_save_completed=stage in ("key-load", "build", "csr-save"),
                       csr_save_started=stage == "csr-save")


def inject(b, monkeypatch, doc, stage, error=PrivateFailure):
    def fail(*args, **kwargs):
        b.frappe.msgprint("PRIVATE-CHILD-KEY-DIAGNOSTIC")
        raise error()
    if stage == "config":
        monkeypatch.setattr(client, "parse_csr_config", fail)
    elif stage == "keygen":
        b.keygen.side_effect = fail
    elif stage == "serialization":
        b.keygen.return_value = SimpleNamespace(private_bytes=fail)
    elif stage == "key-save":
        doc.save.side_effect = fail
    elif stage == "key-load":
        monkeypatch.setattr(client.serialization, "load_pem_private_key", fail)
    elif stage == "build":
        monkeypatch.setattr(client.x509, "CertificateSigningRequestBuilder", fail)
    elif stage == "csr-save":
        def save():
            if doc.save.call_count == 2:
                fail()
        doc.save.side_effect = save
    else:
        raise AssertionError("Unreviewed test stage")


@pytest.mark.parametrize("mode,stage,code,saves", STAGES)
@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("lang", ["en", "ar"])
@pytest.mark.parametrize("flags", [{}, {"mute_messages": False}, {"mute_messages": True}, {"mute_messages": "parent"}])
def test_actual_writers_own_one_stage_aware_failure_without_private_diagnostics(boundary, materials, monkeypatch, mode, stage, code, saves, source, lang, flags):
    b = boundary
    doc = getattr(b, source)
    enable(b, materials, mode)
    b.lang, b.frappe.flags = lang, dict(flags)
    b.frappe.message_log = ["PARENT-ENTRY"]
    inject(b, monkeypatch, doc, stage)
    with pytest.raises(ValidationError) as raised:
        b.invoke(mode, source)
    canonical = csr_local_failure(mode, progress_for(stage))
    assert canonical["code"] == code
    expected = b.catalog[canonical["message"]] if lang == "ar" else canonical["message"]
    assert str(raised.value) == expected and raised.value.__context__ is None
    assert "PRIVATE" not in str(raised.value) + repr(b.visible)
    assert b.frappe.flags == flags and b.frappe.message_log == ["PARENT-ENTRY"]
    assert len(b.visible) == (0 if flags.get("mute_messages") else 1)
    if b.visible:
        assert b.visible[0]["value"] == expected
    assert doc.save.call_count == saves
    assert all(call.kwargs == {} for call in doc.save.call_args_list)
    assert b.keygen.call_count == (0 if stage == "config" else 1)
    b.post.assert_not_called()
    b.route.assert_not_called()
    b.frappe.publish_realtime.assert_not_called()
    b.frappe.db.commit.assert_not_called()
    b.frappe.db.rollback.assert_not_called()
    b.frappe.delete_doc.assert_not_called()
    getattr(b, "device" if source == "company" else "company").save.assert_not_called()


@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("lang", ["en", "ar"])
@pytest.mark.parametrize("denied", [True, False])
def test_late_source_failure_keeps_partial_key_review_and_native_permission_class(boundary, materials, monkeypatch, source, lang, denied):
    b = boundary
    doc = getattr(b, source)
    b.lang = lang
    enable(b, materials, "csr")
    def permission(doctype, ptype, *, doc, user, raise_exception=True):
        if getattr(b, source).save.call_count:
            if denied:
                return False
            raise PrivateFailure()
        return True
    monkeypatch.setattr(client, "has_permission", permission)
    with pytest.raises(PermissionDenied if denied else ValidationError) as raised:
        b.invoke("csr", source)
    translate = lambda text: b.catalog[text] if lang == "ar" else text
    stage = csr_local_failure("csr", progress_for("build"))
    assert str(raised.value) == translate(stage["message"]) + "\n\n" + translate(ACCESS_DENIED if denied else ACCESS_UNCONFIRMED)
    assert raised.value.__context__ is None and len(b.visible) == 1
    assert doc.save.call_count == 1 and b.keygen.call_count == 1
    assert doc.custom_csr_data == "SAVED-CSR"
    b.post.assert_not_called()
    b.frappe.db.commit.assert_not_called()
    b.frappe.db.rollback.assert_not_called()


@pytest.mark.parametrize("stage", ["keygen", "key-save", "build", "csr-save"])
@pytest.mark.parametrize("stop", [KeyboardInterrupt, SystemExit, GeneratorExit])
@pytest.mark.parametrize("flags", [{}, {"mute_messages": False}, {"mute_messages": True}])
def test_cancellation_propagates_without_popup_retry_or_cleanup(boundary, materials, monkeypatch, stage, stop, flags):
    b = boundary
    enable(b, materials, "csr")
    b.frappe.flags = dict(flags)
    inject(b, monkeypatch, b.company, stage, stop)
    with pytest.raises(stop):
        b.invoke("csr")
    assert b.frappe.flags == flags and b.visible == []
    assert b.keygen.call_count == 1
    b.post.assert_not_called()
    b.frappe.db.commit.assert_not_called()
    b.frappe.db.rollback.assert_not_called()
    b.frappe.delete_doc.assert_not_called()


@pytest.mark.parametrize("purpose", ["key", "csr"])
@pytest.mark.parametrize("bits", list(itertools.product((False, True), repeat=4)))
def test_progress_accepts_only_coherent_literal_observations(purpose, bits):
    start, saved, csr_start, csr_saved = bits
    progress = CSRProgress(*bits)
    invalid = ((saved and not start) or (csr_start and not saved)
               or (csr_saved and not csr_start) or (purpose == "key" and (csr_start or csr_saved)))
    if invalid:
        with pytest.raises(ValueError, match="Invalid CSR progress"):
            csr_local_failure(purpose, progress)
    else:
        result = csr_local_failure(purpose, progress)
        assert result["status"] == "ERROR" and result["purpose"] == purpose
        assert set(result) == {"status", "purpose", "code", "message"}


@pytest.mark.parametrize("field", ["key_save_started", "key_save_completed", "csr_save_started", "csr_save_completed"])
@pytest.mark.parametrize("value", [None, 0, 1, "true", {}, []])
def test_progress_does_not_coerce_non_boolean_fields(field, value):
    progress = CSRProgress()
    setattr(progress, field, value)
    with pytest.raises(ValueError, match="Invalid CSR progress"):
        csr_local_failure("csr", progress)


@pytest.mark.parametrize("purpose", [None, "production", "compliance", "CSR", 1, [], {}])
def test_failure_metadata_has_no_unreviewed_purpose(purpose):
    with pytest.raises(ValueError, match="Unsupported CSR purpose"):
        csr_local_failure(purpose, CSRProgress())


@pytest.mark.parametrize("mode", ["key", "csr"])
@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("lang", ["en", "ar"])
def test_success_preserves_opaque_legacy_returns_without_an_extra_popup(boundary, materials, mode, source, lang):
    b = boundary
    b.lang = lang
    enable(b, materials, mode)
    result = b.invoke(mode, source)
    doc = getattr(b, source)
    assert b.visible == [] and b.frappe.flags == {}
    assert doc.save.call_count == (2 if mode == "csr" else 1)
    if mode == "csr":
        csr = x509.load_pem_x509_csr(base64.b64decode(result))
        assert csr.is_signature_valid and isinstance(csr.signature_hash_algorithm, hashes.SHA256)
        assert csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == "TEST ONLY"
        assert csr.subject.get_attributes_for_oid(NameOID.COUNTRY_NAME)[0].value == "SA"
        key = serialization.load_pem_private_key(doc.custom_private_key.encode(), password=None)
        assert csr.public_key().public_numbers() == key.public_key().public_numbers()
        assert len(csr.extensions) == 2
        assert csr.extensions.get_extension_for_oid(ObjectIdentifier("1.3.6.1.4.1.311.20.2")).critical is False
        assert result == doc.custom_csr_data
    else:
        assert isinstance(result, bytes) and result.decode() == doc.custom_private_key
    b.post.assert_not_called()
    b.frappe.db.commit.assert_not_called()


@pytest.mark.parametrize("portal,label", [("Sandbox", "TESTZATCA-Code-Signing"), ("Simulation", "PREZATCA-Code-Signing"), ("Production", "ZATCA-Code-Signing")])
def test_selected_legacy_oid_is_preserved_without_any_transport(boundary, materials, portal, label):
    b = boundary
    enable(b, materials, "csr")
    result = client.create_csr({"doctype": "Company", "name": b.company.name}, portal, "TC")
    csr = x509.load_pem_x509_csr(base64.b64decode(result))
    extension = csr.extensions.get_extension_for_oid(ObjectIdentifier("1.3.6.1.4.1.311.20.2"))
    assert extension.value.value == client.encode_customoid(label)
    b.post.assert_not_called()


@pytest.mark.parametrize("missing", [None, "", "malformed config"])
def test_invalid_saved_configuration_fails_before_key_generation(boundary, missing):
    b = boundary
    b.company.custom_csr_config = missing
    with pytest.raises(ValidationError):
        b.invoke("csr")
    assert len(b.visible) == 1
    b.keygen.assert_not_called()
    b.company.save.assert_not_called()
    b.post.assert_not_called()


def test_all_static_stage_messages_have_actual_arabic_translations(boundary):
    for mode, stage, code, saves in STAGES:
        text = csr_local_failure(mode, progress_for(stage))["message"]
        assert boundary.catalog[text] != text
    for mode, progress in (("key", CSRProgress(True, True)), ("csr", CSRProgress(True, True, True, True))):
        text = csr_local_failure(mode, progress)["message"]
        assert boundary.catalog[text] != text
