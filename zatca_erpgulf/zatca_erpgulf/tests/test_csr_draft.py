"""Test-only declared contexts and ephemeral keys; no saved writes or HTTP.

Drafts are not encrypted custody, provenance, acceptance or activation evidence.
The legacy adapter is invoked only with synthetic saved records/ACLs/saves.
"""

import base64
import copy
import hashlib
import json
import pickle
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from zatca_erpgulf.zatca_erpgulf import csr_draft as drafts
from zatca_erpgulf.zatca_erpgulf import csr_template as templates
from zatca_erpgulf.zatca_erpgulf import sign_invoice_first as client
from zatca_erpgulf.zatca_erpgulf.credential_bundle import CredentialSlot
from zatca_erpgulf.zatca_erpgulf.csr_draft import (
    CSRPreparationContext, PreparedCSRDraft, CSRDraftError, prepare_csr_draft,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_write_access import (
    boundary, saved_boundary, materials, enable, FIELDS,
)


NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
REVISION = "2026-10-24 11:00:00.123456"
DRAFT_ID = "93d57d62-5d74-409d-b4f7-c260f6f5994b"
FLOW_ID = "01e9d5d2-45ba-43a4-bb2e-12bd0fc86440"
CONFIG = (
    "csr.common.name=TEST ONLY\ncsr.serial.number=TEST-SERIAL\n"
    "csr.organization.identifier=TEST-VAT\ncsr.organization.unit.name=TEST UNIT\n"
    "csr.organization.name=TEST ORGANIZATION\ncsr.country.name=SA\ncsr.invoice.type=1100\n"
    "csr.location.address=TEST CITY\ncsr.industry.business.category=TEST CATEGORY")


def context(environment="Production", kind="company", **changes):
    doctype = "ZATCA Multiple Setting" if kind == "multiple_setting" else "Company"
    name = "TEST COMPANY" if kind == "company" else "TEST DEVICE" if kind == "multiple_setting" else "TEST LINKED"
    values = dict(slot=CredentialSlot(doctype, name, environment, "compliance"),
                  company_name="TEST COMPANY", source_kind=kind, source_revision=REVISION,
                  draft_id=DRAFT_ID, flow_id=FLOW_ID, prepared_at=NOW)
    values.update(changes)
    return CSRPreparationContext(**values)


@pytest.fixture
def crypto(materials, monkeypatch):
    key = serialization.load_pem_private_key(materials[0].pem.encode(), password=None)
    generator = Mock(return_value=key)
    monkeypatch.setattr(drafts.ec, "generate_private_key", generator)
    return SimpleNamespace(key=key, generator=generator)


@pytest.fixture
def sample(crypto):
    return prepare_csr_draft(context(), CONFIG)


class PrivateFailure(Exception):
    def __str__(self):
        raise AssertionError("Never stringify a private preparation exception")


class PrivateValue:
    def __str__(self):
        raise AssertionError("Never stringify private input")

    def __bool__(self):
        raise AssertionError("Never truth-test private input")


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("kind", ["company", "linked_company", "multiple_setting"])
def test_all_declared_owner_environment_slots_prepare_only_locally(crypto, environment, kind):
    declared = context(environment, kind)
    draft = prepare_csr_draft(declared, CONFIG)
    assert draft.context == declared and draft.config_text == CONFIG
    assert crypto.generator.call_count == 1
    args, kwargs = crypto.generator.call_args
    assert isinstance(args[0], ec.SECP256K1)
    csr = x509.load_pem_x509_csr(draft.csr_pem)
    key = serialization.load_pem_private_key(draft.private_key_pem, password=None)
    assert csr.is_signature_valid and isinstance(csr.signature_hash_algorithm, hashes.SHA256)
    assert csr.public_key().public_numbers() == key.public_key().public_numbers()
    assert len(csr.subject) == 4 and len(csr.extensions) == 2
    assert csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == "TEST ONLY"
    assert csr.extensions.get_extension_for_oid(templates.CSR_EXTENSION_OID).value.value == templates.encode_customoid(templates.CSR_LABELS[environment])
    assert draft.configuration_sha256 == hashlib.sha256(CONFIG.encode()).hexdigest()


@pytest.mark.parametrize("environment,label", [("Sandbox", "TESTZATCA-Code-Signing"),
    ("Simulation", "PREZATCA-Code-Signing"), ("Production", "ZATCA-Code-Signing")])
def test_independent_legacy_structure_golden_does_not_reuse_template_expectations(crypto, environment, label):
    csr = x509.load_pem_x509_csr(prepare_csr_draft(context(environment), CONFIG).csr_pem)
    assert [(item.oid.dotted_string, item.value) for item in csr.subject] == [
        ("2.5.4.6", "SA"), ("2.5.4.11", "TEST UNIT"),
        ("2.5.4.10", "TEST ORGANIZATION"), ("2.5.4.3", "TEST ONLY")]
    assert [(item.oid.dotted_string, item.critical) for item in csr.extensions] == [
        ("1.3.6.1.4.1.311.20.2", False), ("2.5.29.17", False)]
    encoded = label.encode("ascii")
    assert csr.extensions[0].value.value == b"\x0c" + bytes([len(encoded)]) + encoded
    directory_names = csr.extensions[1].value.get_values_for_type(x509.DirectoryName)
    assert len(directory_names) == 1
    assert [(item.oid.dotted_string, item.value) for item in directory_names[0]] == [
        ("2.5.4.4", "TEST-SERIAL"), ("0.9.2342.19200300.100.1.1", "TEST-VAT"),
        ("2.5.4.12", "1100"), ("2.5.4.26", "TEST CITY"), ("2.5.4.15", "TEST CATEGORY")]
    assert csr.signature_algorithm_oid.dotted_string == "1.2.840.10045.4.3.2"


@pytest.mark.parametrize("changes", [
    {"slot": None}, {"slot": {}}, {"slot": CredentialSlot("Company", "TEST COMPANY", "Production", "production")},
    {"company_name": ""}, {"company_name": "OTHER"}, {"company_name": " TEST COMPANY"},
    {"company_name": "\ud800"}, {"source_kind": "multiple_setting"}, {"source_kind": "invalid"},
    {"source_kind": None}, {"source_revision": None}, {"source_revision": ""},
    {"source_revision": "2026-10-24T9:00:00"}, {"source_revision": "2026-10-24T11:00:00Z"},
    {"source_revision": "2026-99-24 11:00:00"}, {"source_revision": NOW},
    {"draft_id": ""}, {"draft_id": DRAFT_ID.upper()}, {"draft_id": "00000000-0000-0000-0000-000000000000"},
    {"draft_id": None}, {"flow_id": "PRIVATE INVALID"}, {"flow_id": FLOW_ID.upper()},
    {"prepared_at": None}, {"prepared_at": "2026-10-24"}, {"prepared_at": NOW.replace(tzinfo=None)},
    {"prepared_at": NOW.astimezone(timezone(timedelta(hours=3)))},
])
def test_invalid_context_is_not_key_generation_authority(crypto, changes):
    with pytest.raises(CSRDraftError, match="^csr_draft_context$") as raised:
        context(**changes)
    assert raised.value.__context__ is None and raised.value.__cause__ is None
    crypto.generator.assert_not_called()


@pytest.mark.parametrize("value", [None, {}, [], "Production", pytest.param(PrivateValue(), id="opaque")])
def test_preparation_rejects_untyped_context_before_crypto(crypto, value):
    with pytest.raises(CSRDraftError, match="^csr_draft_context$") as raised:
        prepare_csr_draft(value, CONFIG)
    assert raised.value.__context__ is None
    crypto.generator.assert_not_called()


@pytest.mark.parametrize("content", [None, "", b"TEST", {}, [], pytest.param(PrivateValue(), id="opaque"),
    "x" * (drafts.MAX_CONFIG_BYTES + 1), CONFIG + "\nunknown=TEST", CONFIG + "\ncsr.common.name=TEST ONLY",
    CONFIG.replace("csr.country.name=SA", "csr.country.name="),
    CONFIG.replace("csr.country.name=SA", "csr.country.name=TOOLONG"),
    CONFIG.replace("csr.country.name=SA\n", ""), CONFIG.replace("TEST CITY", "TEST\x00CITY"),
    CONFIG.replace("TEST CITY", "TEST\tCITY"), CONFIG.replace("TEST CITY", "TEST\x7fCITY"),
    CONFIG.replace("TEST CITY", "TEST\u2028CITY"), CONFIG.replace("TEST CITY", "TEST\x85CITY"),
    CONFIG.replace("TEST CITY", "\ud800"), CONFIG.replace("TEST CITY", "a" * 1025),
    CONFIG.replace("TEST CITY", "ع" * 513), CONFIG.replace("TEST ONLY", "x" * 1025),
    CONFIG.replace("csr.country.name=SA", "MALFORMED"), CONFIG + "\n\n",
    CONFIG + "\ncustom_private_key=PRIVATE-INJECTION",
])
def test_bad_configuration_fails_before_key_generation(crypto, content):
    with pytest.raises(CSRDraftError, match="^csr_draft_configuration$") as raised:
        prepare_csr_draft(context(), content)
    assert raised.value.__context__ is None and raised.value.__cause__ is None
    crypto.generator.assert_not_called()


@pytest.mark.parametrize("line", CONFIG.splitlines())
def test_every_required_config_key_is_checked_before_generation(crypto, line):
    with pytest.raises(CSRDraftError, match="^csr_draft_configuration$"):
        prepare_csr_draft(context(), "\n".join(item for item in CONFIG.splitlines() if item != line))
    crypto.generator.assert_not_called()


@pytest.mark.parametrize("line", CONFIG.splitlines())
def test_even_identical_duplicate_config_values_are_rejected(crypto, line):
    with pytest.raises(CSRDraftError, match="^csr_draft_configuration$"):
        prepare_csr_draft(context(), CONFIG + "\n" + line)
    crypto.generator.assert_not_called()


@pytest.mark.parametrize("content", [CONFIG + "\n", CONFIG.replace("\n", "\r\n"), CONFIG.replace("=", " = ")])
def test_exact_config_bytes_are_hashed_without_legacy_field_rewriting(crypto, content):
    draft = prepare_csr_draft(context(), content)
    assert draft.config_text == content
    assert draft.configuration_sha256 == hashlib.sha256(content.encode()).hexdigest()
    assert crypto.generator.call_count == 1


@pytest.mark.parametrize("fault,code,calls", [("builder", "csr_draft_configuration", 0),
    ("generation", "csr_draft_generation", 1), ("signing", "csr_draft_generation", 1),
    ("validation", "csr_draft_material", 1)])
def test_private_faults_are_not_stringified_attached_or_retried(crypto, monkeypatch, fault, code, calls):
    if fault == "builder":
        monkeypatch.setattr(drafts, "csr_builder", Mock(side_effect=PrivateFailure()))
    elif fault == "generation":
        crypto.generator.side_effect = PrivateFailure()
    elif fault == "signing":
        monkeypatch.setattr(drafts, "csr_builder", Mock(return_value=SimpleNamespace(sign=Mock(side_effect=PrivateFailure()))))
    else:
        monkeypatch.setattr(drafts.x509, "load_pem_x509_csr", Mock(side_effect=PrivateFailure()))
    with pytest.raises(CSRDraftError, match="^" + code + "$") as raised:
        prepare_csr_draft(context(), CONFIG)
    assert raised.value.__context__ is None and raised.value.__cause__ is None
    assert crypto.generator.call_count == calls


@pytest.mark.parametrize("stop", [KeyboardInterrupt, SystemExit, GeneratorExit])
@pytest.mark.parametrize("stage", ["builder", "generation", "signing"])
def test_cancellation_is_not_caught_as_preparation_failure(crypto, monkeypatch, stop, stage):
    if stage == "builder":
        monkeypatch.setattr(drafts, "csr_builder", Mock(side_effect=stop()))
    elif stage == "generation":
        crypto.generator.side_effect = stop()
    else:
        monkeypatch.setattr(drafts, "csr_builder", Mock(return_value=SimpleNamespace(sign=Mock(side_effect=stop()))))
    with pytest.raises(stop):
        prepare_csr_draft(context(), CONFIG)
    assert crypto.generator.call_count == (0 if stage == "builder" else 1)


@pytest.mark.parametrize("field,value", [("private_key_pem", None), ("private_key_pem", b""),
    ("private_key_pem", b"PRIVATE invalid"), ("private_key_pem", b"x" * 65537),
    ("private_key_pem", "PRIVATE invalid"), ("csr_pem", None), ("csr_pem", b""),
    ("csr_pem", b"PRIVATE invalid"), ("csr_pem", b"x" * 65537), ("csr_pem", "PRIVATE invalid"),
    ("config_text", "PRIVATE invalid"), ("context", None)])
def test_protected_material_constructor_rejects_invalid_bounded_fields(sample, field, value):
    with pytest.raises(CSRDraftError, match="^csr_draft_material$") as raised:
        replace(sample, **{field: value})
    assert raised.value.__context__ is None and raised.value.__cause__ is None


@pytest.mark.parametrize("change", ["other-key", "pkcs8", "key-trailing", "csr-trailing", "corrupt-signature", "subject", "label", "san", "sha384", "extra-extension", "critical", "order"])
def test_material_binding_rejects_valid_but_mismatched_or_noncanonical_inputs(sample, crypto, materials, change):
    values = drafts._configuration(CONFIG)
    custom = templates.encode_customoid(templates.CSR_LABELS["Production"])
    changes = {}
    if change == "other-key":
        key = serialization.load_pem_private_key(materials[1].pem.encode(), password=None)
        changes["private_key_pem"] = key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption())
    elif change == "pkcs8":
        changes["private_key_pem"] = crypto.key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    elif change == "key-trailing":
        changes["private_key_pem"] = sample.private_key_pem + b"\n"
    elif change == "csr-trailing":
        changes["csr_pem"] = sample.csr_pem + b"\n"
    elif change == "corrupt-signature":
        der = x509.load_pem_x509_csr(sample.csr_pem).public_bytes(serialization.Encoding.DER)
        der = der[:-1] + bytes([der[-1] ^ 1])
        changes["csr_pem"] = b"-----BEGIN CERTIFICATE REQUEST-----\n" + base64.encodebytes(der) + b"-----END CERTIFICATE REQUEST-----\n"
    else:
        if change == "subject":
            values["csr.common.name"] = "DIFFERENT TEST"
        if change == "san":
            values["csr.location.address"] = "DIFFERENT TEST CITY"
        if change == "label":
            custom = templates.encode_customoid(templates.CSR_LABELS["Simulation"])
        builder = templates.csr_builder(values, custom)
        if change in ("critical", "order"):
            subject, extension, alternative = templates.csr_attributes(values, custom)
            builder = x509.CertificateSigningRequestBuilder().subject_name(subject)
            if change == "order":
                builder = builder.add_extension(alternative, critical=False).add_extension(extension, critical=False)
            else:
                builder = builder.add_extension(extension, critical=True).add_extension(alternative, critical=False)
        if change == "extra-extension":
            builder = builder.add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        changes["csr_pem"] = builder.sign(crypto.key, hashes.SHA384() if change == "sha384" else hashes.SHA256()).public_bytes(serialization.Encoding.PEM)
    with pytest.raises(CSRDraftError, match="^csr_draft_material$"):
        replace(sample, **changes)


def test_metadata_is_mutation_independent_secret_free_and_never_authorizes_use(sample):
    metadata = sample.diagnostic_projection()
    assert metadata["state"] == "LOCAL_CSR_DRAFT"
    assert all(value is False for name, value in metadata.items() if name.endswith(("_verified", "_authorized", "_confirmed")))
    exported = json.dumps(metadata) + repr(sample) + repr(sample.context)
    for value in (sample.private_key_pem.decode(), sample.csr_pem.decode(), CONFIG, "TEST COMPANY", "TEST ONLY", "TEST-VAT"):
        assert value not in exported
    metadata["activation_authorized"] = True
    assert sample.diagnostic_projection()["activation_authorized"] is False
    with pytest.raises(FrozenInstanceError):
        sample.config_text = "PRIVATE"
    with pytest.raises(FrozenInstanceError):
        sample.context.flow_id = "OTHER"


@pytest.mark.parametrize("serializer", [pickle.dumps, copy.copy, copy.deepcopy])
def test_accidental_pickle_and_copy_transport_are_refused(sample, serializer):
    with pytest.raises(CSRDraftError, match="^csr_draft_not_pickleable$"):
        serializer(sample)


def test_implicit_json_export_is_not_supported(sample):
    with pytest.raises(TypeError):
        json.dumps(sample)


@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
def test_legacy_and_nonwriting_paths_share_exact_subject_tbs_and_extension_structure(boundary, materials, source, environment):
    b = boundary
    enable(b, materials, "csr")
    doc = getattr(b, source)
    doc.custom_csr_config = CONFIG
    kind = "company" if source == "company" else "multiple_setting"
    draft = prepare_csr_draft(context(environment, kind), CONFIG)
    assert b.keygen.call_count == 1
    doc.save.assert_not_called()
    result = client.create_csr({"doctype": doc.doctype, "name": doc.name}, environment, "TC")
    legacy = x509.load_pem_x509_csr(base64.b64decode(result))
    local = x509.load_pem_x509_csr(draft.csr_pem)
    assert legacy.is_signature_valid and local.is_signature_valid
    assert legacy.tbs_certrequest_bytes == local.tbs_certrequest_bytes
    assert legacy.subject == local.subject and list(legacy.extensions) == list(local.extensions)
    assert doc.custom_private_key.encode() == draft.private_key_pem
    assert doc.save.call_count == 2 and b.keygen.call_count == 2
    b.post.assert_not_called()
    b.frappe.db.commit.assert_not_called()
    b.frappe.db.rollback.assert_not_called()


@pytest.mark.parametrize("source", ["company", "device"])
def test_preparation_never_reads_or_modifies_existing_active_records(boundary, materials, source):
    b = boundary
    before = {doc.name: {name: getattr(doc, name, None) for name in FIELDS} for doc in (b.company, b.device)}
    b.frappe.get_doc.side_effect = AssertionError("Pure preparation must not load saved credentials")
    key = serialization.load_pem_private_key(materials[1].pem.encode(), password=None)
    b.keygen.side_effect, b.keygen.return_value = None, key
    kind = "company" if source == "company" else "multiple_setting"
    prepared = prepare_csr_draft(context(kind=kind), CONFIG)
    assert prepared.diagnostic_projection()["activation_authorized"] is False
    b.frappe.get_doc.assert_not_called()
    for doc in (b.company, b.device):
        assert {name: getattr(doc, name, None) for name in FIELDS} == before[doc.name]
        doc.save.assert_not_called()
    b.post.assert_not_called()
    b.frappe.db.commit.assert_not_called()
    b.frappe.db.rollback.assert_not_called()
    b.frappe.delete_doc.assert_not_called()
    assert b.visible == []


def test_default_generation_creates_distinct_test_only_keys_without_existing_material():
    left = prepare_csr_draft(context(), CONFIG)
    right = prepare_csr_draft(context(draft_id="3ccf6b8e-25eb-4db2-8c16-c40dc020a2ef"), CONFIG)
    assert left.public_key_sha256 != right.public_key_sha256
    assert left.private_key_pem != right.private_key_pem


@pytest.mark.parametrize("value", [None, b"PRIVATE invalid", ec.derive_private_key(12345, ec.SECP256R1())])
def test_wrong_generated_key_or_curve_is_not_encoded_or_signed(crypto, value):
    crypto.generator.return_value = value
    with pytest.raises(CSRDraftError, match="^csr_draft_generation$"):
        prepare_csr_draft(context(), CONFIG)
    assert crypto.generator.call_count == 1
