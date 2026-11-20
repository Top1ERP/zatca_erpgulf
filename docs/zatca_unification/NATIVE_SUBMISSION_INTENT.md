# Native committed submission intent — workstream2

This is source-only development. No installed schema, live worker/scheduler,
Company/EGS activation, tenant database or authority request was changed. A new
DocType is a future installation requirement, not permission to migrate a bench.

## Parent transaction and fixed worker

A selected native Sales/POS submit hook creates one STAGED record in its existing
ERP transaction. It does not allocate invoice UUID/ICV, sign, enqueue, send or take
ownership of ERP commit/rollback. The source key is a unique hash of the exact
saved doctype/name. Normal legacy selections retain their earlier callback.

After the outer hook has closed, a before-commit callback reloads the saved
source/settings/permissions and seals READY with the final fiscal observation,
original actor, Company, exact chain ID, operation and UTC intent creation stamp.
Later ERP writes in the same transaction are therefore included. This stamp is
not the invoice issue timestamp. The source observation reuses the existing typed
publication profile: named collection/bookkeeping changes and ZATCA outputs do
not alter it; money, child rows, terms, unknown fiscal fields and cancellation do.
There is no financial conversion, rounding, recalculation or new XML algorithm.

The authenticated envelope uses the existing site/namespace key readiness probe
and a separate `submission-intent` AEAD domain. No credential, Document, builder,
site override or actor override enters queue arguments. Only the intent ID is
queued, after commit. Parent rollback removes the row. An early commit while the
hook is open cannot finalize it. An incorrectly caught error may leave STAGED;
that unsealed state is deliberately not eligible for discovery or execution.

The writer pins the physical connection, socket, actor, site and key/database
configuration, rejects automatic intermediate commits, and requires InnoDB,
unique source/record slots and sufficient physical text capacity. A missing-key
precheck uses no gap lock; concurrent unrelated first invoices must not deadlock
solely because this table starts empty. The unique index arbitrates source races.
Existing records cannot be silently overwritten/rearmed.

A clean owned worker authenticates READY and the original enabled User before
committing a RUNNING fence. A retry under Administrator cannot upgrade a stored
ordinary actor. The fixed native provider rechecks current ACL, Company policy,
fiscal observation and issuer chain; the same binding is checked again under the
actual generation and dispatch reservation source/chain locks. A lost native
selection cannot fall back to legacy transport. PREPARED or explicit receipt-backed
SUCCESS completes the handoff. Other outcomes require review. COMPLETE here is
local handoff completion, not necessarily reporting/clearance acceptance.

The worker uses the provider's existing raw policy under its own persistent review
boundary. The ordinary UI/deferred error wrappers remain unchanged for their
callers; they insert Error Log rows and would otherwise dirty the connection
between the owned claim and finish transactions. The intent stores only the
static English result code. Unrelated writes or pending callbacks still cause
the owned finish guard to hold; no foreign transaction is committed or rolled back
to force a terminal state. Tests reproduce real SQL log writes before checking
the fix, rather than relying on a no-write logger mock.

## Queue loss and uncertain work

The internal five-minute scheduler discovers at most100 authenticated READY
records, independently of invoice age. Normal submission still enqueues promptly
after commit; this cron interval adds no wait to the interactive path. Discovery
requires System Manager, an enabled native rollout and enabled original Users.
It authenticates all selected headers before switching queue identity, enqueues
only the fixed method/record ID, and restores session/permission/cache state even
when enqueue fails. The eventual worker repeats actor/account checks.

RUNNING, REVIEW, COMPLETE and STAGED are not automatically rediscovered. A process
crash after the RUNNING commit, an unknown claim/finish commit acknowledgment or a
failed finish fence does not authorize another send. Native artifact/attempt
custody and explicit operator recovery must resolve these states. A committed
READY row survives an after-commit queue exception; the message must not claim
that no request could have started. Queue deduplication remains only an optimization.

## Acceptance limits and next lifecycle work

Private SQL tests use a fixture-owned TCP-disabled MariaDB server and framework
transaction/source doubles, preseeded active registration, a synthetic signing
builder and mocked HTTP. Standard303 deliberately makes two calls with identical
bytes through the established Reporting fallback; this is not an unknown retry.
This does not qualify installed Frappe15/16 callback/schema behavior, real financial
builders, authentic signed XML/QR/SDK, restart supervision or authority acceptance.

Still open in workstream2: explicit resolution of a started/uncertain handoff;
draft scheduled/manual operation propagation; native PREPARED discovery beyond
the older legacy collector horizon; complete legacy history/drain and activation;
explicit unchanged retry and corrected-clock/operator adoption; source cancel/
delete/rename; frozen master/print and File/external-print compatibility; whole
canonical runtime qualification. FINAL_READY remains inactive. Workstream2 is
not complete and this is not approval to enter workstream3 or deploy.
