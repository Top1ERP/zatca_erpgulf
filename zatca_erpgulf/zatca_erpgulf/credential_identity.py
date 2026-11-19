"""Local consistency of certificate taxpayer claims, not CA trust or revocation.

The ZATCA security profile identifies the VAT owner; the app's CSR template uses
DirectoryName UID. Recognize that explicit legacy encoding and organizationId,
never infer a taxpayer from a free-text common/organization name.
"""

from cryptography import x509
from cryptography.x509.oid import NameOID, ObjectIdentifier
import hashlib
import json


ORGANIZATION_IDENTIFIER = ObjectIdentifier('2.5.4.97')
TAXPAYER_OIDS = (ORGANIZATION_IDENTIFIER, NameOID.USER_ID)


class CredentialIdentityError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _names(certificate):
    names = [certificate.subject]
    try:
        alternative = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        pass
    else:
        names.extend(alternative.get_values_for_type(x509.DirectoryName))
    return names


def _taxpayer_claims(names):
    values = [attribute.value for name in names for oid in TAXPAYER_OIDS
              for attribute in name.get_attributes_for_oid(oid)]
    if not values or any(not isinstance(value, str) or not value.strip() for value in values):
        raise CredentialIdentityError('credential_taxpayer_missing')
    return {value.strip() for value in values}


def require_certificate_taxpayer(certificate, expected_tax_id):
    """All recognized claims must agree with the declared saved Company VAT ID.

    This compares identities only. VAT-format/accounting rules and CA/EGS trust
    remain separate; no network OCSP/CRL call or certificate repair is performed.
    """
    if not isinstance(expected_tax_id, str) or not expected_tax_id.strip():
        raise CredentialIdentityError('credential_taxpayer_missing')
    if _taxpayer_claims(_names(certificate)) != {expected_tax_id.strip()}:
        raise CredentialIdentityError('credential_taxpayer_mismatch')


def declared_egs_identity_key(environment, taxpayer, serial):
    """Local declared identity independent of owner row or signing-key rotation.

    It is not complete legacy/remote history or a NEW_EGS authorization. Renewal
    must retain its chain rather than reserve this identity on another owner.
    """
    if type(environment) is not str or environment not in ('Sandbox','Simulation','Production'):
        raise CredentialIdentityError('credential_egs_identity')
    for value in (taxpayer, serial):
        if (type(value) is not str or not 0 < len(value) <= 140 or value != value.strip()
                or any(ord(c) < 32 for c in value)):
            raise CredentialIdentityError('credential_egs_identity')
    encoded = json.dumps([environment,taxpayer,serial],ensure_ascii=False,separators=(',',':')).encode()
    return hashlib.sha256(b'zatca-egs-identity/v1\0'+encoded).hexdigest()


def claimed_egs_identity_key(certificate_or_csr, environment):
    """Read the existing DirectoryName surname/UID profile without trusting it."""
    names = _names(certificate_or_csr)
    taxpayers = _taxpayer_claims(names)
    serials = [attribute.value for name in names[1:] for attribute in name.get_attributes_for_oid(NameOID.SURNAME)]
    if len(taxpayers) != 1 or len(serials) != 1:
        raise CredentialIdentityError('credential_egs_identity')
    return declared_egs_identity_key(environment, next(iter(taxpayers)), serials[0])
