# Settings and route audit — updated through development increment 4

This inventory describes source behavior, not a new regulatory interpretation or
a claim that live settings were changed. No credentials or tenant values are
included. The implementation plan remains [PLAN.md](PLAN.md).
Shared routing is implemented as described in [API_ROUTING.md](API_ROUTING.md).
Signing and dedicated Compliance owner selection now share the read-only policy
in [CREDENTIAL_SELECTION.md](CREDENTIAL_SELECTION.md). Live HTTP/ICV ownership and
certificate issuance/rotation remain pending.

## Entry points and isolation boundaries

| Entry point | Current development behavior | Remaining work |
| --- | --- | --- |
| Company single check | `sign_invoice.zatca_call_compliance`; Company label still takes precedence over the legacy UI's numeric argument | Normalize source/credential context; explicit POS dispatch |
| Company Run All Compliance | Passes each type explicitly; never writes/restores `custom_validation_type` | Replace invoice-oriented adapter with common snapshot builder |
| POS dedicated compliance method | Disposable identity/file; returns API result; rejects an invoice belonging to another Company | Normalize serialized `source_doc` and issuing-unit context |
| Synthetic onboarding | Shared temporary-file lifetime; no live invoice identity | Golden signed fixtures and remote six-type acceptance |
| Sales/POS Debug XML | Disposable/reused preview UUID; read-only ICV; formatted XML attached directly as private `DEBUG_INVOICE_*` | Remove remaining duplicated tax/type logic and review Phase-1 behavior |
| Live and background submission | Existing default metadata/ICV behavior retained | Stable POS retry identity and scheduler/transaction audit |

The isolated routes are the dedicated compliance methods and the two Debug menu
actions. Legacy live/background functions still expose optional nonzero
`compliance_type` branches. Those branches are **not yet consolidated** into the
dedicated adapter and must not be described as fully isolated. They can still
reach live reference/attachment code; redirecting them requires characterization
tests and a common context first. Relevant modules include `sign_invoice`,
`pos_sign`, `sales_invoice_withoutxml`, `zatca_background_sched`,
`pos_submit__without_xml`, and `pos_schedule_background`.

## Field and credential selection observed in source

| Concern | Current sources/consumers | Risk to address in the shared context |
| --- | --- | --- |
| Environment | Company `custom_select`; shared `api_routing` resolver through legacy wrappers | Blank/unknown selection now blocks; legacy Company settings need preflight before deployment |
| Base URL | `custom_sandbox_url`, `custom_simulation_url`, `custom_production_url` | Joining/HTTPS/standard-gateway environment checks centralized; custom gateway trust still needs review |
| Compliance authorization | `custom_basic_auth_from_csid` on the shared saved credential owner | Direct Multiple Setting / serialized identities now resolve consistently; full version/environment binding remains pending |
| Live authorization | Company `custom_basic_auth_from_production`; machine `custom_final_auth_csid` | Preserve purpose and owner while centralizing selection |
| Private key | `custom_private_key` from the shared saved owner, matched to its selected certificate | Legacy live HTTP/ICV consumers still need migration; full-pipeline rotation snapshot pending |
| Certificate | Company `custom_certificate`; machine readers support both registered spellings and reject conflicts | Issuance writes different fields at different stages; purpose/version-aware migration must precede deployment |
| Linked credentials | `custom_zatca_pos_name`, `custom__use_company_certificate__keys`, `custom_linked_doctype` | One credential owner must drive signing, HTTP, and identity; linked-company fallback must be explicit |
| Compliance type | `custom_validation_type`; legacy numeric `compliance_type`; new explicit batch `validation_type` | Fixed the batch race while preserving the existing single-button precedence |
| Invoice identity | `custom_uuid`, `custom_zatca_icv`, `custom_zatca_issuing_unit` | Dedicated tests no longer persist sample identity on source invoices |
| Counter identity | `icv._issuing_unit`, `_counter_key`, environment string | Legacy machine credential preference and Production/Compliance distinctions must align with the future context |
| Field aliases | `ksa_compliance/field_compat.py`, runtime schema checks | Preserve missing/blank/zero distinctions and detect conflicts; do not add a second alias registry |

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
live HTTP/ICV consumers, certificate subject/expiry/environment checks, CSID
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
