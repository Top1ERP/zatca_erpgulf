"""Prevent native key/auth copies from falling back to legacy owner issuance.

The indexed registry contains public fingerprints only. Ordinary legacy rows are
unchanged when their material has no native registration. No root-SQL sandbox,
key discovery, credential repair, cache or database connection is created here.
Crypto imports are lazy; ordinary unchanged Company forms need no crypto graph.
"""

from .credential_material import NATIVE_OWNER_MARKER, CredentialConfigurationError


def _material_evidence(record, environment=None):
    import base64
    import hashlib
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from .certificate_evidence import parse_public_certificate_text
    from .credential_snapshot import authentication_certificate_der
    from .credential_identity import claimed_egs_identity_key, declared_egs_identity_key

    getter = getattr(record, 'get', None)
    if not callable(getter):
        getter = record.values.get
    result = set()
    identities = set()
    if environment is None:
        environment = getter('custom_select')
    if type(environment) is str:
        environment = environment.strip()  # Match the saved API route policy.

    def retain(material):
        public = material.public_key() if callable(getattr(material,'public_key',None)) else material
        result.add(hashlib.sha256(public.public_bytes(serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest())
        if environment in ('Sandbox','Simulation','Production') and hasattr(material,'extensions'):
            try:
                identities.add(claimed_egs_identity_key(material,environment))
            except Exception:
                pass

    # Invalid legacy material remains the existing validator's responsibility.
    # Other independently parseable fields must still be checked for a copied
    # native identity; one malformed alias cannot conceal another valid field.
    for name, loader in (
        ('custom_private_key', lambda value: serialization.load_pem_private_key(value.encode(), password=None).public_key()),
        ('custom_public_key', lambda value: serialization.load_pem_public_key(value.encode())),
        ('custom_csr_data', lambda value: x509.load_pem_x509_csr(base64.b64decode(value, validate=True))),
        ('custom_certificate', lambda value: parse_public_certificate_text(value)[0]),
        ('custom_certficate', lambda value: parse_public_certificate_text(value)[0]),
        *((name, lambda value: x509.load_der_x509_certificate(authentication_certificate_der('Basic '+value)))
          for name in ('custom_basic_auth_from_csid', 'custom_basic_auth_from_production', 'custom_final_auth_csid')),
    ):
        value = getter(name)
        if type(value) is not str or not 0 < len(value) <= 512 * 1024:
            continue
        try:
            retain(loader(value))
        except Exception:
            continue
    config = getter('custom_csr_config')
    if type(config) is str and 0 < len(config) <= 65536 and environment in ('Sandbox','Simulation','Production'):
        try:
            from .csr_draft import _configuration
            values = _configuration(config)
            identities.add(declared_egs_identity_key(environment,values['csr.organization.identifier'],values['csr.serial.number']))
        except Exception:
            pass
    return tuple(sorted(result)), tuple(sorted(identities))


def _fingerprints(record):
    return _material_evidence(record)[0]


def has_registered_native_material(runtime, record, *, environment=None):
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
        fingerprints, identities = _material_evidence(record,environment)
        if not fingerprints and not identities:
            return False
        clauses, parameters = [], []
        for column, values in (('public_key_sha256', fingerprints), ('egs_identity_key', identities)):
            if values:
                clauses.append(column+' IN ('+','.join('%s' for _ in values)+')')
                parameters.extend(values)
        rows = runtime.db.sql('SELECT name FROM `tabZATCA Issuing Chain` WHERE ('+' OR '.join(clauses)+
            ') AND (onboarding_header IS NOT NULL OR active=1) LIMIT 1 LOCK IN SHARE MODE NOWAIT', tuple(parameters), as_dict=True)
        matched = bool(rows)
    except Exception:
        failed = True
    if failed:
        raise CredentialConfigurationError('native_owner_registry_review')
    return matched
