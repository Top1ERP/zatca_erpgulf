# Implementation status — 2026-10-24

## Scope delivered in this increment

Safety preparation and ninety-six bounded increments (Compliance outcomes, dedicated
Compliance/Debug isolation, shared API routing, signing/Compliance credential
selection, primary live request/PIH ownership, existing-XML request ownership,
generator/background request ownership with early Compliance dispatch,
Company-scoped Sales/POS scheduling, opt-in attached-XML evidence inspection,
opt-in stored response/counter observations, opt-in generated XML evidence,
opt-in embedded public certificate observations, an immutable prepared-artifact
contract, a single-attempt dispatch-observation journal, endpoint-bound
response/returned-XML assessment, an isolated durable journal repository,
an ephemeral signing/authentication material snapshot, legacy credential
lifecycle separation evidence, encrypted versioned credential staging, and
permissioned metadata-only staged inspection, and version/CSR-bound Compliance
observations, an encrypted append-only request/receipt archive, and permissioned
metadata-only archive selection, a single-use two-transaction capture scaffold,
an explicit standard-gateway HTTPS adapter, and permissioned saved-source
revision-bound capture with shared Frappe permission-signature compatibility,
and a fixed-manifest offline rehearsal guard/runner, and explicit local
exact-envelope receipt persistence recovery, and permissioned local recovery
with shared saved-source access policy, and an explicit shared invoice issue-time
contract with Sales/POS/XML/QR/synthetic/initial-advance adapters, and read-only
original-XML advance reference observations with explicit identity binding, and
exact archived-attempt advance source choice with endpoint/clock consistency,
and permissioned saved-source-bound metadata-only advance archive inspection,
and bounded five-tag QR observations with explicit missing-source review policy,
and caller-owned Phase-1 QR metadata staging without recursive save/commit/DDL,
and non-destructive scoped ordinary Sales/POS QR attachment preservation,
and non-destructive initial-advance QR print-hook preservation,
and saved-row access boundaries for explicit QR recovery endpoints,
and non-destructive QR recovery preservation/review without speculative repair,
and exact archived-attempt QR source observations,
and permissioned metadata-only QR source inspection with a shared access engine,
and non-destructive Phase-2 local completion-hook preservation/review,
and caller-owned primary Sales/POS QR-link staging without invoice events/DDL,
and scoped primary QR ownership/schema checks before request/error persistence,
and non-overwriting primary post-response local-error review boundaries,
and explicit exact-attempt local primary receipt persistence/redelivery,
and saved-row/WRITE-access-bound local primary receipt persistence,
and an explicit pinned Unix local primary receipt connection provider,
and encrypted immutable local retained-receipt custody,
and permissioned saved-source/key-bound encrypted custody storage/retrieval,
and an atomic primary start/logical-invoice no-replay hold,
and an exact auth-free local primary observation coordinator,
and a permissioned metadata-only saved-source primary capture boundary,
and exact local primary custody/journal pair inspection and persistence,
and permissioned metadata-only saved-source paired reconciliation access,
and bounded pure primary outcome review with writer/late-response evidence,
and received local presentation/logging-step isolation for all primary statuses,
and selected primary rejection-persistence local-failure isolation,
and explicit caller-owned diagnostic event staging with a legacy compatibility wrapper,
and development diagnostic status schema with read-only staged metadata preflight,
and an explicit original-pair-bound caller-owned diagnostic bridge,
and saved-source/create-ACL diagnostic access with fresh source drift checks,
and bounded/rechecked owned-session lock waits in the optional concrete provider,
and caller database-owner/raw-handle continuity checks for explicit diagnostic staging,
and received local-step isolation across existing-XML Sales/POS APIs and their public wrappers,
and shared guarded existing-XML rejection persistence with exact legacy UUID policy,
and guarded shared existing-XML reported writes with pinned-owner PIH/logging boundaries,
and Company batch message aggregation/display-only translation with English retained-event labels,
and shared presentation for Company single-check and Sales/POS Debug results,
and POS Debug generation independent of the unused live-scheduling selector,
and permissioned/non-destructive shared Sales/POS Debug attachment creation,
and attachment-only Debug UI updates with saved-form/concurrent-click guards,
and auth-free CSID success results with display-only wizard result fields,
and allowlisted single-popup CSID HTTP-failure diagnostics,
and explicit CSID local/transport outcome presentation with progress cleanup,
and shared CSID form guards without implicit save/reload or full Company reads)
are complete in development. ICV continuity has been characterized, not migrated.
The broader [unification plan](PLAN.md) is not complete. No change in this branch
has been deployed to the running application or sent to ZATCA. Increment 16 uses
a new private MariaDB test subprocess, never a tenant database or live service.
The current user mandate forbids ALL working/production environment changes and
agent-initiated authority requests, including Sandbox/Simulation. Development
completion must precede a separately approved isolated fictional-Company rehearsal,
then explicit gradual active-client pilot/rollout decisions. Prior notice alone
does not authorize a live write or request. See
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).

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
- Increment 27 is committed locally as `9d66b5a`. Its GitHub push was rejected by
  the approval reviewer on 2026-10-11 pending destination/content authorization;
  the rejection was not bypassed. After the user's explicit approval of the
  destination, content and development branch, increments 27 and 28 were pushed
  to `Top1ERP/zatca_erpgulf`, advancing only that branch from `50c13bc` to
  `36992be`. This publication did not deploy code, change main, restart services
  or authorize any working-environment change or authority request.

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

## Increment 15: endpoint-bound response and returned-XML assessment

- Added a pure immutable assessment of the candidate-bound receipt. Normal 200
  success and 202 success with warnings are preserved when operation/validation
  are consistent. Generic 409 remains unconfirmed, 303 is a separate observation,
  and HTTP/validation/auth/transport outcomes do not grant retry permission.
- Reporting requires no returned XML; clearance requires an unambiguous match
  of returned identity/type/declared digest/PIH. Changed clearance serialization,
  signature, certificate and QR are allowed without modifying submitted bytes.
- Shared the existing bounded duplicate-key/numeric decoder with historical
  diagnostics, preserving legacy-wrapper semantics there. The new wire reader
  rejects wrappers/HTML/multiple objects instead of repairing them.
- Added 278 local cases. No cryptographic/business-data/provenance verification,
  database writes or runtime adapter adoption. See
  [RESPONSE_ASSESSMENT.md](RESPONSE_ASSESSMENT.md) for policy and official sources.

## Increment 16: durable journal storage and private InnoDB rehearsal

- Added versioned bounded candidate/event codecs. Stored declarations and exact
  XML/receipt bytes reconstruct existing contracts without current ERP settings.
- Added an explicit-connection MariaDB repository with row locks, immutable
  candidate comparison, namespace/identity uniqueness, append history CAS and
  idempotent event redelivery. No internal commits, schema installation or HTTP.
- Added 112 local cases and 25 actual private MariaDB cases, including concurrent
  creation/appending, timeouts, rollback, cross-candidate collisions, corruption,
  and owned-test-server crash recovery. No tenant connection or migration.
- This is not yet an installed Frappe service, outbox, chain allocator, network
  lease or cross-attempt policy. See [JOURNAL_REPOSITORY.md](JOURNAL_REPOSITORY.md).

## Increment 17: ephemeral signing/authentication material binding

- Added a pure frozen snapshot binding route/purpose, private key, signing
  certificate, Basic authentication certificate and explicit UTC validity time.
  Exact DER equality rejects renewed certificates even when the key is unchanged.
- Added an internal read-only capture adapter reusing the existing owner/alias
  policies. One Company projection is frozen before source/device reads; this
  is not an atomic cross-row transaction or verified credential epoch.
- Shared bounded public certificate parsing and authorization field policy.
  Existing signing/hash/QR algorithms and legacy runtime call paths are unchanged.
- Added 100 local cases and an Arabic error catalog entry. Secrets are hidden from
  printable diagnostics; no persistence/HTTP/dispatch/replay authority is granted.
  No existing generator or request adopts this capture yet. See
  [CREDENTIAL_SNAPSHOT.md](CREDENTIAL_SNAPSHOT.md) for provenance/adoption gates.

## Increment 18: legacy credential lifecycle separation evidence

- Added independent per-purpose token/certificate/key/time observations and
  registered certificate-field fingerprints; reports retain no secret material.
- Added an internal read-only saved-source adapter sharing the alias registry and
  frozen Company projection. It is not a public endpoint, migration or selector.
- Reproduced Company shared-certificate overwrite, device alias transition and
  shared-key replacement with the actual legacy functions and mocked side effects.
  Existing signing conflicts and CSID writers remain unchanged.
- Added 122 cases and an English staged migration/storage proposal. Atomic
  provenance, secure bundle storage, UI/return redaction, runtime adoption and
  v15/v16 rehearsal remain gates. See [CREDENTIAL_LIFECYCLE.md](CREDENTIAL_LIFECYCLE.md).

## Increment 19: encrypted versioned credential staging

- Added explicit owner/environment/purpose slots, immutable version/flow/parent
  declarations and AES-256-GCM envelopes with caller-supplied in-memory keys.
  Original certificate/key/auth text is encrypted, not repaired or logged.
- Added a transactional explicit-connection staging repository. Exact envelope
  redelivery is idempotent; changed secrets or envelopes cannot replace a version.
  Parent flow/slot/key consistency is checked without claiming remote completion.
- Added private-only DDL, 92 local cases and 23 real private MariaDB cases for
  isolation, corruption, rollback, competing stages, lock timeouts and crash recovery.
- No activation pointer/API, Frappe installer/migration, key discovery or runtime
  adoption. Protected key management, verified source/remote provenance and
  permissioned localized service integration remain gates. See
  [CREDENTIAL_BUNDLE_STORAGE.md](CREDENTIAL_BUNDLE_STORAGE.md).

## Increment 20: permissioned staged metadata inspection

- Added an internal non-whitelisted operator service, server-bound site/namespace
  and protected resource-provider contracts. No key or connection discovery.
- Requires the operator role and every saved Company/source/device/linked-row
  read permission before acquiring storage resources. Document ignore-permission
  and test-mode flags cannot bypass this boundary; actor drift is rejected.
- Reuses the existing owner/route policy without projecting legacy secret fields.
  Requires an exact version/slot and matching manifest source Company/kind.
- Returns only metadata with authority flags false. Localized generic errors do
  not chain potentially secret-bearing provider/driver exception details.
- Added 105 local cases and three actual private SQL service cases. No runtime
  adoption, key-custody provider installation, activation or live change. See
  [CREDENTIAL_BUNDLE_ACCESS.md](CREDENTIAL_BUNDLE_ACCESS.md) for deployment gates.

## Increment 21: version/CSR-bound Compliance observations

- Derives three/six required types from bounded signature-valid CSR functionality,
  matching its public key to the staged version and UID to saved Company Tax ID.
- Binds exact request/response observations to one manifest/flow/request/version,
  namespace, gateway, embedded certificate, XML type, UUID and declared digest.
- Distinguishes consistent 200/202 validation, exact type-specific raw 406 previous
  completion, rejections and unknown transport. No local marker or repeated single
  result can complete missing types; conflicting attempt/sample identities fail.
- Composes the increment 20 operator gate with an authenticated staged-row read
  before returning metadata. No body/credential export, new whitelist or live use.
- Added 136 local and four actual private SQL cases. These are supplied local
  observations, not verified remote acceptance or durable receipt capture; all
  activation/completion flags remain false. See [COMPLIANCE_EVIDENCE.md](COMPLIANCE_EVIDENCE.md).

## Increment 22: encrypted append-only Compliance archive

- Added bounded versioned binary frames and a dedicated AES archive cipher,
  preserving exact CSR/request/response bytes, including empty HTTP bodies.
- Added explicit-transaction request preparation, immutable receipt append and
  exact scoped history loading against an authenticated staged Compliance bundle.
- Requires independent archive/bundle key material; shared bounded key validation
  preserves existing bundle format/behavior. No key discovery or implicit commits.
- Added private-only DDL, 147 archive-local cases, two net empty-response cases and
  27 actual private SQL cases including races, rollback, corruption and crash recovery.
- No trusted HTTP capture/dispatch, operator endpoint, installer, live adoption or
  activation. Durable supplied observations remain unverified remote evidence. See
  [COMPLIANCE_ARCHIVE.md](COMPLIANCE_ARCHIVE.md).

## Increment 23: permissioned archived Compliance inspection

- Extended the internal staged inspection service, reusing saved source/owner ACLs
  before resource acquisition and authenticated exact-version/slot loading.
- Added an optional explicitly supplied independent archive cipher; existing
  three-argument resource construction and prior inspection modes are unchanged.
- Accepts only a bounded unique explicit selection; checks stored manifest,
  taxpayer, route and shared CSR. Whole-selection failure never returns partial
  success; reports do not claim complete history or verified remote completion.
- Added 145 local cases and seven owned-private SQL service cases. No whitelist,
  key discovery, HTTP, credential activation, UI or live writes. See
  [COMPLIANCE_ARCHIVE_ACCESS.md](COMPLIANCE_ARCHIVE_ACCESS.md).

## Increment 24: single-use two-transaction Compliance capture scaffold

- Added strict non-idempotent reservation using the existing archive primary key;
  observational preparation remains idempotent. An existing reservation never
  becomes authority to send, even when the ciphertext is identical.
- Added an internal coordinator with explicit owned-transaction/clock/transport
  dependencies. Exact-version material is authenticated and freshly time-checked;
  the first transaction commits/closes before one transport-dependency invocation.
- A second transaction stores the immutable received bytes. Unknown preparation,
  transport or receipt commit outcomes never automatically replay. Exact protected
  receipt ciphertext is retained for reviewed persistence reconciliation.
- Added 137 local and 17 owned-private SQL cases, including competing collectors,
  ambiguous commits and owned-server crashes. No default HTTP sender, trusted
  source/transport attestation, operator capture API, live adoption or activation.
  See [COMPLIANCE_CAPTURE.md](COMPLIANCE_CAPTURE.md).

## Increment 25: explicit standard-gateway Compliance HTTPS adapter

- Added an opt-in exact-route policy, original-byte prepared POST and a direct
  zero-retry streaming HTTPAdapter with TLS verification and explicit empty proxy
  map. No Session/redirect/environment-auth or URL fallback is used.
- Added bounded undecoded entity reads, framing/encoding/header checks and
  finite timeout/monotonic budget checks. Budget checks are not a hard wall deadline.
- Existing routes/buttons are unchanged; custom gateways are deliberately not
  supported by this new adapter pending reviewed egress policy.
- Added 191 local and four owned-private SQL integration cases using synthetic
  HTTP pools. No real TLS handshake, ZATCA call, native transport attestation,
  permissioned source provider, runtime adoption or activation. See
  [COMPLIANCE_HTTPS.md](COMPLIANCE_HTTPS.md).

## Increment 26: permissioned saved-source capture and Frappe ACL compatibility

- Added an internal server-bound capture service requiring role/site and direct
  saved-row read/write ACL before resource-provider access. No legacy secret
  projection, whitelist, button adoption or shared Frappe transaction changes.
- Compare exact non-secret Company/source/device/linked-owner fields and modified
  revisions with bounded parameterized FOR UPDATE reads in the reservation
  transaction and a separate closed preflight transaction. Recheck saved ACL
  after closure before releasing the request to the actual transport dependency.
- Guarded calls own three transactions; unguarded callers retain two. Source/ACL
  failure stops transport and never permits automatic replay or activation.
- Shared signature-based quiet permission calls support the inspected Frappe
  15/16 parameter change without internal-TypeError retries. Added Arabic errors.
- Added 206 local source-service, 18 permission-signature and eight owned-private
  SQL cases. Ambient ACL cache/freshness, provider origin, durable source/epoch,
  CSR and actual TLS/transport provenance remain gates; no ERPNext 16 boot or
  live adoption. See [COMPLIANCE_CAPTURE_ACCESS.md](COMPLIANCE_CAPTURE_ACCESS.md).

## Increment 27: guarded offline-only development and phased acceptance policy

- Added a fixed reviewed-test runner with an explicit before-collection I/O guard:
  no Python TCP/IPv6/DNS/normal Requests send, working Frappe site initialization,
  unknown Unix SQL socket or arbitrary subprocess/Bench operation.
- Private SQL now requires the guard before acquisition. Only owned scratch
  sockets and exact reviewed TCP-disabled native commands are admitted. Existing
  request/receipt/synthetic HTTPS cases remain offline; no application runtime
  module, hook, dependency or UI behavior was changed in this increment.
- Added 80 local guard/runner cases and reran all six private SQL suites under it.
  This is an accidental-I/O guard, not an OS sandbox or hostile-code guarantee.
- Recorded the user's absolute no-working-environment/no-authority-send mandate
  and order: finish development, separate fictional-Company acceptance, then
  explicitly approved gradual active-client pilot. A generic continuation or
  deployment approval does not authorize sending. See
  [SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).

## Increment 28: explicit local receipt persistence recovery

- Added an internal recovery primitive with explicit archive/bundle keys and an
  owned connection factory, deliberately without transport/clock dependencies.
  Only the exact protected uncertain-receipt result is accepted; authenticate
  both retained envelopes before SQL and compare full observation bindings.
- Receipt persistence optionally requires the EXACT committed start envelope,
  not merely matching plaintext. Missing/corrupt/resealed starts or conflicting
  receipts cannot be adopted, recreated or overwritten. No schema change.
- One owned transaction appends/confirms identical receipt ciphertext, commits
  and closes. Uncertainty retains the original result, without automatic retry.
  Existing captured state/projections grant no remote/Compliance/activation
  authority. Capture and recovery share the owned-transaction cleanup helper.
- Added 67 local and 13 private SQL cases; all seven private suites ran under
  the offline guard. No live API, installed hook/button, permissioned recovery
  endpoint, durable custody queue, active credential or tenant write was added.
  See [COMPLIANCE_RECEIPT_RECOVERY.md](COMPLIANCE_RECEIPT_RECOVERY.md).

## Increment 29: permissioned local receipt recovery and shared source policy

- Extracted capture's private saved-owner/read-write-ACL/revision policy for reuse
  by local recovery. Current source/Company/route/CSR bindings and direct quiet
  permission-engine checks precede the server key/resource provider.
- Added an internal recovery service/resources contract without transport/clock,
  open/shared connections, whitelist, UI/hook, schema installation or activation.
  Authenticate the retained envelopes before acquiring the owned SQL handle.
- The optional literal-True source guard locks current projected source rows
  before bundle/archive access and repeats checks after append, before commit.
  Recheck actor/saved ACL/revisions after closure; revocation can prevent result
  disclosure but cannot undo an already committed historical receipt. Original
  protected receipt custody remains the caller's duty.
- Added translated English/Arabic failures, 187 local and 12 owned-private SQL
  cases. Current recovery-time rows are NOT generation-time source evidence.
  Ambient ACL/cache/revocation and provider/epoch/CSR/remote provenance remain
  unverified. No authority request or running-site change was made.
  See [COMPLIANCE_RECEIPT_RECOVERY_ACCESS.md](COMPLIANCE_RECEIPT_RECOVERY_ACCESS.md).

## Increment 30: shared issue-time normalization and adapter consistency

- Added an explicit Frappe/clock-independent time contract with bounded ERP date,
  time, text and same-day duration parsing, valid midnight, explicit offsets,
  UTC rollover and deterministic whole-second serialization. Naive fields need
  an explicit timezone; DST gaps/folds fail rather than guessing an offset.
- Preserved legacy QR/time wrapper names. Sales/POS XML validates time from its
  SAME loaded invoice BEFORE UUID persistence, instead of reloading a potentially
  different revision. Debug/compliance metadata UUID isolation remains tested.
- Synthetic samples use aware UTC and emit the shared Z-marked issue time;
  this removes naive-UTC re-interpretation by the QR adapter/site timezone.
  Phase-2 Tag 3 rejects missing/duplicate/blank/nested XML issue fields before
  QR key access. Explicit XML offsets need no system timezone lookup.
- Initial advance Phase-1 QR uses the same helper without inventing midnight.
  All amount formulas and the guard preserving authoritative Phase-2 QR remain
  unchanged. Advance settlement references/settings epochs remain separate gates.
- Added 119 core, 93 adapter and one logger-denial local case (213 total).
  Negative tests exposed incomplete translation mocks; fixtures now mock them
  explicitly and the offline guard blocks frappe.logger before log discovery.
  No log was created by that failed fallback, and no tenant/site was initialized.
- Added English explanations/Arabic error keys. This is not a signature/digest
  fix, SDK/legal amount proof, issued-artifact migration, installed integration
  or actual v16 acceptance. The ERP adapter still delegates Frappe's existing
  timezone getter/default; current configuration provenance is NOT attested.
  See [ISSUE_TIMESTAMP.md](ISSUE_TIMESTAMP.md).

## Increment 31: original advance reference observations and legacy gaps

- Audited the shared direct allocation builder and both legacy item-template
  branches. Characterization reproduces missing/invalid-time midnight fallback,
  day-duration wrapping, offset removal and valid-zero-duration rejection.
- Added a pure read-only type-386 XML metadata primitive with explicit expected
  invoice/UUID/seller identity and bounded no-DTD/no-external-resource parsing.
  It preserves original date/time text, including offsets/fractions, without
  reading current timezone settings or silently inventing missing values.
- Exact-byte fingerprint and frozen metadata are observations, not proof of
  authentic origin, signature, acceptance, tax/GL correctness or SDK compliance.
  It intentionally has NO runtime assembly adoption until a permissioned,
  immutable original-artifact selector and Phase-1/legacy missing-source policy
  are implemented. No live builder, schema or setting was changed.
- Added 101 synthetic primitive and legacy-characterization cases to the fixed
  offline manifest. See [ADVANCE_REFERENCE.md](ADVANCE_REFERENCE.md) for the
  source inventory, conservative lexical limits and explicit adoption gates.

## Increment 32: exact archived-attempt advance source choice

- Added a frozen pure selector requiring one explicit journal plus expected full
  preparation context, UUID/ICV and pinned journal revision. It recomputes the
  response assessment instead of accepting independent success declarations.
- Reporting selects original request bytes; clearance requires returned XML.
  No latest-file/status heuristic, unconfirmed/rejected receipt, changed context
  or request fallback can supply a source. Returned issue date/time must match
  original text, covering a gap in the generic metadata response assessment.
- Added 78 generated-data local cases and 10 cases in a ninth private SQL suite for exact
  committed reconstruction, namespace isolation, late receipt revision and
  uncommitted observation rollback. No schema change or tenant connection exists.
- Selection is still an observation, NOT proof of provenance, permission,
  persistence, signature, acceptance or accounting. It is not adopted by runtime.
  A permissioned server-owned storage/source boundary and missing-original policy
  remain mandatory. See [ADVANCE_SOURCE_SELECTION.md](ADVANCE_SOURCE_SELECTION.md).

## Increment 33: permissioned advance archive metadata inspection

- Added an internal metadata-only operator service with current actor/site/role
  and saved-row read ACL before lookup/owned storage acquisition. It shares
  Company/device/linked owner resolution and quiet permission signature handling,
  without selecting/decrypting signing credentials or exporting XML.
- Binds source identity/UUID/ICV/marker/owner/environment/route to an explicit
  historical declaration. Locks bounded non-secret saved projections before
  exact journal reads, including exact SQL names under case-insensitive collation.
- Clears uncommitted observations on the owned handle first; never commits or
  touches recognizable shared Frappe handles. Attempts rollback and close on all
  outcomes, then rechecks access/source before returning metadata. Failures are
  redacted/Arabic translated. No builder/hook/whitelist/schema adoption exists.
- Added local boundary tests and a tenth owned-private SQL suite. Source lookup,
  tenant/connection origin, authenticated receipt, full epoch/amount/crypto/v16
  acceptance and Phase-1/legacy missing-source policy remain gates. Permission
  cache/table revocation is not atomically locked; all authority flags stay false.
  See [ADVANCE_SOURCE_ACCESS.md](ADVANCE_SOURCE_ACCESS.md).
- Recorded the user's whole-change adoption/cancellation decision AFTER finished
  development and isolated fictional-client rehearsal, without authorizing any
  rehearsal creation/deployment now. See [DUMMY_REHEARSAL_DECISION.md](DUMMY_REHEARSAL_DECISION.md).

## Increment 34: missing-original advance review and five-tag QR observations

- Added a bounded pure five-tag Base64/TLV observer that preserves source clock
  and amount text without current settings, math, identity generation or I/O.
  Extra/duplicate/truncated tags and unsupported lexical forms fail statically.
- Made QR-only/copy-only/missing-archive/ambiguous-original review outcomes explicit.
  QR tags 1..5 cannot supply invoice ID/UUID/ICV/type/original XML. Their format
  does not prove Phase-1 origin. Phase-1 eligibility/workflow stays unchanged;
  no inferred Phase-2 readiness, reconstruction, migration or acceptance follows.
- Added synthetic pure and actual-mocked-builder tests. Characterization found
  one existing ordinary Sales/POS QR generation commit, not a new observation side
  effect. That legacy transaction/attachment lifecycle is a separate migration gate.
- No runtime reference/amount/eligibility/QR builder or schema/button was changed.
  Mixed-phase historical references require official SDK/rule/source evidence,
  not guessed prohibitions or fictional artifacts. See [ADVANCE_SOURCE_GAP.md](ADVANCE_SOURCE_GAP.md).

## Increment 35: caller-owned Phase-1 QR metadata transaction

- Replaced ordinary Sales/POS recursive invoice db_set/save/commit with one
  explicit two-field metadata update, preserving modified marker and unrelated
  data. Mirrors fields after SQL and keeps notification; parent owns commit,
  rollback and document reload on failure. No amount/advance eligibility change.
- Removed dynamic field creation from the invoice helper. Missing QR schema fails
  before attachment operations with Arabic translation; existing install fixtures
  already declare both fields. No schema/fixture installation was performed.
- Added actual mocked-generator and owned private SQL cases for no incidental
  save/commit/DDL, parent-controlled visibility/rollback, failures at File/metadata/
  notify and later parent failure. File/image controllers remain mocked in SQL.
- Existing attachment selection/deletion, other caller commits, physical-file
  rollback and installed v15/v16 hook/customization behavior remain open gates.
  No deployed source or authority call was touched. See [PHASE1_QR_TRANSACTION.md](PHASE1_QR_TRANSACTION.md).

## Increment 36: preserve ordinary Sales/POS QR references without cleanup

- Replaced creation-ranked official-prefix selection/deletion with one pure
  scoped policy and descriptive ordinary-generator helper (old cleanup alias
  retained). Current same-invoice File references win over newer filenames.
- Unlinked/dangling/foreign/malformed/over-limit metadata and missing references
  with REPORTED/CLEARED labels require review. No first/newest automatic relink,
  global URL-existence fallback, deletion, status change or image generation in
  preserve/review paths. Duplicate same-URL rows remain untouched.
- Added a bounded six-field same-invoice File projection for both DocTypes and
  Arabic static review error, without content/physical reads or new endpoints.
  Fresh generation retains increment 35's transaction ownership and amounts.
- Existing advance print cleanup/force, explicit regeneration and Phase-2 helper
  behavior are not migrated. Metadata is not artifact/phase authenticity or a
  concurrency reservation. No accounting eligibility, deployed code or authority
  request changed. See [QR_ATTACHMENT_PRESERVATION.md](QR_ATTACHMENT_PRESERVATION.md).

## Increment 37: preserve advance QR artifacts in the print hook

- Removed implicit final-invoice attachment deletion/relinking and the initial
  advance `force` replacement bypass. Final/non-initial invoices are untouched;
  eligible initial advances share the ordinary bounded preservation/review adapter.
- Kept the signature and existing phase/schema/submission/amount gates. First
  generation formulas, discounts/FX/time/File behavior and status handling stay
  unchanged. No advance lookup/allocation/remaining/eligibility or GL/VAT change.
- Added synthetic local and owned-private SQL cases. Preservation is not artifact
  authenticity; legacy repairs, explicit regeneration authorization/selection/
  commits, concurrency and installed lifecycle remain gates. No deployed code or
  authority request changed. See [ADVANCE_QR_PRESERVATION.md](ADVANCE_QR_PRESERVATION.md).

## Increment 38: saved-row authorization for QR recovery endpoints

- Both preview/mutation require saved Invoice/Company read ACL; mutation also
  checks Invoice write before File queries. The exact saved context is reused
  internally, rather than a second invoice read or cached Company ACL subject.
- Added bounded same-invoice File projections and direct saved File read ACL/
  exact ownership/metadata checks before use/content reads; re-link needs File
  write checks too. Removed global URL-existence authorization. Guest/malformed
  input, loader/ACL faults and actor drift fail with a translated static denial.
- Mutation is POST-only; actual v15 registration and v15/v16-shaped quiet engine
  calls are tested, not a booted v16/HTTP runtime. XML parser fallback cannot
  swallow access denial. No accounting amount/allocation/settlement-eligibility change.
- Legacy heuristic/latest selection, implicit replacements, explicit commits,
  unbounded XML reads and actual File lifecycle remain gates. ACL is not artifact
  authenticity or atomic permission/source locking. No working source or
  authority request changed. See [QR_REGENERATION_ACCESS.md](QR_REGENERATION_ACCESS.md).

## Increment 39: non-destructive recovery selection and transaction boundary

- Replaced newest/first QR/XML guesses and invoice-value reconstruction with
  shared pure PRESERVE/REVIEW decisions. Missing originals cannot authorize a
  recovery GENERATE action; ordinary first-issuance policy remains unchanged.
- Removed XML/image reads, File/link mutations, link clearing and explicit
  commits from the endpoint. Current same-invoice references are preserved,
  otherwise recovery requires review. This does not authenticate QR contents.
- UI offers translated Review QR Code instead of a speculative regeneration.
  Older POST callers receive `preserved` or a review error, never false repair
  success. Invoice write ACL is retained on POST; no File write ACL is needed
  because there is no mutation. No working UI/assets were built or deployed.
- A verified original-artifact provider/recovery mutation remains unfinished;
  other Phase-2 artifact writers, concurrency and installed lifecycle remain
  gates. Amounts/advance selection/settlement eligibility/GL stay unchanged.
  See [QR_RECOVERY_PRESERVATION.md](QR_RECOVERY_PRESERVATION.md).

## Increment 40: exact archived-attempt Phase-2 QR source observations

- Added an internal immutable source selector bound to the declared preparation
  context, UUID/ICV and exact journal revision. Reporting selects original request
  bytes; clearance selects matching returned bytes. No latest/File/status fallback.
- Derived response/identity consistency, exact original/returned lexical clock
  matching and bounded namespace-qualified QR/Base64 observations. No supplied
  success dictionary or current timezone can replace historical evidence.
- Diagnostics/repr omit private XML/QR/identity/body; all verified/authorized
  flags remain false. Base64 structure is not TLV, signing or acceptance proof.
  No runtime provider, whitelist, button activation or recovery mutation added.
- Audited remaining Phase-2 hook prefix reuse/deletion/response/QR extraction
  risks without changing those callers. Permissioned committed-record provenance,
  historical epochs and authenticated/crypto validation remain gates. No amount,
  advance settlement, working environment or authority request changed.
  See [QR_SOURCE_SELECTION.md](QR_SOURCE_SELECTION.md).

## Increment 41: permissioned QR source metadata and shared archive access

- Added internal Sales/POS QR source metadata inspection with saved Invoice/
  Company/device/linked-owner read ACL and exact identity/route/status/revision
  binding before lookup/storage. No XML/QR/raw response export or recovery grant.
- Extracted shared projection/ACL/lock/owned-cleanup orchestration from advance
  metadata inspection. Advance entry points, marker precedence, Sales-only/type386
  constraints/messages remain, with existing local/native regressions unchanged.
- Added Arabic static denials/failures, revocation/actor/source and borrowed/
  cleanup guards. Only declared-owned handles are rolled back/closed; the ambient
  Frappe transaction is untouched. No commits, schema or invoice/File writes.
- Added a twelfth private SQL suite for exact source/journal locks and stale or
  uncommitted observations. Provider origin/ownership, committed historic epoch,
  authentic receipts and crypto/QR validity remain unproven, all flags false.
  No advance allocation/remaining/settlement or working/authority change.
  See [QR_SOURCE_ACCESS.md](QR_SOURCE_ACCESS.md).

## Increment 42: non-destructive Phase-2 completion hook

- Removed saved-response reconstruction, filename/creation prefix reuse, stale
  QR deletion, link replacement and status rewrites from the automatic hook.
  Existing event name/None return and Sales/submitted/accepted-label scope remain.
- Added bounded same-invoice metadata preservation/review using the shared pure
  recovery policy. No contents/images/credentials/global URL fallback or writes.
  Nominal REVIEW is internal and does not abort the parent; real SQL faults still
  propagate. No new public endpoint, UI, review persistence or schema installation.
- Missing local completion remains gated, not falsely successful. Primary Sales/
  POS submission/QR generation and shared legacy XML extractor are unchanged and
  remain separate source/access/transaction integration gates. A current URL is
  not phase/QR/authenticity proof. No advance/accounting/working/authority change.
  See [PHASE2_ARTIFACT_PRESERVATION.md](PHASE2_ARTIFACT_PRESERVATION.md).

## Increment 43: primary Sales/POS QR schema and metadata boundary

- The shared `attach_qr_image` no longer creates fields during attachment. Missing
  schema uses the existing static English/Arabic setup error; phase skip remains.
- One QR-link-only SQL dictionary update replaces invoice `db_set`, avoiding its
  before_change/on_change hooks and modified-time changes. No status/UUID/amount
  rewrite, recursive invoice save, helper commit or rollback. Existing payload,
  File/privacy/image/filename behavior and default dispatch gates remain.
- Global URL reuse, authenticated source binding, physical-file lifecycle and
  primary caller commits/error downgrades are NOT resolved. Missing schema or
  another post-response error can still reach legacy caller status handlers;
  this is a development slice, not an independently deployable live fix.
  No advance/accounting/working/authority change.
  See [PRIMARY_QR_TRANSACTION.md](PRIMARY_QR_TRANSACTION.md).

## Increment 44: scoped primary QR ownership and pre-request rejection

- Replaced primary attach helper's global URL existence check with bounded
  same-invoice metadata preservation/review. Invalid/dangling/foreign/orphaned
  observations cannot implicitly generate or replace a QR. New unambiguous
  primary attachment remains; saved status is not an authentication gate.
- All four primary Sales/POS Reporting/Clearance adapters check schema/link
  ownership before their error-saving try boundary, HTTP/payload/credential work
  and POS Reporting XML creation. Valid batches still defer; invalid batch
  references/schema now stop before local side effects. Static Arabic/English
  review uses the existing key; no invoice/File/status/transaction write occurs.
- This is a loaded-document observation, not ACL/authenticity/revision locking
  or a reservation. Post-response races/local failures and legacy receipt/status
  downgrades remain blocking work. Other writers/global helpers are not unified.
  No advance/accounting/working/authority change.
  See [PRIMARY_QR_OWNERSHIP.md](PRIMARY_QR_OWNERSHIP.md).

## Increment 45: primary post-response local-error review boundary

- All four primary APIs mark their existing response-processing branch sets
  before local formatting/logging/PIH/artifact work. Previously caught local
  failures there no longer run generic invoice error/503 writes or commits.
  This marker is not response validation or a new acceptance verdict.
- A shared static English/Arabic RuntimeError is raised outside the handler,
  without chaining raw local exception text or returning success. No in-call
  retry/repair/transaction operation; narrow legacy validation handlers cannot
  swallow this review signal. Normal/rejection/timeout behavior is retained.
- Existing partial commits, missing early durable receipts, later scheduler/
  queue retries and other adapters remain unresolved. No new durable hold or
  authentic receipt provider is activated. Independent clearance commits can
  still commit parent work, explicitly demonstrated rather than hidden by tests.
  No advance/accounting/working/authority change.
  See [RESPONSE_PROCESSING.md](RESPONSE_PROCESSING.md).

## Increment 46: exact local primary receipt persistence/redelivery

- Added an internal non-activated service reusing existing journal/codecs/owned
  transaction/storage primitives. Exact candidate/predecessor/HTTP-event input
  is rebuilt before SQL; only the exact stored predecessor or identical result
  is eligible. No candidate/start creation, byte replacement or resequencing.
- One owned transaction commits/closes before reporting local completion. Any
  acquire/SQL/guard/commit/close uncertainty retains the exact original receipt
  for explicit LOCAL idempotent storage redelivery, never another HTTP attempt.
  Protected objects are redacted/nonpickleable; all remote/provenance/replay/
  dispatch flags remain false. No invoice/File/status/PIH/schema writes.
- No primary API, scheduler or permissioned provider is wired. This does NOT yet
  fix runtime missing receipts, durable retry holds or legacy partial commits.
  Saved-source/attempt/epoch/provider binding and owned acquisition remain gates;
  a caller-supplied scope is not authority to store/send against a tenant.
  No advance/accounting/working/authority change.
  See [PRIMARY_RECEIPT_PERSISTENCE.md](PRIMARY_RECEIPT_PERSISTENCE.md).

## Increment 47: permissioned saved-source primary receipt persistence

- Extracted reusable saved-row/binding/recheck selection from the archive engine;
  existing advance/QR metadata inspection keeps read/accepted-status policy.
  The new private adapter requires invoice WRITE plus related saved-row READ,
  and binds exact candidate/context/UUID/ICV/predecessor/attempt/response event.
- Actor/site/role/ACL are checked before providers and after closure; exact source
  locks surround journal append in the same owned transaction. Recognizable
  borrowed Frappe/raw handles are never cleaned/committed. No invoice/File/PIH
  writes, secret loads or acceptance inference from current status. Static
  English/Arabic failures are unchained; caller must retain original input even
  when permission is revoked after a completed commit.
- Internal protected server input/output only: no primary API/scheduler/provider
  registration or durable retry hold. Origin/custody/historic epoch/source and
  permission atomicity remain unproven. No advance/accounting/working/authority
  change. See [PRIMARY_RECEIPT_ACCESS.md](PRIMARY_RECEIPT_ACCESS.md).

## Increment 48: explicit pinned Unix local receipt connection provider

- Added an optional concrete provider with explicit server-owned scope/socket/
  database/registration declarations and a typed ephemeral credential callback.
  No tenant/config/secret discovery, raw connector injection or ambient handles.
  Exact scope/socket checks precede secrets; each fresh non-autocommit Unix
  connection checks kernel peer UID/process, database/server/session identity
  and locked site/namespace marker before handoff, cursors and commit.
- Wrong/replaced endpoints or changed targets poison the handle; no TCP fallback,
  ping, reconnect or commit retry. Owned acquisition failures attempt rollback
  and close; static unchained errors do not disclose driver/credential details.
- Synthetic marker DDL is test-only, not a runtime installer. Provider composition
  is exercised only on owned private SQL. No Frappe/API/scheduler registration,
  working config/schema writes or authority calls. Linux/Unix checks do not prove
  historical tenant origin, receipt authenticity or custody; reviewed provisioning,
  least privilege and protected retained-input durability remain release gates.
  See [PRIMARY_RECEIPT_PROVIDER.md](PRIMARY_RECEIPT_PROVIDER.md).

## Increment 49: encrypted immutable local retained-receipt custody

- Added a bounded exact binary codec, dedicated supplied-key AES-GCM envelope
  and immutable caller-transaction SQL repository. Namespace/candidate/attempt/
  predecessor/payload/key bindings are authenticated and rebuilt. Exact XML,
  timestamps, optional UNKNOWN and empty/binary HTTP body bytes are preserved.
- Only an exact existing predecessor/already-recorded result may be staged. One
  exact envelope per attempt, no overwrite/reseal/delete/latest fallback or new
  start/journal append. Scope/authentication checks precede SQL; transaction
  errors poison the handle and expose static unchained errors. Caller owns
  commit/rollback/close; return is not a durable acknowledgment.
- Test-only DDL and owned-private crash/parallel-writer/nonce/scope/conflict tests.
  No working schema/secret discovery/provider installation/API/job/authority call.
  Local key possession is not remote provenance; no permissioned retrieval or
  durable no-replay hold is enabled. Pre-first-commit response loss remains open.
  See [PRIMARY_RECEIPT_CUSTODY.md](PRIMARY_RECEIPT_CUSTODY.md).

## Increment 50: permissioned encrypted local custody storage/retrieval

- Added a protected internal service over the immutable custody repository.
  Invoice WRITE/related READ and exact saved declaration precede scoped keys/SQL;
  authenticated retained candidate/context/epoch/predecessor/attempt/response must
  match. Current status is not receipt/acceptance authority. No sealer/fallback.
- Shared exact-binding and owned-acquisition helpers now serve both primary
  journal persistence and custody. Stage guards source rows around ONE owned
  commit/close and retains identical ciphertext on uncertainty. Retrieval returns
  ciphertext only after owned rollback/close and final actor/source/ACL checks.
  Borrowed parents stay untouched; no ambient commits. Static unchained messages
  include Arabic translations. A late denial cannot undo a completed commit.
- Only synthetic composition with the pinned provider/private SQL is exercised.
  No raw export, source/epoch/provider attestation, runtime provider/API/job/hold
  activation, schema/working/client/authority change. Pre-first-durable-commit
  response loss, partial parent commits and later retry policy remain gates.
  See [PRIMARY_RECEIPT_CUSTODY_ACCESS.md](PRIMARY_RECEIPT_CUSTODY_ACCESS.md).

## Increment 51: atomic primary start/logical-invoice no-replay hold

- Added a non-activated strict repository over an explicit caller transaction.
  Candidate/start codecs rebuild before SQL; the saved candidate must exist and
  its journal must be exactly empty. Explicit first-event append and immutable
  logical-source hold insert share ONE transaction; any error requires full
  rollback, including a losing version's already-appended start.
- The versioned source key fixes namespace/Company/doctype/invoice identity, not
  candidate/version/chain/environment/UUID/ICV/epoch/classification. No idempotent
  reservation reuse, expiry/release/status-based unlock or legacy backfill.
  Exact readback is inspection only; presence/absence/HTTP status cannot grant
  dispatch or replay. Static unchained errors, poisoned handles and hidden data.
- Owned-private atomicity/crash/race/drift tests only; DDL is test-only. No active
  sender/scheduler/permissioned coordinator, global alias/namespace proof, real
  transport/source/epoch attestation or correction/reconciliation policy. Existing
  runtime retries and pre-first-durable-response loss remain unresolved. No live,
  customer, advance/accounting/QR/crypto or authority change.
  See [PRIMARY_ATTEMPT_HOLD.md](PRIMARY_ATTEMPT_HOLD.md).

## Increment 52: exact auth-free primary observation coordinator

- Added a deterministic version-1 request from archived exact XML/UUID/digest;
  its codec/hash binds atomically with strict start/hold reservation. Independent
  typed request/response snapshots bind request hash/attempt/event/time/bytes.
  No auth header, implicit clock/ID allocation or claim of real HTTP provenance.
- Three owned transactions: reserve/close, exact guarded preflight/close, ONE
  supplied observer, then original sealed custody + exact journal event in the
  same transaction. Unknown commit/close never loops/reseals; complete unbound
  responses are retained, not forced into a different revision. All acceptance/
  provenance/dispatch/replay flags remain false and no hold is released.
- New binding DDL is private-test only; observer/keys/source guards are synthetic.
  No permissioned coordinator facade, live provider/API/scheduler/transport or
  schema/customer/advance/accounting/QR/signature changes. Pre-first-receipt-
  commit loss, paired reconciliation, legacy retries/commits and authentic
  source/credential/epoch/transport evidence remain release gates.
  See [PRIMARY_CAPTURE.md](PRIMARY_CAPTURE.md).

## Increment 53: permissioned saved-source local primary capture

- Added exact request/target/START/attempt/body/key binding, saved invoice WRITE
  and related READ before scoped resources/SQL. Shared owned acquisition and
  source guards repeat checks around three coordinator transactions; no active
  observer/provider/API/job is registered and no DDL is added.
- Normal coordinator results go to an explicit trusted server retainer before
  final disclosure checks. Only diagnostics return. Revocation after response or
  commit refuses disclosure without discarding retained material or undoing SQL.
  ACK is not durability proof; failed/interrupted ACK transfers an exact hidden
  server recovery result, never a browser export or permission to retry.
- Observer custody before a normal result, process-loss recovery, paired exact
  reconciliation and authentic source/namespace/key/epoch/provider/transport
  remain gates. No live/source/config/schema/workers/customer/authority,
  advance/accounting/QR/signature or legacy retry change is activated.
  See [PRIMARY_CAPTURE_ACCESS.md](PRIMARY_CAPTURE_ACCESS.md).

## Increment 54: exact local primary receipt pair reconciliation

- Added explicit protected request/original-envelope inspection and LOCAL
  persistence. Authentication and exact scope/start binding precede SQL; existing
  hold/request-codec/hash and literal source guards are mandatory. Inspection
  rolls back/closes without commit. No candidate/start/hold is created.
- Exact START + absent custody may receive BOTH original response parts atomically;
  identical stored pairs are acknowledged without new receipt writes. Partial,
  changed-seal/history and UNKNOWN pairs are review-only, never repaired/adopted.
  Unreadable/binding/cleanup failures are unconfirmed, not safely absent. Original
  input survives uncertain commits; cleanup attempts rollback AND close even on
  interruption. No observer/HTTP/reseal/hold release or automatic follow-up.
- This is an internal explicit-dependency primitive, not a permissioned endpoint
  or runtime adapter. Saved-source paired access, lost/late/unbound policy and
  authentic key/namespace/epoch/provider/transport evidence remain gates. No live
  code/config/schema/assets/workers/customer/authority, accounting/advance/QR/
  signature or existing runtime retry change. See
  [PRIMARY_RECEIPT_RECONCILIATION.md](PRIMARY_RECEIPT_RECONCILIATION.md).

## Increment 55: permissioned local primary pair access

- Added shared saved invoice WRITE/related READ and exact request/target/START/
  attempt/key/payload/original-envelope declarations before scoped keys/SQL.
  Full bounded envelope fingerprint distinguishes independently sealed equal
  plaintext without changing signing/AAD/certificate/XML hashes.
- One owned transaction uses source/ACL checks around exact saved-row locks and
  local pair work. Final checks refuse even diagnostics after source/actor/ACL
  drift; completed commits are not undone. Only metadata returns, with all
  origin/epoch/transport/acceptance/dispatch/replay flags false. Original inputs
  remain caller-owned on denial, interruption and uncertain commit.
- Core partial/different/UNKNOWN review policy is unchanged. This is not a
  whitelist/UI/job/runtime caller, provider/key installer or authority sender.
  Historical/independent lookup/key/custody/provider provenance and legacy
  separate-writer/lost-response policy remain gates. No working source/config/
  schema/assets/workers/customer, advance/accounting/QR/signature or runtime retry
  change. See [PRIMARY_RECONCILIATION_ACCESS.md](PRIMARY_RECONCILIATION_ACCESS.md).

## Increment 56: writer/late-response evidence and pure primary review

- Distinguished current twelve runtime adapters' mutable field/File/PIH/commit
  paths from the non-activated staged single/pair stores. Actual separate private
  writers reproduce partial windows and uncertain second commits. Strict paired
  review never fills the missing half or silently changes an original seal.
- Private tests preserve UNKNOWN and the original sequence-2 response without
  resequencing. Independently supplied late sequence-3 observations remain a
  distinct older contract; strict START-only paired access rejects that changed
  predecessor before SQL. No receiver or late-adoption runtime policy is added.
- Added a pure typed review projection for exact capture/optional paired input,
  with no protected references or I/O/actions. Missing/unbound/unsealed/pair
  uncertainty and disagreement are review reasons, never acceptance or automatic
  retry/repair/identity/hold-release permissions. Different requests/seals/scopes
  are refused rather than relabeled.
- New mocked tests reproduce a remaining primary HTTP400/401/503 local logging
  failure gap: generic handlers can still commit mutable local error fields.
  This is NOT repaired by the new pure reviewer. Isolate that boundary next;
  do not blindly remove commits before response custody/parent lifecycle design.
  No working/source/schema/config/assets/workers/customer/authority action or
  active runtime retry, accounting/advance/QR/signature behavior change occurred.
  See [PRIMARY_WRITERS_AND_REVIEW.md](PRIMARY_WRITERS_AND_REVIEW.md).

## Increment 57: received local presentation/logging-step isolation

- Closed the increment56 error-status local-log/formatter gap in the four actual
  primary Sales/POS APIs in DEVELOPMENT source. Explicit callback guards are
  bound only after transport returns; both event-log branches, hide and all
  existing formatter calls (including lazy text and late rejection formatting)
  use the static translated local-review RuntimeError signal for formerly caught
  ValueError/TypeError/KeyError/framework ValidationError failures.
- The signal escapes legacy narrow generic handlers without extra response/
  status/UUID writes, 503 downgrade, commit, read or retry AFTER the local fault.
  It neither rolls back previous writes nor guarantees receipt custody. Runtime
  errors/interruptions, transport exceptions and pre-request notification errors
  retain their previous propagation. No response/body/PIH/auth/route changes.
- Intentional rejection throws and all normal success/rejection branches remain
  unchanged, including undesirable old placeholders/commits/generic wrapping/
  503 mappings and inconsistent 409 behavior. The twelve increment56 defect tests
  are now exact no-extra-effect regressions. Reject-persistence/caller boundaries,
  durable custody/parent lifecycle and endpoint-bound acceptance remain gates.
  No working source/config/schema/assets/workers/customer/authority action, QR/
  crypto/advance accounting or scheduler/replay change. See
  [RESPONSE_PROCESSING.md](RESPONSE_PROCESSING.md).

## Increment 58: selected primary rejection-persistence isolation

- Guarded local: **8,487 passed in 54.37 seconds**. Guarded combined: **8,487
  local + 1,084 private SQL = 9,571 passed in 102.12 seconds**, across the same
  twelve private suites (438 local + 112 private additions). All HTTP/documents
  are synthetic; SQL uses newly owned temporary servers, never customer sites.
- Three named English-documented helpers replace twelve repeated rejection
  persistence blocks in the four DEVELOPMENT primary APIs. Known local failures
  during invoice load, save/db_set, response text/setter or commit use the same
  static translated review signal, without subsequent generic writes/503/commit/
  retry. The wrapper neither rolls back nor guarantees original-response custody.
- Normal intentional rejection throws, placeholders/valid UUID policy, commit
  ordering, existing generic wrapping/503 mapping, success/303/409 behavior and
  POS pre-HTTP XML linking remain unchanged. Prior commits and parent-work
  effects remain visible; pending state still belongs to the caller.
- The real event logger still swallows errors, returns None and owns an ambient
  commit. That is audited, not rewritten. Immediate generator handlers remain
  narrow; whole-program worker/parent integration and honest caller-owned logger
  transaction/result semantics remain gates alongside exact custody.
- No installed source/config/schema/assets/Bench/customer/authority action;
  no advance/discount/GL/VAT, credentials/routing or signature/QR change.
  See [REJECTION_PERSISTENCE.md](REJECTION_PERSISTENCE.md).

## Increment 59: explicit diagnostic event staging, not runtime adoption

- Guarded combined: **8,608 local + 1,144 private SQL = 9,752 passed in 103.30
  seconds**, across the same twelve private suites. This adds 121 local and 60
  private SQL cases. First local passed 8,604 in 53.95 seconds before four
  callback-return/schema-characterization cases; the final combined run includes
  them. No runtime/ownership assertion was relaxed to make the tests pass.
- `stage_zatca_event` uses normal insertion permissions, no explicit commit/
  rollback/fallback/retry, and propagates exceptions unchanged. Its closed
  INSERT_RETURNED result means only that the call returned, never durable
  storage/complete schema/authority acceptance. Optional explicit received-step
  guarding uses the existing translated static review signal.
- The legacy `log_zatca_event` keeps ignored permissions, ambient commit,
  swallowed ordinary failures/fallback and None behavior. Shared insertion/
  payload construction does not migrate any submission path to staging. Raw
  fallback privacy and diagnostic normalization limitations remain unchanged.
- Private SQL distinguishes pending work from previous commits and explicitly
  reproduces hooks committing/committing-then-failing. A staging helper is NOT
  a sandbox against hook side effects. No exact receipt/capture/provider/worker/
  acceptance integration is claimed. Source metadata also lacks the payload's
  status field; this is recorded without tenant lookup, DDL or migration.
- No installed source/config/schema/assets/Bench/customer/authority action,
  including Sandbox/Simulation. No advance/discount/accounting/QR/crypto change.
  See [EVENT_LOG_TRANSACTION.md](EVENT_LOG_TRANSACTION.md).

## Increment 60: development diagnostic schema and staged preflight

- Guarded combined: **8,737 local + 1,160 private SQL = 9,897 passed in 103.74
  seconds**, across the same twelve private suites (129 local + 16 private SQL
  additions). First local passed 8,731 in 55.34 seconds before six malformed/
  unreadable metadata cases; all six are included in the final combined run.
  Existing ownership/privacy/transaction assertions were not weakened.
- The DEVELOPMENT Event Log DocType now defines read-only Diagnostic Status
  (ordinary Data, not acceptance), with English explanation and Arabic catalog
  entries. Existing UUID fixture/fields/permissions are preserved. No tenant
  migration, automatic collision repair, historic backfill or patch/hook is added.
- New staging alone checks loaded ORM metadata before clock/normalization/doc
  creation: ordinary table, six unique stored fields, exact field types/lookup
  identities and non-narrowed Data widths. Missing/duplicate/fetched/virtual or
  malformed metadata raises static translated unchained schema review, no insert.
  Metadata acquisition/insertion exceptions retain their propagation. The legacy
  wrapper is not gated and no invoice caller is switched to staging.
- This is not physical-column synchronization, installed v16 metadata evidence,
  trusted schema provenance or hook isolation. Real custom-field/Property Setter
  collision review and exact original response custody/parent lifecycle remain
  prerequisites before separately approved fictional-client migration/adoption.
- No installed source/config/schema/assets/Bench/customer/authority action;
  no advance/discount/GL/VAT/QR/crypto or request acceptance change. See
  [EVENT_LOG_TRANSACTION.md](EVENT_LOG_TRANSACTION.md).

## Increment 61: original-pair-bound diagnostic bridge, no active caller

- Final guarded combined: **8,824 local + 1,176 private SQL = 10,000 passed in
  107.21 seconds**, across the same twelve private suites (87 local + 16 private
  SQL additions). Initial local had 8,737 passes and 60 fixture setup errors in
  54.40 seconds because the new module omitted the certificate fixture import.
  Adding that import, without changing runtime/crypto/ownership assertions,
  yielded 8,797 local passes in 57.30 seconds. The final run also includes 27
  added binding/interruption/schema/Arabic/all-declared-source-type cases.
- Added an internal exact-original request/envelope adapter. Supplied authorized
  reconciliation/key dependencies authenticate originals and INSPECT the actual
  pair; only MATCHED continues. Missing/partial/conflict/UNKNOWN/unconfirmed
  observations are review-only. No pair persist/repair, reseal or HTTP occurs.
- Owned inspection rollback/close precedes diagnostic hooks. Original envelope
  authentication is repeated, strict UTF-8 is required, and invoice/UUID/status/
  body derive from archived originals, never free-form or mutable response fields.
  Static English/Arabic review/labels do not translate the body. Result remains
  only INSERT_RETURNED, not acceptance/durable-custody proof or protected export.
- Independent committed pair evidence is not rolled back by a diagnostic failure
  or caller rollback; ambient hooks can still commit unrelated parent work.
  Diagnostic normalization/duplicate rows and bare invoice-number lookup are NOT
  ledger custody, idempotence or permission. Original inputs must remain under
  server custody; provider/source/ACL/race/transport and worker lifecycle remain
  unfinished integration gates.
- No active submission/endpoint/provider wiring, installed source/schema/Bench/
  worker/customer/authority action, including Sandbox/Simulation. No accounting/
  advance eligibility/QR/crypto/PIH/ICV/acceptance policy change. See
  [EVENT_LOG_TRANSACTION.md](EVENT_LOG_TRANSACTION.md).

## Increment 62: permissioned diagnostic access and fresh source drift checks

- Final guarded combined: **8,942 local + 1,212 private SQL = 10,154 passed in
  133.20 seconds**, across the same twelve private suites (118 local + 36 private
  SQL additions). Initial local passed 8,928 in 61.33 seconds before fourteen
  actor/strict-callback cases. First combined had 10,118 passes and 36 failures
  in 116.94 seconds: the new native test inspected a raw-driver open attribute
  on the pinned provider's wrapped handle. It now requires the same documented
  closed property used by existing provider tests, retaining the strict cleanup
  assertion. No runtime, source/ACL/custody or transaction assertion was relaxed.
- Added INTERNAL saved-source diagnostic staging using the existing exact-source
  binding/access engine. Invoice WRITE/related READ plus quiet Event Log CREATE
  are required before keys/owned SQL. Site/role/actor, source revision, original
  request and full envelope declarations remain bound; ignore_permissions is
  not an access shortcut. No endpoint, worker or live caller is registered.
- Fresh independently owned source-only locking reads bracket the diagnostic
  insert/hook call, not just the ambient ORM snapshot. Owned reads rollback/close
  without commit/source mutation/parent cleanup. Changes at these boundaries
  deny success metadata; post-insert changes may follow a pending/committed event
  and do NOT authorize deletion/compensation or pretending no event was written.
- Metadata is static and non-authorizing; non-permission diagnostic failures are
  static translated RuntimeError-family review, avoiding narrow legacy generic
  invoice-failure writers. Existing inspect/persist/logger behavior is preserved.
  Source-neutral parent, lock-wait/race/ACL/ABA/provenance and full installed
  lifecycle remain gates; source locks do not span framework hooks.
- No installed source/config/schema/assets/Bench/worker/customer/authority action,
  including Sandbox/Simulation; no original receipt rewrite, reseal/retry/hold
  release or invoice/advance/accounting/QR/PIH/ICV change. See
  [EVENT_LOG_TRANSACTION.md](EVENT_LOG_TRANSACTION.md).

## Increment 63: owned-session lock waits, not completed diagnostic isolation

- The optional concrete Unix provider validates its peer and sets fixed one-second
  SESSION row/metadata lock waits before registration locking. Exact read-back is
  required before every cursor/commit. Drift/unreadable settings reject/poison
  rather than reset/reconnect; acquisition errors attempt owned rollback/close.
  Existing five-second driver I/O timeouts remain. No GLOBAL or ambient setting
  is changed; arbitrary injected factories are not globally constrained.
- Actual temporary SQL contention tests show registration acquisition cleanup
  and diagnostic source-row timeout 1205 without clearing/committing the blocking
  parent's pending work or modifying the committed original pair. No second
  observer/HTTP call occurs. Individual lock waits are not a whole-transaction
  deadline or permission to retry after uncertainty.
- Original two-second-policy guarded combined: **8,972 local + 1,228 private SQL = 10,200 passed in
  132.20 seconds**, across the same twelve private suites (30 local + 16 private
  additions). Local-only passed 8,972 in 61.78 seconds. No failing guard was waived.
- Source-neutral diagnostic transaction isolation, all-factory enforcement,
  whole-worker/SQL deadline/race/provenance and source/Company-scoped plaintext
  log read/export/retention remain gates. Existing System Manager log permissions
  were inspected, not silently changed; there is no legacy row backfill/migration.
- No installed source/config/schema/assets/Bench/worker/customer/authority action,
  including Sandbox/Simulation; no invoice/advance/GL/VAT/PIH/ICV/QR/crypto or
  acceptance/replay policy change. See [PRIMARY_RECEIPT_PROVIDER.md](PRIMARY_RECEIPT_PROVIDER.md).

The user's follow-up reduces both owned-session waits from two seconds to one
second in the isolated development worktree only. This does not promise a
one-second total operation deadline; driver timeouts and all adoption gates remain.
Guarded combined rerun: **8,972 local + 1,228 private SQL = 10,200 passed in
123.72 seconds**, including real registration/source contention and unchanged
control-session/GLOBAL values. No production or authority action occurred.

## Increment 64: diagnostic caller-handle continuity, not transaction isolation

- Explicit staging pins the existing database owner/raw handle before metadata
  loading, resolves a Werkzeug context-local proxy to its current owner and
  checks identity (not equality) after metadata and around each source callback
  and diagnostic insert. Missing/lazy/unbound or observably replaced/detached
  contexts require static translated review, not implicit initialization or repair.
- No parent SQL, connect/reconnect, cleanup, savepoint, fallback/retry or commit
  is introduced. Late refusal acknowledges that a diagnostic row may already
  exist. The saved-source facade preserves its static RuntimeError review and
  original request/envelope; the legacy logger is not gated or rewired.
- This is NOT transaction identity or isolation: same-handle commits/rollbacks,
  temporary switch-and-restore between checks, hooks and context changes before
  the staging boundary are not certified away. Source-neutral parent/worker
  lifecycle, provenance/races and source/Company-scoped log read/export/retention
  remain gates. No installed v16, ORM/hooks, remote acceptance or activation claim.
- Development code, synthetic tests and translations only; no working application,
  site/schema/config/Bench/worker/customer or authority change.
- Final guarded combined: **9,028 local + 1,244 private SQL = 10,272 passed in
  130.84 seconds**, across the same twelve private suites (56 local + 16 private
  additions). Real parent work/optional diagnostic rows remain pending until the
  test owner decides, and the independent original pair remains unchanged.
  Initial reproduction and fixture/structural-check corrections are documented
  in [EVENT_LOG_TRANSACTION.md](EVENT_LOG_TRANSACTION.md); no guard was waived.

## Increment 65: existing-XML received-step review, not receipt/transaction adoption

- Four existing-XML Reporting adapters reuse the received-step guard for hide,
  event logging and presentation only after HTTP returns. Sales formatters remain;
  POS raw text uses a tiny guarded text getter with no normalization/caching.
- Four broad XML wrappers now re-raise the exact static translated local-review
  signal instead of reclassifying it; simplified Sales does not save/commit a new
  generic Failed response after that signal. No new HTTP/retry/parent cleanup.
- Original signed XML/base64, QR links, auth/routes/settings/owners, PIH/ICV and
  normal 200/202/409 or intentional rejection save/db_set/commit policy remain.
  Callback-own commits survive; review is not acceptance or durable custody.
- These are development-source changes only. No installed source, tenant/schema,
  configuration/Bench/worker/customer or authority change. Remaining existing-XML
  persistence/PIH/writer faults, other generated APIs, source-neutral whole-worker
  lifecycle and scoped log read/export/retention still need separate work.
  See [RESPONSE_PROCESSING.md](RESPONSE_PROCESSING.md).

Final guarded combined: **9,444 local + 1,308 private SQL = 10,752 passed in
132.45 seconds**, across the same twelve private suites (416 local + 64 private
additions). Local source/response snapshots and native parent decisions preserve
original artifacts, fields and history without an extra generic post-fault write.
The initial unchanged-code reproduction and three corrected golden assumptions
are documented in [RESPONSE_PROCESSING.md](RESPONSE_PROCESSING.md); no guard was waived.

## Increment 66: shared guarded existing-XML rejection writes, not atomic custody

- One small explicit-runtime writer replaces fourteen repeated rejection blocks
  in the four existing-XML Sales/POS Reporting APIs. Fixed Sales/POS DocTypes and
  literal boolean code policy are checked before loading; no public endpoint,
  browser option, Company setting, new site initialization or implicit provider.
- Load/UUID/text/save/final-commit faults in the four formerly caught families
  use the existing static translated received-step review and public-wrapper
  escape. No additional generic Error/Failed write, fetch, commit, cleanup or retry.
- Prior ordering remains: simplified UUID db_set commits, except Sales simplified
  404 ordinary assignment; both machine paths assign UUID. Status/raw response/
  ignored-permission save/final commit and deliberate remote throws are unchanged.
  Earlier commits/pending writes/objects need review; there is no compensation.
- Signed artifacts/QR links, PIH/ICV, request/auth/routes/settings, success/409,
  advance/amount/GL/VAT and existing log permissions stay unchanged. No installed
  source/config/schema/Bench/worker/customer or authority change. Successful-
  response/other-writer faults, whole-worker custody/holds/provenance and scoped
  log access/retention remain gates. See [REJECTION_PERSISTENCE.md](REJECTION_PERSISTENCE.md).

Final guarded combined: **9,950 local + 1,528 private SQL = 11,478 passed in
137.49 seconds**, across the same twelve private suites (506 local + 220 private
additions). Initial unchanged-code reproduction: 456 failures/9,472 passes in
107.92 seconds. Exact native visibility and pending-owner decisions preserve
earlier UUID/final commits without extra generic persistence or borrowed cleanup.
No assertion/guard was waived; no installed v16 or authority acceptance is inferred.

## Increment 67: existing-XML reported/PIH/logging boundaries, not atomic success

- Eight repeated 200/202/legacy-409 reported-write blocks use one named explicit-
  runtime adapter. Original raw response -> UUID -> REPORTED label -> ignored-
  permission save -> commit order is retained; no acceptance claim or new endpoint.
- Request-pinned owner notification/PIH save, invoice persistence, lazy success-
  log text/callback and legacy trailing 409 error logging use received-step guards.
  Known formerly caught faults escape as static translated review through public
  wrappers without another generic Error/Failed write or failure commit.
- Normal callback order, prior commits/pending work/objects, Phase-2/hash/owner
  rules, request/XML/QR/ICV/auth/settings/advance/GL/VAT and rejection semantics
  remain. No rollback/repair/replay or implicit custody/hold is introduced.
- No installed source/config/schema/Bench/worker/customer or authority action.
  Other generated/reporting writers, whole-worker commit/error/retry lifecycle,
  exact custody/provenance/holds and Company/source-scoped plaintext-log access/
  retention remain gates. See [EXISTING_XML_REPORTED_WRITES.md](EXISTING_XML_REPORTED_WRITES.md).

Final guarded combined: **10,618 local + 1,800 private SQL = 12,418 passed in
141.19 seconds**, across the same twelve private suites (668 local + 272 private
additions). All 136 native route/status/fault points preserve exact independent
and pending-owner PIH/response/UUID/status/business values under both owner decisions.
Initial characterization and callback-double correction are documented in
[EXISTING_XML_REPORTED_WRITES.md](EXISTING_XML_REPORTED_WRITES.md); no guard was waived.

## Increment 68: Company batch summaries and English diagnostic labels

- One shared collector/presenter for the two Company batch compliance methods;
  child messages are request-locally muted without swallowing exceptions or
  clearing parent messages. Original flag state is restored even on interrupts.
- One translated summary with per-type outcomes/counts and grouped expandable
  escaped technical details; warnings remain visible with unchanged acceptance.
  Arabic is presentation-only. App-generated summary fields and retained-event
  stored title/status remain English; original response content is untouched.
- Avoid a second client catch dialog when the framework owns the error. Remove
  the batch's unnecessary Company type restore/save/reload; dirty form values
  are not discarded and server settings are unchanged.
- This is not general invoice/POS/debug/background/CSID wrapper migration, a
  historical log rewrite, a raw certificate redaction fix or real v16/browser
  verification. No live source/config/schema/Bench/worker/authority action.
  See [MESSAGE_PRESENTATION.md](MESSAGE_PRESENTATION.md).

Final guarded combined: **10,643 local + 1,800 private SQL = 12,443 passed in
140.86 seconds**, across the same twelve private suites (25 new local cases).
The separate mocked Node VM adds **84 English/Arabic UI cases**. The fixed
offline guard remains active; no live/site/authority/v16 acceptance is inferred.

## Increment 69: single-check/Debug summaries, not ordinary submission migration

- One shared development Desk presenter for Company and Sales/POS Debug, with a
  shared request-local Python message context. No installed asset build/change.
- Company single-check uses a new authenticated thin summary wrapper with saved
  Company selection, the existing fallback and normal Company/invoice READ ACL.
  Exactly one existing check runs; it does not imply all six steps are complete.
- Debug public signatures and generation/attachment/signing/settings behavior
  remain. App notices/results are English data, localized in the view only.
  Both menus now display success, skipped and error results once with escaped
  technical details. Original tracebacks and existing English log titles remain.
- Disabled Sales still creates local Debug XML; disabled POS still does not,
  now returning a structured skipped result rather than a misleading popup/None.
  Same-taxpayer skip and separate Debug artifact replacement policy are unchanged.
- No authority/live/schema/config/Bench/worker/customer action. No new transport,
  accounting/advance/QR/hash/retry/credential policy or general permission retrofit.
  The old POS/Background undefined `bypass_background_check`, ignored-permission
  Debug file replacement and broader worker/notification/CSID boundaries remain
  explicit gates. See [MESSAGE_PRESENTATION.md](MESSAGE_PRESENTATION.md).

Final guarded combined: **10,682 local + 1,800 private SQL = 12,482 passed in
142.98 seconds**, across the unchanged twelve private suites (39 new local
cases), plus **160 standalone synthetic VM UI cases** (108 Company + 52 Debug).
Real generator integration skips only the Frappe HTTP type wrapper in the
site-free fixture; source checks and the existing generator body execute.
No offline/permission/acceptance guard or deployment restriction was waived.

## Increment 70: POS Debug Background fix, not live scheduling/type migration

- The broken Phase-2 Background branch read an undefined variable solely to
  calculate an unused private flag. Remove that calculation and nested argument;
  no public bypass parameter, settings field or fallback is added.
- Actual customer-B2C/explicit-sample selection, Phase/schema/POS/GPOS validation,
  existing-artifact notices and explicit tax adapter choice remain. Sales Debug
  uses its selector and is unchanged; ordinary scheduling/submission is untouched.
- Replace the old failure characterization with required local Debug success,
  and cover 168 phase/scheduling/customer/type combinations plus preflight,
  adapter/read-independence and failure regressions. Existing synthetic signed
  XML/QR and invoice fields remain; ERP/signing/tax/transport are mocked.
- No live/site/source/config/assets/schema/Bench/worker/customer or authority
  action. Existing Debug File replacement/access/reload and full framework/crypto
  adoption gates remain. See [POS_DEBUG_LOCAL_ROUTING.md](POS_DEBUG_LOCAL_ROUTING.md).

Final guarded combined: **10,873 local + 1,800 private SQL = 12,673 passed in
143.43 seconds**, across the unchanged twelve private suites (191 new local
cases plus the repaired former defect observation), with the same **160
synthetic English/Arabic UI cases**. No transport/site/ownership guard or normal
preflight was waived. This is not installed ERPNext 16 or authority acceptance.

## Increment 71: Debug source ACL and history, not full File-hook isolation

- Shared explicit-runtime saved invoice READ/WRITE, linked Company READ and File
  CREATE preflight; direct quiet v15/v16-signature checks, literal True, no
  Document ignore-permission bypass. Unknown/changed contexts require review.
- Recheck actor, identities and observed source/Company revisions around new
  File construction; reject observed metadata/ownership redirection before save
  and validate private parent metadata after normal File.save.
- Remove both prefix-query/delete loops and ignored-permission saves. New opaque
  filenames preserve prior files, with ordinary attachment limits. Return the
  actual framework filename. No invoice/Company save, helper commit/rollback,
  retry, field relink, or authority request. Partial hook effects are not erased.
- English diagnostic fields and Arabic presentation; unknown private faults stay
  out of the UI while original causes reach the existing server logger.
- No live source/assets/config/schema/Bench/worker/customer action. This is not
  atomic locking, physical File/rollback/provider provenance, real v16 framework
  or cryptographic/authority acceptance. See [DEBUG_ATTACHMENT_ACCESS.md](DEBUG_ATTACHMENT_ACCESS.md).

Final guarded combined: **11,153 local + 1,800 private SQL = 12,953 passed in
141.65 seconds**, across the same twelve owned-private suites (280 new local
cases), plus **168 synthetic UI cases** (108 Company + 60 Debug). The first
local pass was 11,109 in 71.30 seconds before the final cause/cancellation and
entry-boundary additions. No offline/ACL/ownership/acceptance guard was waived.

## Increment 72: attachment-only Debug UI and post-save review

- Both actual Sales/POS menus use one pending-form runner; inactive/dirty/local
  forms are refused without saving or requesting. Concurrent clicks share one
  promise only, not durable idempotency.
- No full invoice reload, docinfo lookup RPC or attachment-upload field callback.
  Return normal File READ-authorized bounded private metadata from the original
  create request, then update only the attachment list through the normal API.
- Capture document object/identity, route and active form; moved forms are not
  updated. Edits while waiting remain untouched, with a notice about saved data.
- Failed/unsupported metadata refresh keeps confirmed creation and asks for
  manual review, never automatic regeneration. Later ACL/source drift after
  File.save requires review because earlier effects may already exist.
- Single English/Arabic display summary, escaped source identity and untouched
  English/raw payloads. No installed source/assets/config/schema/worker/site/
  customer or authority action. File/Comment/reload/attachment source inspection
  is read-only, not real framework/browser/storage acceptance.

See [DEBUG_UI_LIFECYCLE.md](DEBUG_UI_LIFECYCLE.md). Actual isolated v15/v16,
File/custom-hook/physical rollback, retention and crypto acceptance remain gates.

Final guarded combined: **11,293 local + 1,800 private SQL = 13,093 passed in
141.30 seconds**, across the same twelve owned-private suites. The 140 added
Python cases are 132 ACL/metadata/hook observations and eight real Debug entry
projections with mocked dependencies. Standalone Node checks passed **332 cases**
(108 Company + 60 Debug menu/message + 164 lifecycle). Intermediate combined
runs passed 13,073 and 13,081 before the final integration/link-ID additions.
No offline, permission, source, SQL ownership or authority guard was relaxed.

## Increment 73: CSID success redaction, not credential lifecycle adoption

- Remove Compliance's raw success-body popup/return. Both CSID paths now return
  English status/purpose/message JSON strings only and display one translated
  static success notice after existing persistence completes. No token, secret,
  certificate, request ID, OTP, CSR or auth material is projected.
- Keep the public signatures and JSON-string shape; raw-body/ID consumers must
  migrate. The wizard now consumes only the canonical result contract and shows
  translated read-only outcome text, never raw credential replies.
- Existing saved credential/request-ID values, route/auth/acceptance policy,
  field aliases, ignored-permission writers, saves and retry behavior are not
  redesigned or approved. Failure/log/trace redaction, protected credential
  storage/rotation, access controls and non-Debug auto-save/reload remain gates.
- No site/customer/credential query or write, installed source/assets/config/
  schema/worker change, real HTTP or authority request. All new issuance and
  storage observations are synthetic; no v16/browser/crypto acceptance claim.

See [CSID_SUCCESS_PRESENTATION.md](CSID_SUCCESS_PRESENTATION.md).

Final guarded combined: **11,337 local + 1,800 private SQL = 13,137 passed in
145.35 seconds**, using the same twelve owned-private suites. The 44 added
Python cases cover 24 successful projections, 12 pre-success parse/save faults
and eight invalid pure-builder purposes; the two existing writer transition
cases now also assert auth-free results. Node passed **412 synthetic cases**
(108 Company + 60 Debug messages + 164 Debug lifecycle + 80 CSID). The fixed
manifest and offline/source/permission/SQL ownership guards are unchanged.

## Increment 74: CSID HTTP errors without raw response disclosure

- Replace unsuccessful CSID raw-body/header/reason/endpoint exports with a
  bounded English diagnostic classifier. Known OTP/missing-check codes are
  purpose-bound; 401/403/429/5xx and unknown failures have static interpretations.
- Keep one translated framework-owned ValidationError popup with numeric HTTP
  status. The internal normalized exception is caught before a single final
  throw outside its handler, avoiding raw HTTP exception context/cause.
- Do not label every 400 Invalid OTP. Do not retry, save credentials, commit,
  clean up, log raw content or send an extra request on a rejected response.
- Public signatures/success contract, exact mocked routes/auth/environment
  guards and normal settings remain. Transport/local/200-processing exceptions,
  full log/snapshot security, access/credential lifecycle and form reload/save
  remain separate gates; normalized data is English, not proof about all logs.
- No installed/live/site/customer/credential/schema/worker or authority action.
  All transport, ERP and new response observations are synthetic.

See [CSID_HTTP_FAILURE_PRESENTATION.md](CSID_HTTP_FAILURE_PRESENTATION.md).

Guarded combined evidence: **11,467 local + 1,800 private SQL = 13,267 passed in
142.51 seconds**, across the same twelve owned-private suites. The 130 added
Python cases cover 64 status/body/purpose projections, 20 malformed/unbounded
bodies, six unsupported status types and 40 actual entry-body/catalog cases.
The existing route assertions now require canonical failure, without removing
destination/OTP/auth/environment/no-save checks. Standalone Node checks retain
**412 synthetic cases**. No manifest or offline/permission/SQL guard is relaxed.
The final stable-source local recheck also passed **11,467 cases in 73.09
seconds**, after the fixture resource-close/readability and docstring cleanup.

## Increment 75: CSID local faults without raw exception exports

- Keep the public signatures, split private workers, and share one explicit
  attempt/UI boundary. Record only transport/response/save/overlay observations,
  not secrets, remote acceptance, durable commit or retry authority.
- Replace raw generic/transport/local failure text with canonical English stage
  metadata and Arabic display. Child messages are muted, flags restored exactly
  and parent messages/language preserved. Public errors leave caught raw contexts.
- Attempt progress cleanup in finally, including cancellation paths. A cleanup
  fault preserves known HTTP/local failure metadata and adds a static notice;
  post-save/presentation faults require local review, not automatic regeneration.
- Never undo partial hook/commit/output effects or claim atomic single-dialog
  behavior across arbitrary presentation hooks. No retry, credential cleanup,
  helper commit/rollback, new log writer or live connection is introduced.
- Keep route/auth/environment/save/VAT behavior and HTTP rejection policy; local
  configuration messages become coarse preparation review. Existing ignored-
  permission writers, saved access, client save/reload and complete framework
  log/snapshot/custody/lifecycle controls remain gates.
- All work is in development. No installed assets/source/config/schema/worker/
  site/customer/credential or authority operation. See
  [CSID_LOCAL_OUTCOMES.md](CSID_LOCAL_OUTCOMES.md).

Final guarded combined: **11,656 local + 1,800 private SQL = 13,456 passed in
143.97 seconds**, across the same twelve owned-private SQL suites. The new
reviewed local-outcome suite adds 189 synthetic cases: 27 progress projections/
invalid states, 88 execution faults, 12 cleanup faults, 18 cancellations, eight
parent mute cases, two early returns, 28 preflight cases, four opaque errors and
two already-emitted presentation effects. The earlier compatibility-only local
run passed 11,467 cases in 73.41 seconds. Node checks remain **412 synthetic
cases**. The fixed manifest adds only this reviewed suite; no ownership/network/
site/permission or transport guard is weakened.

## Increment 76: CSID form guards and explicit saved-settings workflow

- Both Company and both device CSID buttons share a runner requiring an active
  saved clean form. Users save OTP/environment manually before creation. Remove
  automatic pre/post-save and full reload, without bypassing timestamp guards.
- Device metadata lookup asks only for the linked Company's abbreviation and
  environment through the normal permissioned API. Recheck captured source/
  revision/link/routing fields and clean/active state before credential creation.
- Coalesce pending cross-button clicks and mark an attempted document for review
  even after uncertainty/rejection. Review precedes dirty save guidance. This is
  in-memory UI policy, not durable/cross-tab idempotency or source provenance.
- Add display-only guidance to the same server success popup. Keep English JSON
  results, credential writes, routing/auth/acceptance and public signatures.
  No source writes, credential sync or extra success popup from the client runner.
- CSR/configuration/other check paths, manual/programmatic saves, server access/
  lifecycle and complete log/read/export/retention controls remain gates. No
  installed/live assets/source/config/schema/worker/site/credential or authority
  action. See [CSID_FORM_LIFECYCLE.md](CSID_FORM_LIFECYCLE.md).

Final guarded combined: **11,664 local + 1,800 private SQL = 13,464 passed in
161.29 seconds**, across the same twelve owned-private suites. Eight new Python
cases verify the single English/Arabic notice and unchanged result. Node passed
**724 synthetic cases**, including 312 actual CSID form handler cases. Existing
Company framework-error tests also require reaching the RPC, not a guard-only
pass. No fixed manifest or runtime/resource guard is changed.

## Increment 77: CSR form consent and shared credential-action guards

- Both Company/device CSR buttons share the existing CSID clean/active form,
  limited metadata, pending and review boundary. No automatic save/reload/model
  sync and no device Company/CSR console dumps in these two handlers.
- Require translated confirmation before replacing the saved private key;
  recheck observed source/configuration after consent and device lookup. Coalesce
  pending CSR/CSID clicks and require review after any entered credential RPC.
- Treat legacy CSR returns only as returned calls requiring review, never proof
  of persistence, CSR validation or certificate issuance. Static messages never
  echo the return/unknown exception. Normal framework error ownership remains.
- Do not change server key/CSR writes, cryptography, public signatures, routing
  or permissions. Configuration draft staging, device single Compliance, active
  key rotation, backend access/log lifecycle and installed v15/v16 remain gates.
  See [CSR_FORM_LIFECYCLE.md](CSR_FORM_LIFECYCLE.md).

Standalone Node checks: **900 synthetic cases**, including **176 new CSR cases**
and all previous 724. Python fixed-manifest/resource guards are unchanged. No
tenant site, customer key/credential change or authority operation is used.
Final guarded combined: **11,664 local + 1,800 private SQL = 13,464 passed in
143.64 seconds**, across the same twelve owned-private SQL suites. This is
offline regression evidence, not installed v15/v16 or authority acceptance.

## Increment 78: exact-source CSR configuration draft without automatic save

- Company configuration action now prepares an unsaved draft only. It shares
  pending/review guards with CSR/CSID, rechecks observed source/active/clean state,
  and stages only the configuration field; never saves/reloads the Company.
- New exact-name/revision API checks saved-row READ and WRITE with the existing
  quiet permission-signature helper. Shared legacy-format builder reads bounded
  single-line values; no configuration/credential write, key generation or HTTP.
- A single translated display summary distinguishes draft preparation/staging
  from persistence or issuance. Raw draft values remain unchanged in the field,
  not displayed as HTML. Static errors preserve parent messages/flag ownership.
- Keep the legacy abbreviation/string API as a distinct compatibility surface;
  escape its popup HTML. Backend key/CSR rotation/access, device single check,
  complete log lifecycle, concurrent source ownership and installed v15/v16/
  fictional-Company adoption remain gates. No live or authority operation.
  See [CSR_CONFIGURATION_DRAFT.md](CSR_CONFIGURATION_DRAFT.md).

Final guarded combined: **11,766 local + 1,800 private SQL = 13,566 passed in
147.74 seconds**, across the same twelve owned-private SQL suites. The manifest
adds only 102 reviewed synthetic CSR configuration cases. All seven Node VM
scripts passed **1,024 cases**, including 124 new configuration form cases.
These are offline checks, not installed ERPNext/Desk or authority acceptance.

## Increment 79: saved-device single Compliance facade and shared form policy

- Replace full Company read/full device payload/automatic device save with one
  identity-and-revision API and one localized single-check summary. No automatic
  reload/model write/retry; observed changes during the RPC require review.
- Read exact saved device/linked Company/sample Sales Invoice, check saved-row
  READ permissions and device revision, and refuse cross-Company samples before
  one legacy Compliance delegation. Keep Company label/numeric fallback, saved
  credential-owner policy and established acceptance/technical-detail semantics.
- Share pure comparison revision/name validation and UI saved-form policy with
  CSR configuration/credential runners. Coalesce pending actions across device
  Compliance and CSR/CSID; credential review precedes dirty save guidance.
- This is not six-step completion, source/credential epoch pinning, durable
  duplicate prevention or complete legacy log/redaction/ACL adoption. No authority
  request, live source/assets/config/schema/credential/site or worker operation.
  See [DEVICE_SINGLE_COMPLIANCE.md](DEVICE_SINGLE_COMPLIANCE.md).

Final guarded combined: **11,909 local + 1,800 private SQL = 13,709 passed in
146.69 seconds**, across the same twelve owned-private SQL suites. The fixed
manifest adds only **143 reviewed synthetic device cases**. All eight Node VM
scripts passed **1,152 cases**, including **128 new device form cases**. Existing
CSR/configuration shared-policy regressions remain covered. No actual site,
framework/Desk v16, key/SDK validation or authority acceptance is asserted.

## Increment 80: coordinated Company Compliance forms and saved-source facade

- All three Company check buttons use one saved-clean-active form runner,
  shared CSR/CSID/configuration pending/review policy and one limited RPC. No
  automatic save/reload/model merge or separate manual global freeze lifecycle.
- New exact Company/revision/mode facade checks ordinary source READ ACLs and
  saved revision, reads the saved sample for invoice modes and refuses cross-
  Company samples before one legacy delegation. Automatic requires no sample.
- Recheck source after automatic consent and before presenting returned results.
  Changed forms preserve edits and review a possibly completed request; no
  automatic retry or false unsent claim. Framework errors keep their owner.
- Clarify temporary Compliance submission versus local-only preview in the
  translated alternative consent. Add the missing Arabic sample-number prompt.
- Retain legacy result/acceptance/generation/routing/technical-detail contracts.
  Durable duplicates/method choice, source/credential races, related dependencies,
  broader legacy ACL/log custody and installed v15/v16 remain gates. No live or
  authority operation. See [COMPANY_COMPLIANCE_FORMS.md](COMPANY_COMPLIANCE_FORMS.md).

Final guarded combined: **12,069 local + 1,800 private SQL = 13,869 passed in
147.73 seconds**, across the same twelve owned-private SQL suites. The manifest
adds only **160 reviewed synthetic Company cases**. All nine Node VM scripts
passed **1,444 cases**, including **292 new Company form cases**. No actual
site, ERPNext 16/Desk, SDK or authority acceptance is asserted.

## Increment 81: direct CSR/key/CSID writer authorization and ordinary saves

- Share exact saved Company/device loading and explicit READ+WRITE target ACLs,
  with READ-only linked Company dependency for devices. Reject source/abbreviation
  mismatch and ignore caller credential fields/permission flags.
- Stop selecting a different write target by abbreviation and remove selected
  ignored-permission saves. CSR uses authorized saved configuration and rechecks
  before key generation and final CSR save, without retry/commit/rollback.
- Local preflight denial uses a static translated PermissionError; CSID late-save
  denial preserves the existing storage-unconfirmed stage. Never infer safe retry.
- Preserve signatures/returns, routing/crypto/field selection. Active-key conflicts,
  field/source/epoch concurrency, full CSR error/log ownership and remaining cache
  writers are still gates. No live/installed/authority operation. See
  [CREDENTIAL_WRITER_ACCESS.md](CREDENTIAL_WRITER_ACCESS.md).

Final guarded combined: **12,300 local + 1,800 private SQL = 14,100 passed in
148.48 seconds**, across twelve owned-private SQL suites, including **231 new
synthetic writer-access cases**. All nine Node VM scripts passed **1,444 cases**.
Allowed routing/lifecycle fixtures now explicitly grant synthetic ACL and assert
ordinary saves. No actual site, ERPNext 16/Desk, SDK or authority acceptance claim.

## Increment 82: one stage-aware local key/CSR failure owner

- Local CSR and internal key generation share one error owner and a private key
  worker, not nested public failure wrappers. Canonical stage metadata is English;
  the final single popup translates known keys, including actual Arabic entries.
- Distinguish preparation, uncertain key storage, key-save-returned/CSR-incomplete,
  uncertain CSR storage and unconfirmed local completion. Late source denial adds
  its access notice to the same partial-key review message, retaining native
  PermissionError. Unknown source faults do not masquerade as crypto failures.
- Do not stringify/log private crypto/ORM diagnostics, clear parent notifications,
  retry, restore keys, commit, roll back or introduce an authority call. Preserve
  cancellation, ordinary saves, three source checks, legacy successful return
  shapes and cryptographic/environment labels.
- Active bundle preservation, staged epoch/rotation, field custody/concurrency,
  broad framework diagnostics and installed v15/v16 acceptance remain gates.
  The existing key-before-CSR replacement risk is not solved by error aggregation.
  See [CSR_LOCAL_OUTCOMES.md](CSR_LOCAL_OUTCOMES.md).

The first guarded local run exposed four missing late unknown-source notices
in the new suite (**4 failed, 12,578 passed in 75.95 seconds**). The source adapter
was corrected without weakening assertions, access rules or resource guards.
The next combined run passed all **12,582 local cases**, but all **1,800 private
SQL cases** had fixture setup errors because the new MariaDB process exited before
readiness (**156.80 seconds**). No tenant/server fallback or guard relaxation was
used; the same fixed runner was rerun with reviewed execution permission for the
owned temporary SQL subprocess.

Final guarded combined: **12,582 local + 1,800 private SQL = 14,382 passed in
150.68 seconds**, across the same twelve private suites, including **282 new
synthetic key/CSR cases**. All nine Node VM scripts passed **1,444 cases**. No
offline/resource/normal-permission guard was waived. No installed v15/v16,
SDK, browser/Desk or authority acceptance is claimed.

## Increment 83: conservative local shared-key preservation

- Block local key/CSR replacement for authorized saved targets containing either
  certificate alias, any of the three auth fields or an onboarding request ID.
  Invalid/historical/whitespace/masked material is preserved too; unknown type/
  read state fails closed without private-value parsing, coercion or export.
- Recheck the key worker before generation and before assignment, and CSR at
  entry/final saved-source load. Retain one localized failure and partial-key
  review if a later check fails. Pre-issuance successful return shapes/crypto,
  ordinary saves, source ACLs and related Company READ-only policy remain.
- Update translated consent to pre-issuance only. No force, credential clearing,
  expiry/environment fallback, active storage, automatic retry/restore/transaction
  cleanup, live change or authority request is introduced.
- Explicitly model unissued targets only in allowed synthetic fixtures; retain
  populated negative ACL fixtures. Replace two legacy key-overwrite cases with
  no-generation/no-save/preserved-binding assertions. CSID overwrite evidence
  stays unchanged. Add only the reviewed preservation suite to the fixed manifest.
- Same-object post-crypto checks are not database locks. Active renewal, unseen
  source/hook/commit races, other CSID writers, field/epoch custody, full framework
  diagnostics and installed v15/v16 remain gates. See
  [CSR_KEY_PRESERVATION.md](CSR_KEY_PRESERVATION.md).

Final guarded combined: **12,853 local + 1,800 private SQL = 14,653 passed in
164.51 seconds**, across twelve private suites, including **271 new synthetic
preservation cases**. First combined passed **14,652 in 148.40 seconds** before
the added alias-registry case was collected. All nine Node VM scripts passed
**1,444 cases**, including revised Arabic/English consent. No installed v15/v16,
browser/Desk, SDK or authority acceptance is claimed; no guard was waived.

## Increment 84: saved Final-auth preservation across CSID writers

- Block both selected CSID writers if either saved Final-auth field is populated
  or its state is unverifiable, after ordinary saved-source ACL/binding checks.
  No role/force/env override or credential clearing bypass is added.
- Share bounded pure presence semantics with the existing six-field CSR guard.
  Recheck same-object observations before transport and before successful-response
  certificate/auth assignment. Late failure keeps uncertain-stage review, not an
  unsent claim. Cleanup failure appends without erasing a preservation notice.
- Translate only static final display keys, including actual Arabic CSV entries;
  preserve English metadata, parent state and cancellation, without secret parsing/
  logging, retry/restore/transaction cleanup, actual sending or live changes.
- Preserve initial transition and original URL/OTP/Compliance-auth/payload/save
  assertions in explicitly pre-Final synthetic fixtures. The known Company shared
  certificate overwrite and device alias conflict remain characterized, not fixed.
- Absent Final auth does not protect certificate-only/unknown remote material or
  authorize renewal. Same-object checks are not database locks/epochs. Staged
  private custody, all other writers, complete framework diagnostics, coherent
  activation and installed v15/v16 acceptance remain gates. See
  [CSID_PRESERVATION.md](CSID_PRESERVATION.md).

Final guarded combined: **13,122 local + 1,800 private SQL = 14,922 passed in
153.12 seconds**, across twelve private suites, including **269 new synthetic
cases** (221 CSID preservation + 48 shared presence). All nine Node VM scripts
passed **1,444 cases**. Prior CSR, route/auth/save and initial-transition defect
assertions remain; no resource/permission/transport guard was waived. No installed
v15/v16, browser/Desk, SDK or authority acceptance is claimed.

## Increment 85: shared CSR template and non-writing draft preparation

- Extract one ordered subject/SAN/extension builder and label encoder. Legacy
  public CSR/encoder contracts, curve/hash/encoding, labels, parser/fallback and
  key-save/guard order remain; no signing certificate/digest/QR change is made.
- Add an internal unactivated key/CSR draft with explicit Compliance slot/owner/
  revision/UUID/UTC declarations. Strict nine-key config and attribute preflight
  precede generation. No saved source, existing key, clock, filesystem, store or
  HTTP is read; no active credential, document, schema or pointer is changed.
- Check canonical bounded key/CSR bytes, signature/hash/public-key/subject and
  ordered extensions. Hide raw fields from repr/diagnostics, refuse pickle/copy
  transport, and raise static failures without private exception context.
  Python field/asdict disclosure is not a serialization sandbox or custody.
- No button/request/selector/store/schema/migration/activation uses the draft.
  Pending-key protected custody, permissions/source/epoch/receipt flow, coherent
  activation and installed v15/v16 remain gates. Initial certificate/alias defects
  are not fixed or automatically selected away. No actual tenant key/CSR, live
  change or authority operation occurs. See
  [CSR_DRAFT_PREPARATION.md](CSR_DRAFT_PREPARATION.md).

Final guarded combined: **13,264 local + 1,800 private SQL = 15,064 passed in
147.59 seconds**, across twelve private suites, including **142 new synthetic
cases**. First combined passed **15,061 in 146.25 seconds** before the three
independent structure goldens were added. All nine Node VM scripts passed
**1,444 cases**. Six new exact-TBS legacy adapter comparisons and prior guards/
transition characterizations remain. No resource/permission/crypto/transport guard
was waived; no installed v15/v16, SDK, Desk or authority acceptance is claimed.

## Increment 86: encrypted pending key/CSR staging, not an active vault

- Add a separate AES-256-GCM envelope for the exact prepared draft, with explicit
  caller keys/namespace and authenticated canonical context/fingerprints. Strict
  material validation follows decryption; no certificate, key or field is inferred,
  regenerated, repaired or activated. Issued-credential storage is unchanged.
- Add an immutable caller-transaction repository: exact envelope redelivery only,
  locked exact-context reads, no overwrite/reseal/retry/commit/rollback/close/DDL.
  Errors poison the handle and expose static codes without child exception context.
- Add only two reviewed fixed-manifest suites and fixture-only private DDL.
  Synthetic encryption tests and owned private SQL exercise tampering, concurrency,
  parent visibility, loss and committed/uncommitted crash recovery. No tenant SQL,
  customer material, live change or authority operation occurs.
- This is not a permissioned source service or key-management installation.
  Manifest identities are restricted metadata, not independent source/epoch proof;
  source/ACL/provider/key/nonce/flow/activation policy remains a gate. AAD/SQL nonce
  uniqueness does not make actual-key nonce reuse safe. Existing CSR/CSID buttons
  and initial shared-certificate/device-alias defects remain unchanged. See
  [PENDING_CSR_CUSTODY.md](PENDING_CSR_CUSTODY.md).

Final guarded combined: **13,344 local + 1,827 private SQL = 15,171 passed in
154.19 seconds**, across thirteen private suites, including **107 new cases**
(80 local + 27 private SQL). All nine Node VM scripts passed **1,444 cases**.
First run had **12 failures and 15,159 passes in 155.66 seconds**; the generator
context manager restored private child exception context. An ordinary operation
boundary fixes the cause without weakening assertions. No offline resource,
normal permission, crypto or transport guard was waived. Installed v15/v16,
Desk/browser, SDK and authority acceptance remain unverified.

## Increment 87: permissioned saved-source pending CSR custody boundary

- Add an internal metadata-only stage/inspect service. Exact saved target
  READ+WRITE, related Company READ, scoped actor/role and source/manifest/hash
  matching precede protected resource access; both quiet ACL signatures are used.
- Reload permissions/source around callbacks and bounded locked reads in the
  same staging transaction. Reject ambient handles, drift, owner/environment/key
  fallback and linked-device implicit Company selection. No generation/reseal,
  plaintext/ciphertext export, active-field write or automatic transaction cleanup.
- Any failure/reentrancy/cancellation poisons the service; caller retains the exact
  envelope and owns whole-transaction rollback/review. Child popups are muted;
  one translated display failure uses static English contract keys without raw
  private exception context. Success remains explicitly uncommitted/observational.
- Extend only fixed-manifest synthetic tests and the existing owned private SQL
  suite. No installed schema/provider/button/worker, live/customer operation or
  authority request. Historical provider/epoch proof, protected provisioning,
  nonce policy, issuance/activation and installed v15/v16 remain gates. See
  [PENDING_CSR_ACCESS.md](PENDING_CSR_ACCESS.md).

Final guarded combined: **13,543 local + 1,844 private SQL = 15,387 passed in
157.30 seconds**, across thirteen private suites, including **216 new cases**
(199 local + 17 native SQL). First local-only run passed **13,495 in 82.37
seconds** before extra role/input/message tests and native composition were added.
All nine Node VM scripts passed **1,444 cases**. No offline resource, ordinary
permission, crypto or transport assertion was waived; no installed v15/v16,
Desk/browser, SDK or authority acceptance is claimed.

## Increment 88: pinned single-acquisition pending CSR resources

- Add an unactivated explicit Unix resource lease over shared socket/peer/session
  checks, with a distinct pending-domain registration and pinned storage-key ID.
  Scope/socket checks precede local login; verified pending target precedes scoped
  keys, followed by another target/session/key-ID check. No discovery/fallback,
  arbitrary connector, reconnect, schema installation or automatic commit.
- Extend the shared probe only with two literal registration-table choices;
  existing receipt callers retain the exact default query and behavior. New
  pending handles poison drift/driver/probe interruptions and allow caller cleanup;
  failed acquisition attempts rollback AND close only its newly owned handle.
- Lease reentry/reacquisition never creates another connection or loses access to
  handed-off resources. Metadata-only saved-source staging remains uncommitted;
  actual vault/tenant/key/epoch provenance and source/ACL-aware commit/issuance
  coordination remain gates, not properties established by a marker or key ID.
- Add only fixed-manifest synthetic and existing owned-private SQL tests. No live
  source/config/schema/site/customer credential/worker/Bench or authority operation.
  No button/provider is installed; existing credentials/signing remain unchanged.
  See [PENDING_CSR_PROVIDER.md](PENDING_CSR_PROVIDER.md).

Final guarded combined: **13,626 local + 1,862 private SQL = 15,488 passed in
159.78 seconds**, across thirteen private suites, including **101 new cases**
(83 local + 18 native SQL). Local-only runner passed **13,626 in 83.01 seconds**.
All nine Node VM scripts passed **1,444 cases**. Existing receipt default queries/
session/cleanup tests remain unchanged; no offline resource, ordinary ACL, crypto
or transport guard was waived. Installed v15/v16, Desk/browser, SDK, actual key
provisioning and authority acceptance remain unverified.

## Increment 89: encrypted Password backing-state drift detection

- Extend internal pending-source capture with explicit Password schema and a
  version-2 source fingerprint; require an expected protected backing-state hash
  in each exact source binding. No automatic old-binding recalculation/migration.
- Add bounded exact-owner read-only `__Auth` comparisons in the same transaction
  before and after repository work. Detect encrypted-byte rotation/deletion even
  with unchanged UI masks/modified markers. Reject unknown/plain/orphan/duplicate/
  oversized backing rows without decrypting, exposing, repairing or clearing them.
- Keep the existing metadata-only single translated failure and caller-owned
  rollback/disposal boundary. Success exposes only an observation boolean, not
  ciphertext/digest or a verified credential epoch/remote/activation claim.
- Add only the fixed local suite and owned-private synthetic backing-table tests.
  No installed schema/provider/button, customer/live credential/worker/Bench or
  authority operation occurs. Real historical/monotonic epoch, field custody,
  committed source/ACL coordination and installed v15/v16 remain gates. See
  [PENDING_CSR_PASSWORD_STATE.md](PENDING_CSR_PASSWORD_STATE.md).

Final guarded combined: **13,708 local + 1,887 private SQL = 15,595 passed in
163.91 seconds**, across thirteen private suites, including **107 new cases**
(82 local + 25 native SQL). First local-only run passed **13,707 in 84.10
seconds**; first combined passed **15,594 in 166.71 seconds** before the explicit
Password-field-count preflight bound/regression case. All nine Node VM scripts
passed **1,444 cases**. No offline resource, ordinary ACL, crypto or transport
assertion was waived. Installed v15/v16, Desk/browser, SDK and authority acceptance
remain unverified.

## Increment 90: owned pending save with final exact guards

- Add an uninstalled single-use local transaction coordinator over the existing
  source/ACL/backing/cipher/repository path. Exclusively claim a fresh concrete
  lease; refuse pre-used/other-owned resources without cleanup of their work.
- Recheck exact lookup/source/permissions, locked backing state and original
  stored envelope before ONE commit/close; then recheck visible source/lookup/
  ACLs before metadata disclosure. Existing caller-owned stage/inspect remain.
- Preserve unknown commit/close outcomes and late denial: no success guessing,
  automatic retry/reseal/activation or undo claim. Attempt owned cleanup with
  interruption priority; combine stage/guard/cleanup failure into one translated
  display message with English contract keys and no raw private diagnostics.
- Add only fixed-manifest synthetic and existing owned-private SQL composition.
  No site/schema/provider/button/worker/Bench/customer/live or authority operation.
  Observed checks are not atomic permission/epoch/provenance proof; historical
  binding provisioning, unknown outcome reconciliation and installed v15/v16
  remain gates. See [PENDING_CSR_TRANSACTION.md](PENDING_CSR_TRANSACTION.md).

Final guarded combined: **13,771 local + 1,905 private SQL = 15,676 passed in
163.16 seconds**, across thirteen private suites, including **81 new cases**
(63 local + 18 native SQL). Local-only runner passed **13,771 in 83.21 seconds**.
All nine Node VM scripts passed **1,444 cases**. Existing caller-owned transaction
and provider behavior remain tested; no resource/ordinary-ACL/crypto/transport
assertion was waived. Installed v15/v16, Desk/browser, SDK and authority acceptance
remain unverified.

## Increment 91: read-only exact-original pending outcome review

- Review retained original ciphertext on a separately supplied fresh owned lease;
  never stage, commit, reseal, discover latest, activate or request the authority.
- Reuse saved-source/normal READ+WRITE ACL/backing/binding checks. Exact/absent/
  conflict are bounded authenticated observations, not inferred from exceptions.
  A resealed copy is a conflict even with identical plaintext; corrupt rows fail.
- Recheck the classification before one rollback/close and current visible
  permissions/source/binding before disclosure. Unknown cleanup, drift, reentry
  and interruption withhold metadata without automatic cleanup/retry repetition.
- Preserve English contract keys and one display-only translated failure. No new
  runtime schema/provider/button/site/worker/customer/authority operation occurs.
  Historical provisioning, independent provenance/epoch, conflict policy and
  installed v15/v16 remain gates. See [PENDING_CSR_REVIEW.md](PENDING_CSR_REVIEW.md).

Final guarded combined: **13,838 local + 1,925 private SQL = 15,763 passed in
166.97 seconds**, across thirteen private suites, including **87 new cases**
(67 local + 20 native SQL). The first local-only run passed **13,838 in 81.98
seconds**. All nine Node VM scripts passed **1,444 cases**. Native tests extend
actual commit-before/commit-after/close/late-denial cases with a separately owned
exact-original read-only review, trap stage/commit during review, and verify that
corruption, late test mutations and cleanup acknowledgment failures never produce
a false observation or an unintended write. No guard was waived; installed
v15/v16, Desk/browser, SDK and authority acceptance remain unverified.

## Increment 92: immutable original source declaration and envelope pair

- Preserve one copied canonical original source/backing/manifest/scope/key binding
  linked to every exact original envelope field, using the same repository and
  caller-owned transaction; no second source/ACL policy or runtime wiring.
- Create only a new pair or accept a fully exact existing pair without rewriting.
  Refuse unbound envelopes, orphan history and rebindings. Plain INSERTs prevent
  adopting a competing envelope-only write after absent reads; any failure
  requires the caller to roll back the whole transaction, not just one record.
- Bound/revalidate exact stored metadata and authenticated envelope on lookup;
  never infer history from current settings, choose latest or export raw material.
  Existing service type/API and owned save/review behavior remain unchanged.
- Add private-only rehearsal SQL and one reviewed fixed-manifest local suite.
  No site/schema/provider/button/worker/customer/authority operation occurs.
  Stored declarations/hashes are not independent provenance or authoritative
  epochs. Initial permissioned provisioning and owned committed-lookup integration
  remain gates. See [PENDING_CSR_SOURCE_HISTORY.md](PENDING_CSR_SOURCE_HISTORY.md).

First local-only guarded run: **13,884 passed in 85.45 seconds**; nine Node VM
scripts: **1,444 cases passed**. Final guarded combined: **13,884 local + 1,949
private SQL = 15,833 passed in 168.92 seconds**, across thirteen private suites,
including **70 new cases** (46 local + 24 native SQL). Native tests verify actual
pair visibility/rollback, exact redelivery and immutable original settings/site,
orphan/corruption rejection, partial readback failure, both isolation lock waits,
a competing READ-COMMITTED envelope-only insertion race, and composition with
the unchanged saved-source service. No guard was waived. Installed v15/v16,
Desk/browser, SDK and authority acceptance remain unverified.

## Increment 93: permissioned initial source capture with owned pair save

- Capture a new original binding from shared normal saved-source READ+WRITE/
  related-READ policy and same-transaction locked source/opaque backing state,
  without historical lookup or placeholder/source-hash inputs. Preserve existing
  metadata-only public contracts; no second authorization/storage/cleanup policy.
- Stage only a completely new pair. Refuse existing exact pairs and unbound/orphan
  identities rather than recreating history or retrying an uncertain save. Keep
  caller-owned staging uncommitted and optional owned completion single-use.
- Recheck captured binding/backing/original ciphertext and current source/ACLs
  before one commit/close, then visible source/permissions before disclosure;
  never borrow a closed lookup connection or undo already committed history.
- Reuse one redacted display-only translated failure with English contract keys.
  Add only fixed-manifest synthetic and existing owned-private SQL tests; no
  schema/provider/button/site/worker/customer/authority operation. Independent
  source/key/tenant/epoch provenance and committed-pair review remain gates. See
  [PENDING_CSR_INITIAL_CAPTURE.md](PENDING_CSR_INITIAL_CAPTURE.md).

Local-only guarded run: **13,941 passed in 83.53 seconds**; all nine Node VM
scripts: **1,444 cases passed**. Final guarded combined: **13,941 local + 1,974
private SQL = 15,915 passed in 188.19 seconds**, across thirteen private suites,
including **82 new cases** (57 local + 25 native SQL). Native tests verify actual
initial source-bound pair commits, caller-owned visibility/commit/rollback,
existing/orphan identity refusal, pre-commit source/backing/history/envelope/
permission drift rollback, and both-record commit-before/commit-after/close/late
denial outcomes. Historical lookup is trapped in every new creation path. No
resource/ordinary-ACL/crypto/transport assertion was waived; installed v15/v16,
Desk/browser, SDK and authority acceptance remain unverified.

## Increment 94: owned exact-original pair review without historical recapture

- Review original envelope/source-binding pair on one separately supplied fresh
  owned lease, sharing source/normal-ACL/provider/backing/cleanup policy. No
  external historical lookup, SQL write, recapture, reseal, retry or authority call.
- Distinguish authenticated exact/absent/envelope-only/binding-only/valid-conflict
  observations. Corrupt/inconsistent pairs and SQL faults remain unconfirmed,
  never inferred absence. Only an exact pair yields its restricted original
  declaration for comparison with current source and opaque backing state.
- For other states, retain no adopted historical binding: report historical
  agreement false and observe current backing stability only. Recheck the pair
  before one rollback/close and current visible source/permissions before metadata
  disclosure. No closed borrowed lookup, raw material/hash export or undo claim.
- Extend only fixed-manifest synthetic/owned-private SQL tests; no live source/
  schema/provider/button/site/worker/customer/authority operation. Independent
  source/key/tenant/epoch provenance and protected draft intake remain gates. See
  [PENDING_CSR_BOUND_REVIEW.md](PENDING_CSR_BOUND_REVIEW.md).

Local-only guarded run: **14,024 passed in 85.55 seconds**; all nine Node VM
scripts: **1,444 cases passed**. Final guarded combined: **14,024 local + 2,006
private SQL = 16,030 passed in 174.79 seconds**, across thirteen private suites,
including **115 new cases** (83 local + 32 native SQL). Four existing native
initial-save ambiguity/late-denial cases now review the same original through a
new lease. Native tests trap all staging/commit during pair review and verify the
five observations, corruption/source/backing refusal, classification drift rollback
and cleanup acknowledgment loss. No resource/ordinary-ACL/crypto/transport guard
was waived. Installed v15/v16, Desk/browser, SDK and authority acceptance remain
unverified.

## Increment 95: permissioned one-shot preparation and protected original handoff

- Connect the shared in-memory builder/cipher to initial NEW-pair storage through
  the existing source/normal-ACL/owned-resource/backing policy. Configuration comes
  from saved rows; declared context must match before acquisition. Locked absence
  in both pending tables is required before generation, without old-key loading.
- Generate/seal once, privately retain the exact encrypted original before any
  custodian callback, and require literal True handoff acknowledgment before SQL
  staging. An acknowledgment is not durability/provenance; metadata says so.
- Recheck source/backing/access after handoff, then reuse strict new-pair/final
  exact guards and one commit/close. Existing populated active fields stay intact.
  Failures/interruption/uncertain completion do not regenerate or retry; a trusted
  server owner retains protected recovery input, never a UI/HTTP export.
- Reuse one comprehensive display-only translated failure and English keys;
  extend only fixed-manifest/owned-private tests. No runtime schema/provider/button/
  tenant/worker/live/authority operation. Durable custody/key/source/tenant/epoch
  provenance and installed acceptance remain gates. See
  [PENDING_CSR_PREPARATION.md](PENDING_CSR_PREPARATION.md).

First local-only guarded: **14,081 passed in 85.93 seconds**; nine Node VM scripts:
**1,444 cases passed**. Final guarded combined: **14,081 local + 2,022 private
SQL = 16,103 passed in 173.24 seconds**, across thirteen private suites, including
**73 new cases** (57 local + 16 native SQL). Native tests verify retained exact
new-pair contents, populated active-field preservation, zero generation/old-key
decryption on existing IDs, custody/guard failure without staging, both-row
commit/close ambiguity and fresh read-only review without regeneration. No
resource/ordinary-ACL/crypto/transport assertion was waived; installed v15/v16,
Desk/browser, SDK and authority acceptance remain unverified.

## Increment 96: shared Sales/POS XML and first-invoice presence boundaries

- Consolidate actual Sales/POS metadata and PIH/QR/signature reference builders
  behind the unchanged public entry points, preserving normal element order,
  text/attribute values and the existing signing placeholder.
- Use one six-type specification for both adapters and automatic onboarding;
  normalize explicit valid selectors and refuse invalid sample selectors before
  fragment append. Preserve existing type flags rather than changing tax rules.
- Share saved credential-owner selection for PIH, including normalized linked
  checkbox and taxpayer/source checks; refuse empty/non-text selected PIH without
  inventing a seed, falling back to another owner or resetting a chain.
- Consolidate the duplicated legacy UUID placeholder policy without changing
  live UUID persistence, POS regeneration or retry behavior. Remove an obsolete
  commented POS supplier block with unreachable statements.
- Add English explanation and an Arabic display key. Extend the offline fixed
  manifest only; no runtime source, assets, schema, Company, worker or authority
  operation. See [SHARED_INVOICE_XML.md](SHARED_INVOICE_XML.md).

The first-invoice work is **not complete**: existing saved PIH presence is not
verified genesis/history, source reads are not a pinned issuance transaction,
and legacy UUID/ICV writes can precede the reference guard. Counter migration,
stable retry artifacts, credential epochs/concurrency, installed v15/v16 and
SDK/authority acceptance remain gates. The new targeted suite passed **171
cases in 1.10 seconds**. Final guarded combined: **14,252 local + 2,022 private
SQL = 16,274 passed in 172.76 seconds**, across the same thirteen private suites.
All nine Node VM scripts passed **1,444 cases**. An initial restricted-execution
combined run passed all 14,252 local cases but could not start the private native
server (2,022 setup errors); an approved native-process run passed 222 targeted
private cases and then the complete combined selection. The application offline
guard remained active; no guard, ordinary ACL or crypto assertion was weakened.
The seven changed runtime modules have a net reduction of **189 source lines**,
including obsolete comments; tests/docs grow separately. This is not a measured
runtime speed/memory/query improvement. No working environment or authority
request was used.

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
to 1,887. Increment 14 adds 161 cases to reach 2,048. Increment 15 adds 278 cases,
bringing the combined selected suite to 2,326. Increment 16 adds 112 local cases
to reach 2,438 passing local tests. Increment 17 adds 100 cases to reach
2,538 passing local tests. Increment 18 adds 122 cases to reach
2,660 passing local tests. Increment 19 adds 92 cases to reach
2,752 passing local tests. Increment 20 adds 105 to reach
2,857 passing local tests. Increment 21 adds 136 to reach
2,993 passing local tests. Increment 22 adds 149 to reach
3,142 passing local tests. Increment 23 adds 145 to reach
3,287 passing local tests. Increment 24 adds 137 to reach
3,424 passing local tests. Increment 25 adds 191 to reach
3,615 passing local tests. Increment 26 adds 224 to reach
3,839 passing local tests. Increment 27 adds 80 to reach
3,919 passing local tests. Increment 28 adds 67 to reach
3,986 passing local tests. Increment 29 adds 187 to reach
4,173 passing local tests. Increment 30 adds 213 to reach
**4,386 passing local tests**, plus **143 passing real private-database cases**
(25 journal + 30 bundle/service + 34 archive/service + 17 capture + 4 HTTPS
+ 8 source capture + 13 receipt recovery + 12 permissioned recovery, **4,529 total**).
The local-only runner passed 4,385 cases in 23.58 seconds before the final aware
default-clock case was added. The final combined runner passed all 4,529 cases in
39.88 seconds. All eight private SQL suites were rerun under the offline guard;
they never connect to a tenant.

Increment 31 adds 101 cases, reaching **4,487 passing local tests** (24.34 seconds),
plus the same **143 private SQL cases**, **4,630 total** (40.30 seconds). Both
commands ran under the offline guard; the private server was fixture-owned,
temporary and TCP-disabled. No working site's database was accessed.

Increment 32 adds **78 local + 10 private SQL cases**, reaching **4,565 local +
153 private SQL = 4,718 passing cases** across nine private suites. The final
guarded combined run passed in **40.98 seconds** (an earlier combined run passed
in 47.89 seconds). The first local run exposed two test-helper keyword-collision
failures for invalid journal inputs; the helper was corrected before both green
combined runs. No site, tenant data or authority request was involved.

Increment 33 adds **77 local + 23 private SQL cases**, reaching **4,642 local +
176 private SQL = 4,818 passing cases** across ten private suites. The final
guarded combined run passed in **43.38 seconds**. An earlier local-only run
passed 4,641 in 27.55 seconds before the ambient-proxy acquisition failure case
was added; earlier combined runs passed 4,816/4,817 before the final hardening.
All source/SQL/ACL data is synthetic; no working-site transaction was acquired.

Increment 34 adds **76 local cases**, reaching **4,718 local + 176 private SQL =
4,894 passing cases** in **43.16 seconds** under the guarded combined runner.
The initial local run reported six test-assertion failures: four raw-zero/privacy
substring checks (zero can occur in a fingerprint) and two incorrect no-commit
assumptions about unchanged ordinary QR generation. Assertions were corrected to
check projection keys and characterize the legacy commit without changing it.
The subsequent full run passed; no tenant, file image or authority was accessed.

Increment 35 adds **26 local + 12 private SQL cases**, reaching **4,744 local +
188 private SQL = 4,932 passing cases** across eleven private SQL suites. The
final guarded combined run passed in **43.97 seconds**. The earlier local-only
run passed 4,743 in 24.31 seconds before the static fixture-declaration case.
Native SQL proves parent-owned visibility/rollback for synthetic rows through
the real generator with mocked File/image/ERP behavior, NOT physical-file or
installed Frappe acceptance. No schema migration or working transaction ran.

Increment 36 adds **78 local + 8 private SQL cases**, reaching **4,822 local +
196 private SQL = 5,018 passing cases** across the same eleven private suites.
The final guarded combined run passed in **44.63 seconds** (an earlier complete
run passed in 45.22 seconds). The first local run exposed two catalog failures
from an unquoted comma in the new English CSV key; quoting that single row fixed
both translation lookup and the existing catalog-shape regression. All generated
and File-query data is synthetic; no actual image, tenant or authority was read.

Increment 37 adds **62 local + 4 private SQL cases**, reaching **4,884 local +
200 private SQL = 5,084 passing cases** across the same eleven private suites.
The guarded combined run passed in **44.50 seconds**. An earlier local-only
run passed 4,879 in 24.87 seconds before five added discount/Arabic cases.
All invoice/File data is synthetic; the advance SQL scenarios prove metadata
preservation, not physical File lifecycle, full app or regulatory amount validity.

Increment 38 adds **179 local cases**, reaching **5,063 local + 200 private SQL =
5,263 passing cases** across the same eleven private SQL suites. The final
guarded run passed in **47.83 seconds**. Initial unit runs stopped all 172
then-selected new cases before the endpoint body because the Frappe typing
decorator expected request-local `flags`. The unit fixture unwraps that decorator
without creating a site; subsequent local results were 5,056 passing in 25.35
seconds before seven final cases. HTTP POST/guest registration is checked
separately. XML reads use synthetic memory only, never real files or invoices.

Increment 39 adds **50 local + 16 private SQL cases**, reaching **5,113 local +
216 private SQL = 5,329 passing cases** across the same eleven private suites.
The final guarded combined run passed in **45.03 seconds**, following an earlier
complete run in 50.91 seconds; the preceding local run passed 5,113 in 24.91
seconds. Access tests are updated from historical
re-link/parser/commit expectations to preservation/review and forbidden-call
tripwires. No physical content is read; native SQL uses new synthetic owned rows
and proves unchanged QR/File state and parent-controlled pending-work visibility.

Increment 40 adds **158 local + 15 private SQL cases**, reaching **5,271 local +
231 private SQL = 5,502 passing cases** across the same eleven private suites.
The guarded combined run passed in **48.04 seconds**. The initial local run had
one fixture failure: the selection helper's positional `journal` parameter
collided with a deliberately invalid `journal` keyword override. Renaming the
test helper parameter fixed it; all expectation/clock/response negative cases
and the full run passed afterward. Data/certificates/receipts are synthetic;
consistent bytes and committed private SQL are not authentic authority evidence.

Increment 41 adds **192 local + 48 private SQL cases**, reaching **5,463 local +
279 private SQL = 5,742 passing cases** across twelve private suites. The final
guarded combined run passed in **48.92 seconds**; an earlier 5,716-case run passed
in 48.66 seconds before 26 final local negatives. The existing 5,271 local cases
passed in 25.69 seconds immediately after extraction, then 5,437 local cases
passed in 26.57 seconds with the first QR access matrix. Original advance local/
SQL regressions pass against the shared engine without assertion changes.
All source data/permissions/receipts are synthetic; actual source locks and
owned cleanup are not provider-origin, installed-v16 or crypto acceptance proof.

Increment 42 adds **61 local + 16 private SQL cases**, reaching **5,524 local +
295 private SQL = 5,819 passing cases** across the same twelve private suites.
The guarded combined run passed in **48.95 seconds**; the preceding local run
passed 5,524 in 26.61 seconds. Tests forbid saved-response reads, content/image/
File/status mutations, notifications and transaction cleanup. Native synthetic
rows prove parent-only pending-work visibility/commit/rollback and unchanged
QR/status/attachments. Primary adapters/extractor are unchanged; this is not
complete installed-app, physical-file, cryptographic or remote acceptance proof.

Increment 43 adds **30 local + 24 private SQL cases**, reaching **5,554 local +
319 private SQL = 5,873 passing cases** across the same twelve private suites.
The final guarded combined run passed in **49.82 seconds**; local-only passed
5,554 in 27.12 seconds. The first combined run had 24 new SQL failures because
the synthetic File save lacked the existing adapter's `ignore_permissions`
keyword; the double was corrected, not the production save contract. Actual
owned SQL verifies parent-only visibility/commit/rollback and unchanged status,
business/modified columns under injected failures. File/image/ERP are mocked;
no physical filesystem, installed-v16 or remote acceptance claim is made.

Increment 44 adds **104 local + 32 private SQL cases**, reaching **5,658 local +
351 private SQL = 6,009 passing cases** across the same twelve private suites.
The final guarded combined run passed in **50.10 seconds**. The initial local
run stopped ten legacy HTTP/retry characterizations at the new ownership gate:
the fixture's saved URLs had no File rows. Explicit scoped synthetic rows were
added to that fixture, preserving every original UUID/ICV assertion and adding
mock HTTP-call assertions. No ownership rule was relaxed. Native SQL covers
parent-only pending-work visibility/commit/rollback, unchanged current references/
status/attachment rows, and foreign URL rejection before mock HTTP/error writes.
This is not post-response concurrency, installed ERPNext 16 or remote acceptance
evidence; receipt-aware caller error handling remains a blocking next step.

Increment 45 adds **143 local + 24 private SQL cases**, reaching **5,801 local +
375 private SQL = 6,176 passing cases** across the same twelve private suites.
The final guarded combined run passed in **51.87 seconds**. The first local run
exposed unmocked translation/cache/logger access; the offline guard blocked it.
A subsequent fixture-only mistake attempted to patch the minimal signal module's
nonexistent frappe attribute. Only its translator is now patched; no site was
initialized and no guard/runtime rule was weakened. Local fault snapshots prove
no additional generic failure reads/writes/commits or retry after covered faults;
native SQL proves early parent ownership and preservation of late already-
committed receipt/status/UUID without a fourth failure commit. The late cases
deliberately reproduce existing premature parent commits, not their resolution.
No durable receipt/review hold, installed-v16 or authority acceptance is proven.

Increment 46 adds **82 local + 41 private SQL cases**, reaching **5,883 local +
416 private SQL = 6,299 passing cases** across the same twelve private suites.
The final guarded combined run passed in **51.17 seconds**; the first local-only
run passed 5,883 in 28.04 seconds. Initial SQL negatives corrected test-only
expectations for close-failure cleanup and an unrelated pending value rejected
by the existing revision CHECK; no cleanup/runtime guard/schema constraint was
relaxed. Native tests cover exact bytes, late/identical/conflicting delivery,
concurrent serialization, lost commit/close acknowledgements, missing starts,
source guards/autocommit rejection and unrelated parent transaction ownership.
All authority/provenance/replay flags remain false; primary APIs/schedulers are
NOT wired to this primitive, so runtime durable receipt/retry holds remain open.

Increment 47 adds **188 local + 54 private SQL cases**, reaching **6,071 local +
470 private SQL = 6,541 passing cases** across the same twelve private suites.
The final guarded combined run passed in **54.22 seconds**. Extraction-only
passed the existing 5,883 local cases in 27.43 seconds; the first access matrix
passed 6,049 in 30.04 seconds. The first combined run failed two new secret-read
tests because their substring filter included a non-secret certificate-owner
flag; only that legitimate flag was exempted, not credential reads or guards.
Native SQL checks exact source/journal locks, stale ambient versus actual rows,
write/read denial before acquisition, rollback on pre-commit revocation, post-
close disclosure denial without undoing commit and untouched borrowed-parent work.
Existing advance/QR access regressions keep their assertions. No installed v16,
provider origin, historical epoch/custody, remote acceptance or runtime retry hold
is proven; no live provider/API/scheduler is activated.

Increment 48 adds **60 local + 40 private SQL cases**, reaching **6,131 local +
510 private SQL = 6,641 passing cases** across the same twelve private suites.
The final guarded combined run passed in **65.62 seconds**. Actual owned Unix
peer/socket/target/marker checks compose with the non-activated permissioned
service; negative tests reject missing/wrong registration, swapped database,
session/peer drift and denied access before credentials. The added unit cases
also exercise socket replacement/symlinks, cleanup failures and interruptions.
No customer provider/configuration was selected; no installed v16, genuine
receipt provenance, durable custody or remote acceptance is proven.

Increment 49 adds **121 local + 37 private SQL cases**, reaching **6,252 local +
547 private SQL = 6,799 passing cases** across the same twelve private suites.
The final guarded combined run passed in **58.24 seconds**. The initial local
run caught nine generator-contextmanager exception-context leaks and one invalid
test assumption that a valid alternative namespace must fail structural decoding.
Normal guarded callbacks now remove raw exception context; separate tests retain
the explicit distinction between structural parsing and AEAD authentication.
The corrected local run passed 6,250 in 30.40 seconds; first combined passed
6,790 in 58.89 seconds before final negatives were added. Native tests prove
committed/uncommitted owned-database crash outcomes, exact local redelivery,
parallel conflicts, nonce/scope isolation, no new starts/overwrites and preserved
custody after journal drift without adoption rights. No worker capture/hold,
permissioned retrieval, actual v16 or authentic remote receipt is proven.

Increment 50 adds **302 local + 44 private SQL cases**, reaching **6,554 local +
591 private SQL = 7,145 passing cases** across the same twelve private suites.
The final guarded combined run passed in **63.05 seconds**. Initial new tests
had 266 setup errors from an omitted fixture import (all existing 6,252 local
cases passed); after fixing that import, four new tests exposed acquisition-time
permission denials being classified as generic failures. Cleanup now preserves
translated denial without disclosing original context; no ACL was relaxed.
The first corrected combined run passed 7,109 in 62.96 seconds. Added native
cases compose actual pinned provider/immutable custody with synthetic saved ACL,
separate sessions, scope/source locks, both lost-acknowledgment commit outcomes,
identical local redelivery and late denial preserving history. Final additions
cover ciphertext/response/context/epoch misbinding and non-authorizing status.
Existing receipt/QR/advance regressions pass unchanged; no installed v16,
authentic transport, historic provider/epoch or runtime review hold is proven.

Increment 51 adds **86 local + 57 private SQL cases**, reaching **6,640 local +
648 private SQL = 7,288 passing cases** across the same twelve private suites.
The final guarded combined run passed in **66.43 seconds**. First local passed
6,625 in 34.05 seconds; first combined passed 7,261 in 63.74 seconds before the
last 388/381/383/386 classification cases. No reservation/rollback assertion was
relaxed. Native SQL verifies atomic start/hold visibility and rollback, committed/
uncommitted owned-database crashes, same/different-version races at both isolation
levels, preparation drift with genuinely distinct local identities, unchanged
holds after UNKNOWN/HTTP, corruption/autocommit refusal and no legacy backfill.
These are synthetic contracts, not SDK/advance accounting/installed-v16/authority
acceptance evidence. No active primary retry/transport path or schema is changed.

Increment 52 adds **164 local + 39 private SQL cases**, reaching **6,804 local +
687 private SQL = 7,491 passing cases** across the same twelve private suites.
The final guarded combined run passed in **73.32 seconds**. First local passed
6,777 in 35.91 seconds; first combined passed 7,460 in 67.64 seconds. Expanded
negative/corruption/competition cases passed 7,491 in 70.21 seconds before final
import organization. No reservation/correlation/guard/rollback assertion was
relaxed. Native SQL proves no open owned handles at observer entry, committed
start/hold/request binding, atomic receipt/custody append and rollback, actual
commit outcomes with synthetic lost acknowledgments, pre/post-observer drift
and only one observer between competing same/different-version coordinators.
No authenticated HTTP, trusted transport/source/epoch, permissioned coordinator,
installed v16 or genuine authority acceptance is proven or activated.

Increment 53 adds **143 local + 44 private SQL cases**, reaching **6,947 local +
731 private SQL = 7,678 passing cases** across the same twelve private suites.
The final guarded combined run passed in **73.71 seconds**. Initial local passed
6,923 in 39.44 seconds; initial combined passed 7,654 in 72.68 seconds. The final
addition covers malformed/forged requests and wrong targets before saved lookup,
non-authorizing current status and observer-owned pre-result interruption custody.
Actual private SQL proves scoped pinned-provider/source-lock composition,
atomic encrypted custody/journal append, denial before credentials, pre-observer
revocation, response retention after denial, post-commit refusal without undoing
history, and protected handoff after failed/interrupted retention. No guard,
rollback, namespace, permission or once-only observer assertion was relaxed.
Typed dependencies/ACK do not establish provenance or durable observer/retainer
custody. No runtime or real authority/installed-v16/SDK acceptance is activated.

Increment 54 adds **123 local + 42 private SQL cases**, reaching **7,070 local +
773 private SQL = 7,843 passing cases** across the same twelve private suites.
The final guarded combined run passed in **79.89 seconds**. Initial local had
6 failures/7,044 passes in 41.52 seconds: the reused capture-only SQL model lacked
custody `load`, so existing-pair scenarios were correctly unconfirmed. Extending
that test double with authenticated retrieval corrected the fixture; no
production guard, comparison or assertion was weakened. Initial combined passed
7,821 in 79.60 seconds before added empty/binary/error-body, malformed-presence,
wrong-key and missing-start/binding cases. Real private SQL proves atomic local
pair persistence/rollback, exact identical redelivery, no partial/conflict repair,
commit uncertainty, corrupt-binding/ciphertext refusal, concurrent redelivery at
both isolation levels and owned-server restart with unchanged holds. Existing
primary sender/retry, live schema/source/config/customer and authority behavior
remain untouched. No permissioned paired API, installed-v16/SDK/remote acceptance
or end-to-end durable response capture is established.

Increment 55 adds **322 local + 98 private SQL cases**, reaching **7,392 local +
871 private SQL = 8,263 passing cases** across the same twelve private suites.
The final guarded combined run passed in **96.44 seconds**. Initial local passed
7,364 in 49.63 seconds; first combined passed 8,235 in 95.97 seconds before added
current-status and interruption cases. The reused pair model now accepts an
explicit namespace, preserving its previous default and exact namespace
assertions. No source/guard/ownership/rollback assertion was relaxed. Real private
SQL proves source locks and scoped pinned-provider composition, denial before
key/DB credentials, stale SQL refusal, original paired store/partial review,
acquisition/precommit/post-close revocation and actual uncertain commit outcomes.
Complete original-envelope declarations distinguish equal-plaintext reseals
before keys; both permission signatures and English/Arabic static failures are
synthetic boundary evidence, not actual installed-v16/browser/SDK/authority or
historically independent custody/provenance proof. No runtime caller or working
environment/authority action is activated.

Increment 56 adds **107 local + 13 private SQL cases**, reaching **7,499 local +
884 private SQL = 8,383 passing cases** across the same twelve private suites.
The guarded combined run passed in **101.30 seconds**. Initial local had 20
failures/7,479 passes in 52.10 seconds: the new no-protected-reference assertion
mistook an absent seal's `None` for a protected object because the metadata pair
state was also `None`. It now compares non-None protected objects and additionally
requires EXACTLY the two state-string fields, preserving/strengthening the
privacy invariant; no runtime or storage guard was relaxed. Private SQL uses the
actual single-store helpers/repositories, partial windows, uncertain independent
commits, unchanged holds and original versus independently supplied late events.
Mocked real primary adapters reproduce remaining HTTP400/401/503 logging-failure
overwrites; this is explicitly an UNFIXED runtime-source gap, not a claimed
acceptance/retry repair. No activated reviewer, actual late receiver, installed
v16/SDK/authority or end-to-end durable response capture is established.

Increment 57 adds **550 local + 88 private SQL cases**, reaching **8,049 local +
972 private SQL = 9,021 passing cases** across the same twelve private suites.
The final guarded combined run passed in **103.63 seconds**. First combined
passed 9,009 in 102.98 seconds before twelve real event-logger-function cases.
Those confirm insert/commit + fallback failures cannot add generic API writes,
while swallowed failures/normal None returns remain unchanged and do NOT prove
custody. Logger-owned commits and its fallback policy are still integration gates.
First local had 3
failures/8,034 passes in 54.09 seconds: the POS Reporting normal-rejection golden
expected only four response-field writes but omitted its PREEXISTING pre-HTTP
XML-link `db_set`. The corrected golden requires the exact five-field sequence,
not a relaxed range, preserving existing behavior; runtime branches were not
changed to satisfy it. Private phase1 QR SQL tests show 72 early error-status
format/log/hide cases keep original response/status/UUID and parent-pending work
uncommitted until the explicit test owner decides commit/rollback. Sixteen late
400/401 formatting cases show already committed rejection fields/parent work
are preserved without an added generic error commit/503; pending Sales Clearance
raw response remains under the parent's decision. Existing independent commits,
intentional-rejection generic wrapping and POS placeholders remain characterized
defects, not certified/fixed behaviors. No guard/ownership/rollback/route/identity
assertion was waived; the twelve old defect observations now enforce exact
no-extra-effect snapshots. No SDK/installed-v16/browser/remote acceptance or
end-to-end durable response guarantee is claimed; working code and all authority
endpoints remain untouched.

| Suite | Scope |
| --- | --- |
| `test_received_response_steps.py` | Actual four APIs/all rejection branch families: early/late formatter, lazy text, log/hide snapshots, all formerly caught types, exact normal rejection goldens, unchanged RuntimeError/interruption/transport/pre-request behavior, Arabic/forwarding/AST scope; existing phase1 QR SQL suite adds real parent-controlled pending work and partial committed rejection observations |
| `test_primary_review_policy.py` | Closed capture/pair review reasons, exact full request/envelope equality and mismatch refusal, no protected output/I/O/acceptance or automatic actions, observed disagreement, twelve-adapter direct-name inventory and existing primary error-status logging gap; existing journal SQL suite adds real independent-writer partial windows/unknown commits and original-versus-independent-late history |
| `test_primary_reconciliation_access.py` | Saved WRITE/related READ and both quiet permission signatures, exact request/START/full original seal binding before scoped keys/SQL, metadata-only pair outcomes, actor/source/ACL drift before/after commit, borrowed parents/interruption/Arabic/privacy; existing QR SQL suite adds actual pinned-provider/source-lock composition, rollback/uncertainty and no partial repair |
| `test_primary_receipt_reconciliation.py` | Exact request/original-envelope authentication before SQL, mandatory existing hold/request binding, paired inspection/atomic local persistence, identical/partial/conflict/UNKNOWN policy, guard/commit/cleanup/interruption privacy and no resealing/transport; existing journal SQL suite adds actual rollback/uncertainty/corruption/concurrent redelivery/owned-server restart |
| `test_primary_capture_access.py` | Exact request/target/start/resource binding, saved WRITE/related READ and both quiet permission signatures, metadata-only output, mandatory protected handoff before late denial, interruptions/Arabic/borrowed-parent privacy; existing QR SQL suite adds real pinned-provider/atomic custody composition and revocation without undoing history |
| `test_primary_capture.py` | Exact deterministic auth-free body/supplied response correlation, three owned transactions, literal guards, once-only observer, unknown outcomes/exact protected recovery, no reseal/hold release/acceptance and static errors; existing journal SQL suite adds actual atomic storage/rollback, commit uncertainty, binding drift and competing coordinators |
| `test_primary_attempt_hold.py` | Exact rebuilt start and logical-source key across changing versions/chain/epoch/route/UUID/classification, strict reserve/no release/no authorization, later UNKNOWN/HTTP inspection, poisoned transactions/privacy; existing journal SQL suite adds atomic start/hold, owned crashes, cross-version races, identity drift and rollback/no-backfill evidence |
| `test_primary_receipt_custody_access.py` | Saved invoice WRITE/related READ before scoped keys/SQL, exact envelope/retained binding, guarded owned commit and ciphertext-only rollback/close retrieval, late denial/uncertainty/borrowed-parent/Arabic/privacy; existing QR SQL suite adds actual pinned-provider/custody composition, stale SQL, unknown commits and post-close revocation |
| `test_primary_receipt_custody.py` | Exact bounded binary codec and dedicated AES-GCM binding, empty/binary/status/UNKNOWN observations, tampering/bounds/domain/key/privacy, transaction poisoning/no raw error context; existing journal SQL suite adds immutable custody, owned-database crashes, competing writers, nonce/scope conflicts and stale-journal retention without replay |
| `test_primary_receipt_provider.py` | Explicit Unix provisioning/typed credentials, scope/socket before secrets, fixed direct driver options, kernel peer/DB/marker/session checks, poisoned handles, no reconnect/retry, owned cleanup/interruptions and redaction; existing QR SQL suite adds actual provider/service composition and negative target/ACL cases |
| `test_primary_receipt_access.py` | Saved System Manager/site/source WRITE and related READ, exact attempt/event/predecessor/context binding, shared owner/route/source revisions, quiet v15/v16-shaped ACL, guards/borrowed handles/revocation/Arabic/protected input; existing QR private SQL suite adds source/journal transaction and stale/denied/late-revocation cases |
| `test_primary_receipt_persistence.py` | Explicit protected exact-attempt local receipt persistence/redelivery, unknown commit/close and source guards, codecs/tampering/namespace/stage checks before SQL, no replay/start/transport/clock; existing journal SQL suite adds actual idempotence/concurrency/uncertainty/parent-ownership tests |
| `test_response_processing.py` | Actual four primary APIs with mocked HTTP/ERP/File, failure-stage snapshots, no generic post-response failure writes/retry, static unchained Arabic review and unchanged runtime-error propagation; private QR SQL suite adds early parent-controlled work and late existing-commit receipt/status preservation |
| `test_primary_qr_transaction.py` | Actual shared Sales/POS attach helper with mocked File/image/ERP, QR-link-only staging, phase gates, translated missing schema, failures and owned-row preservation; private QR SQL suite adds parent visibility/rollback with unchanged accepted status/business/modified fields |
| `test_primary_qr_ownership.py` | Actual primary QR scoped preservation/review and all four API pre-request rejection boundaries, shape validation/bounds/Arabic/query faults, no global fallback or writes; private QR SQL suite adds parent-owned pending work, scoped synthetic File rows and unchanged artifacts |
| `test_offline_rehearsal.py` | Guarded ordinary Python network/site/process rejection, private-only socket/command registry, inherited peer/symlink checks, owned cleanup, no unguarded SQL acquisition and fixed offline test runner |
| `test_issue_timestamp.py` | Explicit typed/text issue-time parsing, valid zero duration, single-digit hours, offsets/DST/UTC rollover, bounded/static input errors, frozen whole-second UTC/XML/QR contract and no Frappe/site/clock dependency |
| `test_issue_timestamp_adapters.py` | Actual mocked Sales/POS metadata and Phase-1/Phase-2/synthetic/initial-advance QR paths, no second invoice read, invalid time before UUID writes, duplicate/blank XML times before keys, Arabic error keys and unchanged legacy amount/Phase-2 advance guards |
| `test_phase1_qr_transaction.py`, `test_phase1_qr_transaction_mariadb.py` | Actual generator metadata-only staging, no recursive save/commit/DDL, failures/Arabic/schema fixtures, actual-v15 notification arguments; owned InnoDB parent-controlled visibility/rollback with mocked File/image |
| `test_qr_attachment_policy.py` | Both DocTypes/current references versus newer filenames, orphan/dangling/foreign/bounded metadata, no deletes/relink/global fallback and Arabic; actual generator with mocked ERP/image/File |
| `test_advance_qr_preservation.py` | Actual mocked advance print hook, no forced replacement/final cleanup, shared review policy/Arabic, early gates, old dates, unchanged discount/FX arithmetic and propagated failures; private SQL suite also covers four advance preservation/review cases |
| `test_qr_regeneration_access.py` | Actual unwrapped endpoint bodies, saved Invoice/Company/File ACL and ownership, malformed/Guest/private failures, bounded File projection, v15/v16-shaped quiet engines, actor drift/Arabic, no XML/content IO, pure preserve/review, no mutations/commits and read-only UI wiring |
| `test_qr_source_selection.py` | Explicit journal/context/revision and endpoint-bound QR bytes, Sales/POS candidate matrix, clock/identity/response drift, namespace/ambiguity/DTD/bounded Base64, redacted immutable observations and false authority flags; existing archived-source SQL suite adds committed/uncommitted selection cases |
| `test_qr_source_access.py`, `test_qr_source_access_mariadb.py` | Shared metadata engine with saved Sales/POS/Company/device/linked ACL, exact binding/SQL locks, revocation/source drift/cleanup/borrowed handles, v15/v16-shaped engines/Arabic, no ambient writes; new owned-private SQL suite and unchanged advance access regressions |
| `test_phase2_artifact_preservation.py` | Actual completion hook/shared preservation policy, no response/content/image/re-link/status/transaction effects, accepted labels versus orphan/ambiguous/bounded metadata, scope/Arabic/error gates; existing QR SQL suite adds 16 parent-ownership cases |
| `test_advance_reference.py` | Synthetic original type-386 identity/seller/clock observations, lexical preservation, bounded secure parsing/static errors, no settings lookup and characterization of unchanged legacy reference defects |
| `test_advance_source_selection.py`, `test_advance_source_selection_mariadb.py` | Explicit exact journal/context/UUID/ICV source choice, Reporting request/Clearance return distinction, changed-clock rejection and false authority flags; owned-private committed reconstruction, namespace/late-revision separation and uncommitted rollback limits |
| `test_advance_source_access.py`, `test_advance_source_access_mariadb.py` | Metadata-only saved ACL/source/owner/marker binding, revocation/redaction/owned cleanup, borrowed-handle rejection and Arabic; real private source/journal locks, stale ambient/SQL identity and uncommitted rollback |
| `test_advance_source_gap.py` | Bounded five-tag QR shape/clock/amount observations, missing identity gaps, explicit non-authorizing gap/phase plans, unchanged accounting eligibility and actual mocked builder/legacy commit characterization |
| `test_compliance_result.py` | Pure result classification and malformed payloads |
| `test_compliance_api_outcomes.py` | Mocked real API/button functions, failures, previous completion, translations |
| `test_nonproduction_isolation.py` | Preview identity, live-identity regression, counter boundaries, explicit types, cross-company rejection, debug artifact protection, temporary-file lifetime |
| `test_api_route_contract.py`, `test_api_routing.py` | Pure routing, six compatibility wrappers, malformed settings, environment overrides, and mocked onboarding request boundaries |
| `test_credential_selection.py`, `test_field_compat.py` | Saved owner resolution, certificate aliases, key matching, signing/QR parity without writes, auth purposes, Arabic messages, six-type local preparation, existing field compatibility |
| `test_credential_snapshot.py` | One copied route/key/certificate/auth material binding, same-key renewal rejection, validity/curve, saved-source capture, frozen Company projection, static privacy/Arabic failures, no writes/HTTP or provenance claim |
| `test_credential_lifecycle.py` | Independent purpose/token/field observations, same-key renewal, alias reversal, missing/bounded material, frozen privacy, saved-source capture and actual legacy writer/key rotation characterization with mocked side effects |
| `test_credential_bundle.py` | Explicit slots/versions, AES-GCM integrity and exact secret/text preservation, bounded strict codec, key custody boundary, immutable staged envelopes and SQL transaction/error/privacy contracts |
| `test_credential_bundle_access.py` | Site/role/document gates before key acquisition, shared secret-free owner projection, exact slot/source/provider binding, actor drift, static unchained localized errors, metadata-only no-write service |
| `test_compliance_evidence.py` | Signed CSR functionality/key/UID requirements, six-type exact wire/XML/certificate/route bindings, raw 200/202/406 distinctions, observation conflicts/bounds/privacy and staged operator composition; no remote verification |
| `test_compliance_archive.py` | Exact bounded framed codec, independently keyed envelopes, AAD/rehydration integrity, start/receipt binding, static transaction/privacy/no-discovery contracts and empty-body preservation |
| `test_compliance_archive_access.py` | ACL-first authenticated explicit selection, saved owner/Sales/POS source matching, shared CSR, count/byte limits, no partial result, actor drift, privacy/translation and historical inspection compatibility |
| `test_compliance_capture.py` | Two owned transaction boundaries, exact snapshot-derived header/body, strict spent reservation, unknown commits/transport/clock, validity/age checks, no automatic retry/discovery and protected recovery material |
| `test_compliance_receipt_recovery.py` | Explicit exact-envelope persistence, namespace/stage/authentication rejection before SQL, exact committed start, identical receipt storage, unknown commits/cleanup/privacy and no transport/clock/resealing |
| `test_compliance_receipt_recovery_mariadb.py` (separate opt-in) | Owned-private initial/recovery commit ambiguity, concurrent recovery at both isolation levels, corrupt/resealed/missing rows, autocommit rejection and owned-process crash; synthetic transport only |
| `test_compliance_receipt_recovery_access.py` | Shared saved-owner/read-write ACL before keys, exact retained/current bindings, SQL source drift, provider/actor/precommit/postclose denial, guard literal True, protected output, interruptions and Arabic failures |
| `test_compliance_receipt_recovery_access_mariadb.py` (separate opt-in) | Owned-private same-transaction source/receipt locks, stale ambient projection, concurrent recoveries, unknown commits, revoked access before provider/before commit/after close and blocked writer release |
| `test_compliance_https.py` | Real preparation/HTTPAdapter with synthetic pools, exact auth/body, standard destination approval, zero retries/no redirects/env auth, TLS configuration, body/framing/encoding/time bounds, safe failures and no real sockets |
| `test_compliance_https_mariadb.py` (separate opt-in) | Private committed reservation/archive plus real adapter pipeline/synthetic pool; success, redirect, TLS-shaped failure, oversize and no duplicate invocation |
| `test_compliance_capture_access.py`, `test_permission_compat.py` | Saved read/write ACL before providers, exact owner/route/CSR binding, three closed guarded transactions, revision/ACL drift before/during/after SQL, static privacy, translations and version-shaped quiet permission engine calls |
| `test_compliance_capture_access_mariadb.py` (separate opt-in) | Owned-private saved-row locking and concurrent writer, source edits/uncertain preflight commit, immutable archive, synthetic HTTPS pool and no duplicate invocation; fake Frappe ACL only |
| `test_compliance_capture_mariadb.py` (separate opt-in) | Committed visibility/no locks before fake transport, competing collectors, pre-existing reservations, ambiguous commits, exact receipt reconciliation and owned-server crash recovery |
| `test_compliance_archive_mariadb.py` (separate opt-in) | Real private request/receipt commits, idempotence/conflicts, scope, corruption, rollback/connection loss, nonce guard, two-worker isolation, lock timeout and owned-server crash recovery |
| `test_credential_bundle_mariadb.py` (separate opt-in) | Private encrypted InnoDB roundtrip, parent/slot isolation, immutable secret-version conflicts, concurrent stages, corruption, nonce collision, lock timeout and owned-server crash/rollback recovery |
| `test_submission_context.py` | Four primary request adapters, environments/owners, Production auth, actual PIH helper with mocked records, rejection/timeout, request-pinned owner, batch mode, legacy 409 behavior |
| `test_legacy_submission_context.py` | Four existing-XML adapters and wrappers, actual temporary file reads, saved machine-link guards, unchanged artifacts, auth and PIH ownership |
| `test_icv_identity_contract.py` | Read-only characterization of legacy identity/rotation/purpose behavior and collision edge cases; not a counter migration |
| `test_invoice_xml_core.py` | Shared metadata/reference/type fragments, saved PIH owner/flag/source parity, missing-hash preservation and Arabic display, automatic six-type parity, legacy UUID filter and mocked first-counter behavior; not genesis/atomic issuance proof |
| `test_generation_routes.py` | Four remaining reporting adapters, six generator diversion boundaries, confirmed outcomes/errors, real temporary sample bridge, ordinary signing source, mode deferral |
| `test_background_scheduling.py` | Shared Sales/POS worker selection, Company isolation/windows/settings, stale status and draft boundaries, actual parent routing and worker bridge |
| `test_retry_identity_contract.py` | Read-only Sales/POS UUID regeneration/filtering, twelve HTTP failure/timeout boundaries, saved ICV and existing artifact identity divergence |
| `test_artifact_evidence.py`, `test_artifact_inventory.py` | Namespace-aware immutable metadata, saved identity reconciliation, exact-byte conflicts, permission/privacy/path/file controls, static safe errors, and no-write diagnostic bridge |
| `test_history_evidence.py`, `test_history_inventory.py` | Strict stored response observations, response/file XML identity, saved-unit counter purpose/key/position/tail, permissions, and unchanged default diagnostics |
| `test_generated_inventory.py` | Opt-in operator gate, known generated path, cross-DocType ambiguity, bounded file safety, source/byte comparison, no scan/write and composed history |
| `test_certificate_evidence.py`, `test_certificate_inventory.py` | Bounded immutable embedded DER/SPKI/text observations, renewal/key distinction, structural ambiguity, no-current-credential/permission/privacy and three-source composition |
| `test_issuance_candidate.py` | Pure frozen exact-byte candidate, explicit chain/version/epoch/route declarations, source/type matching, same-key drift, structured scope/privacy and no-I/O |
| `test_dispatch_journal.py` | Frozen single-attempt receipt history, exact bounded bytes, unknown/late/auth observations, idempotence/conflicts, no second start or acceptance/replay authority |
| `test_response_assessment.py` | Endpoint/HTTP/validation consistency, warnings, bounded strict wire JSON, returned XML identity/type/digest/PIH, legitimate changed clearance artifact, no provenance/crypto/accounting/retry authority |
| `test_journal_storage.py`, `test_journal_repository.py` | Versioned exact-byte rehydration, strict schemas, namespace/SQL boundaries, stale history/CAS and static transaction failures; no implicit commits/live adapter |
| `test_journal_repository_mariadb.py` (separate opt-in) | Actual private InnoDB commits, recovery, rollback, two-worker contention/isolation, identity/event/attempt uniqueness and corrupt-record detection; never a tenant |
| `test_tax_details_compat.py`, `test_tax_details_regression.py` | Tax adapter regressions |
| `test_qr_tlv_compliance.py` | Existing QR/TLV regressions |
| `test_zatca_response.py` | Existing response handling |
| `test_compatibility_hardening.py` | Existing mocked runtime/advance compatibility regressions |

HTTP/Frappe I/O in the local boundary tests is mocked. The separately opt-in
repository rehearsal uses real SQL only on its own new private server. Run against the
development worktree, not the installed production package. From the worktree:

```sh
PYTHONDONTWRITEBYTECODE=1 ../../env/bin/python tools/run_unification_rehearsal.py
```

For all selected local cases plus twelve owned-private SQL suites:

```sh
PYTHONDONTWRITEBYTECODE=1 ../../env/bin/python tools/run_unification_rehearsal.py --private-sql
```

The reviewed manifest is `zatca_erpgulf/zatca_erpgulf/tests/rehearsal_selection.py`.
Private fixtures refuse acquisition without the explicit guard. The runner keeps
environment-only private opt-in and broad/unreviewed test targets disabled.

Tested with the existing Python 3.10/Frappe 15 environment, plus MariaDB 10.11.14
for the isolated repository rehearsal. See [JOURNAL_REPOSITORY.md](JOURNAL_REPOSITORY.md)
and [COMPLIANCE_ARCHIVE.md](COMPLIANCE_ARCHIVE.md) for the separate
opt-in SQL command and recovery/key-management limits. No real v16 runtime, full
site integration, browser language switch, ZATCA SDK run, remote Compliance
request, or production invoice submission was performed in this increment.

## Next gate

Increments 31/32 provide reference/source consistency, 33 adds a permissioned
metadata boundary, 34 defines missing-source review and 35 removes the ordinary
QR helper's recursive save/commit/DDL. Increment 36 adds ordinary-generator
attachment preservation; 37 extends it to the initial-advance print hook and
removes final-invoice cleanup. Increment 38 adds explicit regeneration saved-row
access checks. Increment 39 removes heuristic reconstruction/implicit replacement
and helper-owned commits. Increment 40 adds exact journal-bound QR observations;
41 binds metadata-only saved-row access/source locks through a shared engine,
not authenticated recovery. Increment 42 removes speculative repair/deletion
from the automatic Phase-2 completion hook. Increment 43 removes primary QR
attachment DDL and invoice event/modified-time effects. Increment 44 adds bounded
primary QR ownership/schema preflight before request/error persistence and removes
global URL reuse from that attachment helper. Increment 45 prevents generic
error/503 persistence for previously caught local failures during primary response
processing, without asserting acceptance. Increment 46 adds an internal exact
retained primary receipt storage/redelivery primitive, not runtime activation.
Increment 47 adds saved-row WRITE/related-READ access and exact attempt/event/
source guards, not provider/historical authenticity. Increment 48 adds an optional
explicit pinned Unix provider, not runtime installation or origin attestation.
Increment 49 adds exact encrypted custody on explicit caller transactions, not
permissioned retrieval, automatic capture or a durable dispatch/review hold.
Increment 50 adds permissioned owned custody storage/ciphertext retrieval, not
live key/provider registration, transport authenticity or a no-replay hold.
Increment 51 adds an atomic local start/logical-source hold repository, not an
activated coordinator or a reusable lease. Increment 52 adds an auth-free exact
local observer coordinator, not real HTTP/authentication or runtime activation.
Increment 53 adds that permissioned metadata-only owned-resource boundary with
mandatory protected-result handoff before final ACL disclosure, not durable
retainer installation or real transport. Increment 54 adds exact paired
inspection/local persistence, not a permissioned paired facade or runtime repair.
Increment 55 adds saved-source/owned-resource metadata access for paired operations,
not independent provenance or runtime adoption. Increment 56 adds actual
single-writer/late-response characterization and pure non-authorizing review,
not an activated receiver or partial-state repair. Increment57 isolates known
local formatting/event-log/hide failures for all primary statuses without changing
normal rejection classification or legacy persistence. Increment58 extends that
boundary to selected rejection-persistence faults without extra post-fault writes,
not atomicity or rollback of prior commits. Increment59 supplies explicit diagnostic
staging/result/permission semantics while preserving the legacy wrapper, without
runtime adoption or hook isolation. Increment60 adds the missing status field in
development source and a staged-only metadata preflight, not a site migration or
physical schema guarantee. Increment61 adds an internal exact-original matched-pair
diagnostic adapter with separate transaction ownership, not a live caller or
provider registration. Increment62 adds source WRITE/related READ/create-ACL
checks and fresh owned source comparisons around diagnostic insertion, not
atomic locking across hooks or rollback of possible event writes. Increment63
bounds/rechecks individual row/metadata waits only in the optional concrete Unix
provider, not all factories or complete transaction deadlines. Increment64 detects
observed diagnostic database-owner/raw-handle drift at explicit boundaries, not
same-handle commits or complete transaction isolation. Increment65 extends the
selected received-step guard to four existing-XML APIs and preserves local review
through their broad public wrappers, not all local writers or worker lifecycle.
Increment66 unifies fourteen guarded existing-XML rejection-write blocks with
exact UUID commit policy, not successful-response writer isolation. Increment67
adds selected existing-XML reported/PIH/logging boundaries and shared writes, not
atomic transactions, protected custody or complete worker lifecycle. Next complete
source-neutral parent/race/provenance, log read/export/retention and whole-worker integration for caller-owned event logging only
with original receipt custody, schema review, caller exception boundaries and intentional rejection/parent lifecycle
together, continue lost/late/unbound and partial-write policy, and audit source/namespace/key/
lookup custody and transport-source-epoch/response evidence before
wiring durable receipt storage/review holds; remove legacy partial/parent commits before artifact
work; cover concurrent source changes and the remaining writers; establish
audited server-owned site/namespace/
connection and committed-revision provider provenance with historical epoch and authentic
receipt/crypto/QR validation and protect the remaining writers before adoption,
then installed lifecycle/physical-file
rollback and concurrent source changes; keep source
recovery/mixed-phase bridge and server-owned site/namespace/chain/lookup/connection
provenance and authentic capture/acceptance as gates before raw export or
settlement adoption. Verify
timezone/settings snapshots for new issuance separately. Neither increment 30
nor 31/32/33/34/35/36/37/38/39/40/41/42/43/44/45/46/47/48/49/50/51/52/53/54/55/56/57 consolidates advance amounts/GL or cryptographic digests.

All implementation/rehearsal below remains OFFLINE and in development. No live
provider/site binding, dummy Company on a working bench, authority request or
installed-source/config/schema change is authorized. Follow the completion-first
fictional-Company then gradual-pilot order in [SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).

Bind the new ephemeral material snapshot to verified transactional source/settings
provenance and a durable credential epoch, then adopt it in preparation/request
services. Resolve certificate issuance/rotation field conflicts before deployment.
Use the increment 18 separation evidence and staged storage proposal to preserve
active Production material during onboarding/renewal; implement explicit bundle
provenance and redacted operator boundaries before adding runtime selection.
The increment 19 encrypted store, increment 20 permissioned metadata service,
increment 21 CSR-bound observation set, increment 22 supplied-observation archive,
increment 23 permissioned archive metadata selection, increment 24 capture scaffold,
increment 25 opt-in HTTPS adapter and increment 26 permissioned saved-source
capture are staging/diagnostics only. Provide protected key custody and audited
tenant/namespace/owned-connection acquisition. Rehearse the new guarded source
boundary with installed v15/v16 schemas/permissions and the opt-in HTTPS adapter;
rehearse actual TLS, supported dependency matrices and restored Frappe integration.
The increment 28 local receipt recovery primitive now has an internal permissioned
saved-source boundary in increment 29, but still needs audited tenant/key/owned
connection provenance and durable custody before integration. It cannot
recover a response lost with process memory; implement lost/late-response policy.
Implement trusted transport attestation and verify source/remote-flow evidence
and CSR-to-issuance provenance before controlled epoch activation or migration
of legacy fields.
Resolve foreground unique-ID/gPOS policy parity and transactional worker/retry
coordination; design an explicit ICV continuity mapping using the increment 6 audit.
Use the follow-up [retry identity evidence](RETRY_IDENTITY.md) to introduce a
durable issuance artifact contract before changing UUID or counter allocation.
Bind the pure endpoint/response/returned-XML assessment to verified receipt capture
and artifact integrity; bind the isolated repository to an approved Frappe storage
service and implement cross-attempt policy, chain locking and durable outbox/leases;
extend observed certificate identity with verified credential provenance and
wider counter/log history. Rehearse on restored sites before proposing
tenant reconciliation or changes to issuance/replay.
Prepare a separately
pinned v16 bench and golden XML fixtures before consolidating cryptography or
advance-payment calculations. Obtain a suitable off-host backup destination and
choose the pilot/rollout window before any production deployment.
