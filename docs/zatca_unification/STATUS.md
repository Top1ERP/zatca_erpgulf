# Implementation status — 2026-10-09

## Scope delivered in this increment

Safety preparation and fourteen bounded increments (Compliance outcomes, dedicated
Compliance/Debug isolation, shared API routing, signing/Compliance credential
selection, primary live request/PIH ownership, existing-XML request ownership,
generator/background request ownership with early Compliance dispatch,
Company-scoped Sales/POS scheduling, opt-in attached-XML evidence inspection,
opt-in stored response/counter observations, opt-in generated XML evidence,
opt-in embedded public certificate observations, an immutable prepared-artifact
contract, and a single-attempt dispatch-observation journal)
are complete in development. ICV continuity has been characterized, not migrated.
The broader [unification plan](PLAN.md) is not complete. No change in this branch
has been deployed to the running application or sent to ZATCA.
The user requires prior notice before any live application change or restart;
this development continuation does not authorize deployment.

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

## Increment 9: opt-in attached-XML identity evidence

- Added site-free immutable metadata inspection and comparison with saved
  invoice identity, plus a permission-checked read-only Sales/POS Frappe bridge.
- Explicit seller/root/reference paths avoid buyer VAT, nested UUID, or
  SignedProperties-digest confusion; input ambiguity and unsafe files remain
  visible failures rather than selecting the newest attachment.
- Exact byte fingerprints distinguish different artifacts with the same identity.
  No signature/remote acceptance/replay authority is claimed or granted.
- Added 145 local parser/permission/file/identity/no-write tests, English
  documentation and Arabic fatal messages. See [ARTIFACT_EVIDENCE.md](ARTIFACT_EVIDENCE.md).
- No tenant inventory execution, migration, hook/UI registration, or generation/
  HTTP behavior change. Wider response/counter/loose-file inventory is pending.

## Increment 10: opt-in response/counter history

- Preserved the default attached-XML inspector; explicit `include_history=True`
  adds strict stored response observations and saved-unit counter diagnostics.
- Shared one XML identity checker for local attachments and embedded response
  XML; reject JSON/field ambiguity without changing stored evidence or accepting
  a saved status/display label as remote verification.
- Inspect legacy Production-purpose counter tuple/key/position/tail with read
  permission; distinguish API environment and flag collisions/missing contexts
  without auth-derived remapping, seeding, merging, or reducing counters.
- Added 129 local pure/bridge tests and an Arabic diagnostic. Wider history,
  credential epochs, atomic snapshots, and restored-site execution remain pending.
  See [HISTORY_EVIDENCE.md](HISTORY_EVIDENCE.md). No live behavior was changed.

## Increment 11: opt-in generated XML evidence

- Explicit `include_generated=True` adds one known signed-file location, not a
  directory scan. Loose-file access requires System Manager plus the existing
  Invoice/Company read permissions; defaults remain unchanged.
- Shared bounded file and XML inspection detects unsafe names, malformed files,
  metadata divergence and exact-byte conflicts. Missing files are not proof of
  non-issuance; matching sources are preserved without selecting a winner.
- Detect same-named Sales/POS documents because the legacy filename omits
  DocType/Company. No writer, replay, counter or identity behavior was changed.
- Added 43 local cases and an Arabic message; combined history remains read-only.
  See [GENERATED_EVIDENCE.md](GENERATED_EVIDENCE.md). No tenant execution occurred.

## Increment 12: embedded public certificate observations

- Explicit `include_certificate=True` adds fingerprint-only observations from
  each requested XML source without reading current credentials or secret fields.
- Share the safe XML parser, constrain signature/certificate location and
  ambiguity, and bound Base64/DER parsing. Observe certificate DER and public-key
  fingerprints separately so renewal does not imply a changed key.
- Different observed versions remain unresolved provenance, not automatically
  repaired. No signature/epoch/owner/purpose/trust/replay verification is claimed.
- Added 85 local cases and an Arabic diagnostic; live signing, digest algorithms,
  counters and HTTP remain unchanged. See [CERTIFICATE_EVIDENCE.md](CERTIFICATE_EVIDENCE.md).

## Increment 13: immutable prepared-artifact contract

- Added typed frozen source/chain/version, declared public credential epoch and
  pinned-route context, plus an exact-byte prepared candidate. No runtime adapter
  uses it; it is not a persisted ledger or an authorized replay payload.
- Separate scoped issuance key from content manifest so same-version changes in
  bytes, certificate/epoch, source snapshot or route remain visible drift.
- Derive UUID/ICV/PIH/type/certificate from bounded XML, bind source identity and
  operation/public fingerprints, and revalidate manually constructed API routes.
- Added 237 local cases, including type 386 identity; advanced amounts/accounting,
  crypto/SDK checks, provenance, persistence and locks remain separate gates.
  See [ISSUANCE_CANDIDATE.md](ISSUANCE_CANDIDATE.md) for the persistence design.

## Increment 14: single-attempt dispatch observations

- Added immutable event/sequence/candidate binding and a memory-only single-attempt
  journal. Late receipts retain earlier unknown outcomes; equal event-ID redelivery
  is idempotent, conflicting facts and second starts fail explicitly.
- Preserve exact bounded response bytes and static transport causes without
  reading a clock or inferring acceptance from status/body. No UUID/ICV/PIH reset.
- HTTP 401/403 are authorization-failure observations; other statuses, including
  200 and 409, remain unverified receipts pending the separate response contract.
- Added 161 local cases; no durable SQL lease, retry permission, acceptance or
  live behavior was implemented. See [DISPATCH_JOURNAL.md](DISPATCH_JOURNAL.md).

## Verification

The initial regression suite reproduced **19 failures and 12 passes** on the
unchanged implementation (after isolating the Frappe HTTP decorator). The first
fix passed all 31 cases, then 160 with expanded coverage and 206 after increment 2.
Increment 3 passed 358 cases; increment 4 passed 467 (104 new credential cases
plus five existing field-alias cases). Increment 5 added 138 cases to reach 605.
Increment 6 added 173 cases to reach 778. Increment 7 adds 241 cases, bringing
the selected suite to 1,019. Increment 8 adds 168 cases, bringing the combined
selected suite to 1,187. The follow-up retry audit adds 61 cases, bringing the
combined selected suite to 1,248. Increment 9 adds 145 cases, bringing the
combined selected suite to 1,393. Increment 10 adds 129 cases, bringing the
combined selected suite to 1,522. Increment 11 adds 43 cases, bringing the combined
selected suite to 1,565. Increment 12 adds 85 cases, bringing the combined selected
suite to 1,650. Increment 13 adds 237 cases, bringing the combined selected suite
to 1,887. Increment 14 adds 161 cases, bringing the combined selected suite to
**2,048 passing tests**:

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
| `test_artifact_evidence.py`, `test_artifact_inventory.py` | Namespace-aware immutable metadata, saved identity reconciliation, exact-byte conflicts, permission/privacy/path/file controls, static safe errors, and no-write diagnostic bridge |
| `test_history_evidence.py`, `test_history_inventory.py` | Strict stored response observations, response/file XML identity, saved-unit counter purpose/key/position/tail, permissions, and unchanged default diagnostics |
| `test_generated_inventory.py` | Opt-in operator gate, known generated path, cross-DocType ambiguity, bounded file safety, source/byte comparison, no scan/write and composed history |
| `test_certificate_evidence.py`, `test_certificate_inventory.py` | Bounded immutable embedded DER/SPKI/text observations, renewal/key distinction, structural ambiguity, no-current-credential/permission/privacy and three-source composition |
| `test_issuance_candidate.py` | Pure frozen exact-byte candidate, explicit chain/version/epoch/route declarations, source/type matching, same-key drift, structured scope/privacy and no-I/O |
| `test_dispatch_journal.py` | Frozen single-attempt receipt history, exact bounded bytes, unknown/late/auth observations, idempotence/conflicts, no second start or acceptance/replay authority |
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
  zatca_erpgulf/zatca_erpgulf/tests/test_artifact_evidence.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_artifact_inventory.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_history_evidence.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_history_inventory.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_generated_inventory.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_certificate_evidence.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_certificate_inventory.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_issuance_candidate.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_dispatch_journal.py \
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
Implement the strict endpoint/response/returned-XML classification contract,
cross-attempt policy and durable repository/outbox/leases;
extend observed certificate identity with verified credential provenance and
wider counter/log history. Rehearse on restored sites before proposing
tenant reconciliation or changes to issuance/replay.
Prepare a separately
pinned v16 bench and golden XML fixtures before consolidating cryptography or
advance-payment calculations. Obtain a suitable off-host backup destination and
choose the pilot/rollout window before any production deployment.
