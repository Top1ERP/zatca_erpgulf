# Explicit diagnostic event staging — increment 59

Development only, 2026-10-16. No tenant/site initialization, working application
change or authority request. This contract is not wired into invoice submission.

## Two explicit contracts

`stage_zatca_event` inserts a diagnostic event with `ignore_permissions=False`.
It calls neither commit nor rollback, does not retry or invoke a fallback logger,
and propagates every exception unchanged. A caller using the received-response
step guard can convert the previously caught local error families into the
existing static translated review signal. Other failures remain unchanged.
No new UI, endpoint, translation text or permission override is introduced.

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

The repository Event Log DocType defines title/invoice_number/time/api_response;
its custom-field fixture adds custom_uuid. Neither source defines the legacy
payload's status field. A source-only regression records this mismatch; no
tenant metadata was read and no field/migration/DDL was added. Installed schema
may differ. A normal ORM insert return is not proof of that field's persistence.
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
