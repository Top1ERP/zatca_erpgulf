"""Local consistency of certificate taxpayer claims, not CA trust or revocation.

The ZATCA security profile identifies the VAT owner; the app's CSR template uses
DirectoryName UID. Recognize that explicit legacy encoding and organizationId,
never infer a taxpayer from a free-text common/organization name.
"""

from cryptography import x509
from cryptography.x509.oid import NameOID, ObjectIdentifier


ORGANIZATION_IDENTIFIER = ObjectIdentifier('2.5.4.97')
TAXPAYER_OIDS = (ORGANIZATION_IDENTIFIER, NameOID.USER_ID)


class CredentialIdentityError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require_certificate_taxpayer(certificate, expected_tax_id):
    """All recognized claims must agree with the declared saved Company VAT ID.

    This compares identities only. VAT-format/accounting rules and CA/EGS trust
    remain separate; no network OCSP/CRL call or certificate repair is performed.
    """
    if not isinstance(expected_tax_id, str) or not expected_tax_id.strip():
        raise CredentialIdentityError('credential_taxpayer_missing')
    names = [certificate.subject]
    try:
        alternative = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        pass
    else:
        names.extend(alternative.get_values_for_type(x509.DirectoryName))
    values = [attribute.value for name in names for oid in TAXPAYER_OIDS
              for attribute in name.get_attributes_for_oid(oid)]
    if not values or any(not isinstance(value, str) or not value.strip() for value in values):
        raise CredentialIdentityError('credential_taxpayer_missing')
    if {value.strip() for value in values} != {expected_tax_id.strip()}:
        raise CredentialIdentityError('credential_taxpayer_mismatch')
