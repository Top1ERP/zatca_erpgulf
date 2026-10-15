# Exact local primary receipt persistence — increment 46

## Internal primitive, not activated submission behavior

`primary_receipt_persistence` reuses the existing single-attempt DispatchJournal,
versioned codecs, MariaDB journal repository and tested owned-transaction helper.
It adds NO sender, public endpoint, Frappe hook, scheduler integration, schema
installer, active provider or current-setting/credential lookup. Primary APIs
retain the increment 45 error boundary; they do not call this primitive yet.

The service requires an explicitly supplied canonical namespace and factory for
a NEW OWNED non-autocommit connection, never the ambient Frappe transaction.
The optional exact saved-source/permission guard must return literal True before
and after append using that same owned transaction. Callbacks are trusted server
dependencies, not input accepted from an operator. No provider/ACL origin is
established merely by supplying such a factory or callback.

## Exact retained input and one local transaction

`RetainedPrimaryReceipt` contains one namespace, exact previously-started journal
and one exact HTTP_RESPONSE event. The candidate/context and all event codecs are
reconstructed before SQL acquisition; source/attempt/sequence/time/body/digest and
derived-state mismatches fail with static unchained codes. An empty or already
terminal predecessor cannot be used to invent another attempt. A retained late
response may follow an explicitly recorded TRANSPORT_UNKNOWN, with its original
sequence and prior event intact. No new identity/time/event is generated here.

The service locks/loads the existing journal. It accepts ONLY the exact declared
predecessor or the exact already-stored resulting journal. It never calls `put`,
creates a candidate/start, folds a newer unknown event into another revision,
resequences a response, replaces bytes, repairs history or changes credentials.
The repository's fixed SQL, row locking, expected journal hash and idempotent
identical-event handling perform the actual append. Conflicting namespaces,
histories, attempts or responses are not overwritten.

Commit AND close must complete before the service returns
`RECEIPT_STORED_OBSERVATION_NO_REPLAY`. Acquisition, SQL, source guard, commit or
close uncertainty returns `RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY`, retaining the
EXACT same input object. A lost acknowledgement can mean the database did commit;
the service does not guess. An explicit later LOCAL call may submit that same
retained observation to storage again. Identical stored data is idempotent;
it is not another HTTP send. There is no automatic local loop or HTTP retry.
Interruptions propagate after owned cleanup; the caller must retain its input.

The existing owned-transaction helper from Compliance capture is reused without
changing its behavior or existing capture/recovery tests. Failure during close
attempts rollback after the close failure, not before it; that cannot undo an
already completed commit. Such an outcome deliberately remains unconfirmed.

Objects hide protected fields from repr and reject pickling. The static internal
diagnostic includes no IDs, raw XML/response, URL, credential or original driver
exception. Only local transaction completion is observed; all origin, source,
epoch, remote-receipt, acceptance, dispatch and replay flags remain false. These
are still protected Python objects, not safe arbitrary serialization/export APIs.

## Limits and blocking adoption work

[Increment 47](PRIMARY_RECEIPT_ACCESS.md) subsequently adds an internal saved-row/
WRITE-access wrapper with exact attempt/event binding and same-transaction source
guards. It is NOT installed or wired to primary APIs/schedulers; provider origin,
historical/custody evidence and the remaining runtime limitations below stay open.

- This is LOCAL receipt storage, not a transport/acceptance validator or a durable
  scheduler/queue/manual retry hold. A stored receipt does not authorize a send,
  Production CSID, PIH/accounting update, QR recovery or settlement.
  A future coordinator must not ignore an unconfirmed result and continue local
  acceptance/PIH/artifact projection as though receipt storage succeeded.
- The primary adapters still lack a verified saved-source/candidate/attempt/epoch
  binding and audited namespace/owned-connection acquisition. Do not attach a
  made-up journal or current credentials merely to enable the service.
- The predecessor must already have been committed by a reviewed reservation
  service. This component cannot prove that before loading it, reserve a start,
  or send after an uncertain reservation. No row lock may span HTTP.
- Process loss before durable receipt persistence can lose the retained memory
  input. A durable response capture/spool and review hold, exact-attempt dispatch
  coordination and committed provider provenance remain necessary.
- Journal BLOBs follow the existing protected raw-storage design, not a newly
  encrypted archive. Key custody/storage access, retention and a permissioned
  operator boundary are unresolved. No raw export endpoint is introduced.
- Existing primary partial commits and other writer/retry paths remain. Physical
  File lifecycle, actual Frappe v15/v16 fresh/upgrade/browser integration, crypto/
  SDK/authority acceptance and source/permission races are not proven here.

No normal primary/Compliance/Debug/POS/advance entry point or amount, discount,
GL/VAT, advance lookup/allocation/remaining/age/settlement rule changes. Runtime
controls gain no new button, endpoint, translation message or schema installation.

## Offline evidence

82 local cases cover exact/status-neutral/late/idempotent observations, source
guards, frozen-object tampering/revalidation before acquisition, missing/terminal/
wrong attempts, namespace/dependency validation, no start/transport/clock lookup,
unknown SQL/commit/close/cleanup outcomes, interruptions, protected repr/pickling
and explicit LOCAL redelivery with no acceptance/replay authorization.

41 new cases in the EXISTING private journal SQL suite cover Sales/POS and
standard/simplified candidates, late replies and 200/401/409 observations, exact
raw bytes and repeated local delivery; lost commit-before/after/close ACKs,
missing starts/candidates, newer/conflicting history, concurrent identical
delivery under both isolation levels, autocommit rejection, source guards and
separate parent transaction visibility/commit/rollback. All data/certificates/
sources are synthetic; only owned temporary InnoDB is used, with TCP disabled.

The first local selection passed **5,883 cases in 28.04 seconds**. The initial
combined run had two new test failures: close-error cleanup was incorrectly
expected before close instead of after it. The expectation was corrected to the
existing helper contract; no runtime cleanup was weakened. An unrelated-parent
test was also narrowed to a pending synthetic header update to avoid incidental
empty-child-range locks obscuring transaction ownership.
The first version of that pending value exceeded the existing revision CHECK;
the database rejected it. The synthetic value now stays within the constraint;
no schema/constraint or runtime validation was relaxed. It deliberately models
unrelated pending SQL, not valid revision/event reconstruction.

The final guarded selection passed **5,883 local + 416 private SQL = 6,299 cases
in 51.17 seconds**, across the same twelve private SQL suites. See
[STATUS.md](STATUS.md) for cumulative evidence and remaining adoption gates. No installed
source/config/schema/assets/workers/customer data or authority request changed.
Complete offline development before separately approved NEW isolated fictional-
client v15/v16 rehearsals and the whole-change adoption/cancellation decision.
