# Settings and route audit — updated through development increment 14

Increment 14 adds a pure single-attempt journal over the prepared candidate. It
does not resolve settings, authorize retries or classify receipts as accepted;
see [DISPATCH_JOURNAL.md](DISPATCH_JOURNAL.md). Live paths remain unchanged, and
the user requires prior notice before any live application change.

Increment 13 adds a pure immutable prepared-artifact contract. It pins explicit
route/chain/epoch/snapshot declarations and observes drift without reading current
settings or changing live paths. See [ISSUANCE_CANDIDATE.md](ISSUANCE_CANDIDATE.md).

Increment 12 adds opt-in embedded public certificate fingerprints only, without
reading today's credential fields or changing settings/signing/HTTP. An observed
DER marker is not a verified credential epoch; see
[CERTIFICATE_EVIDENCE.md](CERTIFICATE_EVIDENCE.md).

Increment 11 adds only opt-in generated XML diagnostics with System Manager and
Invoice/Company read permissions. It detects the legacy same-name Sales/POS file
ambiguity without changing generation or replay; see
[GENERATED_EVIDENCE.md](GENERATED_EVIDENCE.md).

This inventory describes source behavior, not a new regulatory interpretation or
a claim that live settings were changed. No credentials or tenant values are
included. The implementation plan remains [PLAN.md](PLAN.md).
Shared routing is implemented as described in [API_ROUTING.md](API_ROUTING.md).
Signing and dedicated Compliance owner selection now share the read-only policy
in [CREDENTIAL_SELECTION.md](CREDENTIAL_SELECTION.md). Four primary and four
existing-XML HTTP adapters now pin request and PIH owner as described in
[SUBMISSION_CONTEXT.md](SUBMISSION_CONTEXT.md) and
[LEGACY_XML_AND_ICV.md](LEGACY_XML_AND_ICV.md). Increment 7 completes the four
without-XML/background request adapters and early generator Compliance diversion
in [GENERATION_AND_COMPLIANCE.md](GENERATION_AND_COMPLIANCE.md). Increment 8 shares
Company-scoped worker eligibility in [BACKGROUND_SCHEDULING.md](BACKGROUND_SCHEDULING.md).
ICV migration, transactional worker/retry safety, and certificate issuance/rotation
remain pending.

Increment 9 adds the opt-in saved-identity/attached-XML inventory in
[ARTIFACT_EVIDENCE.md](ARTIFACT_EVIDENCE.md). It is not a submission hook or
authority to repair UUIDs/counters or replay an invoice.
Increment 10 adds explicitly opt-in response/counter observations in
[HISTORY_EVIDENCE.md](HISTORY_EVIDENCE.md), without changing live selection or keys.

## Entry points and isolation boundaries

| Entry point | Current development behavior | Remaining work |
| --- | --- | --- |
| Company single check | `sign_invoice.zatca_call_compliance`; Company label still takes precedence over the legacy UI's numeric argument | Normalize source/credential context; explicit POS dispatch |
| Company Run All Compliance | Passes each type explicitly; never writes/restores `custom_validation_type` | Replace invoice-oriented adapter with common snapshot builder |
| POS dedicated compliance method | Disposable identity/file; returns API result; rejects an invoice belonging to another Company | Normalize serialized `source_doc` and issuing-unit context |
| Synthetic onboarding | Shared temporary-file lifetime; no live invoice identity | Golden signed fixtures and remote six-type acceptance |
| Sales/POS Debug XML | Disposable/reused preview UUID; read-only ICV; formatted XML attached directly as private `DEBUG_INVOICE_*` | Remove remaining duplicated tax/type logic and review Phase-1 behavior |
| Live and background submission | Shared per-Company worker eligibility; existing default metadata/ICV retained | Stable POS retry identity, foreground unique-ID parity, and transaction audit |

The dedicated compliance methods and two Debug menu actions isolate their sample
identity/artifacts. Increment 7 also redirects nonzero `compliance_type` calls
from all six legacy generators to the dedicated Sales/POS adapter before live
metadata/file generation. Explicit sample type and actual result/error are
preserved. The separate Compliance counter may still advance; only live invoice
identity and attachments are protected by this boundary.

## Field and credential selection observed in source

| Concern | Current sources/consumers | Risk to address in the shared context |
| --- | --- | --- |
| Environment | Company `custom_select`; shared `api_routing` resolver through legacy wrappers | Blank/unknown selection now blocks; legacy Company settings need preflight before deployment |
| Base URL | `custom_sandbox_url`, `custom_simulation_url`, `custom_production_url` | Joining/HTTPS/standard-gateway environment checks centralized; custom gateway trust still needs review |
| Compliance authorization | `custom_basic_auth_from_csid` on the shared saved credential owner | Direct Multiple Setting / serialized identities now resolve consistently; full version/environment binding remains pending |
| Live authorization | Company `custom_basic_auth_from_production`; machine `custom_final_auth_csid` | Twelve adapters share route/auth/PIH owner; ICV and certificate epoch/issuance migration remain pending |
| Private key | `custom_private_key` from the shared saved owner, matched to its selected certificate | Six live generators now use the saved invoice issuer; ICV and full-pipeline rotation snapshot pending |
| Certificate | Company `custom_certificate`; machine readers support both registered spellings and reject conflicts | Issuance writes different fields at different stages; purpose/version-aware migration must precede deployment |
| Linked credentials | `custom_zatca_pos_name`, `custom__use_company_certificate__keys`, `custom_linked_doctype` | One credential owner must drive signing, HTTP, and identity; linked-company fallback must be explicit |
| Compliance type | `custom_validation_type`; legacy numeric `compliance_type`; new explicit batch `validation_type` | Fixed the batch race while preserving the existing single-button precedence |
| Invoice identity | `custom_uuid`, `custom_zatca_icv`, `custom_zatca_issuing_unit` | Dedicated tests no longer persist sample identity on source invoices |
| Counter identity | `icv._issuing_unit`, `_counter_key`, environment string | Increment 6 characterizes raw-token fingerprints, linked-owner mismatch, purpose/API-environment differences, and key collisions; explicit continuity mapping required |
| Field aliases | `ksa_compliance/field_compat.py`, runtime schema checks | Preserve missing/blank/zero distinctions and detect conflicts; do not add a second alias registry |
| Automatic Background eligibility | Company enablement, saved phase aliases, submission mode, both Company windows | Shared Sales/POS selector; no any-Company authorization; preserve manual/batch authority |

Code anchors for the next increment:

- `sign_invoice_first.py`: `get_compliance_api_url`, `compliance_api_call`,
  `production_csid`, `digital_signature`, `extract_certificate_details`,
  `certificate_hash`, and certificate selection inside signature generation.
- `sign_invoice.py`: `get_api_url`, reporting/clearance credential selection,
  `zatca_call_compliance`, and `run_all_compliance_summary`.
- `pos_sign.py`: dedicated compliance and reporting/clearance adapters.
- `icv.py`: issuing-unit fingerprint and environment-specific counter allocation.

## Remaining credential-context contract

Resolve one immutable request context before XML signing or HTTP. It should carry
document purpose, environment, Company, issuing-unit owner, credential purpose
and version, endpoint, and non-secret provenance. Keep keys/tokens out of its
printable representation. Required checks include:

Increment 3 supplies an immutable **route**; increment 4 adds shared saved-owner
selection for signing/Compliance, source/link consistency guards, and actual
key/certificate public-key matching. This is not the complete request context:
legacy HTTP/ICV consumers, certificate subject/expiry/environment checks, CSID
binding, issuance migration, and atomic version/rotation handling remain pending.

1. Recognized environment and permitted endpoint for the requested purpose.
2. Source invoice Company matches the requested Company; linked ownership is
   explicit and taxpayer identity is validated.
3. Signing certificate/key and HTTP credential belong to the same resolved unit.
4. Missing or conflicting fields produce a translated error, not fallback to
   another taxpayer, environment, or credential purpose.
5. Debug performs no request; Compliance never selects reporting or clearance.
6. Rotation/onboarding cannot silently replace historical signing evidence or
   rewind the live counter chain.

Do not switch all call sites to this context until Company, own-machine, and
linked-company cases have tests for both API purposes and every environment.
Certificate format/hash behavior and schema migrations remain separately gated.

## Deliberate limits of increment 2

- Compliance still allocates in its dedicated `Compliance` counter. This is not
  a fully write-free operation; only live invoice identity and the Production
  counter are excluded by the changed path. Debug may replace private debug
  attachments, but does not write a live submission filename or invoice status.
- Live UUID/ICV allocation and its existing commits were preserved. Removing
  commits from document hooks for v16 needs transaction-level integration tests.
- The new temporary-file helper preserves the existing formatted bytes. It does
  not change hashing, signatures, discount calculation, or QR semantics.
- Local mocked tests do not validate actual ZATCA acceptance, Frappe File hooks,
  full accounting behavior, or ERPNext 16 compatibility.
