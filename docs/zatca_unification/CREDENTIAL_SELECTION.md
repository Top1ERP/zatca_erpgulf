# Credential selection — development increment 4

This is a staged source refactor, not a deployment, CSID migration, or proof of
ZATCA acceptance. No saved customer setting or certificate was changed.

## Implemented boundary

`credential_material.py` holds pure field-selection policies and immutable
provenance objects with secret values excluded from their printable representation.
`credential_settings.py` resolves saved records and parses cryptographic material
without saves, commits, field repair, or HTTP.

The shared policy is now used by the signing helpers in `sign_invoice_first.py`:
private-key selection, certificate details/hash, UBL certificate population,
QR public key, and QR certificate signature. The dedicated Compliance HTTP
function uses the same owner policy. Existing call signatures remain compatible.
Increment 5 also connects the four primary live reporting/clearance adapters as
described in [SUBMISSION_CONTEXT.md](SUBMISSION_CONTEXT.md); increment 6 connects
four existing-XML adapters in [LEGACY_XML_AND_ICV.md](LEGACY_XML_AND_ICV.md).
Increment 7 connects the four without-XML/background reporting adapters in
[GENERATION_AND_COMPLIANCE.md](GENERATION_AND_COMPLIANCE.md). CSID issuance,
wizard flows, ICV migration, and an atomic credential-version snapshot remain pending.

Increment 12 adds independent observations of the public certificate embedded in
historical XML, without reading today's credentials. This is not a verified
epoch or an atomic signing/request snapshot; see
[CERTIFICATE_EVIDENCE.md](CERTIFICATE_EVIDENCE.md).

## Saved ownership and fields

Caller objects, dictionaries, and JSON supply only saved document identity.
Secrets, issuing-unit links, and flags are reloaded from saved records. Debug
therefore uses the saved issuer settings, not unsaved form edits. Missing sources
mean the explicitly requested Company; synthetic onboarding has this context.

| Saved source | Selected owner |
| --- | --- |
| Company or no source | Requested Company |
| Sales/POS Invoice without an issuing unit | Invoice Company, which must match the requested Company |
| Sales/POS Invoice with an issuing unit | Resolve the saved Multiple Setting below |
| Multiple Setting, company-keys flag disabled | That issuing unit |
| Multiple Setting, company-keys flag enabled | Its explicitly linked Company |

Each issuing unit must have a linked Company. If that Company differs from the
requested Company, both saved Tax IDs must be nonempty and equal. This is only a
configuration consistency check, not verification of certificate subject Tax ID
or authorization to use another entity's credentials. An unrelated source
invoice/Company is rejected. Checkbox zero is preserved, including string `"0"`;
unknown values do not silently select linked credentials.

| Purpose | Company / linked Company field | Own issuing-unit field |
| --- | --- | --- |
| Compliance | `custom_basic_auth_from_csid` | `custom_basic_auth_from_csid` |
| Production | `custom_basic_auth_from_production` | `custom_final_auth_csid` |

The Production selector was introduced here and is connected to the four primary
live HTTP adapters in increment 5 and four existing-XML adapters in increment 6.
Empty credentials never fall back to the other purpose.
An optional Basic prefix and copied whitespace are normalized. Tokens remain
opaque: their embedded certificate/environment is not validated in this increment.

## Certificate alias conflict is a release gate

Company certificates use `custom_certificate`. Multiple Setting readers now
consult the existing shared alias registry for `custom_certficate` and
`custom_certificate`. Either spelling can supply the value. Equal values are
accepted ignoring whitespace for comparison, but the selected legacy text is
preserved for digest parity. Different nonempty values block signing with a
translated error; neither field is overwritten or automatically preferred.

This is deliberately conservative: existing Compliance issuance writes the
misspelled field while final-CSID issuance writes the other field. A difference
may be a legitimate certificate transition, not corrupt configuration. **Do not
deploy until issuance/rotation and purpose-specific certificate storage have a
tested migration policy.** Do not resolve a conflict by blindly copying one
certificate onto the other or deleting historical evidence.

The selected private key must parse and have the same public key as the selected
certificate before signing. QR tag 8 is derived directly from the certificate,
not a saved public-key cache. The old `create_public_key` write helper remains
available for compatibility, but the QR path no longer calls it. No claim is made
that every historical public API in the module is now write-free.

## Verification and unchanged behavior

`test_credential_selection.py` includes 104 cases with generated, in-memory EC
certificates and mocked saved records/HTTP. It covers own/linked Company and
device contexts, caller-field injection, malformed settings, key mismatch,
field conflicts, purpose separation, Arabic message catalog entries, unchanged
legacy certificate-digest computation, real ECDSA verification, UBL population,
QR key/signature bytes, and local preparation of all six synthetic XML types.
No real site, customer key, network, certificate issuance, or invoice is used.

The tests preserve the current digest and signing algorithms; they do not certify
their regulatory correctness. SignedProperties formatting, XML canonicalization,
QR monetary semantics, Phase-1 payloads, and advance calculations are unchanged.
Local preparation is not SDK validation or confirmed remote Compliance.

## Remaining gates

1. Bind environment/route, owner, credential purpose/version, and certificate/key
   into one immutable request snapshot. Current helpers reload records between
   calls, so a concurrent rotation can still mix versions across a full pipeline.
2. Finish migration/testing of legacy live/background HTTP adapters and ICV ownership.
   Exercise saved/unsaved document lifecycle behavior in Frappe before rollout.
3. Separate Compliance and Production certificate lifecycles; verify expiry,
   supported algorithm, certificate taxpayer identity, CSID/key binding, and
   selected environment. Prefix normalization alone is not authentication proof.
4. Add SDK/golden fixtures, including time-zone semantics: synthetic XML currently
   uses naive `utcnow()` while QR timestamp conversion interprets naive values in
   the site's time zone. This pre-existing behavior is not changed here.
5. Run real v15/v16 site integration, Arabic UI, and authorized remote Compliance
   checks. No ERPNext 16 compatibility claim follows from these mocked tests.

See [STATUS.md](STATUS.md) for the complete selected test command and
[PLAN.md](PLAN.md) for backup, pilot, accounting, and release requirements.
