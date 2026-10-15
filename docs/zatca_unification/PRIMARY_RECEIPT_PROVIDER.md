# Explicit local primary receipt connection provider — increment 48

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
