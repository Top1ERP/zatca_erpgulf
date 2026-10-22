# Explicit local primary receipt connection provider — increments 48 and 63

## Scope and non-activation

`primary_receipt_provider.py` adds an optional, server-configured Linux/Unix
MariaDB provider for the permissioned LOCAL receipt service from increment 47.
It is not registered in Frappe, a primary API, scheduler, hook, installer or
migration. Only synthetic tests compose these services. No customer settings,
credentials or databases were discovered/read and no authority endpoint was used.

This is connection-target checking, NOT authenticated authority receipt capture,
credential-epoch provenance, invoice acceptance or permission to replay HTTP.
All existing receipt provenance/remote/replay flags remain false. The provider
does not create candidates, starts, receipts, customers or invoices, nor alter
QR generation, advance eligibility/amounts or accounting.

## Explicit dependencies and acquisition order

The server must supply a validated `ReceiptDatabaseBinding`: exact site/storage
namespace, normalized absolute socket pathname, provisioned device/inode/owner,
database, server ID and canonical registration UUID. A separate trusted callback
supplies typed ephemeral LOCAL database credentials, never CSID material.
Declarations, credentials, provider and owned handle have redacted reprs and
reject pickle. These are protected internal Python dependencies, not web JSON.

1. The saved-source service checks actor/site/role, invoice WRITE, related READ
   and exact retained candidate/attempt/source binding before invoking providers.
2. The concrete provider revalidates its declaration and exact requested scope.
   It checks the socket file, exact device/inode/UID and absence of pathname or
   parent symlink substitution BEFORE requesting credentials or opening SQL.
3. It directly creates a fresh PyMySQL connection with explicit database/user/
   password and Unix socket, autocommit disabled, bounded connect/read/write
   timeouts, local infile disabled and no default-file discovery. There is no
   arbitrary raw connection factory, ambient Frappe handle, DSN discovery,
   TCP/TLS fallback, ping or reconnect.
   Increment63 validates the owned peer and sets fixed SESSION-only two-second
   row/metadata lock waits before the first registration lock; details below.
4. On the owned connection it rechecks the socket, AF_UNIX peer pathname and
   Linux SO_PEERCRED process/UID, then reads DATABASE(), server ID, session
   autocommit and positive connection ID. The exact site/namespace/registration
   marker is selected FOR UPDATE in that same transaction.
5. Before each cursor acquisition and commit, these checks repeat and the first
   process/session ID pair must still match. A failed identity check permanently
   poisons that handle. Closed handles are never revived. Existing service source
   locks/rechecks and exact journal append rules remain unchanged.

Acquisition failure rolls back and closes ONLY the newly owned connection,
attempting both cleanup operations even when either fails. Interruptions retain
their propagation after cleanup. Driver construction failure before returning a
raw connection remains the driver's cleanup responsibility. Ordinary errors use
static unchained internal codes, not driver messages, passwords or paths. No new
UI message is added; the existing service retains its Arabic/English failures.

Commit is attempted once, not retried on error. Rollback/close remain available
for owned cleanup after rejection. A close flag does not independently prove
physical close succeeded. The persistence caller must retain its original
protected receipt on any acquisition/SQL/commit/close/disclosure uncertainty;
this provider is NOT a durable spool or retry hold.

## Provisioning and trust limits

`rehearsal_schema.sql` adds a synthetic provisioning marker table. Only an owned
temporary test server creates/seeds it. Runtime code cannot provision, repair or
discover a marker. A real registration lifecycle, restricted account grants,
server configuration and credential custody require separate review before ANY
activation. Test root/blank credentials apply exclusively to the newly owned
private test server and are not an operational account recommendation.

Matching marker/server-ID values are not cryptographic tenant-origin evidence:
they can be cloned or wrongly provisioned. Kernel peer UID/path/inode/session
checks narrow local target drift; they do not defeat a compromised same-user
server, privileged process, malicious in-process Python or historical source
misbinding. Explicit configuration alone does not prevent an administrator from
incorrectly selecting a working database; no such configuration was used here.

The wrapper is not a SQL sandbox. Only reviewed fixed-query transaction writers
may use its cursors; arbitrary SQL/DDL could break transaction guarantees. Python
private attributes are not a security boundary. Existing service callbacks are
still trusted dependencies; this optional concrete implementation is not a
globally enforced connection policy. Unsupported platforms fail closed; a remote
TLS provider and operational socket replacement/restart procedure remain separate
design/audit work, with no automatic inode rebinding or reconnect fallback.

## Offline evidence

Added **60 local cases** covering explicit driver arguments, scope/socket checks
before secrets, malformed/untyped credentials, target/marker/peer/session drift,
poisoned handles, commit uncertainty, redaction and interruption/cleanup errors.
Added **40 private SQL cases** to the existing QR/source suite: actual Unix peer
and registration checks composed with saved Sales/POS, standard/simplified and
Company/device/linked-owner receipt storage, denial before credential acquisition,
wrong marker/inode rejection, switched database rejection and fresh sessions.

Final guarded combined run: **6,131 local + 510 private SQL = 6,641 passing cases
in 65.62 seconds**, across the same twelve owned-private SQL suites. The guard
denied external network/site initialization and allowed fixture-owned Unix SQL
only. This is process-local accidental-I/O protection, not an OS sandbox.
Python 3.10/MariaDB 10.11 exercised actual SQL/peer behavior; permissions and saved
Frappe data remain synthetic v15/v16-shaped fixtures, not installed ERPNext 16,
browser, authentic receipt, customer provenance or full deployment evidence.

Next: audit protected receipt custody and exact transport/source/epoch binding,
then durable local review holds before considering primary API integration.
Legacy partial commits and later scheduler retries remain unresolved. Full
isolated v15/v16, SDK/crypto/accounting/browser tests and separately approved
fictional-client acceptance still precede any active-client adoption.

## Owned session lock waits — increment 63 (2026-10-22)

The optional concrete Unix provider now sets `innodb_lock_wait_timeout=2` and
`lock_wait_timeout=2` ONLY on its directly created fresh owned connection, after
kernel peer validation and BEFORE the first registration `FOR UPDATE`. It reads
back both session variables and requires an exact two-int (2,2) result before
continuing to SQL target/session/registration checks. No GLOBAL setting, ambient
Frappe handle, configured site, operational service or server policy is changed.
The fixed connect/read/write timeouts remain five seconds.

Before each cursor acquisition and commit, peer/session/target checks now also
verify these session settings. A changed/disabled/unreadable policy rejects and
poisons that handle; it is not silently reset, retried or reconnected. Failure
during configuration/read-back/registration acquisition attempts BOTH owned
rollback and close, and propagates interruptions after cleanup. No SQL commit,
schema provisioning, key discovery, invoice state write or authority request is
introduced. Input binding/API signatures and existing permission gates are unchanged.

MariaDB documents row-lock waits separately from metadata-lock waits, and a row
lock timeout ordinarily rolls back the statement, not the entire transaction.
Metadata waits can occur multiple times within one statement. See the primary
[InnoDB variable reference](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/innodb-system-variables)
and [server variable reference](https://mariadb.com/docs/server/server-management/variables-and-modes/server-system-variables).
Thus two seconds is NOT an overall transaction/wall-clock deadline, universal
statement cancellation or proof that an earlier write did not occur. Existing
reviewed service owners must still rollback/close after failure and retain the
exact original recovery input. No automatic replay is added.

This is NOT a SQL sandbox. An error on a returned raw cursor is still the reviewed
caller's cleanup responsibility; identity/policy-check errors poison the wrapper.
Arbitrary injected factories in other staged services are NOT globally forced to
use this provider/policy. Installed source-neutral diagnostic transaction design,
scope/provenance, hook effects, row/metadata contention coverage across all writers
and whole-worker lifecycle remain adoption gates. A parent holding a source row
now causes bounded failure through this provider, not successful isolation or
permission to drop locks, commit or rollback that parent.

Added thirty synthetic local tests for setup-before-lock ordering, typed exact
read-back, no GLOBAL SQL, setup/probe errors/interruptions and post-handoff drift
without repair/reconnect. Sixteen private SQL cases verify real session/global
separation, drift on both variables, registration-row acquisition contention and
source-row contention through permissioned diagnostics. The source contention
case requires server error 1205, never a socket-read failure, leaves the blocking
parent's pending change under its own explicit commit/rollback, and preserves
the independent exact original pair without a new observer. Metadata settings
are read-back/drift tested; this is not a complete metadata-lock/DDL race matrix.

Final guarded combined evidence: **8,972 local + 1,228 private SQL = 10,200 passed
in 132.20 seconds**, across the same twelve private suites. The local-only run
passed 8,972 in 61.78 seconds. No failed guard/ownership assertion was relaxed.
All SQL is on newly owned temporary servers with synthetic data. No installed
v16/ORM/hook/SDK/authority acceptance or working environment change is established.
