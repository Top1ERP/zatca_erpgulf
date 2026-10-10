# ZATCA path unification: ERPNext 15 and 16

Implementation plan opened 2026-10-09. Status and executed tests are recorded in
[STATUS.md](STATUS.md). This is incremental application development, not approval
to deploy across tenants, upgrade ERPNext, submit production invoices, or delete
legacy accounting records. The older `docs/zatca_advance_redesign/` records remain
historical evidence; their deployment claims do not apply to this new branch.

The user explicitly requires prior notice before modifying the live application.
Before any installed-source edit, deployment, migration, runtime configuration
change or bench/worker restart, explain the scope and operational impact to the
user. Development-branch continuation is not live deployment authority; the
pilot/rollout decision and remaining acceptance gates are still required.

## Target design

Retain the public button and hook entry points while gradually replacing their
duplicated internals with a shared, tested pipeline:

`ERP adapter -> effective settings -> immutable invoice snapshot -> amounts/tax -> XML -> signing/QR -> explicit output mode`

Adapters handle ERPNext version and document differences. The core must not read
the database, commit transactions, attach files, or send HTTP requests. Services
own those side effects explicitly. English docstrings explain invariants and
regulatory rule references; UI messages use translation keys with Arabic entries.

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
- Roll out first to an explicitly chosen pilot after backup and restore review,
  then expand with monitoring. A code rollback must preserve issued artifacts
  and reconcile current counters; restoring an old database blindly is unsafe.

## Minimum acceptance matrix

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

No successful mock test substitutes for the v16 bench, SDK checks, or a controlled
remote Compliance acceptance test. External tests must use the intended
environment and credential purpose; never send a diagnostic sample to a live
reporting/clearance endpoint.
