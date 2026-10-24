# Pinned pending CSR resources — increment 88 (development only)

## Bounded implementation

Increment 90 adds an exclusive internal lease claim for an optional
[owned pending save coordinator](PENDING_CSR_TRANSACTION.md). Only the matching
owner acquires a claimed NEW lease; pre-used/other-claimed leases are not cleaned
by that coordinator. Unclaimed direct-provider behavior is retained.

Increment 89 adds [encrypted Password-state comparisons](PENDING_CSR_PASSWORD_STATE.md)
inside the saved-source service after resource acquisition, before and after
repository work. This provider still checks only its pinned storage domain/key ID,
not credential plaintext, history or an authoritative issuing-unit epoch.

`UnixPendingCSRResourceProvider` is an explicit single-acquisition resource lease
for the internal saved-source service. It supplies a fresh local SQL handle and
a separately supplied scoped pending-CSR cipher. **Nothing is installed or wired
to a button, hook, queue, invoice, signer, CSID request or authority client.**

Existing local socket/peer/session checks are reused from the receipt provider.
The only shared-engine change is an optional registration-table selector with
two literal app-owned choices. Receipt callers keep their original default query
and lifecycle; there is no arbitrary table/SQL/host argument or receipt-marker
fallback for pending keys. The new pending handle adds a distinct registration
table and pinned storage-key ID, not another unreviewed connection implementation.

## Explicit declarations, not configuration discovery

`PendingCSRDatabaseBinding` reuses the shared Linux/Unix provisioning validation
and adds a required storage-key ID. The binding pins site/namespace, normalized
absolute socket pathname, socket device/inode/owner UID, database name, server ID,
registration UUID and key ID. It is a **server provisioning declaration**, not
independent evidence that the chosen database/site or historical key is correct.

The local database login uses the existing protected `ReceiptDatabaseCredentials`
contract; despite that legacy name, it contains only the explicit local database
user/password, not invoice or authority credentials. `PendingCSRStorageKeys`
requires an exact scope, explicit key ID and a pending-only cipher which already
contains that selected key. It does not generate, derive or discover keys.

No site configuration, environment variable, Password backing table, file,
arbitrary connector, DSN, TCP/TLS fallback, default option file, reconnect or ping
is used. Fixed PyMySQL options disable local-infile/default-file reads and use
non-autocommit UTF-8 with five-second connection/read/write timeouts.

## Acquisition and ownership

```text
saved-source service's actor/ACL/source/binding checks
  -> exact provider scope + socket observation
  -> explicit local login -> one fresh Unix connection
  -> set SESSION lock waits to 1 second
  -> verify peer/target/session + locked pending registration/key ID
  -> scoped key provider -> recheck peer/target/session/registration/key ID
  -> protected resource handoff to caller-owned staging transaction
```

Peer checks use AF_UNIX pathname plus Linux SO_PEERCRED PID/UID, socket identity,
database/server/autocommit/session identity, and read-back session lock waits.
Registration binds site/namespace/registration UUID and key ID under `FOR UPDATE`.
The [private rehearsal DDL](pending_csr_provider_rehearsal.sql) is installed only
by the owned test fixture, never by the provider/app. Correct production
provisioning, database grants and credential/key custody remain audit gates.

The lease accepts only one acquisition. Failed or reentrant acquisition is not
retried, even when a callback swallows the reentrant error. After successful
handoff, another acquisition is refused without replacing or losing access to
the original resources. The trusted server caller retains `lease.resources`
for explicit rollback/close even if the saved-source service later denies access.

During failed acquisition the provider attempts **both** rollback and close on
only its own freshly created handle. It never acquires or cleans an ambient
Frappe parent. Cancellation propagates; cleanup interruptions take priority over
ordinary acquisition errors. Ordinary failures are static allowlisted English
codes without raw exception text/context. The saved-source boundary continues
to own the single translated user message; no new popup/log/translation path
or operator-facing resource export is introduced here.

## Handoff checks and limits

Before each handle cursor/commit, recheck the pinned socket/peer/session, waits,
target and pending registration/key ID. Drift, direct driver failures and probe
interruptions poison the handle; no session repair, reconnection or commit retry
occurs. Explicit rollback remains available after failure; explicit close is
idempotent locally and never retries a failed driver close.

Successful acquisition/staging is **not a commit**. Only the caller decides its
transaction outcome; commit is not automatic or proof of source/ACL/remote
authorization. An unknown commit outcome must be reviewed separately, not retried.
Registration/source locks remain subject to that same transaction. The one-second
wait settings bound individual row/metadata lock waits, not total operation time,
statement cancellation or end-to-end UI latency.

The returned cursor is not a SQL sandbox and the handle is not a source/ACL-aware
commit coordinator. Only reviewed fixed-query consumers may use it. Errors during
cursor execution and late service denial require caller-owned whole-transaction
rollback/disposal; arbitrary SQL, DDL or later source/permission changes cannot be
made safe by a registration marker. The single-use lease is not durable workflow
idempotency or a prohibition on intentional caller SQL/transaction operations.

Scope/key-ID matching does not prove the actual key bytes came from a trustworthy
vault or are independent of other stores. AES nonce/volume/rotation/backup/recovery,
field-level secret/export/log custody and key provisioning still need approval.
These Python objects expose fields to trusted code; repr/pickle restrictions are
not a memory/serialization sandbox or secure erasure guarantee. Provider, binding,
resources and raw cursors must never be exported through RPC/log/queue payloads.

Existing guarded CSR/CSID buttons, initial certificate/alias defects, signing,
active selection and installed schema are unchanged. This is not a certificate
issuance/renewal/activation workflow. Next bind a trustworthy source/credential
epoch and exact retained draft to a reviewed transaction/issuance/receipt
coordinator, before considering any activation or runtime wiring. Full development
then separately approved fictional-Company rehearsal still precedes adoption or
gradual active-client pilots. No live change or authority operation occurs.

## Offline evidence

Only the reviewed `pending_csr_provider` local suite joins the fixed manifest.
The existing private pending-CSR suite adds a distinct registration table in its
owned temporary TCP-disabled MariaDB database. Native tests compose the actual
provider, cipher, repository and source locks with mocked saved Frappe rows/ACLs.
Fixture-only root/empty-password login is never read from or used against a tenant.

The local-only fixed guarded runner passed **13,626 cases in 83.01 seconds**.
No resource, ordinary ACL, crypto or transport assertion was relaxed. Installed
ERPNext/Frappe 15/16, Desk/browser, SDK, actual vault provisioning or authority
acceptance are not established by these offline tests.

Final guarded combined: **13,626 local + 1,862 private SQL = 15,488 passed in
159.78 seconds**, across thirteen owned-private SQL suites, including **101 new
cases** (83 local + 18 native SQL). Native composition covers Company/device
staging/inspection, caller-only commit/rollback with parent work, pre-provider
row ACL denial, actual registration/server/key-ID mismatches, post-handoff wait
drift and registration lock contention/release. Existing receipt provider tests
also pass without changing their expected default queries or lifecycle. All nine
standalone Node VM scripts passed **1,444 cases**. No offline/ordinary-permission/
crypto/transport guard was waived; no customer material or authority request was used.
