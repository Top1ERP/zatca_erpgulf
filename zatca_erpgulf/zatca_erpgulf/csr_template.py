"""Shared local CSR structure; no source loading, key generation or persistence.

Keep the legacy subject/extension ordering and encoding explicit. Callers own
configuration validation, environment policy, key custody and error presentation.
This template is not certificate issuance or regulatory acceptance evidence.
"""

import asn1
from types import MappingProxyType
from cryptography import x509
from cryptography.x509.oid import NameOID, ObjectIdentifier


CSR_LABELS = MappingProxyType({
    "Sandbox": "TESTZATCA-Code-Signing",
    "Simulation": "PREZATCA-Code-Signing",
    "Production": "ZATCA-Code-Signing",
})
CSR_EXTENSION_OID = ObjectIdentifier("1.3.6.1.4.1.311.20.2")


def encode_customoid(custom_string):
    """Preserve the existing UTF8String encoding of the signing label."""
    encoder = asn1.Encoder()
    encoder.start()
    encoder.write(custom_string, asn1.Numbers.UTF8String)
    return encoder.output()


def csr_attributes(values, customoid):
    """Return ordered subject, signing-label extension and directory-name SAN."""
    custom_extension = x509.extensions.UnrecognizedExtension(CSR_EXTENSION_OID, customoid)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, values.get("csr.country.name")),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, values.get("csr.organization.unit.name")),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, values.get("csr.organization.name")),
        x509.NameAttribute(NameOID.COMMON_NAME, values.get("csr.common.name")),
    ])
    alternative = x509.SubjectAlternativeName([x509.DirectoryName(x509.Name([
        x509.NameAttribute(NameOID.SURNAME, values.get("csr.serial.number")),
        x509.NameAttribute(NameOID.USER_ID, values.get("csr.organization.identifier")),
        x509.NameAttribute(NameOID.TITLE, values.get("csr.invoice.type")),
        x509.NameAttribute(ObjectIdentifier("2.5.4.26"), values.get("csr.location.address")),
        x509.NameAttribute(NameOID.BUSINESS_CATEGORY, values.get("csr.industry.business.category")),
    ]))])
    return subject, custom_extension, alternative


def csr_builder(values, customoid):
    """Build without a key; new preparation can validate before generating one."""
    subject, custom_extension, alternative = csr_attributes(values, customoid)
    return (x509.CertificateSigningRequestBuilder().subject_name(subject)
            .add_extension(custom_extension, critical=False)
            .add_extension(alternative, critical=False))
