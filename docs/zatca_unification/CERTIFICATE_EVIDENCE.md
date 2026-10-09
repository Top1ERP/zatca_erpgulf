# Embedded public certificate observations — increment 12

Development only. No current credential, private key, saved certificate field,
tenant invoice, counter, file or status was changed. No tenant inspection,
schema migration, deployment, worker restart, SDK or remote request was executed.

## Why current settings are not historical evidence

The live helpers resolve saved credential ownership before signing, certificate
detail/digest calculation, UBL certificate insertion and HTTP authentication.
Those separate resolutions are not one atomic, version-pinned issuance snapshot.
Today's certificate may be renewed or belong to a changed configuration; reading
it again cannot establish which credential version was used for an older XML.
The legacy issuing-unit fingerprint also cannot substitute for a certificate
epoch and its purpose/endpoint/owner provenance.

This increment extracts a stable **observed embedded certificate identity**, not
a verified signing epoch or a durable issuance ledger. Neither the XML's saved
status nor its declared certificate proves that a trusted key signed it.

## Pure, bounded observations

`certificate_evidence.py` shares the existing bytes-only, namespace-aware,
no-DTD/no-external-resource parser with metadata inspection. It accepts one
`ds:Signature` in the canonical UBL extension location used by the live Sales/POS
builders. Duplicate/alternate signatures, unsafe/duplicate signature IDs, a
missing or ambiguous direct `invoiceSignedData` reference, nonempty reference
URI, duplicate/misplaced certificates and nonscalar certificate values remain
static failures. These are structural constraints, not signature verification.

One `ds:KeyInfo/ds:X509Data/ds:X509Certificate` is decoded using strict Base64
with only XML's ASCII whitespace removed. Certificate text is bounded at 128 KiB,
decoded DER at 64 KiB. X.509 parsing and DER round-trip comparison reject invalid
or trailing/noncanonical representations rather than selecting a parsed prefix.
Backend exceptions become static codes without certificate text or parser errors.

The immutable, fingerprint-only projection contains:

| Observation | Meaning and limit |
| --- | --- |
| `der_sha256` | SHA-256 of the observed exact DER; a certificate-version marker, not a verified credential epoch |
| `public_key_sha256` | SHA-256 of DER SubjectPublicKeyInfo; distinguishes changed keys from certificate renewal with the same key |
| `element_text_sha256` | SHA-256 of parsed ASCII element text, preserving its whitespace; XML parser line-ending/entity normalization means this is not the raw XML lexeme or a saved credential-field fingerprint |
| `der_byte_length` | Size of the observed decoded certificate only |

The implementation uses the longstanding X.509 DER loading and public-byte APIs
documented by [cryptography](https://cryptography.io/en/41.0.4/x509/reference/).
It introduces no version-specific UTC-validity accessor or dependency change.
Local tests use the installed cryptography 46.0.5; the declared 41–46 range and
ERPNext 16's actual dependency/runtime combination are not fully exercised.

These fingerprints are **not** ZATCA's certificate digest or SignedProperties
digest. No digest convention, certificate subject/issuer/validity/trust chain,
key authorization, signature algorithm, signature value, QR or remote acceptance
is validated or changed. No expiry/issue-time decision is inferred. Raw DER,
subject/issuer names, tokens and public/private key material are not returned.

## Opt-in inventory integration

Explicit `include_certificate=True` on the existing internal, non-whitelisted
`inspect_saved_invoice_artifacts` adds these observations to each requested XML
source: private attached files, optional known generated file and optional stored
response XML. Existing defaults and scopes remain unchanged when disabled.
Non-boolean options fail with an Arabic-translated message.

Invoice/Company/File/counter read permissions remain required. Generated-file
mode still additionally requires the standard System Manager gate. Certificate
observation never resolves current Company/device credentials, reads secret
fields or falls back to a saved Company certificate if the XML has none.

Reports retain each source, count distinct certificate/key fingerprints and flag
`artifact_certificate_versions_differ` without selecting a preferred/newest
certificate. A renewed certificate can share a public key without sharing DER.
Different original/cleared certificates may have a legitimate explanation;
`CONFLICT` denotes unresolved provenance, not a regulatory rejection verdict.

Missing/invalid certificate evidence remains a reconciliation issue. It does not
erase invoice identity errors or cause new UUID/ICV allocation. Even a matching
DER marker leaves `credential_epoch_verified`, `owner_verified`,
`purpose_verified`, `trust_verified`, `signature_verified`,
`remote_acceptance_verified` and `replay_authorized` false.

## Verification and next gate

85 new local cases cover valid public DER, certificate renewal and key changes,
XML encodings/whitespace, bounded invalid Base64/DER, source/path/reference/ID
ambiguity, immutable fingerprint privacy, static errors, strict options, Arabic
messages, no-current-credential/no-write behavior, Sales/POS permissions, and
composition across attached/generated/response XML and historical counters.
Synthetic certificates are self-signed and the fixture's XML signature is
deliberately invalid: observations must never certify trust or acceptance.

The combined selected suite passes 1,650 cases locally on v15/Python 3.10. No
actual v16/site/SQL/SDK/HTTP integration result is claimed.

Next define the immutable issuance/version contract and explicit provenance
needed to bind owner, endpoint, purpose, credential epoch, exact bytes, UUID/ICV
and PIH. A verified epoch must come from controlled issuance evidence, not a
current-settings lookup or this observed marker alone. Rehearse historical
inventory/mapping on restored data before enabling migration, dispatch locks or
exact-byte replay. The legacy live writer/signing/request behavior is unchanged.
