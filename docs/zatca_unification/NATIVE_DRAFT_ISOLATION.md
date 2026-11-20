# Borrowed native draft transaction isolation — workstream2

Source-only development, no installed site/schema, live source, worker restart,
Company activation or authority request. This is the selected-native ERP draft
boundary used by the manual Sales/POS and shared scheduled callers. It does not
claim whole installed accounting/filesystem or complete batch lifecycle acceptance.

## Admission and normal completion

`submit_draft` retains the fixed operation scope and now protects an enabled Phase2
native selection with one borrowed savepoint. Unmarked/Phase1 submit policy stays
outside this savepoint service. The native boundary pins the physical connection/
socket, database/site/key configuration and original actor, rejects intermediate
automatic commits, locks the current saved source/children and compares their
complete typed fiscal observation with the caller's saved draft. Normal READ/WRITE
checks use that current locked source, so an older owner snapshot cannot retain
an expired grant merely because owner is excluded from the fiscal hash. A changed source
or non-draft cannot be overwritten using an older read snapshot.

The boundary requires the inspected Frappe callback deque shape and transaction
write counter/value cache. A bounded catalog of at most8192 base tables must use
InnoDB; known nontransactional storage is not silently assumed rollbackable.
This catalog is a conservative admission condition, not an MDL fence over all
possible concurrent schema changes. Installed/custom-engine/DDL compatibility
remains an acceptance gate. Administrative DDL during posting is not supported.

A private savepoint and a first before-commit fence precede ordinary ERP submit.
The fence stops an early framework commit before previous invoice finalizers.
Explicit session COMMIT/ROLLBACK counters detect a raw transaction replacement;
a missing savepoint also detects engine abort/implicit commit. No helper method
commits or rolls back the enclosing transaction or creates another connection.

Deferred native registration supplies cancellation and active-registration checks.
A normal return requires an armed, uncancelled handoff. A cancelled or missing
hook cannot look successful merely because ERP submit swallowed an exception.
Only a successful scope may finalize/publish its later parent intent. Normal
completion releases the private savepoint and its own fence while preserving
previous and newly added legitimate parent callbacks for the eventual ERP commit.

## Confirmed local rollback and uncertain failure

On an ordinary submit failure, the boundary first invalidates its retained queue
closures, checks the same parent transaction and append-only callback prefixes,
runs only this operation's before-rollback callbacks, rolls back to its savepoint,
and runs only its after-rollback callbacks. A second local rollback removes any
cleanup SQL writes. The original callback prefixes and parent write counter are
restored; the framework value cache is cleared. Earlier invoice writes, intents,
callbacks and diagnostics remain owned by the enclosing transaction. This is not
a reset of the chain, UUID/ICV/PIH or an accepted document.

If connection/site/actor/key/transaction/callback provenance is lost, SQL rollback
cannot be acknowledged, or cleanup changes the callback topology, the collector
must stop and let its framework caller own the enclosing failure. It cannot
continue by pretending another operation's writes are clean. The helper does not
issue a speculative full rollback or resurrect callbacks after an engine abort.
Unexpected SQL/ORM failure during savepoint admission is also fatal: a locking
read can fail before local transaction/epoch proof exists. Pure known source/
schema reviews retain their explicit nonfatal classification.
Fatal errors escape both background collector catch layers. Safe source/admission
reviews can skip one source; normal validation exceptions retain their existing
messages only after local rollback is confirmed.

The published native transaction error is reconstructed outside its exception
handler so the original child exception/context is not returned as a diagnostic.
Arabic catalog messages are translated at display; stored diagnostics use English
static codes. Fatal boundary review and ordinary source review have distinct text.

The existing transport fence now also spans this wider draft scope after the ZATCA
hook has closed. Native saved transport is guarded before validation/exchange;
owned native workers cannot begin inside the borrowed ERP operation. Canonical
legacy transport fences share the same check. Privileged raw connections, direct
third-party network/file code and arbitrary server scripts are not sandboxed by
this request-local service.

## Evidence and remaining work

Private SQL tests exercise three saved sources with a failing middle invoice,
real encrypted parent intent/callback custody, retained closure cancellation,
prior SQL/diagnostics, rollback cleanup writes, both actual background commit
policies, stale caller/concurrent source changes, early/raw commit/rollback,
callback mutation, actor/site/key drift, missing/cancelled handoff, unsupported
engines and post-hook transport/worker attempts. ERP submit/ledger rows and
canonical signing inputs remain explicit synthetic doubles. File callback order
is tested; installed physical File cleanup and authentic ERP GL remain unqualified.

Complete mixed legacy/native and submitted-invoice batch coordination, whole
canonical runtime and installed15/16 acceptance remain open. The older collector
still has its24-hour discovery horizon; later native PREPARED discovery, started/
uncertain handoff recovery, explicit retry/corrected-clock adoption, source
cancel/delete/rename, publication and reviewed legacy cutover are separate
workstream2 requirements. No financial reference or XML/QR algorithm changed.
Workstream2 remains active; this is not deployment or workstream3 approval.
