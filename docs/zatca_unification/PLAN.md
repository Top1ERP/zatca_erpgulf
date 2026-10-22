# ZATCA path unification: ERPNext 15 and 16

Implementation plan opened 2026-10-09. Status and executed tests are recorded in
[STATUS.md](STATUS.md). This is incremental application development, not approval
to deploy across tenants, upgrade ERPNext, submit production invoices, or delete
legacy accounting records. The older `docs/zatca_advance_redesign/` records remain
historical evidence; their deployment claims do not apply to this new branch.

The current user restriction (2026-10-10) forbids applying results to ANY working
or production environment and forbids agent-initiated tax-authority requests,
including Sandbox/Simulation Compliance. Continue offline development only.
No installed-source/configuration/schema write, Company creation on a working
site, migration or Bench/worker restart is authorized by "continue" or prior notice.
The mandatory order is completed development, then separately approved isolated
fictional-Company rehearsal, then explicitly approved gradual active-client
pilot/rollout. API sending needs separate explicit authority changing the ban.
See [SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md); it supersedes any older
operational request or less restrictive deployment wording in historical records.

## Target design

Retain the public button and hook entry points while gradually replacing their
duplicated internals with a shared, tested pipeline:

`ERP adapter -> effective settings -> immutable invoice snapshot -> amounts/tax -> XML -> signing/QR -> explicit output mode`

Adapters handle ERPNext version and document differences. The core must not read
the database, commit transactions, attach files, or send HTTP requests. Services
own those side effects explicitly. English docstrings explain invariants and
regulatory rule references; UI messages use translation keys with Arabic entries.

Operation messaging policy: collect related outcomes into one comprehensive
user-facing summary, translate only app-owned display labels for the user's UI
language, and keep generated diagnostic storage English. Original authority
payloads/codes/identifiers remain unchanged. Increment 68 adopts this policy for
the two Company batch checks and retained-event labels. Increment 69 adds the
Company single-check wrapper and Sales/POS Debug menus with a shared presenter.
Ordinary invoice/POS submission, legacy direct calls, CSR/CSID and background
boundaries still require staged adoption; original diagnostic details remain
unchanged, even when a legacy exception is localized. Debug POS/Background's
existing undefined bypass selector remains a generation gate, not a message fix.
See [MESSAGE_PRESENTATION.md](MESSAGE_PRESENTATION.md).

| Mode | Intended output | Side-effect boundary to enforce |
| --- | --- | --- |
| Phase 1 | Local QR for supported Sales/POS documents | No Phase-2 API or production hash-chain mutation |
| Debug XML | Clearly labelled diagnostic artifact | No submission, status change, or live UUID/ICV/PIH allocation |
| Local onboarding preview | Six synthetic XML/signature/QR samples | No HTTP request or customer/invoice creation |
| Compliance | Selected real-document snapshot or six synthetic samples | Compliance endpoint and Compliance CSID of the selected environment; no live invoice status/chain mutation |
| Phase 2 simplified | Signed issued artifact and reporting workflow | Durable issuance identity, authoritative stored XML/QR, controlled retries |
| Phase 2 standard | Clearance workflow and returned cleared artifact | Do not present a debug/local artifact as a cleared invoice |

These are target contracts, not claims that all existing paths already satisfy
them. Compliance is an API purpose, not a synonym for Sandbox. Environment and
credential purpose must be resolved together; local success must never fabricate
remote compliance completion or replace ZATCA's final-CSID decision.

## Migration choice

| Approach | Benefit | Risk / decision |
| --- | --- | --- |
| Keep all parallel XML/signing implementations | Small immediate patches | Divergent fixes and settings; retain only as temporary adapters |
| Replace everything in one release | One final implementation immediately | Unacceptable regression radius across tenants and tax/accounting flows |
| Shared pure core with thin, version-aware adapters | Reusable contracts and staged comparisons | Chosen; retire a legacy path only after its replacement passes the same fixtures |

Do not create permanent v15 and v16 forks of the tax/signing logic. Use capability
checks in a small compatibility layer, not scattered version-string conditions.
Reuse `ksa_compliance/field_compat.py`, `zatca_runtime.py`, and the existing tax
adapters after testing their fallback behavior; do not introduce competing
resolvers. Existing accepted signed XML is immutable evidence, not a template to
be reserialized during cleanup.

## Ordered implementation gates

### 0. Recovery and source-control safety

- Inventory all affected sites and dependent apps; preserve dirty work if found.
- Back up SQL, public/private files, original encryption configuration, app Git
  history/source, and runtime versions before implementation.
- Verify checksums, archive integrity, and an isolated sample restore. Distinguish
  SQL/file recovery from a complete Frappe application restore.
- Compare actual Git trees before merging differently named/cherry-picked
  histories. Archive recoverable references; do not delete remote branches or
  force-push as a cleanup shortcut.
- Develop in an independent worktree. Keep data, certificates, and backups out
  of GitHub. Arrange an authorized off-host encrypted copy before rollout.

### 1. Contracts, outcome handling, and characterization

- **First increment:** reject ambiguous Compliance results, transport failures,
  and malformed HTTP 406 responses in both all-type buttons. Preserve explicit
  successful validation and distinguish previous completion.
- Inventory public Sales Invoice, POS Invoice, Sales Invoice with `is_pos`,
  single/all Compliance, synthetic onboarding, debug, and scheduler entry points.
- Add scrubbed golden fixtures and side-effect assertions for each route before
  moving signing or accounting code. Never commit a customer's private key.
- Preserve warnings and request IDs in diagnostics. Separate local preparation,
  remote validation, previous completion, rejection, and unknown transport state.

### 2. Settings, fields, and credential context

- Increment 19 implements isolated encrypted version staging, not active selection
  or field migration. See [CREDENTIAL_BUNDLE_STORAGE.md](CREDENTIAL_BUNDLE_STORAGE.md).
  Caller-supplied AES-GCM keys and explicit SQL contracts have private rehearsals;
  future protected key custody, tenant permissions, transactional source/remote flow
  evidence and controlled activation must be verified before adoption.
- Increment 18 adds independent legacy purpose/field observations and a versioned
  bundle migration proposal in [CREDENTIAL_LIFECYCLE.md](CREDENTIAL_LIFECYCLE.md).
  It characterizes shared key/certificate overwrites without changing writers or
  selecting credentials. Secure storage, atomic activation, saved provenance,
  secret-bearing response redaction and restored-site migration remain gates.
- Increment 17 adds a locally bound ephemeral signing/authentication material
  snapshot and internal read-only adapter, reusing saved-owner and alias policy.
  See [CREDENTIAL_SNAPSHOT.md](CREDENTIAL_SNAPSHOT.md). Exact certificate/key/token
  binding and explicit UTC validity are implemented; cross-row atomic provenance,
  durable epoch, taxpayer/environment/trust verification and runtime adoption
  remain gates. No existing path uses the new snapshot automatically.
- Build an effective-settings registry with field, scope, default, precedence,
  legacy alias, consumer, and migration policy. Distinguish missing, blank, and
  explicit zero; do not replace a valid zero with a legacy true value.
- Cover phase, environment, company/issuing unit/POS machine, linked-company
  credentials, submission policy, B2C/B2B, branch identity/address, tax source,
  discounts, advance-payment markers, printing, and background windows.
- Resolve endpoint + credential purpose + credential version as one context.
  Check taxpayer/issuing-unit identity, expiry, and key/certificate pairing.
  Do not overwrite production credentials while preparing new onboarding ones.
- Audit `custom_certificate` versus `custom_certficate`, aliased B2C/advance
  flags, misleading background-display switches, and ineffective discount flags.
- Document each fallback; report conflicting settings instead of silently
  selecting an unrelated company/certificate. Preserve user-owned custom fields.

### 3. Amounts, advance invoices, and ERP adapters

- Normalize document data once using Decimal amounts and explicit currency
  precision. Keep exchange-rate precision separate from two-decimal amounts.
- Reconcile row discounts, document discounts, inclusive/exclusive tax, rounding,
  charges, and grand-total discounts against ERPNext's actual accounting totals.
- Support advance invoice type 386 and final-invoice deductions with original
  issue identity/time, reference UUID/number, and tax-category/rate snapshots.
- Do not infer a tax rate from rounded tax/taxable values: 0.13 / 0.87 is not
  evidence of a 14.94% tax rate. Group advance references by actual category/rate.
- Test partial/multiple advances, final invoices, cancellations, partial/cumulative
  returns, concurrent allocation, and currency/rounding residuals. VAT report,
  XML prepaid/reference amounts, GL, and outstanding receivables must reconcile.
- Resolve the reviewed risks in rounded allocation, forced Paid status, tax
  account filtering, and duplicate VAT reporting with failing tests first.
- Missing required advance schema must fail clearly; it must not silently
  produce zero deductions. Preserve legacy records until migration is approved.

### 4. XML, cryptography, and QR core

- Increment 67 extends [existing-XML reported-label writer boundaries](EXISTING_XML_REPORTED_WRITES.md).
  Eight duplicate reported-write blocks share one named adapter, while pinned-owner
  PIH/notification, response persistence, lazy success-log payload and legacy trailing
  error logging run through received-step guards. Original order/commits/409 labels
  remain; known faults add no generic post-fault persistence, not atomicity or custody.
  Other generated writers, whole-worker lifecycle and scoped log access remain gates.
- Increment 66 unifies fourteen [existing-XML rejection persistence blocks](REJECTION_PERSISTENCE.md)
  behind one named writer through the received-step guard. It preserves explicit
  UUID commit/assignment policy, including Sales simplified 404 versus POS 404.
  Known local load/text/save/commit failures cannot add generic error persistence;
  prior UUID/hook/parent commits are not undone. Success/remaining-writer faults,
  exact custody, whole-worker lifecycle and scoped log access remain gates.
- Increment 65 extends [received local-step review](RESPONSE_PROCESSING.md) to the
  four existing-XML Sales/POS Reporting APIs and preserves that signal through
  their broad public wrappers. Hide/event/presentation failures no longer add
  generic error persistence; POS raw text and Sales formatting remain unchanged.
  Normal rejection/duplicate/owner/commit policy and original artifacts stay as-is.
  Selected persistence/PIH/remaining-writer faults, worker lifecycle, exact custody
  and scoped log read/export/retention remain unfinished; no live wiring/deployment.
- Increment 64 pins the caller's diagnostic database owner/raw identity before
  metadata loading and rechecks it around source callbacks and insertion. It
  resolves a context-local proxy to its current owner; observed drift/unavailable
  contexts fail with translated review and no parent cleanup/reconnect. This is
  boundary detection, not transaction identity, hook isolation or runtime adoption.
  Same-handle commits, ABA changes, source-neutral worker lifecycle and scoped
  log read/export/retention remain gates. See [EVENT_LOG_TRANSACTION.md](EVENT_LOG_TRANSACTION.md).
- Increment 63 adds [owned-session bounded lock waits](PRIMARY_RECEIPT_PROVIDER.md)
  to the optional Unix provider only: fixed SESSION row/metadata waits, verified
  before registration locks and every cursor/commit, rejecting drift without
  repair/reconnect or GLOBAL changes. Actual private source/registration locks
  demonstrate failure/owned cleanup without changing parent work or originals.
  Source-neutral diagnostic transaction isolation, arbitrary factory policy and
  Company/source-scoped log read/export/retention remain unfinished gates.
- Increment 62 adds [saved-source diagnostic access and fresh drift checks](EVENT_LOG_TRANSACTION.md).
  Source WRITE/related READ plus Event Log CREATE precede keys/owned SQL. Exact
  request/envelope binding and fresh source-only owned reads bracket insertion;
  late changes deny metadata without claiming rollback of possible hook writes.
  Public failure is a static translated RuntimeError review, not a generic invoice
  rejection. No endpoint/worker/HTTP caller is activated. Source-neutral parent,
  bounded lock waits, full race/ACL/provenance and installed lifecycle remain gates.
- Increment 61 adds an [original-pair-bound diagnostic bridge](EVENT_LOG_TRANSACTION.md).
  It authenticates the exact original envelope, invokes read-only matching-pair
  inspection and closes owned SQL before caller-owned diagnostic hooks. Only
  archived candidate/event data is used; missing/partial/conflict/uncertain or
  undecodable originals remain review-only. No pair persistence/repair/reseal,
  replay/acceptance authority or live invoice wiring is added. Finish authorized
  source/ACL/race/provenance and whole-worker/parent integration before adoption.
- Increment 60 adds [diagnostic source schema and staged preflight](EVENT_LOG_TRANSACTION.md).
  A read-only Diagnostic Status Data field is defined in DEVELOPMENT DocType
  source with Arabic labels; no site migration/backfill/collision repair occurs.
  Staging checks ordinary table/unique fields/types/storage/widths before insert,
  failing with static translated review. The legacy wrapper is not gated/rewired.
  Physical schema, custom-field/Property Setter collisions and exact receipt/
  parent lifecycle remain adoption gates; no submission staging caller is added.
- Increment 59 adds [explicit diagnostic event staging](EVENT_LOG_TRANSACTION.md):
  normal permissions, no explicit commit/rollback/fallback/retry, same-object
  exception propagation and a closed INSERT_RETURNED result, not durability or
  acceptance. The legacy wrapper keeps its transaction/fallback/None contract;
  no submission caller is switched. Source schema status-field coverage and
  actual hook/parent/custody lifecycle remain gates before staging adoption.
- Increment 58 adds [selected rejection-persistence isolation](REJECTION_PERSISTENCE.md)
  in the four primary Sales/POS APIs. Three named adapters replace twelve
  repeated blocks, preserving normal rejection/UUID/commit policy. Known local
  loading/writing/text/commit faults cannot add generic failure writes or retry;
  previous partial commits are not undone. Next design the event logger's honest
  caller-owned result/transaction contract together with exact durable custody,
  intentional rejection and parent lifecycle, not blanket commit deletion.
- Increment 57 adds [received presentation/logging-step isolation](RESPONSE_PROCESSING.md)
  to the four primary Sales/POS APIs for ALL statuses. Formatting (including lazy
  text), event log and hide callbacks use the existing static translated local
  review signal on formerly caught errors, never generic post-fault writes or
  retry. Deliberate HTTP-rejection throws/normal writer policy remain unchanged.
  Next audit rejection-persistence/caller boundaries plus the actual event logger's
  swallowed failures/own commits, and plan intentional
  rejection mapping, durable custody and parent transaction lifecycle together;
  no working source or authority action is authorized by this development change.
- Increment 56 adds [writer/late-response evidence and pure outcome review](PRIMARY_WRITERS_AND_REVIEW.md).
  Current mutable runtime writers are distinct from staged single/pair stores.
  Actual independent private writers reproduce partial windows; original sealed
  sequence-2 responses cannot be rewritten after UNKNOWN, and independent late
  sequence-3 observations are not the strict START-only pair contract. Review
  binds exact protected input, returns states only and never authorizes actions.
  Next isolate local rejection/error-status logging failures in the four primary
  source APIs before broader parent-commit/custody integration; no runtime wiring.
- Increment 55 adds [permissioned local primary pair access](PRIMARY_RECONCILIATION_ACCESS.md).
  Shared saved invoice WRITE/related READ and exact original request/envelope
  declarations precede scoped keys/owned SQL. Source locks and final ACL checks
  bound metadata-only inspection/LOCAL persistence; partial/conflict policy stays
  review-only. Full seal fingerprinting does not change XML signatures. No
  runtime caller or provider/key installation; independent provenance and legacy
  separate-writer/lost-response review remain gates before integration.
- Increment 54 adds [exact local primary receipt pair reconciliation](PRIMARY_RECEIPT_RECONCILIATION.md).
  Read-only inspection or explicit LOCAL persistence requires the original seal,
  exact existing hold/request binding and literal source guards. Both absent
  response parts may be stored atomically; partial/different pairs are REVIEW
  ONLY. Uncertainty retains original input, never invokes transport/reseal or
  releases a hold. Permissioned paired access and authentic provenance remain
  gates; no runtime caller or schema is installed.
- Increment 53 adds a [saved-source local primary capture access boundary](PRIMARY_CAPTURE_ACCESS.md).
  Invoice WRITE/related READ and exact request/start/key binding precede resources
  and guarded owned SQL. EVERY returned core result goes to explicit trusted
  server custody before final ACL disclosure; output is metadata only. Failed or
  interrupted handoff transfers protected recovery, not an automatic retry.
  ACK is not durable proof. Paired reconciliation, pre-result observer custody,
  authentic source/epoch/provider/transport and runtime activation remain gates.
- Increment 52 adds an [auth-free exact primary observation coordinator](PRIMARY_CAPTURE.md).
  Three owned transactions bind deterministic request bytes to strict start/hold,
  close preflight before ONE synthetic observer, then store original encrypted
  custody and HTTP event atomically. No actual HTTP/auth adapter or runtime caller.
  Unknown results retain exact protected material without retry/reseal/release.
- Increment 51 adds an [atomic primary start/logical-invoice hold](PRIMARY_ATTEMPT_HOLD.md).
  One caller transaction appends an explicit first event and strictly reserves
  the same logical source across changed candidate/version/chain/environment.
  Existing/uncertain reservations never authorize reuse; no status/clock-based
  release. Test-only SQL, no runtime sender/permissioned coordinator activation.
- Increment 50 adds [permissioned encrypted local receipt custody](PRIMARY_RECEIPT_CUSTODY_ACCESS.md).
  Shared source/owned-acquisition helpers require invoice WRITE/related READ and
  exact receipt/key declarations before scoped keys/SQL. Stage retains the same
  envelope across uncertain commits; retrieval returns ciphertext only after
  rollback/close and final ACL. No runtime capture/hold/provider activation.
- Increment 49 adds [encrypted local retained-receipt custody](PRIMARY_RECEIPT_CUSTODY.md).
  Exact bounded codec/dedicated AES-GCM and immutable caller-transaction SQL keep
  one envelope for an existing attempt; identical LOCAL redelivery only. No
  journal append, HTTP, owned coordinator or permissioned retrieval is activated.
  Committed ciphertext survives owned-database crash tests; responses lost before
  the first durable commit still need a no-replay review/lost-response policy.
- Increment 48 adds an [explicit pinned Unix receipt connection provider](PRIMARY_RECEIPT_PROVIDER.md).
  Scope/socket checks precede typed local credentials; fresh direct SQL checks
  kernel peer, target/session and locked site/namespace marker before handoff,
  cursors and commit. No reconnect/fallback/discovery/runtime provisioning.
  Synthetic composition only: provisioning/custody/receipt authenticity, durable
  holds and exact transport-source-epoch binding remain gates before activation.
- Increment 47 adds [saved-source access to local primary receipt persistence](PRIMARY_RECEIPT_ACCESS.md).
  Shared archive selection retains existing metadata behavior; private receipt
  access requires invoice WRITE/related READ and exact attempt/event/predecessor
  binding, with same-transaction source locks and post-close rechecks. No runtime
  provider/scheduler activation, authentic epoch/origin claim or durable retry hold.
- Increment 46 adds [exact local primary receipt persistence/redelivery](PRIMARY_RECEIPT_PERSISTENCE.md).
  Existing journal/codecs/owned transactions preserve one exact retained response,
  including uncertain commits, without start creation, new HTTP or replay rights.
  It is not wired to primary APIs/scheduler; permissioned saved-source/attempt/
  epoch/provider binding, owned acquisition and durable review holds remain gates.
- Increment 45 adds [primary post-response local-error review](RESPONSE_PROCESSING.md).
  Previously caught local failures in existing response branches no longer run
  generic receipt overwrite/503 writes/commits. Static Arabic/English failure
  is not acceptance or a success return; no in-call retry. Exact durable receipt/
  review holds, partial parent commits and other adapters remain release gates.
- Increment 44 adds [scoped primary QR ownership/pre-request rejection](PRIMARY_QR_OWNERSHIP.md).
  Same-invoice bounded preservation/review replaces the primary attach global
  URL check. All four primary adapters reject existing schema/link issues before
  request/error persistence and POS XML writes; valid batch deferral remains.
  No authenticated source/ACL/reservation claim; receipt-aware post-response
  error handling, concurrent changes and remaining writers are still gates.
- Increment 43 removes [primary Sales/POS QR attachment DDL/invoice events](PRIMARY_QR_TRANSACTION.md).
  QR-link-only staging preserves status/UUID/business/modified fields. Legacy
  global URL reuse and caller commits/error downgrades are explicitly unresolved;
  pre-request setup checks and receipt-aware caller handling remain release gates.
  No authenticated source/recovery or working-system change is enabled.
- Increment 42 replaces [the automatic Phase-2 completion hook](PHASE2_ARTIFACT_PRESERVATION.md)
  with non-destructive metadata preservation/review. No response-based repair,
  filename cleanup, link/status change or parent transaction ownership remains
  there. Missing completion stays gated; primary attach helpers/extractor/schema/
  global URL and caller commits still need integration. Normal adapters unchanged.
- Increment 41 adds [permissioned QR source metadata/shared archive access](QR_SOURCE_ACCESS.md).
  Saved ACL/owner/source/route and exact SQL/journal observations are checked,
  without raw export or recovery activation. Advance metadata uses the same
  engine with unchanged marker/type restrictions; settlement selection/amounts
  remain untouched. Audited provider/epoch/authentic-origin/crypto gates remain.
- Increment 40 adds [exact archived-attempt QR source observations](QR_SOURCE_SELECTION.md).
  Reporting request versus clearance-returned bytes are bound to the exact
  declared journal/context/identity with lexical clock and strict bounded QR
  extraction. This is not authenticated provenance or permission to recover.
  Bind a saved-source/owner/epoch/committed-record provider and crypto validation
  before mutation; audited Phase-2 prefix deletion/reuse remains unsafe/unmodified.
- Increment 39 adds [non-destructive explicit recovery preservation/review](QR_RECOVERY_PRESERVATION.md).
  No filename/latest reconstruction, content IO, automatic re-link or commits at
  the button. Missing originals require review; trusted original-artifact recovery
  still needs implementation before re-enabling mutations. Ordinary generation
  and accounting/advance eligibility are unchanged. Audit other writers next.
- Increment 38 adds [saved-row access for explicit QR recovery](QR_REGENERATION_ACCESS.md):
  Invoice/Company/File ACL and exact ownership, bounded projection and POST-only
  mutation. Access is not provenance; increment 39 separately removes heuristic
  repair and helper commits. Installed source/ACL/File races remain gates.
- Increment 37 extends [non-destructive QR preservation to the advance print hook](ADVANCE_QR_PRESERVATION.md).
  No forced replacement or implicit final-invoice attachment cleanup; first
  generation and accounting selection/amounts remain unchanged. Explicit
  regeneration authorization/selection/commits and installed lifecycle remain gates.
- Increment 36 adds [non-destructive ordinary QR attachment preservation](QR_ATTACHMENT_PRESERVATION.md)
  for Sales/POS, replacing newest-file cleanup/global URL fallback with current
  same-invoice link preservation or explicit review. The advance print cleanup/
  force gate is addressed separately in increment 37; regeneration access/
  selection/commits and other writers remain gates.
- Increment 35 introduces [caller-owned Phase-1 QR metadata staging](PHASE1_QR_TRANSACTION.md):
  no recursive invoice save, explicit commit or schema creation in the ordinary
  generator. Next bound attachment selection/deletion and caller commit policy;
  actual File rollback, hook customizations and installed v15/v16 remain gates.
- Increment 34 adds [five-tag QR/missing-original review policy](ADVANCE_SOURCE_GAP.md)
  without changing accounting eligibility or inventing historical references.
  Audit ordinary QR attachment cleanup, explicit commit/re-entrant document saves
  and transaction ownership next. Mixed-phase bridging and actual source recovery
  still require permissioned provenance, official rule/SDK and accounting evidence.
- Increment 33 adds [permissioned metadata-only advance archive inspection](ADVANCE_SOURCE_ACCESS.md)
  with saved source/owner ACL, owned source/journal row locks and cleanup. Audited
  provider provenance, authenticated capture, missing-original policy and backend
  source export remain gates; it is not a builder replacement or acceptance grant.
- Increment 32 adds [exact archived-attempt advance source choice](ADVANCE_SOURCE_SELECTION.md):
  Reporting request versus Clearance returned bytes, pinned context/revision and
  original clock consistency. This is a pure observation, not verified source
  selection. Add a permissioned saved-source/committed-record storage boundary
  and authenticated capture evidence before adopting it in runtime settlement.
- Increment 31 adds [read-only original advance reference observations](ADVANCE_REFERENCE.md)
  and characterizes three current assembly paths. Implement permissioned immutable
  original-artifact/acceptance selection and Phase-1/legacy missing-source policy
  before adopting it. Preserve original date/time/UUID; do not apply today's
  timezone to historical references or silently invent midnight. This is not
  advance amount/GL consolidation or cryptographic proof.
- Increment 30 adds the [explicit shared issue-time contract](ISSUE_TIMESTAMP.md)
  for Sales/POS XML, ordinary/advance Phase-1 QR, Phase-2 Tag 3 and synthetic
  samples, without changing signatures or amount formulas. Capture verified
  timezone/settings epochs and audit advance settlement reference time/UUID
  bindings before extending it. Existing Frappe timezone defaults and offsetless
  legacy XML are characterized, not authoritative historical timezone evidence.
- Consolidate XML assembly only after golden comparisons for each invoice type.
- Canonicalize/hash the exact intended bytes. Test namespace context, encoding
  declarations, signature transforms, certificate digest, SignedProperties
  digest, signature verification, and final QR values independently.
- Freeze signed bytes: no cosmetic XML/whitespace rewrite after hashing/signing.
- Separate Phase-1 QR payload from Phase-2 signing requirements. Use accepted
  returned artifacts where appropriate; never select a debug attachment as live
  output. Validate QR totals for advance/rounding cases against official examples
  and SDK results before deciding the canonical source field.
- Make both Create XML for Debug actions consume the same core without allocating
  live counters or committing invoice changes.

### 5. Orchestration, persistence, and retry safety

- Increment 28 adds explicit local receipt persistence recovery only: authenticate
  retained start/receipt, require the exact committed start ciphertext, and
  append the identical receipt in one owned transaction without HTTP or resealing.
  See [COMPLIANCE_RECEIPT_RECOVERY.md](COMPLIANCE_RECEIPT_RECOVERY.md). Increment 29
  adds a [permissioned internal saved-source boundary](COMPLIANCE_RECEIPT_RECOVERY_ACCESS.md),
  sharing capture's owner/ACL/revision policy. Audited tenant/key/owned-connection
  origin, durable retained-receipt custody, lost/late-response policy and
  cross-attempt coordination remain gates; no runtime adoption exists.
- Keep encrypted credential staging separate from the artifact journal. There is
  no active-pointer/dispatch API in increment 19, and exact version reads cannot
  choose latest or fall back across environment/purpose/owner. Approval of staging
  storage is not authorization to activate credentials, migrate or replay invoices.
- Pass the ephemeral credential snapshot through a future preparation/request
  service only after transactional provenance and epoch policy are verified.
  Do not serialize its secrets into the journal, a worker job, or diagnostics.
- Increment 16 adds exact-byte storage codecs and an explicit-connection MariaDB
  repository, rehearsed with real commits/concurrency/crash recovery on its own
  private server. See [JOURNAL_REPOSITORY.md](JOURNAL_REPOSITORY.md). No schema or
  service is installed in Frappe, and no tenant database is accessed. Production
  storage permissions/encryption, migration, outbox/leases and chain allocation
  remain gates; SQL serialization is not authorization to resend an invoice.
- Increment 15 implements the pure receipt/operation/returned-XML consistency
  assessment, not authoritative receipt capture or live acceptance writes. See
  [RESPONSE_ASSESSMENT.md](RESPONSE_ASSESSMENT.md). Genuine expected 200 is success
  and 202 success with warnings; malformed/wrong-invoice observations and generic
  409 cannot authorize acceptance. Metadata matching is not crypto/accounting proof.
- Pass compliance type explicitly instead of temporarily mutating Company.
- Ensure Compliance/Debug do not overwrite a real invoice's UUID or ICV fields.
- Use durable, auditable artifact state; serialize allocation within each issuing
  unit/environment and make accepted status/PIH updates idempotent.
- Define retry behavior for unknown transport outcome versus corrected rejected
  documents. Never issue a fresh identity casually on a network retry.
- Audit scheduler company isolation, submission windows, overdue backlog, POS
  identity regeneration, hooks, and duplicate concurrent requests.
- Remove transaction commits from document hooks through service boundaries,
  not by bypassing Frappe's transaction protections.

### 6. ERPNext 15/16 compatibility and release acceptance

- Pin exact Frappe/ERPNext and dependent-app revisions for two isolated benches.
  Do not upgrade the production bench to test compatibility.
- Use the guarded offline runner during development. A full fictional-Company
  application rehearsal starts only AFTER development completion and separate
  approval for an isolated bench. Do not substitute a working client's extra
  Company or enable real CSID/Compliance calls as a test shortcut.
- The current official v16 guide requires Python 3.14+ and Node.js 24+ and
  disallows commits in document hooks. Test transaction behavior, ordering,
  permissions, translations, navigation, and DocType extension integration.
  [Frappe migration guide](https://github.com/frappe/frappe/wiki/Migrating-to-version-16)
- Test legacy item-wise tax JSON, v16 child rows, and unsaved calculated rows,
  including genuine zero tax. Avoid unconditional 15% fallbacks.
  [ERPNext tax-data migration](https://github.com/frappe/erpnext/wiki/Item-Wise-Tax-Details:-JSON-%E2%86%92-Child-Table)
- Resolve dependency constraints against the pinned branches, especially
  cryptography/lxml/pikepdf and supported wheels. Do not claim support from a
  `requires-python` change or pure unit tests alone.
- Validate fresh installation and v15-to-v16 migration, preserved customizations,
  reports, hooks, Sales/POS accounting, and English/Arabic buttons.
- Use official XML/security specifications and pinned SDK fixtures as acceptance
  evidence. Community examples are supplementary, not authority to ignore a
  mandatory rule. Record each source/revision and rule ID with its test.
  [ZATCA XML standard](https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/20230519_ZATCA_Electronic_Invoice_XML_Implementation_Standard_%20vF.pdf)
- After completed development AND isolated fictional-Company acceptance, obtain
  explicit approval for a named active-client pilot after backup/restore review,
  then another gradual rollout decision. Current authority sending remains banned
  unless explicitly changed; deployment cannot activate a prohibited send.
  A code rollback must preserve issued artifacts
  and reconcile current counters; restoring an old database blindly is unsafe.

## Minimum acceptance matrix

The user decides whether to adopt ALL changes or cancel them only after finished
development and separately approved isolated fictional-client rehearsal. Preserve
the untouched working baseline and tested-commit evidence. Adoption is not an
implicit deployment, worker restart or authority-send authorization. See
[DUMMY_REHEARSAL_DECISION.md](DUMMY_REHEARSAL_DECISION.md).

| Dimension | Required cases |
| --- | --- |
| ERP/runtime | v15 and v16 pinned benches; fresh install and upgrade |
| Source | Sales Invoice; Sales Invoice `is_pos`; POS Invoice; synthetic samples |
| Phase/type | Phase 1/2; standard/simplified invoices, credit and debit notes |
| Purpose | Debug; local preview; single/all/synthetic compliance; clearance; reporting |
| Settings | Company/POS/linked-company credentials; aliases/zero/missing; both UI languages |
| Amounts | Discount models; inclusive/exclusive; tax categories; rounding; foreign currency |
| Advance | Type 386; partial/multiple allocations; returns; GL/outstanding/VAT reconciliation |
| Failure/retry | 400/401/403/406/500; timeout; invalid body; duplicate and concurrent requests |
| Invariants | No real invoice/chain mutation in tests; immutable accepted XML; no credential leaks |

No successful mock test substitutes for v16 application/SDK checks or genuine
remote acceptance evidence. Remote acceptance remains UNVERIFIED while the user
prohibits requests. Do not perform it now, label mocks as authority PASS, or use
pilot/deployment approval as API-send authorization. If the user later explicitly
changes the ban, a separate reviewed scope/environment/purpose gate is required.
