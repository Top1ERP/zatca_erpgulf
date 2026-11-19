"""Prevent native key/auth copies from falling back to legacy owner issuance.

The indexed registry contains public fingerprints only. Ordinary legacy rows are
unchanged when their material has no native registration. No root-SQL sandbox,
key discovery, credential repair, cache or database connection is created here.
Crypto imports are lazy; ordinary unchanged Company forms need no crypto graph.
"""

from .credential_material import NATIVE_OWNER_MARKER, CredentialConfigurationError


def _fingerprints(record):
    import base64
    import hashlib
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from .certificate_evidence import parse_public_certificate_text
    from .credential_snapshot import authentication_certificate_der

    getter = getattr(record, 'get', None)
    if not callable(getter):
        getter = record.values.get
    result = set()

    def retain(public):
        result.add(hashlib.sha256(public.public_bytes(serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest())

    # Invalid legacy material remains the existing validator's responsibility.
    # Other independently parseable fields must still be checked for a copied
    # native identity; one malformed alias cannot conceal another valid field.
    for name, loader in (
        ('custom_private_key', lambda value: serialization.load_pem_private_key(value.encode(), password=None).public_key()),
        ('custom_public_key', lambda value: serialization.load_pem_public_key(value.encode())),
        ('custom_csr_data', lambda value: x509.load_pem_x509_csr(base64.b64decode(value, validate=True)).public_key()),
        ('custom_certificate', lambda value: parse_public_certificate_text(value)[0].public_key()),
        ('custom_certficate', lambda value: parse_public_certificate_text(value)[0].public_key()),
        *((name, lambda value: x509.load_der_x509_certificate(authentication_certificate_der('Basic '+value)).public_key())
          for name in ('custom_basic_auth_from_csid', 'custom_basic_auth_from_production', 'custom_final_auth_csid')),
    ):
        value = getter(name)
        if type(value) is not str or not 0 < len(value) <= 512 * 1024:
            continue
        try:
            retain(loader(value))
        except Exception:
            continue
    return tuple(sorted(result))


def has_registered_native_material(runtime, record):
    """Check saved/application projections; never accept a client fingerprint."""
    failed = False
    try:
        # Installed metadata gates old unmigrated installations. After the owner
        # marker exists, a failed registry query is review, never legacy fallback.
        get_meta = getattr(runtime, 'get_meta', None)
        if not callable(get_meta):
            return False
        meta = get_meta(record.doctype)
        if meta.has_field(NATIVE_OWNER_MARKER) is not True:
            return False
        fingerprints = _fingerprints(record)
        if not fingerprints:
            return False
        rows = runtime.db.sql('SELECT name FROM `tabZATCA Issuing Chain` WHERE public_key_sha256 IN ('+
            ','.join('%s' for _ in fingerprints)+') AND (onboarding_header IS NOT NULL OR active=1) '
            'LIMIT 1 LOCK IN SHARE MODE NOWAIT', fingerprints, as_dict=True)
        matched = bool(rows)
    except Exception:
        failed = True
    if failed:
        raise CredentialConfigurationError('native_owner_registry_review')
    return matched
