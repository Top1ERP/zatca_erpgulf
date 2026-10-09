"""Site-free candidate declarations; fixtures do not prove signing/acceptance."""

import base64
import copy
import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from unittest.mock import Mock

import frappe
import pytest
import requests

from zatca_erpgulf.zatca_erpgulf import issuance_candidate as issuance
from zatca_erpgulf.zatca_erpgulf.api_routing import ENVIRONMENT_FIELDS, resolve_api_route
from zatca_erpgulf.zatca_erpgulf.certificate_evidence import inspect_embedded_certificate
from zatca_erpgulf.zatca_erpgulf.tests.test_artifact_evidence import OTHER_UUID, SELLER, UUID, node, xml_bytes
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates, certificate_root


CHAIN_ID = "7438a1a3-96ec-479e-a5e8-cab8040f59cd"
EPOCH_ID = "df8a2443-bc13-43f7-9d76-a413842c6a6e"
OTHER_ID = "bde67f01-e42e-4940-9aeb-6f35a0cb5664"
SOURCE_DIGEST = hashlib.sha256(b"synthetic ERP snapshot, not real accounting evidence").hexdigest()


def scope(**changes):
    values = dict(
        doctype="Sales Invoice", invoice_name="INV-TEST", company_name="TEST",
        seller_tax_id=SELLER, environment="Production", chain_id=CHAIN_ID,
        legacy_issuing_unit="existing-chain", issuance_version=1,
    )
    values.update(changes)
    return issuance.IssuanceScope(**values)


def content(der, *, code="388", indicator="0200000", invoice_name="INV-TEST", seller=SELLER):
    root = certificate_root(der)
    root.find("cbc:ID", namespaces=issuance.NS).text = invoice_name
    root.xpath("./cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID", namespaces=issuance.NS)[0].text = seller
    node(root, "cbc", "InvoiceTypeCode", code, name=indicator)
    return xml_bytes(root)


def context(der, *, selected_scope=None, endpoint="invoices/reporting/single", base="https://gateway.invalid/phase2"):
    selected_scope = selected_scope or scope()
    observed = inspect_embedded_certificate(content(der))
    epoch = issuance.DeclaredCredentialEpoch(
        "Company", "TEST", EPOCH_ID, observed.der_sha256, observed.public_key_sha256,
    )
    route = resolve_api_route(
        {"custom_select": selected_scope.environment, ENVIRONMENT_FIELDS[selected_scope.environment]: base},
        endpoint,
    )
    return issuance.PreparationContext(selected_scope, epoch, route, SOURCE_DIGEST)


def candidate(der, *, selected_scope=None, code="388", indicator="0200000", endpoint=None):
    selected_scope = selected_scope or scope()
    endpoint = endpoint or ("invoices/reporting/single" if indicator[:2] == "02" else "invoices/clearance/single")
    return issuance.PreparedIssuanceCandidate(
        context(der, selected_scope=selected_scope, endpoint=endpoint),
        content(der, code=code, indicator=indicator, invoice_name=selected_scope.invoice_name, seller=selected_scope.seller_tax_id),
    )


def assert_code(call, code):
    with pytest.raises(issuance.IssuanceContractError) as error:
        call()
    assert error.value.code == code
    assert str(error.value) == code


def test_candidate_preserves_exact_bytes_and_never_claims_verification(certificates):
    prepared = candidate(certificates[0])
    assert prepared.xml_bytes == content(certificates[0])
    assert prepared.artifact.uuid == UUID
    assert prepared.artifact.icv == 77
    report = prepared.diagnostic_projection()
    assert report["purpose"] == "production"
    assert report["schema_version"] == 1
    assert report["byte_length"] == len(prepared.xml_bytes)
    assert report["file_sha256"] == hashlib.sha256(prepared.xml_bytes).hexdigest()
    assert report["source_snapshot_sha256"] == SOURCE_DIGEST
    for flag in (
        "persistence_verified", "credential_epoch_verified", "chain_mapping_verified",
        "source_snapshot_verified", "signature_verified", "remote_acceptance_verified", "replay_authorized",
        "counter_continuity_verified", "xsd_verified", "invoice_hash_verified", "qr_verified",
    ):
        assert report[flag] is False
    assert prepared.xml_bytes.decode() not in repr(prepared)
    assert "PRIVATE-DN" not in repr(prepared)
    assert "gateway.invalid" not in repr(prepared)
    assert "SignatureValue" not in json.dumps(report)
    assert issuance.compare_prepared_candidates(prepared, candidate(certificates[0])) == ()
    report["icv"] = 999
    assert prepared.artifact.icv == 77


@pytest.mark.parametrize("attribute", ["context", "xml_bytes", "artifact", "certificate", "key_sha256", "manifest_sha256"])
def test_candidate_fields_are_frozen(certificates, attribute):
    prepared = candidate(certificates[0])
    with pytest.raises(FrozenInstanceError):
        setattr(prepared, attribute, None)


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("code", ["388", "381", "383", "386"])
def test_type_source_and_environment_matrix(certificates, environment, doctype, indicator, code):
    prepared = candidate(certificates[0], selected_scope=scope(environment=environment, doctype=doctype), code=code, indicator=indicator)
    assert prepared.invoice_type_code == code
    assert prepared.invoice_type_indicator == indicator
    assert prepared.context.scope.environment == environment
    assert prepared.context.credential_epoch.purpose == "production"
    assert prepared.diagnostic_projection()["replay_authorized"] is False


@pytest.mark.parametrize("indicator,endpoint", [
    ("0100000", "invoices/reporting/single"), ("0200000", "invoices/clearance/single"),
])
def test_xml_classification_and_operation_must_agree(certificates, indicator, endpoint):
    assert_code(lambda: candidate(certificates[0], indicator=indicator, endpoint=endpoint), "invoice_operation_mismatch")


@pytest.mark.parametrize("name", ["INV عربي 01", "series/INV-01", "INV..01", "INV%2f01"])
def test_identity_names_are_not_filesystem_paths(certificates, name):
    prepared = candidate(certificates[0], selected_scope=scope(invoice_name=name))
    assert prepared.artifact.invoice_id == name
    assert prepared.diagnostic_projection()["invoice"] == name


@pytest.mark.parametrize("doctype", ["Company", "Purchase Invoice", "", None, []])
def test_only_live_sales_pos_sources_are_supported(doctype):
    assert_code(lambda: scope(doctype=doctype), "source_doctype")


@pytest.mark.parametrize("field,code", [
    ("invoice_name", "invoice_name"), ("company_name", "company_name"),
    ("seller_tax_id", "seller_tax_id"), ("legacy_issuing_unit", "issuing_unit_reference"),
])
@pytest.mark.parametrize("value", ["", " padded ", "line\nbreak", "null\x00", "x" * 141, None, False, [], "\ud800"])
def test_scope_text_is_bounded_canonical_and_utf8(field, code, value):
    assert_code(lambda: scope(**{field: value}), code)


@pytest.mark.parametrize("environment", ["", "production", " Production", "Debug", "Compliance", None, []])
def test_environment_is_not_document_purpose(environment):
    assert_code(lambda: scope(environment=environment), "environment")


@pytest.mark.parametrize("version", [0, -1, True, False, "1", 1.0, None, [], issuance.MAX_ISSUANCE_VERSION + 1])
def test_issuance_version_is_explicit_bounded_integer(version):
    assert_code(lambda: scope(issuance_version=version), "issuance_version")


@pytest.mark.parametrize("value", ["", CHAIN_ID.upper(), CHAIN_ID.replace("-", ""), "00000000-0000-0000-0000-000000000000", "auth-fingerprint", None, []])
def test_chain_mapping_reference_requires_canonical_nonnil_uuid(value):
    assert_code(lambda: scope(chain_id=value), "chain_id")


@pytest.mark.parametrize("field,code", [
    ("certificate_der_sha256", "credential_certificate_fingerprint"),
    ("public_key_sha256", "credential_public_key_fingerprint"),
])
@pytest.mark.parametrize("value", ["", "A" * 64, "a" * 63, "a" * 65, "z" * 64, "raw certificate PRIVATE-DN", None, []])
def test_credential_fingerprints_never_accept_raw_material(certificates, field, code, value):
    original = context(certificates[0]).credential_epoch
    assert_code(lambda: replace(original, **{field: value}), code)


@pytest.mark.parametrize("value", ["", EPOCH_ID.upper(), "raw-auth-token", "Basic token", None, [], "00000000-0000-0000-0000-000000000000"])
def test_credential_version_is_an_opaque_reference_not_auth(certificates, value):
    assert_code(lambda: replace(context(certificates[0]).credential_epoch, version_id=value), "credential_version_id")


@pytest.mark.parametrize("purpose", ["compliance", "otp", "debug", "", "Production", None])
def test_live_candidate_cannot_select_onboarding_credential_purpose(certificates, purpose):
    assert_code(lambda: replace(context(certificates[0]).credential_epoch, purpose=purpose), "credential_purpose")


@pytest.mark.parametrize("owner", ["Sales Invoice", "File", "", None])
def test_declared_owner_is_company_or_issuing_unit(certificates, owner):
    assert_code(lambda: replace(context(certificates[0]).credential_epoch, owner_doctype=owner), "credential_owner_doctype")


@pytest.mark.parametrize("owner_name", ["", " padded", "key\x00material", None, "x" * 141])
def test_declared_owner_name_is_bounded_identity(certificates, owner_name):
    assert_code(lambda: replace(context(certificates[0]).credential_epoch, owner_name=owner_name), "credential_owner_name")


def test_own_device_and_linked_company_are_unverified_declarations(certificates):
    prepared = candidate(certificates[0])
    for doctype, name in (("Company", "LINKED-COMPANY"), ("ZATCA Multiple Setting", "DEVICE")):
        ctx = replace(prepared.context, credential_epoch=replace(prepared.context.credential_epoch, owner_doctype=doctype, owner_name=name))
        other = replace(prepared, context=ctx)
        assert other.key_sha256 == prepared.key_sha256
        assert issuance.compare_prepared_candidates(prepared, other) == ("credential_epoch_changed",)
        assert other.diagnostic_projection()["credential_epoch_verified"] is False


@pytest.mark.parametrize("value", ["", "X" * 64, "a" * 63, None, []])
def test_source_snapshot_digest_is_required_but_not_verified(certificates, value):
    assert_code(lambda: replace(context(certificates[0]), source_snapshot_sha256=value), "source_snapshot_fingerprint")


@pytest.mark.parametrize("field,value", [("scope", {}), ("credential_epoch", {}), ("scope", None), ("credential_epoch", None)])
def test_context_cannot_be_forged_from_mutable_dicts(certificates, field, value):
    assert_code(lambda: replace(context(certificates[0]), **{field: value}), "preparation_context")


@pytest.mark.parametrize("endpoint", ["compliance", "compliance/invoices", "production/csids", "debug", "", None, []])
def test_candidate_route_excludes_debug_compliance_and_arbitrary_operations(certificates, endpoint):
    ctx = context(certificates[0])
    assert_code(lambda: replace(ctx, route=replace(ctx.route, endpoint=endpoint)), "submission_operation")


def test_route_environment_and_purpose_are_not_fallbacks(certificates):
    ctx = context(certificates[0])
    assert_code(lambda: replace(ctx, route=replace(ctx.route, environment="Sandbox")), "route_environment")
    assert_code(lambda: replace(ctx, route=replace(ctx.route, required_credential="compliance")), "route_credential_purpose")


@pytest.mark.parametrize("changes", [
    {"base_url_field": "custom_sandbox_url"}, {"url": "http://unsafe.invalid/invoices/reporting/single"},
    {"url": "https://user:PRIVATE@unsafe.invalid/invoices/reporting/single"},
    {"url": "https://unsafe.invalid/?token=PRIVATE/invoices/reporting/single"},
    {"url": "https://gw-fatoora.zatca.gov.sa/e-invoicing/simulation/invoices/reporting/single"},
    {"url": "https://unsafe.invalid/compliance/invoices"}, {"url": None},
    {"url": "https://" + "a" * 4096 + "/invoices/reporting/single"},
    {"url": "https://\ud800.invalid/invoices/reporting/single"},
])
def test_hand_built_api_routes_are_revalidated_without_exposing_urls(certificates, changes):
    ctx = context(certificates[0])
    assert_code(lambda: replace(ctx, route=replace(ctx.route, **changes)), "route_configuration")


@pytest.mark.parametrize("value,code", [(None, "xml_bytes_required"), ("<Invoice/>", "xml_bytes_required"),
                                       (bytearray(b"xml"), "xml_bytes_required"), (b"", "xml_size"),
                                       (b"not XML PRIVATE-DN", "xml_syntax")])
def test_artifact_bytes_are_required_and_parser_failures_static(certificates, value, code):
    assert_code(lambda: issuance.PreparedIssuanceCandidate(context(certificates[0]), value), code)


def test_embedded_identity_and_certificate_must_match_declarations(certificates):
    ctx = context(certificates[0])
    assert_code(lambda: issuance.PreparedIssuanceCandidate(ctx, content(certificates[0], invoice_name="OTHER")), "invoice_id_mismatch")
    assert_code(lambda: issuance.PreparedIssuanceCandidate(ctx, content(certificates[0], seller="OTHER-SELLER")), "seller_tax_id_mismatch")
    assert_code(lambda: issuance.PreparedIssuanceCandidate(ctx, content(certificates[1])), "credential_certificate_mismatch")
    ctx = replace(ctx, credential_epoch=replace(ctx.credential_epoch, public_key_sha256="0" * 64))
    assert_code(lambda: issuance.PreparedIssuanceCandidate(ctx, content(certificates[0])), "credential_public_key_mismatch")


@pytest.mark.parametrize("code", ["", "380", "999", "3860"])
def test_unknown_invoice_type_does_not_fall_back(certificates, code):
    assert_code(lambda: issuance.PreparedIssuanceCandidate(context(certificates[0]), content(certificates[0], code=code)), "invoice_type_code")


@pytest.mark.parametrize("indicator", ["", "03", "0300000", "010000", "02000000", "0200002", " 0200000", "٠٢٠٠٠٠٠"])
def test_invoice_indicators_are_explicit_not_settings_fallbacks(certificates, indicator):
    assert_code(lambda: issuance.PreparedIssuanceCandidate(context(certificates[0]), content(certificates[0], indicator=indicator)), "invoice_type_indicator")


@pytest.mark.parametrize("action", ["remove", "duplicate", "nested"])
def test_invoice_type_node_is_unique_scalar(certificates, action):
    root = certificate_root(certificates[0])
    target = node(root, "cbc", "InvoiceTypeCode", "388", name="0200000")
    if action == "remove":
        root.remove(target)
    elif action == "duplicate":
        root.append(copy.deepcopy(target))
    else:
        node(target, "cbc", "Note", "private")
    assert_code(lambda: issuance.PreparedIssuanceCandidate(context(certificates[0]), xml_bytes(root)), "invoice_type")


def test_missing_certificate_never_falls_back_to_company_material(certificates):
    root = certificate_root(certificates[0])
    node(root, "cbc", "InvoiceTypeCode", "388", name="0200000")
    certificate = root.xpath(".//ds:X509Certificate", namespaces=issuance.NS)[0]
    certificate.getparent().remove(certificate)
    assert_code(lambda: issuance.PreparedIssuanceCandidate(context(certificates[0]), xml_bytes(root)), "certificate_value")


def test_derived_fields_cannot_be_injected_to_bypass_construction(certificates):
    with pytest.raises(TypeError):
        issuance.PreparedIssuanceCandidate(context(certificates[0]), content(certificates[0]), key_sha256="forged")
    assert_code(lambda: issuance.PreparedIssuanceCandidate({}, content(certificates[0])), "preparation_context")


@pytest.mark.parametrize("change", ["xml_whitespace", "snapshot", "epoch_id", "issuing_unit", "api_base"])
def test_same_issuance_key_detects_drift_instead_of_silent_overwrite(certificates, change):
    prepared = candidate(certificates[0])
    if change == "xml_whitespace":
        other = replace(prepared, xml_bytes=prepared.xml_bytes + b"\n")
        expected = "issued_xml_bytes_changed"
    elif change == "snapshot":
        other = replace(prepared, context=replace(prepared.context, source_snapshot_sha256="b" * 64))
        expected = "source_snapshot_changed"
    elif change == "epoch_id":
        other = replace(prepared, context=replace(prepared.context, credential_epoch=replace(prepared.context.credential_epoch, version_id=OTHER_ID)))
        expected = "credential_epoch_changed"
    elif change == "issuing_unit":
        other = replace(prepared, context=replace(prepared.context, scope=replace(prepared.context.scope, legacy_issuing_unit="new-unit-reference")))
        expected = "issuing_unit_reference_changed"
    else:
        ctx = context(certificates[0], base="https://other-gateway.invalid/phase2")
        other = replace(prepared, context=ctx)
        expected = "api_route_changed"
    assert other.key_sha256 == prepared.key_sha256
    assert other.manifest_sha256 != prepared.manifest_sha256
    assert issuance.compare_prepared_candidates(prepared, other) == (expected,)
    assert prepared.xml_bytes == content(certificates[0])


@pytest.mark.parametrize("index", [1, 2])
def test_credential_rotation_is_drift_even_when_chain_and_version_match(certificates, index):
    first, other = candidate(certificates[0]), candidate(certificates[index])
    assert first.key_sha256 == other.key_sha256
    assert first.manifest_sha256 != other.manifest_sha256
    assert issuance.compare_prepared_candidates(first, other) == ("issued_xml_bytes_changed", "credential_epoch_changed")


@pytest.mark.parametrize("field", ["uuid", "icv", "previous_hash"])
def test_identity_or_chain_metadata_change_is_exact_byte_drift(certificates, field):
    first = candidate(certificates[0])
    root = issuance.parse_diagnostic_xml(first.xml_bytes)
    if field == "uuid":
        root.find("cbc:UUID", namespaces=issuance.NS).text = OTHER_UUID
    elif field == "icv":
        root.xpath("./cac:AdditionalDocumentReference[cbc:ID='ICV']/cbc:UUID", namespaces=issuance.NS)[0].text = "78"
    else:
        root.xpath("./cac:AdditionalDocumentReference[cbc:ID='PIH']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject", namespaces=issuance.NS)[0].text = base64.b64encode(b"different declared PIH, not a verified chain").decode()
    other = replace(first, xml_bytes=xml_bytes(root))
    assert other.key_sha256 == first.key_sha256
    assert other.manifest_sha256 != first.manifest_sha256
    assert issuance.compare_prepared_candidates(first, other) == ("issued_xml_bytes_changed",)
    assert first.artifact.uuid == UUID
    assert first.artifact.icv == 77


def test_declared_seller_change_does_not_hide_as_new_invoice_key(certificates):
    first = candidate(certificates[0])
    other = candidate(certificates[0], selected_scope=scope(seller_tax_id="300000000000004"))
    assert first.key_sha256 == other.key_sha256
    assert issuance.compare_prepared_candidates(first, other) == ("issued_xml_bytes_changed", "seller_tax_id_changed")


@pytest.mark.parametrize("changes", [
    {"doctype": "POS Invoice"}, {"invoice_name": "OTHER"}, {"company_name": "OTHER"},
    {"environment": "Simulation"}, {"chain_id": OTHER_ID}, {"issuance_version": 2},
])
def test_identity_environment_chain_or_version_changes_have_different_keys(certificates, changes):
    first = candidate(certificates[0])
    other = candidate(certificates[0], selected_scope=scope(**changes))
    assert first.key_sha256 != other.key_sha256
    assert issuance.compare_prepared_candidates(first, other) == ("different_issuance_key",)
    assert other.diagnostic_projection()["replay_authorized"] is False


def test_structured_key_cannot_collide_through_separator_concatenation(certificates):
    first = candidate(certificates[0], selected_scope=scope(invoice_name="a-b", company_name="c"))
    other = candidate(certificates[0], selected_scope=scope(invoice_name="a", company_name="b-c"))
    assert first.key_sha256 != other.key_sha256


@pytest.mark.parametrize("value", [None, {}, "saved invoice", [], SimpleNamespace()])
def test_comparison_does_not_trust_mutable_or_serialized_claims(certificates, value):
    prepared = candidate(certificates[0])
    assert_code(lambda: issuance.compare_prepared_candidates(prepared, value), "issuance_candidate")


def test_candidate_can_be_built_without_database_filesystem_http_or_credentials(certificates, monkeypatch):
    ctx, xml = context(certificates[0]), content(certificates[0])
    forbidden = Mock(side_effect=AssertionError("Candidate attempted I/O"))
    monkeypatch.setattr(frappe, "get_doc", forbidden)
    monkeypatch.setattr(frappe, "db", SimpleNamespace(sql=forbidden, commit=forbidden, set_value=forbidden), raising=False)
    monkeypatch.setattr(requests, "post", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)
    prepared = issuance.PreparedIssuanceCandidate(ctx, xml)
    assert prepared.xml_bytes == xml
    forbidden.assert_not_called()
