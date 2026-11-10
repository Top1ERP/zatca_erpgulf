"""Shared in-memory signing and QR sequence for existing invoice generators.

The caller prepares the invoice and selects its saved issuer. This module owns
neither identity allocation nor credentials, files, transactions, API routing or
submission. Keep those boundaries in the Sales/POS/Debug/Compliance adapters.
"""

import base64
from dataclasses import dataclass, fields
from typing import Callable


@dataclass(frozen=True, repr=False)
class SigningTools:
    """Capture existing adapter functions without retaining its namespace.

    Legacy modules expose these imports to integrations and tests. Bind their
    current functions at entry instead of bypassing those compatibility points
    or caching them globally. This is not an atomic credential snapshot.
    """

    removetags: Callable
    canonicalize_xml: Callable
    getinvoicehash: Callable
    digital_signature: Callable
    extract_certificate_details: Callable
    certificate_hash: Callable
    signxml_modify: Callable
    generate_signed_properties_hash: Callable
    populate_the_ubl_extensions_output: Callable
    generate_tlv_xml: Callable
    get_tlv_for_value: Callable
    update_qr_toxml: Callable

    @classmethod
    def from_namespace(cls, namespace):
        """Read only declared operation names; never copy documents or keys."""
        operations = {item.name: namespace[item.name] for item in fields(cls)}
        if not all(callable(operation) for operation in operations.values()):
            raise TypeError("invalid_signing_tools")
        return cls(**operations)


@dataclass(frozen=True, repr=False)
class SignedInvoiceXml:
    """Unformatted artifact, not evidence of submission or authority acceptance."""

    encoded_hash: str
    qr_payload: str
    xml: str

    def __repr__(self):
        return "<SignedInvoiceXml protected local artifact>"


def encode_qr_payload(tlv_data, encode_tag):
    """Keep the producer's tag order and existing UTF-8/binary TLV policy."""
    return base64.b64encode(
        b"".join(encode_tag(tag, value) for tag, value in tlv_data.items())
    ).decode("utf-8")


def sign_invoice_xml(file_content, company_abbr, source_doc, *, tools: SigningTools):
    """Run the existing signing sequence once, propagating failures unchanged.

    Preserve invoice exclusions/canonicalization, certificate and property hash
    rules, owner arguments, function order and final QR embedding. Formatting
    happens later at each adapter's existing file or temporary-artifact boundary.
    Synthetic Company onboarding keeps its separate hash-stabilization check.
    """
    tag_removed_xml = tools.removetags(file_content)
    canonicalized_xml = tools.canonicalize_xml(tag_removed_xml)
    hash1, encoded_hash = tools.getinvoicehash(canonicalized_xml)
    encoded_signature = tools.digital_signature(hash1, company_abbr, source_doc)
    issuer_name, serial_number = tools.extract_certificate_details(company_abbr, source_doc)
    encoded_certificate_hash = tools.certificate_hash(company_abbr, source_doc)
    modified_xml, namespaces, signing_time = tools.signxml_modify(
        company_abbr, file_content, source_doc
    )
    signed_properties_hash = tools.generate_signed_properties_hash(
        signing_time, issuer_name, serial_number, encoded_certificate_hash
    )
    signed_xml = tools.populate_the_ubl_extensions_output(
        modified_xml, encoded_signature, namespaces, signed_properties_hash,
        encoded_hash, company_abbr, source_doc,
    )
    qr_payload = encode_qr_payload(
        tools.generate_tlv_xml(signed_xml, company_abbr, source_doc),
        tools.get_tlv_for_value,
    )
    xml = tools.update_qr_toxml(signed_xml, qr_payload, company_abbr)
    return SignedInvoiceXml(encoded_hash, qr_payload, xml)
