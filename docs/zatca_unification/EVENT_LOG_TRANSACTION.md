# Explicit diagnostic event staging — increments 59–61

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
