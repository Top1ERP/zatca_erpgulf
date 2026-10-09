# Implementation status — 2026-10-09

## Scope delivered in this increment

Safety preparation and eight bounded increments (Compliance outcomes, dedicated
Compliance/Debug isolation, shared API routing, signing/Compliance credential
selection, primary live request/PIH ownership, existing-XML request ownership,
generator/background request ownership with early Compliance dispatch,
and Company-scoped Sales/POS scheduling)
are complete in development. ICV continuity has been characterized, not migrated.
The broader [unification plan](PLAN.md) is not complete. No change in this branch
has been deployed to the running application or sent to ZATCA.

### Recovery evidence

- Backed up all 33 sites found with this app installed: SQL, public/private files,
  original site configurations, five dependent app source/Git trees, a ZATCA Git
  bundle, bench configuration, and runtime package inventory.
- Verified archive integrity, SQL completion/table counts, and checksums.
- Restored two representative sites' databases and files into an isolated
  MariaDB instance without network access or Frappe workers. Verified encrypted
  password recovery where encrypted rows existed. The test server was stopped.
- Backups are owner-only local recovery material, not additionally encrypted and
  not off-host. Online file copying/MyISAM auxiliary tables are not a coordinated
  maintenance-window snapshot. Full Frappe boot was not tested.
- Detailed manifests and restore reports remain in the private operations backup
  directory, outside Git. No customer backup/configuration is part of this change.

### Git evidence

- Deployed branch stays at `2e97708e115e31c675182647d10829d6175e7449`.
- Development base: origin/main `2c38ff1b984f8b8f961fa7bc8d028576d2195cab`.
- The two revisions have the same tree:
  `529d3cb16fbc6ba3687397ba0adfc60688564fc8`.
- Local main was fast-forwarded, safety tags created, and two stale local
  remote-tracking references removed after archiving. No GitHub branch was
  deleted, no history forced, and no deployed source file changed.
- Development is in an independent worktree on
  `codex/zatca-unification-v15-v16-20261009`.

## Compliance fix

Previously, `compliance_api_call` caught network exceptions and returned an error
tuple. Both all-type buttons counted any return without an exception as PASS.
The HTTP 406 detector also filtered out malformed entries before `all`, allowing
an empty iterator to appear successful. HTTP 200/202 with no confirmed validation
could also pass through.

Changes:

- Added the pure `compliance_result.py` contract.
- Transport failures now raise a translated failure; no success-shaped tuple.
- HTTP 200/202 require explicit PASS/WARNING validation without errors.
- Previous completion requires HTTP 406, a validation ERROR, and a nonempty list
  consisting entirely of `Submitted before` errors. Summaries distinguish this
  as `compliance_status: ALREADY_COMPLETED` without claiming new clearance.
- Both aggregators reject unconfirmed return values, independently of the HTTP
  boundary. Existing PASS/FAIL UI fields remain compatible.
- Added Arabic translations and English explanations of the new invariants.

This first increment did **not** change endpoint routing, credentials, signing, QR payloads,
discounts, GL/VAT reporting, or the server's final-CSID requirements. In particular,
it does not claim to fix a cryptographic digest error or incomplete remote tests.
The second increment below addresses Company validation-type mutation and the
dedicated Compliance/Debug identity and file side effects. Remaining legacy
branches and credential-context differences are recorded in
[SETTINGS_AND_ROUTES.md](SETTINGS_AND_ROUTES.md).

## Increment 2: dedicated Compliance and Debug isolation

- Centralized the six type labels/codes. Batch calls pass the type explicitly,
  without a Company write/restore cycle. Single-check UI precedence is preserved.
- Sales/POS metadata builders accept an explicit non-production purpose. Debug
  reuses a valid existing UUID or creates an unpersisted preview; Compliance
  creates a fresh sample UUID. Default live generation remains unchanged.
- Compliance still uses its separate counter but cannot write the source
  invoice's `custom_zatca_icv` or `custom_zatca_issuing_unit`.
- Dedicated Sales/POS compliance and synthetic onboarding share owner-only,
  unique temporary files, automatically removed on return or exception.
- Debug attaches formatted XML directly from memory, without overwriting or
  unlinking a live submission file. Intra-company debug no longer saves a new
  invoice status or commits the transaction.
- The dedicated POS check now returns its API result and verifies invoice
  Company ownership before signing or sending.
- Added English explanations and Arabic messages. Endpoint, certificate, and
  credential selection were audited but not changed in this increment.

## Increment 3: shared API routing

- Replaced six URL-selection implementations with compatibility wrappers over a
  pure resolver and a read-only Frappe adapter.
- Added an immutable route with explicit environment, operation, base field,
  and required credential purpose. Actual credential resolution is not yet unified.
- Removed implicit Production fallback for blank/unknown selections, including
  CSR creation and diagnostics. Valid explicit onboarding overrides remain local.
- Standardized slash/whitespace handling, required valid HTTPS bases, and blocked
  standard-gateway paths that conflict with the selected environment.
- The dedicated onboarding helper cannot resolve reporting/clearance operations.
  Production onboarding remains supported; it is not forced to Sandbox.
- Added translated errors and tests at the CSR, Compliance, and final-CSID request
  boundaries. See [API_ROUTING.md](API_ROUTING.md) for compatibility and release gates.

## Increment 4: signing and Compliance credential ownership

- Added pure credential-field policies and a read-only saved-owner resolver.
  Caller-provided secret values/flags are not trusted; Company, own-device, and
  linked-company signing and Compliance authentication share one selection policy.
- Added key/certificate public-key matching before signing, source-Company and
  linked Tax-ID consistency guards, and strict purpose-specific authorization.
- Registered both machine certificate spellings in the existing alias registry.
  Missing one spelling is supported; conflicting nonempty values stop signing
  without field repair. Issuance/rotation migration remains a deployment gate.
- Removed the QR path's public-key cache save/commit. Public-key bytes are derived
  directly from the selected certificate; the old explicit cache writer remains
  available only for compatibility.
- Added English documentation, Arabic errors, generated-certificate tests, and
  local preparation checks for all six synthetic document types. Signing/digest
  algorithms are unchanged. See [CREDENTIAL_SELECTION.md](CREDENTIAL_SELECTION.md).
- At the end of increment 4, Production authorization selection was unit tested
  but not yet connected to live HTTP adapters. Increment 5 integrates the four
  primary adapters; a full signing/credential-version snapshot remains pending.

## Increment 5: primary reporting/clearance request context

- Added an immutable route/auth/owner result consumed by the four main Sales/POS
  reporting and clearance adapters, with target name/doctype checks and strict
  Production-purpose authorization in the configured environment.
- Replaced seven repeated PIH/notification branches with a shared completion
  helper using the owner identity selected for HTTP. It retains the existing PIH
  Phase-2 and unchanged-hash guards without changing ICV allocation.
- Invalid local context blocks HTTP and artifact preparation; existing exception
  handlers can still record errors on invoices. Deferred reporting stays deferred.
- Added 138 mocked cases, Arabic messages, and English documentation. Legacy 409
  differences are characterized, not changed. See
  [SUBMISSION_CONTEXT.md](SUBMISSION_CONTEXT.md) for scope and deployment gates.

## Increment 6: existing-XML adapters and ICV characterization

- Migrated four additional reporting adapters to the shared context and replaced
  eight repeated PIH/notification blocks. Existing XML bytes, UUID/hash, QR
  references, timeouts, and response behavior are preserved.
- Machine-specific paths retain their issuing-unit requirement, now checked on
  the saved invoice instead of trusting a caller-supplied field.
- Added 151 real-file/mocked-HTTP cases and 22 read-only ICV identity cases, English
  documentation, and an Arabic error. No counter allocation or migration changed.
- Audited raw-credential-dependent fingerprints, ignored linked-owner flags,
  purpose/API-environment mismatch, and key collision edge cases. See
  [LEGACY_XML_AND_ICV.md](LEGACY_XML_AND_ICV.md) for the required continuity plan.

## Increment 7: generation ownership and early Compliance dispatch

- Migrated the last four audited reporting adapters and eight PIH branches to
  the shared context. Twelve live HTTP request adapters now share owner selection.
- Redirected nonzero sample codes in all six generators before live metadata/file
  generation; removed twelve duplicated sample/live branches and propagated
  confirmed results and failures to callers.
- Ordinary signing/QR uses the saved invoice issuer, consistent with HTTP. The
  dedicated check defaults to its invoice source when no explicit source exists.
- Added 241 request/generation/real-temporary-file bridge cases. The suite also
  characterizes the old Background deferral behavior, pending worker-policy work.
  See [GENERATION_AND_COMPLIANCE.md](GENERATION_AND_COMPLIANCE.md).

## Increment 8: Company-scoped background scheduling

- Shared one selection loop and pure scheduling rules for Sales/POS, preserving
  the public cron/helper entry points and foreground preparation deferral.
- Replaced cross-Company window authorization with saved invoice Company policy;
  both POS windows work, including overnight/midnight/fractional Time values.
- Rechecked saved status before processing, and reloaded drafts after on_submit;
  invalid Company settings or one invoice failure do not stop other Companies.
- Preserved the discovery horizon and Sales/POS commit distinction. Concurrency,
  rollback/savepoints, stable signed retries, and foreground unique-ID parity
  remain separate release gates. See [BACKGROUND_SCHEDULING.md](BACKGROUND_SCHEDULING.md).
- Added 168 local cases, including the actual parent routing and worker bridge.

### Follow-up retry identity audit

- Added 61 read-only metadata/HTTP/artifact-wrapper characterization cases.
- Confirmed POS regeneration, UUID reset in ten adapters versus retention in the
  two primary Sales adapters, retained ICV on rejection, and file/field identity
  divergence. UUID/ICV/signing behavior was deliberately not changed in this audit.
- Recorded the evidence-ledger and exact-artifact replay sequence in
  [RETRY_IDENTITY.md](RETRY_IDENTITY.md), including concurrency/migration gates.

## Verification

The initial regression suite reproduced **19 failures and 12 passes** on the
unchanged implementation (after isolating the Frappe HTTP decorator). The first
fix passed all 31 cases, then 160 with expanded coverage and 206 after increment 2.
Increment 3 passed 358 cases; increment 4 passed 467 (104 new credential cases
plus five existing field-alias cases). Increment 5 added 138 cases to reach 605.
Increment 6 added 173 cases to reach 778. Increment 7 adds 241 cases, bringing
the selected suite to 1,019. Increment 8 adds 168 cases, bringing the combined
selected suite to 1,187. The follow-up retry audit adds 61 cases, bringing the
combined selected suite to **1,248 passing tests**:

| Suite | Scope |
| --- | --- |
| `test_compliance_result.py` | Pure result classification and malformed payloads |
| `test_compliance_api_outcomes.py` | Mocked real API/button functions, failures, previous completion, translations |
| `test_nonproduction_isolation.py` | Preview identity, live-identity regression, counter boundaries, explicit types, cross-company rejection, debug artifact protection, temporary-file lifetime |
| `test_api_route_contract.py`, `test_api_routing.py` | Pure routing, six compatibility wrappers, malformed settings, environment overrides, and mocked onboarding request boundaries |
| `test_credential_selection.py`, `test_field_compat.py` | Saved owner resolution, certificate aliases, key matching, signing/QR parity without writes, auth purposes, Arabic messages, six-type local preparation, existing field compatibility |
| `test_submission_context.py` | Four primary request adapters, environments/owners, Production auth, actual PIH helper with mocked records, rejection/timeout, request-pinned owner, batch mode, legacy 409 behavior |
| `test_legacy_submission_context.py` | Four existing-XML adapters and wrappers, actual temporary file reads, saved machine-link guards, unchanged artifacts, auth and PIH ownership |
| `test_icv_identity_contract.py` | Read-only characterization of legacy identity/rotation/purpose behavior and collision edge cases; not a counter migration |
| `test_generation_routes.py` | Four remaining reporting adapters, six generator diversion boundaries, confirmed outcomes/errors, real temporary sample bridge, ordinary signing source, mode deferral |
| `test_background_scheduling.py` | Shared Sales/POS worker selection, Company isolation/windows/settings, stale status and draft boundaries, actual parent routing and worker bridge |
| `test_retry_identity_contract.py` | Read-only Sales/POS UUID regeneration/filtering, twelve HTTP failure/timeout boundaries, saved ICV and existing artifact identity divergence |
| `test_tax_details_compat.py`, `test_tax_details_regression.py` | Tax adapter regressions |
| `test_qr_tlv_compliance.py` | Existing QR/TLV regressions |
| `test_zatca_response.py` | Existing response handling |
| `test_compatibility_hardening.py` | Existing mocked runtime/advance compatibility regressions |

All HTTP/Frappe I/O in the new boundary tests is mocked. Run them against the
development worktree, not the installed production package. From the worktree:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  ../../env/bin/python -m pytest -q -p no:cacheprovider \
  zatca_erpgulf/zatca_erpgulf/tests/test_compliance_result.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_compliance_api_outcomes.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_nonproduction_isolation.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_api_route_contract.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_api_routing.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_credential_selection.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_field_compat.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_submission_context.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_legacy_submission_context.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_icv_identity_contract.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_generation_routes.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_background_scheduling.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_retry_identity_contract.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_tax_details_compat.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_tax_details_regression.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_qr_tlv_compliance.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_zatca_response.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_compatibility_hardening.py
```

Tested with the existing Python 3.10/Frappe 15 environment. No real v16 runtime,
full site integration, browser language switch, ZATCA SDK run, remote Compliance
request, or production invoice submission was performed in this increment.

## Next gate

Bind the shared route and saved-owner policy to one credential/version snapshot;
resolve certificate issuance/rotation field conflicts before any deployment.
Resolve foreground unique-ID/gPOS policy parity and transactional worker/retry
coordination; design an explicit ICV continuity mapping using the increment 6 audit.
Use the follow-up [retry identity evidence](RETRY_IDENTITY.md) to introduce a
durable issuance artifact contract before changing UUID or counter allocation.
Prepare a separately
pinned v16 bench and golden XML fixtures before consolidating cryptography or
advance-payment calculations. Obtain a suitable off-host backup destination and
choose the pilot/rollout window before any production deployment.
