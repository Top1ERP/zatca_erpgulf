# Credential lifecycle separation — development increment 18

This increment adds read-only legacy separation evidence and a proposed migration
design. It does not install a DocType, migrate credentials, change CSID writers,
select a signing certificate, or connect the new snapshot to runtime submissions.

## Why separate purpose and environment

ZATCA distinguishes Compliance CSID for compliance checks from Production CSID
for core invoice APIs. Its onboarding process obtains Production CSID after the
required compliance checks. See sections 3.3.3–3.3.5 and the CSID FAQ in the
[official detailed technical guideline](https://zatca.gov.sa/en/E-Invoicing/Introduction/Guidelines/Documents/E-invoicing-Detailed-Technical-Guideline.pdf).
An environment label and credential purpose are independent dimensions in this
application; an endpoint named `production/csids` does not prove that a Sandbox
certificate is usable in Production. Local observations cannot substitute for
the server's completion/authorization decision.

## Writer/reader evidence in current source

| Action | Company | Own ZATCA Multiple Setting | Risk |
| --- | --- | --- | --- |
| `create_csid` | Writes `custom_certificate` and Compliance auth/request ID | Writes `custom_certficate` and Compliance auth/request ID | A new Company Compliance certificate replaces its old shared certificate |
| `production_csid` | Writes `custom_certificate` and Production auth | Writes `custom_certificate` and final auth | Company Compliance text is replaced; device may now have two different certificate fields |
| Shared signing selector | Reads `custom_certificate` | Treats both spellings as aliases; conflicting text fails | Purpose is not represented by certificate storage |
| `create_csr` / `create_private_keys` | Replaces shared private key | Replaces shared private key | Previously saved certificate/auth can become incompatible before renewal completes |
| Legacy ICV identity | Uses environment-selected auth in its key | Uses final auth, then Compliance auth/name fallback | Credential migration must not reset/merge chains or counters |

Tests invoke the actual existing issuance/key functions with synthetic documents,
mock saves and mock HTTP to reproduce these transitions. No remote issue or saved
tenant credential was inspected. This is source evidence, not a diagnosis of any
particular customer's current certificate.

The current Compliance writer also displays/returns its response body containing
credential material. Public UI/return/log redaction is a separate release gate;
this increment's new assessment never exposes that body or its secrets.

## Implemented read-only assessment

`credential_lifecycle.inspect_legacy_credential_lifecycle` accepts explicit owner,
settings, observation time and certificate field names. The internal adapter
`credential_settings.capture_credential_lifecycle_assessment` reuses the saved
owner policy, existing alias registry, and one frozen Company projection. Neither
is whitelisted or connected to a button, scheduler or invoice hook. A future
operator endpoint must add explicit permissions and provenance controls.

Each purpose is inspected independently with the shared bounded authentication
certificate decoder and increment 17 material-binding checks. The report contains
only public fingerprints, exact stored-text fingerprints, known field names,
static statuses/review codes, owner references, environment and explicit UTC time.
It retains no key, raw certificate, authorization, password or replacement text.
Canonical certificate text derived transiently from a token is **not** returned
for signing: legacy digest text and historical XML must not be rewritten.

| Observation | Meaning, not authorization |
| --- | --- |
| `TOKEN_MATERIAL_LOCALLY_BOUND` | Token certificate, key, selected curve and local time agree; not server acceptance or stored-text compatibility |
| `DIFFERENT_AUTH_CERTIFICATES` | Two decoded token certificates differ, even if their public keys match |
| `SAME_AUTH_CERTIFICATE` | The public certificate identity is equal; purpose/environment/secret provenance is still unverified |
| `CERTIFICATE_ALIAS_CONFLICT` | Existing shared selector still rejects the two spellings; this assessment does not relax it |
| `*_CERTIFICATE_NOT_STORED` | Token reveals a certificate absent from the registered certificate fields; not permission to reconstruct/replace it |
| `UNMATCHED_STORED_CERTIFICATE` | Preserve this evidence for review; do not discard it as stale automatically |

Malformed/oversized certificate fields do not hide independent token observations.
Malformed auth/key/expiry retain review statuses, not readiness. Missing one auth
never falls back to the other. All database/epoch/trust/revocation/taxpayer/
environment/remote completion verification and migration/dispatch/replay authority
flags are false. Existing legacy conflict behavior and runtime CSID writers are
unchanged.

## Proposed storage and transition design — not installed

Increment 19 implements the encrypted staging envelope and explicit SQL boundary
in [CREDENTIAL_BUNDLE_STORAGE.md](CREDENTIAL_BUNDLE_STORAGE.md), rehearsed only on
owned private databases. It does not install Frappe storage, migrate these fields,
activate versions or verify remote provenance; the transition gates below remain.

Prefer a versioned credential bundle store over more shared Company text fields.
One slot has `(owner doctype/name, environment, purpose)` plus a controlled version
UUID; references from Company/device identify the active version. Each bundle
links the certificate's public DER/text provenance, key reference, encrypted secret
reference, source request/issuance flow and validity interval. Purpose-specific
bundles may share a key, but that must be verified, not inferred from equal names.
Do not put private keys/authentication in journal JSON, public metadata, Git,
diagnostic responses or worker arguments. Exact encryption/vault and restricted
permissions require a restored-site design review before schema implementation.

1. Produce authorized, read-only per-owner/environment evidence. Preserve original
   certificate text/fields and encrypted recovery material; public fingerprints
   alone do not prove password or environment provenance.
2. Stage Compliance/key material in its own version without replacing the active
   Production key/certificate. Associate request ID and all six relevant sample
   outcomes with that exact flow; never infer completion from an HTTP-independent
   local status or a previous flow's request ID.
3. Stage returned Production material separately. Validate key/token/certificate
   binding plus trusted taxpayer/unit/environment provenance; failure leaves the
   previous active Production version intact. Do not promote by field spelling.
4. In an explicit controlled transaction, verify expected saved source links,
   Company/device settings, modification/version state and selected bundle;
   atomically activate only the intended slot. Public certificate hashes cannot
   detect every password rotation or prove an atomic database snapshot.
5. Retain old version/evidence references for historical artifacts and audit.
   Rotation is not authority to re-sign an old issued XML, replay an invoice,
   reset UUID/ICV/PIH or infer a new chain. Unknown/rejected outcomes require the
   separate reviewed issuance/retry policy.
6. Rehearse migration, rollback, interrupted onboarding, concurrent rotation,
   lost key, same-key renewal, environment switch and own/linked POS owners on
   restored v15/v16 sites. Existing accepted artifacts must remain byte-identical.
7. Only after the migration and SDK/remote gates, adopt one snapshot in the
   preparation/signing/request services, keep thin legacy adapters, and remove
   legacy writes/fallbacks in an explicit later release. Notify the user before
   any live source/schema/settings change or bench restart.

## Verification and remaining gates

`test_credential_lifecycle.py` adds 122 cases across environments/owner modes,
absent/same/different certificates, alias reversal, Company overwrite and
re-onboarding, exact text/DER distinctions, known token formats, malformed/bounded
inputs, key rotation, local validity, frozen safe diagnostics, saved-source
injection guards, Company projection rotation and no-write/no-HTTP inventory.
Four characterization cases exercise real legacy CSID/key functions with mocked
side effects. They do not approve their current writes or secret-bearing UI.

The selected local suite passes 2,660 cases. The separate private MariaDB rehearsal
passes 25 cases (2,685 total). No tenant query/migration, real certificate issuance,
browser UI language switch, ERPNext 16 runtime, SDK or invoice submission occurs.
See [STATUS.md](STATUS.md) for commands and [PLAN.md](PLAN.md) for broader gates.
