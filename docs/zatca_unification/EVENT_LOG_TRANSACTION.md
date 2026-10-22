# Explicit diagnostic event staging — increments 59–64

Development only, 2026-10-16. No tenant/site initialization, working application
change or authority request. This contract is not wired into invoice submission.

## Two explicit contracts

`stage_zatca_event` inserts a diagnostic event with `ignore_permissions=False`.
It calls neither commit nor rollback, does not retry or invoke a fallback logger,
and propagates insertion exceptions unchanged. Increment60 adds the read-only
metadata preflight described below; malformed/incompatible metadata produces a
static translated schema error BEFORE payload construction. Metadata acquisition
failures propagate unchanged. A caller using the received-response
step guard can convert the previously caught local error families into the
existing static translated review signal. Other failures remain unchanged.
Increment59 introduced no new UI, endpoint, translation text or permission
override. Increment60 adds only the metadata/error translations described below.

The closed `EventLogWriteResult.INSERT_RETURNED` result means ONLY that the
insert call returned. It is not None, a framework Document or a response/body/
identity-bearing object. It is not an acceptance/durability verdict, and cannot
certify that all fields were persisted. Do not treat its truthiness, the caller's
diagnostic Success label, HTTP status or framework return value as authority
acceptance. The result deliberately makes no committed/uncommitted assertion.

`log_zatca_event` remains the legacy compatibility wrapper: ignored permissions,
ambient commit, ordinary-exception fallback through `frappe.log_error`, and None
whether insertion succeeded or a failure was swallowed. The existing twelve
submission adapter families keep this contract. Shared payload construction and
insertion remove duplication WITHOUT globally removing commits or changing the
legacy fallback/error string. This refactor is not a privacy fix for that string.

Both contracts use the existing diagnostic normalizer and payload defaults.
Wrapped JSON is extracted, invalid UTF-8 bytes use replacement and dict/list
values may be serialized. Therefore this is NOT the exact-byte encrypted receipt
archive and cannot replace original request/response custody.

## Parent ownership and hooks

The new helper performs no transaction operation itself. In the ordinary insert
case, SQL stays pending until the explicit owner commits/rolls back. Insertion
can fail after writing; the caller must clean up its failed/pending transaction,
not assume no row was written. There is no helper-owned compensation or savepoint.

Framework Document insertion runs hooks. Local Frappe 15 source inspection shows
normal create permission checks and before/after-insert/post-save callbacks.
A third-party hook can commit, perform I/O or change parent work; this helper is
NOT a sandbox and cannot promise hook-free atomicity. Synthetic private SQL tests
explicitly demonstrate hook commit and commit-then-raise: event and unrelated
parent work survive rollback, even when staging itself never calls commit.
Installed v16/hooks/lifecycle remain separate acceptance gates.

Do not switch the primary APIs to staging without exact independent original
receipt retention and caller/worker/intentional-rejection lifecycle integration.
A later exception could otherwise roll back their only diagnostic response.
No active capture provider/key/connection registration, durable review hold,
automatic retry, acceptance classification or PIH/ICV/QR mutation is added here.

## Source schema gap, not a live schema diagnosis

At increment59, the repository Event Log DocType defined title/invoice_number/time/api_response;
its custom-field fixture added custom_uuid. Neither source defined the legacy
payload's status field. A source-only regression recorded this mismatch; no
tenant metadata was read and no field/migration/DDL was added. Installed schema
may differ. A normal ORM insert return is not proof of that field's persistence.
Increment60 adds the missing field in DEVELOPMENT source only, as described below.
Review the intended schema and installed-version migration before activation;
do not silently create a field or backfill customer logs during this refactor.

## Offline evidence

The fixed-manifest runner includes a new synthetic local contract suite. It
checks exact legacy payload/default/normalizer parity, explicit normal versus
ignored permission arguments, unchanged legacy None/fallback behavior, same-
object error propagation, static review-guard integration, callback return-value
nonclassification and absence of runtime staging callers. Source-only schema
characterization is not installed Frappe evidence.

The existing private QR/response SQL suite adds diagnostic rows on its newly
owned temporary InnoDB server. Independent readers verify exact payload and
unrelated parent-work visibility before/after explicit owner commit/rollback,
failure before/after insertion, and hook commit/commit-then-fail. No HTTP occurs.
The diagnostic insert/ORM hooks are synthetic SQL bridges, not a real tenant
Document lifecycle or SDK/authority acceptance test. Cumulative counts are in
[STATUS.md](STATUS.md).

Final guarded combined evidence: **8,608 local + 1,144 private SQL = 9,752 passed
in 103.30 seconds**, across the same twelve private suites (121 local + 60 SQL
additions). The 60 new SQL cases cover both contracts, three response forms,
five insertion/hook outcomes and both explicit parent decisions. The first local
run passed 8,604 in 53.95 seconds before four additional callback-return/schema
cases, all included in the final combined run. No guard/ownership assertion was
weakened; no installed application or authority acceptance claim follows.

## Source field and preflight — increment 60

The development DocType JSON now defines one ordinary read-only Data field named
`status`, labelled Diagnostic Status, with an English explanation and Arabic
catalog entries. It is a diagnostic label, not an authority verdict. UUID remains
the existing `custom_uuid` fixture; existing fields and permissions are unchanged.
There is no new Custom Field duplicate, patch, hook, field rename/delete or
historic backfill. The JSON modified timestamp is source metadata, not a live
database mutation. No `migrate`, reload, build or site operation was performed.

`stage_zatca_event` now loads ORM metadata and calls `require_event_log_schema`
BEFORE clock/normalizer/document construction/insertion. The legacy wrapper does
not call this preflight and keeps its commit/fallback/None/permission behavior.
The check requires an ordinary non-single/non-child/non-virtual Event Log table,
exactly one of each of the six payload fields, matching field lookup identities,
Data types for title/invoice/time/UUID/status and Long Text for api_response.
Virtual/fetched fields, malformed metadata and narrowed Data widths fail closed;
default Data width or an explicit integer width of at least 140 is allowed.
Unknown additional fields are not deleted or renamed.

Bad metadata raises the static English/Arabic RuntimeError-family schema review
error OUTSIDE the metadata exception handler. It includes no raw field/site/body
or chained driver error; no diagnostic event is inserted by that invocation.
The preflight itself performs no SQL, DDL, transaction or repair operation. Its
loaded metadata is NOT proof of physical-column synchronization, trusted field
provenance, current schema locks or hook-free insertion. Acquisition errors and
unhandled interruptions retain their propagation. Exact original response custody
remains necessary; this normalizing diagnostic table is not its replacement.

Before any separately approved fictional-client migration, inspect custom-field/
Property Setter collisions, actual columns, storage widths and exact installed
Frappe/ERPNext revisions. Do not automatically delete/coerce an existing `status`
field or reinterpret an old missing/empty status as acceptance. A future approved
migration would enable storing the legacy payload's status as well; it does not
reconstruct historical labels. No tenant inventory or migration is authorized or
performed here. Staging is still not called by invoice submission.

Local tests merge only source JSON/fixture metadata into synthetic list/tuple
shapes, not installed v15/v16 metadata. Private tests show preflight rejection
does not write an event or commit/discard unrelated parent work. The existing
diagnostic SQL bridge now verifies an actual temporary VARCHAR(140) status column
against the payload JSON; it is not a Frappe schema-migration/lifecycle test.

Increment60 final guarded combined evidence: **8,737 local + 1,160 private SQL
= 9,897 passed in 103.74 seconds**, across the same twelve private suites (129
local + 16 private SQL additions). First local passed 8,731 in 55.34 seconds
before six extra malformed/lookup metadata cases, included in the final run.
The sixteen new private cases reject missing/duplicate/wrong-type/narrow status
metadata, using list/tuple shapes and both explicit parent commit/rollback
decisions. No preflight failure inserted an event, committed pending work or
discarded the parent's work. Existing insert/hook tests still pass with the
temporary separate status column. No guard or custody assertion was relaxed.

## Original-pair-bound diagnostic adapter — increment 61

`stage_retained_primary_event(request, sealed, reconciliation=..., cipher=...)`
is an internal server-only bridge, NOT a whitelisted endpoint or active invoice
caller. The trusted server must authorize saved-source access and supply exact
owned-connection/source-guard/key dependencies. Their provenance is not attested
by accepting Python objects; this helper is not permission or transport evidence.

The bridge authenticates the ORIGINAL envelope, checks its exact started request
and namespace, and invokes the existing real pair reconciliation INSPECT operation.
Only an exact matching custody/journal observation may continue. Missing,
custody-only, journal-only, conflicting, UNKNOWN and unconfirmed inspection
outcomes require review without diagnostic insertion. There is no call to pair
persist, no missing-half repair, resealing, new event/attempt identity or HTTP.
A caller-supplied success Boolean/state/body/UUID is not an alternative gate.

The owned inspection rolls back and closes BEFORE diagnostic construction or
framework hooks. After that read, the original envelope is authenticated again
and checked against the same original request. Invoice name and UUID come from
the exact archived candidate; HTTP status/body come from the retained event,
never mutable invoice response fields. Strict UTF-8 decoding rejects incompatible
bodies without a diagnostic replacement; encrypted original bytes remain intact.
Valid diagnostic text still uses the legacy normalizer and is not the exact-byte
receipt store. Empty bodies and all observed HTTP statuses remain observations,
not success/rejection/acceptance verdicts. New fixed diagnostic labels and review
text have English/Arabic catalog entries; response content is never translated.

The bridge then calls existing `stage_zatca_event`, including its schema/normal
permission checks. Known insertion errors can use the explicit received-step
guard. It returns only INSERT_RETURNED, not the receipt, envelope, private keys
or a durable/accepted capability. Pair-input/inspection/decoding errors raise a
static unchained RuntimeError-family review signal. Other insertion exceptions
and interruptions retain their propagation. Original protected inputs may remain
in stack frames: never serialize/log them; keep the ORIGINAL request/envelope
under server custody on every outcome.

Diagnostic insertion uses the caller's ambient transaction, NOT the pair's owned
transaction. A later diagnostic failure or owner rollback cannot undo the already
committed pair merely because that diagnostic did not finish. Hooks can still
commit unrelated ambient work, including on error. A match is observed at the
inspection moment, not a perpetual lock or a guarantee against later authorized
deletion/source/permission changes. Caller provenance, race policy, ACL rechecks,
initial pre-first-durable-response loss and complete worker lifecycle still need
integration. No automatic retry, hold release, PIH/ICV/invoice/QR/GL/VAT update,
live registration, migration or authority request is added.

The legacy log has no doctype/version/attempt ledger key. Do not recover or
authorize an invoice by its invoice_number alone, or mistake a diagnostic row
for exact scoped custody. Explicit repeat calls may create repeat diagnostic
rows; no diagnostic deduplication/retry/outbox policy is invented here. Existing
submission callers still use the legacy logger. This internal bridge and the
original capture/pair providers remain unwired to actual invoice HTTP.

Offline tests use synthetic originals and source metadata with mocked framework
insertion. They check exact pair binding, different seals with identical plaintext,
namespace/attempt/key mismatch, strict decoding, partial/missing/uncertain pairs,
cleanup and insertion interruptions, Arabic labels/body preservation, schema
failure and Sales/POS standard/simplified invoice/credit/debit/advance candidate
forms. That candidate matrix does not certify accounting or installed v16.
Private tests use actual existing pair repositories and separately owned parent
transactions on the new temporary server. They observe the pair and ambient
diagnostic independently before/after owner decisions, insert faults and hook
commit-then-fail; no synthetic observer is called a second time.

Increment61 final guarded combined evidence: **8,824 local + 1,176 private SQL
= 10,000 passed in 107.21 seconds**, across the same twelve private suites (87
local + 16 private additions). Initial local had 60 setup errors due to the new
suite's missing certificate-fixture import, with the prior 8,737 tests passing.
After that test dependency fix, 8,797 local passed in 57.30 seconds; 27 subsequent
binding/interruption/schema/Arabic/type-matrix cases are included in the final
combined run. No runtime, custody or ownership assertion was relaxed to pass.
The sixteen SQL cases cover pair missing/matched, before/after insert failure
and hook commit-then-fail, with both explicit ambient owner decisions. Source/
permission provenance, actual ORM/hooks/v16 and authority acceptance remain
unverified; no deployment or live request occurred.

## Saved-source access and drift checks — increment 62 (2026-10-21)

`SavedPrimaryReconciliationService.stage_diagnostic` is an explicit INTERNAL
saved-source facade, not a whitelisted method, button, worker or active HTTP
caller. It reuses the existing site/actor/System Manager policy, source invoice
WRITE and related Company/device/linked-owner READ checks. A quiet Event Log
CREATE check must also return literal True before lookup/key/owned-SQL access;
it is repeated after lookup/key loading, around diagnostic insertion and before
metadata disclosure. The source/lookup must match the exact original request,
start, namespace, key ID, receipt and full envelope fingerprints. Existing
ignore_permissions flags are not authority. Normal Document insertion still
enforces its own permission check; no ignore-permissions bypass is added.

The permission adapter selects the explicit v15 raise_exception=False or
v16-shaped print_logs=False engine signature. Create checks use doc=None, not
an unsaved Document permission shortcut. Unknown signatures fail closed;
permission-engine faults never cause TypeError retries or fallback signatures.
This is inspected-signature/synthetic evidence, not installed Frappe16 rehearsal.

The exact-pair bridge remains read-only toward the pair. A trusted callback now
brackets the actual diagnostic Document.insert, including its hooks. That callback
rechecks exact source binding, actor and ACL, and opens a fresh OWNED source-only
transaction to lock/compare the saved source revision/field projections. It
rolls back/closes BEFORE returning literal True. It does not rely solely on an
ambient cached/repeatable-read Document. The successful path uses three owned
reads: pair inspection, pre-insert source comparison and post-insert comparison.
None commits, mutates source rows, repairs a pair or cleans the parent connection.

This is detection at explicit boundaries, NOT atomic source/ACL locking across
hooks. Locks are deliberately released before hooks; a change can still occur
between checks. A late denial/changed source can follow a pending or hook-committed
diagnostic row. Do not delete it, compensate, roll back the parent automatically
or say nothing was inserted. The caller must review any staged row and own its
transaction; independently retained originals remain untouched. A source-neutral
diagnostic parent and bounded SQL lock-wait policy still need review before
adoption: existing pending parent source writes can conflict with fresh owned
locking reads. Revoked ACLs, ABA changes and external hook effects are not
globally serialized by these checks.

Only static metadata is returned: DIAGNOSTIC_INSERT_RETURNED_OBSERVATION_NO_REPLAY
with transaction completion/acceptance/provenance/send/replay flags False. The
normal insertion result does not attest durability or hook-free execution.
Permission failures use static translated denial; other diagnostic failures use
a static translated RuntimeError-family review raised outside handlers, NOT
legacy ValidationError generic invoice-failure persistence. Interruptions still
propagate after owned cleanup. English/Arabic late-source messages acknowledge
that an event may already exist. Original request/envelope custody is mandatory.

Inspect/persist public behavior and the legacy logger remain unchanged. There is
no runtime registration, automatic retry, original receipt write/reseal, invoice/
PIH/ICV/QR/accounting/schema/worker change or authority request. Exact installed
source/key/provider/custody provenance, source-neutral caller lifecycle, race and
permissions policy remain adoption gates before a separately approved fictional
client rehearsal. Diagnostic access is not a new permission to issue invoices.

Tests cover source WRITE/related READ/create denial before keys, both quiet ACL
signature shapes, actor/site/role denial, exact source drift around lookup/key/
owned-close/construction/hooks, static metadata and Arabic review. Private SQL
tests deliberately commit source revision, Company tax identity or device-owner
drift while leaving the synthetic ambient Document unchanged. Fresh locking
reads reject it before insertion or deny success after insertion; explicit parent
commit/rollback alone decides the diagnostic row. The matched original pair
remains unchanged and no original synthetic observer is invoked again.

The diagnostic sink is still plaintext normalized Long Text, not encrypted
receipt custody. Source/create permission and metadata-only return do NOT prove
that all other users allowed to read/export the legacy log have matching Company
access. Shared log read/export/retention policy and saved diagnostic scope need
separate review before adoption; existing log permissions are not changed here.

Increment62 final guarded combined evidence: **8,942 local + 1,212 private SQL
= 10,154 passed in 133.20 seconds**, across the same twelve private suites (118
local + 36 private additions). Initial local passed 8,928 in 61.33 seconds before
fourteen actor/strict-callback tests. The first combined run had 36 new native
test failures/10,118 passes in 116.94 seconds: a test asserted a raw-driver open
attribute on a pinned wrapped connection. Correcting it to the provider's public
closed property preserves the closure requirement and matches existing provider
tests; no runtime or ownership/ACL/custody check was weakened. The 36 native cases
cover both signature-shaped engines, three SQL drift targets, three insertion
timings and two explicit parent decisions. Installed application/hooks/v16 and
authority acceptance remain unverified; no working environment was changed.

## Bounded owned lock waits, not completed isolation — increment 63

The optional [concrete Unix provider](PRIMARY_RECEIPT_PROVIDER.md) now sets and
rechecks SESSION-only row/metadata lock waits of one second on each freshly
owned handle before any registration lock. Wrong or changed settings fail closed,
without GLOBAL changes, reconnect or automatic reset. Other injected factories
are not globally constrained; this provider is still not registered in runtime.

Actual private SQL tests hold a source row with a pending unrelated parent
change, then invoke the saved diagnostic facade through the concrete provider.
Server lock timeout 1205 yields static local review, owned cleanup and no diagnostic
insert. Parent work remains pending until that test owner commits/rolls back;
the already stored original pair and original observer remain unchanged. A
separate test holds the registration row during acquisition and confirms owned
failure cleanup without touching the blocking connection or registration.

This bounds individual waits, not total transaction time, all SQL factories or
post-commit/worker lifecycle. Source-neutral diagnostic transaction isolation is
NOT complete. Hooks/callbacks may still affect ambient work and source/ACL changes
are not atomic across those hooks. The source Event Log still permits the
System Manager role read/export/share/write; these permissions were inspected,
not changed. A Company/source-scoped log read/retention strategy and legacy-row
migration policy remain gates before adoption, not an automatic global ACL change.

## Caller database-handle continuity — increment 64 (2026-10-22)

The explicit `stage_zatca_event` boundary now pins its existing caller database
owner and raw `_conn` BEFORE loading metadata. A Werkzeug `LocalProxy` is resolved
to the current owner, not compared as a stable proxy: local Frappe15 source exposes
`frappe.db` through `local("db")`. Identity checks deliberately use `is`, not
value equality. A replacement wrapper sharing the same raw connection is still
a changed owner. Missing/detached raw handles, unbound contexts and ordinary
identity-read failures raise static English/Arabic `EventLogParentError`, outside
the identity exception handler, without leaking driver/site/body/context details.
The writer does not initialize a lazy connection or infer one from settings.

The pinned identity is checked after metadata loading and before/after each trusted
source callback bracketing Document insertion. A clock/normalizer/get_doc side
effect therefore cannot silently redirect the subsequent insert; source callback
drift fails before insertion, and insertion/post-source drift denies even the
`INSERT_RETURNED` observation. The saved-source facade retains its existing static
diagnostic review error and original request/envelope semantics. Interruptions
propagate unchanged. Schema and source policy remain separate gates; ordinary
Document errors are not globally rewritten. The legacy ignored-permission logger
does NOT acquire this guard or change its commit/fallback/None behavior.

No SQL, parent commit/rollback/close, connect/reconnect, savepoint, compensation or
retry is added. An error after insertion must not say that nothing was written.
The real pending work still belongs to its explicit owner, including any staged
diagnostic row. Exact original pair custody is independent and is not modified.

This is **boundary identity observation**, NOT SQL transaction identity, connection
provenance attestation, a sandbox or a source-neutral worker design. Same-handle
commits/rollbacks, a closed or internally reconnected handle retaining its identity, and a temporary context
switch restored before the next check are not detected by identity alone. Earlier
hooks may already have committed unrelated work; no compensation is attempted.
Context changes before this staging boundary and all unreviewed factories/hook
effects remain outside its guarantee. Existing hook-commit characterizations must
continue to pass rather than being reclassified as isolated transactions.

Synthetic cases cover metadata, clock, normalizer, document construction, both
source callbacks and insertion, replacing the wrapper/raw handle, detaching it
and retargeting a stable local proxy. Additional cases exercise unavailable owners,
unchanged proxies, interruption propagation, Arabic late review and unchanged
legacy policy. Saved Sales/POS cases preserve the exact matched pair and static
non-authorizing failure. Native temporary-SQL cases keep unrelated pending parent
work and optional diagnostic rows invisible until the test's explicit decision,
while refusing success after wrapper/raw drift and preserving the original pair.
These fixtures are not real tenant ORM/hook/worker or installed Frappe16 evidence.

Source-neutral caller lifecycle, whole-worker deadlines, provenance/ACL/races and
Company/source-scoped plaintext-log read/export/retention remain adoption gates.
No site, schema, working app, worker, customer, authority request or live provider
registration is changed. The owned lock-wait policy remains one second.

The initial guarded local characterization reproduced **28 failures and 8,973
passes in 63.83 seconds** on the unchanged writer (29 new cases at that point).
The first combined implementation run produced **55 failures and 10,217 passes
in 130.02 seconds**: one old source-only assertion counted exactly three staging
calls before the new guard, and 54 older private-SQL diagnostic cases did not
declare their existing parent `_conn`. In 30 of those cases the resulting review
also reached an unmocked translator; the offline guard blocked its logging path.
The fix explicitly binds those synthetic bridges to their already owned private
transaction, keeps translations local and replaces the old count with the exact
eight-call allowlist plus helper-level forbidden transaction/connection operations.
No missing-parent rejection, guard, source/custody or ownership assertion is waived.

Final guarded combined evidence: **9,028 local + 1,244 private SQL = 10,272 passed
in 130.84 seconds**, across the same twelve private suites (56 local + 16 private
additions). The offline guard remained active: external network and site
initialization denied, fixture-owned Unix SQL only. Native existing hook-commit
cases still demonstrate that identity continuity is not transaction isolation.
No installed application, customer data or authority action occurred.
