# Committed native collection requests and PREPARED discovery

Workstream2 development,2026-11-21. No installed schema/site, live source,
worker/service or authority API was changed. Default activation gates remain.
This extends the existing Submission Intent store/worker; no parallel receipt,
invoice-number allocator, financial algorithm or new public RPC was introduced.

## Mixed draft and submitted batches

Previously submitted native collection entries entered the owned dispatcher
inline. After a prior draft appended ERP writes/callbacks, the next submitted
invoice could fail the clean owned-worker admission check. Manual Sales/POS and
shared scheduled submitted collections now stage a protected request in their
existing transaction and return `DEFERRED / accepted=False`. They neither commit
foreign ERP writes nor invoke generation/transport. Drafts retain their existing
v1 submit handoff and savepoint isolation. Unmarked legacy callbacks are unchanged.

Only successful ERP before-commit finalization makes a new collection request
READY; its fixed queue entry still receives only a record ID after commit.
Rollback removes the staged request and invalidates retained closures. Fatal
registration/finalization errors escape the collector rather than being swallowed
and followed by another commit. A queue exception after actual commit preserves
READY for the existing recovery service. DEFERRED is a local request result,
not invoice reporting/clearance acceptance.

## Separate immutable command domain, shared service

Original v1 submit headers/payloads are unchanged. Collection headers add exactly
`request_kind=collection-v1`, `expected_issuance_id` and `active_key`, authenticated
in the separate `collection-intent` AEAD domain. The source key is command-specific;
the nullable unique active key binds actor, source, Company, chain, operation,
fiscal observation and expected version. The worker authenticates corresponding
physical index fields as well as the immutable header. Source READ+WRITE,
Company/selected-owner READ, account enablement and site/physical DB pinning apply.

The existing readonly DocType adds nullable Data fields `active_key` (unique),
`expected_issuance_id` (indexed) and `operation`. No Link rename can rewrite them.
These are source declarations requiring a separately authorized installed schema
rehearsal/migration; no automatic repair/migration runs here. Old v1 row values
stay NULL, with no cipher/header backfill.

A single INSERT/no-op duplicate update arbitrates the active slot under current
engine uniqueness, including an older RR snapshot. It never overwrites another
header, actor or state, and does not first lock an absent index gap. A committed
READY/WAITING command can be reused. RUNNING/REVIEW do not imply resend authority.
COMPLETE releases only its collection slot; its original record remains retained.
An explicit manual action can create a new command after a pre-generation failure
only while current native custody is absent, untouched PREPARED or accepted.
Rejected/uncertain/in-flight native custody blocks ordinary registration. No old
command is silently rearmed. Existing expected versions remain pinned through the
same native provider, source checks, reservation and receipt verification.

## Age-independent Background discovery

The internal recovery cron also discovers authenticated native PREPARED originals
without an invoice creation cutoff. Only untouched PREPARED rows with no active
attempt are candidates. Company selection uses the existing phase/method alias
readers, with normal READ and a bound of1024 Companies. Batches-only companies
are excluded before candidate pagination. At most100 records/16MiB original
request bytes are examined. Existing active scheduled commands for that actor/
version, including review holds, are excluded. No legacy artifact is imported.

This service explicitly acquires a clean scheduler transaction, prepares fixed
scheduled requests, and commits only that acquired transaction. Before commit is
attempted it may roll back its own staging on failure; after a commit attempt it
never compensates an unknown acknowledgment. Its error does not falsely assert
that such a commit succeeded. Scheduler identity is the actual authorized actor,
not an impersonation of the invoice creator. The normal worker repeats account,
source, expected version and current Background/window policy checks.

This adopts the existing Background schedule policy. It does not turn Batches
into automatic delivery, rewrite issue times or complete Standard/non-Background
crash recovery. Entry/submit/manual Standard behavior remains as documented in
[NATIVE_PROVIDER.md](NATIVE_PROVIDER.md). Native unknown/rejected states stay out.

## Actual framework proxy identity

Inspection of the local Frappe source showed `frappe.db` is a LocalProxy while
`frappe.local.db` holds its target. Earlier direct test doubles hid an incorrect
identity comparison in borrowed parent/savepoint guards. `current_database` now
unwraps Werkzeug LocalProxy and compares its actual local target; the proxy's
stable identity cannot pin a replaced connection. Parent binding, native draft
isolation and trusted queue actor restoration share this helper. Tests exercise
the actual proxy class on private SQL and verify full draft and queue paths.
This remains source/fixture evidence, not installed ERP15/16 acceptance.

## Qualification and remaining gates

Private SQL covers actual manual mixed draft/submitted callers, all owner forms,
Sales/POS, current expected originals, exact-byte reuse, coalescing behind an old
RR view on a second physical connection, explicit pre-generation manual recovery,
unknown-delivery holds, queue loss, next-window waiting, index tampering,
LocalProxy and artifact creation metadata set to2024. ERP submit/accounting, canonical
financial metadata/signing and HTTP remain explicit doubles. No financial
reference or original240 comparison91/117/32 changed.

Still open in workstream2: started/uncertain intent resolution, explicit unchanged
retry/corrected-clock operator adoption, complete Standard/non-Background recovery,
source cancellation/deletion/rename, full legacy history/drain and activation,
frozen master/print/File compatibility, whole canonical mixed-batch runtime and
installed accounting/filesystem qualification. Workstream2 is not closed; no
workstream3 transition, live installation or pilot is authorized by this bundle.
