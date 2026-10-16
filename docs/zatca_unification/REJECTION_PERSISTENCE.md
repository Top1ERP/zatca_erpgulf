# Primary rejection persistence boundaries — increment 58

Development only, 2026-10-16. No working application/customer/Bench action or
authority request, including Sandbox/Simulation. This is local failure isolation,
not endpoint acceptance, an atomic transaction or a durable receipt repository.

## Bounded change

The four primary Sales/POS Reporting/Clearance APIs now execute their existing
rejection-persistence blocks through the shared received-response step guard.
Three small named helpers replace twelve repeated blocks, removing obsolete
commented-out writes and documenting their English transaction contracts.
The helpers are local compatibility adapters, not a new public endpoint.

The guard encloses invoice loading, selected response text reads and the existing
save/db_set/commit sequence. Previously caught ValueError, TypeError, KeyError
and framework ValidationError failures escape as the existing static English/
Arabic `LocalResponseProcessingError`, outside the raw exception handler. No
extra generic invoice fetch, error write, 503 downgrade, commit or retry runs
after that fault. Unhandled RuntimeError/interruptions retain old propagation.
No automatic rollback or compensating write is introduced.

Deliberate rejection `frappe.throw` calls remain OUTSIDE the guard. If local
persistence succeeds, the original rejection exceptions, messages and even the
legacy generic wrapping/503 mapping are unchanged. This is deliberately not a
blanket catch around transport, classification, translation or the whole API.
The existing Sales Clearance 303 return and success/legacy-409 branches remain
unchanged; POS Clearance still treats 409 differently from POS Reporting.

## Existing differences preserved, not endorsed

| Path | Existing rejection persistence, before intentional throw |
| --- | --- |
| Sales Reporting | Preserve a valid stored UUID; otherwise placeholder. Assign status and raw response, save with ignored permissions, commit. |
| Sales Clearance | Preserve a valid UUID; otherwise commit its placeholder. Commit status, then stage normalized response via the existing setter without a new commit. |
| POS Reporting/Clearance | Commit UUID, status and response placeholders in the existing order. POS Reporting also has a pre-HTTP request-XML link. |

These field values are not authoritative receipt/acceptance evidence. A callback
can fail after a commit actually succeeded. Per-field commits can also commit
unrelated parent work; rollback cannot undo them. A failed save may leave pending
SQL or a mutated in-memory object. Callers must review originals and reload/
discard objects, not infer rejection/non-delivery and automatically retry.

The response is not copied into a durable journal by this change. Do not remove
all old commits without first integrating exact independent custody and parent
failure lifecycle: that could roll back the only existing response evidence.

## Event logger and callers: audit, not a transaction rewrite

The real `event_log.log_zatca_event` still inserts with ignored permissions,
commits the ambient connection, catches ordinary exceptions and calls
`frappe.log_error`. Both successful insertion and swallowed failure return None.
A caller cannot safely reinterpret None as either success or failure. The
increment57 received-step guard handles known errors ESCAPING that logger; it
does not detect swallowed insert/commit failures or prevent the logger's commit.
The other existing-XML/generation adapters also share that legacy logger.

The immediate Sales/POS `zatca_call` generator handlers catch narrow framework/
value/key/type exceptions, not the RuntimeError-family review signal. That is
source evidence, not whole-program queue/plugin/transaction proof. Broader
handlers, hooks and worker lifecycle still require integration testing. We have
not changed logging privacy/fallback, public return contracts or all twelve
adapter families under cover of this bounded persistence fix.

The next gate is an explicit caller-owned event-log contract with honest failure
propagation/result semantics, integrated with exact custody and intentional
rejection/parent lifecycle. Do not merely delete commit or change all legacy
logger callers globally. Acceptance mapping, partial/lost/late response handling,
source/key/provider provenance and no-replay hold integration remain unfinished.

## Offline verification

Increment59 subsequently adds an explicit [diagnostic event staging contract](EVENT_LOG_TRANSACTION.md)
with normal permissions and honest INSERT_RETURNED semantics. It is not wired
into these primary APIs; their legacy logger still commits/swallows/returns None.
Exact custody and whole-parent lifecycle remain prerequisites, not solved by
adding the separate staging primitive.

The fixed-manifest guarded runner denies external network and site initialization.
New tests execute the actual four primary functions using synthetic documents
and mocked HTTP. They cover every guarded persistence point before/after writes,
all four formerly caught error families, text-read faults, unhandled errors,
normal rejection status/UUID-policy goldens and the distinct POS 409 branches.
Snapshots are taken INSIDE each fault and must remain exact after propagation.

Private SQL cases use only newly owned temporary MariaDB, not tenant databases.
They bridge the actual persistence callbacks to InnoDB and read visibility from
an independent connection. Exact expected rows distinguish pending save/setter
work from already committed UUID/status/response and unrelated parent work.
Explicit synthetic parent commit/rollback must yield the specified final row;
the guard performs neither action. Existing partial commits are characterized,
not hidden or claimed fixed. Real File/ORM hooks, installed v16, SDK/crypto/QR,
full lifecycle and authority acceptance remain unverified.

The guarded local run passed **8,487 cases in 54.37 seconds**. The combined run
passed **8,487 local + 1,084 private SQL = 9,571 cases in 102.12 seconds**, across
the same twelve private suites. This increment adds 438 local and 112 private
SQL cases; no failing runtime/ownership assertion was relaxed. The SQL cases
cover 28 distinct route/fault points, two rejection statuses and both parent
decisions. These counts are offline evidence, not an installed v15/v16 or
authority certification.
