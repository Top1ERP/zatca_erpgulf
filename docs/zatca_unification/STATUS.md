# Implementation status — 2026-10-15

## Scope delivered in this increment

Safety preparation and forty-eight bounded increments (Compliance outcomes, dedicated
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
and an explicit pinned Unix local primary receipt connection provider)
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

| Suite | Scope |
| --- | --- |
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
Next audit provisioning/key custody and retained-receipt durability/exact
transport-source-epoch binding before
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
nor 31/32/33/34/35/36/37/38/39/40/41/42/43/44/45/46/47/48 consolidates advance amounts/GL or cryptographic digests.

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
