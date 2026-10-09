"""Synthetic metadata evidence only; no cryptographic acceptance fixtures."""

import base64
import copy
import hashlib
from dataclasses import FrozenInstanceError

from lxml import etree
import pytest

from zatca_erpgulf.zatca_erpgulf import artifact_evidence as evidence


UUID = "b05809d9-7851-4767-b7e9-47af44c80cb9"
OTHER_UUID = "fe72f76e-12da-45fd-ab71-1a7bc0e113d5"
SELLER = "300000000000003"
DIGEST = base64.b64encode(b"d" * 32).decode()
PIH = base64.b64encode(b"legacy-initial-seed-not-validated-here").decode()


def node(parent, namespace, tag, text=None, **attrs):
    result = etree.SubElement(parent, f"{{{evidence.NS[namespace]}}}{tag}", **attrs)
    result.text = text
    return result


def artifact_root(*, invoice_id="INV-TEST", uuid=UUID, icv="77", seller=SELLER, qr=True):
    root = etree.Element(f"{{{evidence.NS['ubl']}}}Invoice", nsmap=evidence.NS)
    node(root, "cbc", "ID", invoice_id)
    node(root, "cbc", "UUID", uuid)
    node(root, "cbc", "Note", "اختبار محلي فقط—not a real signed invoice")
    # Buyer appears first to expose unsafe global CompanyID/UUID selection.
    buyer = node(node(root, "cac", "AccountingCustomerParty"), "cac", "Party")
    node(node(buyer, "cac", "PartyTaxScheme"), "cbc", "CompanyID", "BUYER-NOT-SELLER")
    for label, value in (("ICV", icv), ("PIH", PIH), ("QR", "synthetic-QR" if qr else "")):
        ref = node(root, "cac", "AdditionalDocumentReference")
        node(ref, "cbc", "ID", label)
        if label == "ICV":
            node(ref, "cbc", "UUID", value)
        else:
            node(node(ref, "cac", "Attachment"), "cbc", "EmbeddedDocumentBinaryObject", value)
    party = node(node(root, "cac", "AccountingSupplierParty"), "cac", "Party")
    tax = node(party, "cac", "PartyTaxScheme")
    node(tax, "cbc", "CompanyID", seller)
    node(node(tax, "cac", "TaxScheme"), "cbc", "ID", "VAT")
    signed = node(node(root, "ds", "Signature"), "ds", "SignedInfo")
    trap = node(signed, "ds", "Reference", Id="xadesSignedProperties")
    node(trap, "ds", "DigestValue", "DO-NOT-SELECT-PROPERTIES-DIGEST")
    ref = node(signed, "ds", "Reference", Id="invoiceSignedData")
    node(ref, "ds", "DigestMethod", Algorithm=evidence.SHA256_URI)
    node(ref, "ds", "DigestValue", DIGEST)
    return root


def xml_bytes(root=None):
    return etree.tostring(root if root is not None else artifact_root(), encoding="UTF-8", xml_declaration=True)


def saved_identity(**changes):
    values = dict(doctype="Sales Invoice", invoice_name="INV-TEST", company_name="TEST",
                  seller_tax_id=SELLER, environment="Production", uuid=UUID, icv=77,
                  issuing_unit="existing-chain", status="REPORTED")
    values.update(changes)
    return evidence.SavedInvoiceIdentity(**values)


def test_explicit_identity_paths_encoding_and_exact_bytes():
    content = xml_bytes()
    found = evidence.inspect_invoice_artifact(content)
    assert (found.invoice_id, found.uuid, found.icv, found.seller_tax_id) == ("INV-TEST", UUID, 77, SELLER)
    assert found.invoice_digest == DIGEST
    assert found.previous_hash == PIH
    assert found.qr_present
    assert found.byte_length == len(content)
    assert found.file_sha256 == hashlib.sha256(content).hexdigest()
    assert evidence.compare_saved_identity(saved_identity(), found) == ()
    with pytest.raises(FrozenInstanceError):
        found.uuid = OTHER_UUID
    assert DIGEST not in repr(found) and PIH not in repr(found)


def test_fingerprint_is_not_the_invoice_digest_and_preserves_whitespace():
    first = xml_bytes()
    second = first.replace(b"><", b">\n<")
    a, b = map(evidence.inspect_invoice_artifact, (first, second))
    assert a.file_sha256 != b.file_sha256
    assert a.invoice_digest == b.invoice_digest
    assert evidence.compare_saved_identity(saved_identity(), b) == ()


@pytest.mark.parametrize("encoding", ["UTF-8", "UTF-16", "UTF-16LE"])
def test_declared_encoding_is_preserved_as_bytes(encoding):
    content = etree.tostring(artifact_root(), encoding=encoding, xml_declaration=True)
    result = evidence.inspect_invoice_artifact(content)
    assert result.uuid == UUID
    assert result.file_sha256 == hashlib.sha256(content).hexdigest()


def test_reject_resolver_never_falls_back_to_loading_resources():
    parser = etree.XMLParser(load_dtd=True, resolve_entities=True)
    parser.resolvers.add(evidence._RejectExternalResources())
    with pytest.raises(evidence.ArtifactEvidenceError, match="^xml_external_resource$"):
        etree.fromstring(b'<!DOCTYPE doc SYSTEM "file:///never-read-this.dtd"><doc/>', parser)


@pytest.mark.parametrize("content, code", [
    ("<Invoice/>", "xml_bytes_required"), (None, "xml_bytes_required"),
    (b"", "xml_size"), (b"<", "xml_syntax"), (b"<Invoice/>", "xml_root"),
    (b"<Secret>DO-NOT-LEAK</Wrong>", "xml_syntax"),
])
def test_static_errors_never_include_parser_source(content, code):
    with pytest.raises(evidence.ArtifactEvidenceError) as caught:
        evidence.inspect_invoice_artifact(content)
    assert str(caught.value) == code
    assert caught.value.code == code


def test_size_limit_before_parsing(monkeypatch):
    monkeypatch.setattr(evidence, "MAX_XML_BYTES", 10)
    with pytest.raises(evidence.ArtifactEvidenceError, match="^xml_size$"):
        evidence.inspect_invoice_artifact(b"x" * 11)


@pytest.mark.parametrize("declaration", [
    '<!DOCTYPE ubl:Invoice [<!ENTITY leak SYSTEM "file:///private-do-not-read">]>',
    '<!DOCTYPE ubl:Invoice SYSTEM "https://example.invalid/do-not-fetch">',
    '<!DOCTYPE ubl:Invoice [<!ENTITY leak "DO-NOT-LEAK">]>',
])
def test_doctype_is_never_accepted(declaration):
    content = xml_bytes().replace(b"?>", b"?>\n" + declaration.encode(), 1)
    with pytest.raises(evidence.ArtifactEvidenceError, match="^xml_doctype$"):
        evidence.inspect_invoice_artifact(content)


PATHS = (
    ("./cbc:ID", "invoice_id"), ("./cbc:UUID", "invoice_uuid"),
    ("./cac:AdditionalDocumentReference[cbc:ID='ICV']/cbc:UUID", "invoice_icv"),
    ("./cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID", "seller_tax_id"),
    (".//ds:Reference[@Id='invoiceSignedData']/ds:DigestValue", "invoice_digest"),
    ("./cac:AdditionalDocumentReference[cbc:ID='PIH']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject", "previous_hash"),
)


@pytest.mark.parametrize("xpath, code", PATHS)
@pytest.mark.parametrize("mutation", ["missing", "duplicate", "blank", "nested-text"])
def test_required_scalar_values_are_unambiguous(xpath, code, mutation):
    root = artifact_root()
    target = root.xpath(xpath, namespaces=evidence.NS)[0]
    if mutation == "missing":
        target.getparent().remove(target)
    elif mutation == "duplicate":
        target.getparent().append(copy.deepcopy(target))
    elif mutation == "blank":
        target.text = " "
    else:
        node(target, "cbc", "Note", "nested")
    with pytest.raises(evidence.ArtifactEvidenceError, match=f"^{code}$"):
        evidence.inspect_invoice_artifact(xml_bytes(root))


@pytest.mark.parametrize("xpath, code", [
    ("./cac:AccountingSupplierParty", "seller_tax_id"),
    ("./cac:AdditionalDocumentReference[cbc:ID='ICV']", "invoice_icv"),
    ("./cac:AdditionalDocumentReference[cbc:ID='PIH']", "previous_hash"),
    (".//ds:Reference[@Id='invoiceSignedData']", "invoice_digest_reference"),
])
@pytest.mark.parametrize("empty_duplicate", [False, True])
def test_duplicate_containers_fail_even_when_other_container_is_empty(xpath, code, empty_duplicate):
    root = artifact_root()
    target = root.xpath(xpath, namespaces=evidence.NS)[0]
    duplicate = copy.deepcopy(target)
    if empty_duplicate:
        for child in list(duplicate):
            if child.tag != f"{{{evidence.NS['cbc']}}}ID":
                duplicate.remove(child)
    target.getparent().append(duplicate)
    with pytest.raises(evidence.ArtifactEvidenceError, match=f"^{code}$"):
        evidence.inspect_invoice_artifact(xml_bytes(root))


@pytest.mark.parametrize("uuid", ["Not Submitted", "garbage", "0", "", UUID.replace("-", "")])
def test_bad_artifact_uuid_is_not_a_new_identity_candidate(uuid):
    with pytest.raises(evidence.ArtifactEvidenceError, match="invoice_uuid"):
        evidence.inspect_invoice_artifact(xml_bytes(artifact_root(uuid=uuid)))


@pytest.mark.parametrize("icv", ["0", "-1", "1.2", "one", "", "9" * 65])
def test_bad_artifact_icv_is_not_normalized_to_zero(icv):
    with pytest.raises(evidence.ArtifactEvidenceError, match="invoice_icv"):
        evidence.inspect_invoice_artifact(xml_bytes(artifact_root(icv=icv)))


@pytest.mark.parametrize("value", ["Not Found", "%%%", base64.b64encode(b"short").decode()])
def test_digest_must_decode_to_sha256_length(value):
    root = artifact_root()
    root.xpath(".//ds:Reference[@Id='invoiceSignedData']/ds:DigestValue", namespaces=evidence.NS)[0].text = value
    with pytest.raises(evidence.ArtifactEvidenceError, match="^invoice_digest_format$"):
        evidence.inspect_invoice_artifact(xml_bytes(root))


def test_wrong_digest_algorithm_does_not_use_another_reference():
    root = artifact_root()
    root.xpath(".//ds:Reference[@Id='invoiceSignedData']/ds:DigestMethod", namespaces=evidence.NS)[0].set("Algorithm", "sha1")
    with pytest.raises(evidence.ArtifactEvidenceError, match="^invoice_digest_method$"):
        evidence.inspect_invoice_artifact(xml_bytes(root))


def test_binary_whitespace_and_empty_optional_qr_are_only_metadata_checks():
    root = artifact_root(qr=False)
    root.xpath(".//ds:Reference[@Id='invoiceSignedData']/ds:DigestValue", namespaces=evidence.NS)[0].text = f"\n {DIGEST[:20]}\n{DIGEST[20:]} "
    found = evidence.inspect_invoice_artifact(xml_bytes(root))
    assert found.invoice_digest == DIGEST
    assert not found.qr_present


@pytest.mark.parametrize("mutation", ["duplicate-ref", "empty-duplicate-ref", "duplicate-value", "duplicate-id"])
def test_optional_qr_is_not_allowed_to_be_ambiguous(mutation):
    root = artifact_root()
    ref = root.xpath("./cac:AdditionalDocumentReference[cbc:ID='QR']", namespaces=evidence.NS)[0]
    if mutation in ("duplicate-ref", "empty-duplicate-ref"):
        duplicate = copy.deepcopy(ref)
        if mutation == "empty-duplicate-ref":
            duplicate.remove(duplicate[1])
        root.append(duplicate)
    elif mutation == "duplicate-value":
        ref[1].append(copy.deepcopy(ref[1][0]))
    else:
        ref.append(copy.deepcopy(ref[0]))
    with pytest.raises(evidence.ArtifactEvidenceError, match="^qr_ambiguous$"):
        evidence.inspect_invoice_artifact(xml_bytes(root))


@pytest.mark.parametrize("changes, code", [
    ({"invoice_name": "OTHER"}, "invoice_id_mismatch"),
    ({"seller_tax_id": ""}, "saved_tax_id_missing"),
    ({"seller_tax_id": "BUYER-NOT-SELLER"}, "seller_tax_id_mismatch"),
    ({"uuid": None}, "saved_uuid_missing"), ({"uuid": "Not Submitted"}, "saved_uuid_missing"),
    ({"uuid": "arbitrary-text"}, "saved_uuid_invalid"),
    ({"uuid": OTHER_UUID}, "saved_uuid_mismatch"),
    ({"icv": None}, "saved_icv_missing"), ({"icv": ""}, "saved_icv_missing"),
    ({"icv": 0}, "saved_icv_invalid"), ({"icv": False}, "saved_icv_invalid"),
    ({"icv": "77.0"}, "saved_icv_invalid"), ({"icv": 78}, "saved_icv_mismatch"),
    ({"icv": "9" * 65}, "saved_icv_invalid"),
    ({"issuing_unit": ""}, "saved_unit_missing"),
    ({"issuing_unit": " "}, "saved_unit_missing"),
    ({"environment": ""}, "saved_environment_unknown"),
])
def test_saved_identity_conflicts_are_reported_without_repair(changes, code):
    saved = saved_identity(**changes)
    before = repr(saved)
    assert evidence.compare_saved_identity(saved, evidence.inspect_invoice_artifact(xml_bytes())) == (code,)
    assert repr(saved) == before


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
def test_compatible_normalization_does_not_rewrite_saved_identity(environment):
    saved = saved_identity(uuid=f" {UUID.upper()} ", icv="077", seller_tax_id=f" {SELLER} ", environment=environment)
    assert evidence.compare_saved_identity(saved, evidence.inspect_invoice_artifact(xml_bytes())) == ()


def test_identity_comparison_accumulates_independent_conflicts():
    saved = saved_identity(invoice_name="OTHER", uuid=OTHER_UUID, icv=78, seller_tax_id="OTHER-VAT")
    assert evidence.compare_saved_identity(saved, evidence.inspect_invoice_artifact(xml_bytes())) == (
        "invoice_id_mismatch", "seller_tax_id_mismatch", "saved_uuid_mismatch", "saved_icv_mismatch",
    )
