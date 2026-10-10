# Durable journal storage rehearsal — increment 16

Development branch only, 2026-10-10. This adds a MariaDB repository and protected
payload codecs, exercised in a new private test server. It does not install tables
in Frappe, connect to a tenant, dispatch HTTP, change UUID/ICV/PIH or restart any
live service. Prior notice and rollout authority remain mandatory before a live
application/schema/configuration change or bench/worker restart.

## What now persists

`journal_storage.py` encodes versioned preparation declarations separately from
the exact XML BLOB. It reconstructs the existing frozen candidate on read, using
stored route/source/epoch declarations rather than current Company settings.
Unknown fields (including credentials), duplicate keys, invalid versions, bounds
and unsafe JSON fail explicitly. Candidate construction rechecks XML structure,
identity/type/route and embedded public certificate observations.

Event metadata preserves event/attempt IDs, sequence, supplied UTC time at
microsecond precision and response SHA-256/length. Exact response bytes use a
separate nullable BLOB: no response and an empty response remain different.
Invalid/non-JSON bodies can be stored without being mistaken for acceptance.
Decoding recomputes fingerprints and reconstructs the existing event contract.

`MariaDBJournalRepository` accepts an explicit DB-API connection with tuple
cursors, autocommit disabled, and a canonical namespace UUID. It discovers no
socket/site/password and reads no Frappe settings. All values are SQL parameters;
table identifiers are fixed. The caller owns commit/rollback and connection
lifetime. There are no repository transaction commits or document-hook changes.

| Operation | Durable consistency boundary | Not provided |
| --- | --- | --- |
| put(candidate) | Insert once or compare all existing declarations/bytes; conflicting evidence cannot replace the record | Signing, counter allocation or authorization to issue |
| load(key) | Lock candidate, reconstruct bytes/events, verify key/manifest/denormalized fields/revision/journal hash | Proof that declarations or remote receipts are authentic |
| append(key,event,expected hash) | Row lock + expected history hash; event insert and header revision/hash update in one caller transaction | Dispatch lease, cross-attempt retry policy or HTTP |
| Identical event-ID redelivery | Return the existing history even with the earlier expected hash | Another network submission |
| Changed event facts/stale expected hash | Fail explicitly, require caller rollback | Overwrite or silent merge |

The single-attempt journal continues to forbid a second start after timeout,
authentication failure, rejection or generic duplicate response. Stored failure
does not reset identity or grant replay. Returned objects retain their existing
false provenance/acceptance/replay flags; a function return is not proof that the
caller committed its transaction.

## Schema and concurrency

[rehearsal_schema.sql](rehearsal_schema.sql) is only a test schema, not a Frappe
patch/install hook. Both tables use InnoDB. Their namespace-scoped primary keys
and foreign key bind event rows to one candidate. Unique constraints prevent
reusing an event/attempt ID, UUID within an environment, or ICV within a declared
environment/chain. Canonical decimal ICV text preserves the existing bounded
integer contract without narrowing it to MariaDB's integer width.

These identity constraints are an internal collision guard, not a migration
mapping, allocator, corrected-invoice policy or claim about existing tenant data.
Legacy collisions must be reconciled on restored data before adopting them.
Namespace must come from a controlled site mapping, not an arbitrary UI input.

put uses a duplicate-key clause that assigns only the existing primary key to
itself; it never updates XML or declarations. A duplicate on another identity
constraint is followed by an explicit requested-key lookup and fails if that key
was not inserted. Existing-key content drift is compared after reconstruction.
[MariaDB duplicate-key behavior](https://mariadb.com/docs/server/reference/sql-statements/data-manipulation/inserting-loading-data/insert-on-duplicate-key-update)

Candidate reads use FOR UPDATE, so concurrent appenders serialize on that row;
a stale worker cannot append based on an earlier history. Autocommit is rejected
because these locks require transaction scope in InnoDB.
[MariaDB locking reads](https://mariadb.com/docs/server/reference/sql-statements/data-manipulation/selecting-data/for-update)

Any operation failure makes the repository handle unusable. Caller must roll
back the whole transaction and discard that handle. Static codes distinguish
lock timeout/deadlock/uniqueness/other database errors without exposing driver
messages or SQL parameter data. No internal automatic retry is performed.
Do not hold row locks across HTTP, and do not interpret a database retry as
authorization to repeat a ZATCA request. Server errors and unknown commit outcome
require reconciliation before later service actions.

The row lock serializes this candidate's history only. It is **not** a stable
issuing-chain allocation lock, active network lease, durable queue/outbox or
cross-attempt coordinator. Administrative edits remain possible; recomputed
hashes detect inconsistent storage, not a malicious privileged editor who changes
all evidence and hashes together. Recovery/access control are external duties.

## Actual isolated verification

- 112 new local codec/SQL-boundary cases cover exact reconstruction, field/version
  bounds, response fingerprints, namespace/type validation, static driver errors,
  autocommit rejection, stale history, CAS failure and no implicit transaction,
  schema, network or live invoice operations.
- 25 opt-in tests ran on MariaDB **10.11.14** / InnoDB with actual commits,
  independent connections, two-worker concurrency under REPEATABLE READ and
  READ COMMITTED, lock timeout, rollback/connection interruption, identity and
  event/attempt collisions, namespace separation and deliberate test corruption.
- A SIGKILL of **only the owned test server subprocess** followed by restart
  exercised InnoDB crash recovery. Committed candidate/start survived; uncommitted
  event/header changes rolled back together. This is not an OS/power-loss,
  replicated/failover or customer-site disaster-recovery certification.

The fixture creates a new private temporary data directory, ignores default
option files, disables TCP, and checks its exact socket/data directory before
creating the test database. It reads no bench/site connection information. Its
owned process is stopped at teardown. Synthetic files remain in pytest's private
temporary directory for normal retention; they contain no customer data.
The initial sandbox run could not bind a Unix socket; the successful rehearsal
used an explicitly reviewed local-socket execution escalation, not tenant access.

Selected local suite: **2,438 passing**. With the separate 25 real-database cases:
**2,463 passing cases total**. No actual ERPNext 16, Frappe site/hook integration,
browser, SDK, customer data migration or ZATCA request was exercised.

Run local cases using the STATUS command. The private database suite is opt-in:

```sh
ZATCA_RUN_ISOLATED_MARIADB=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  ../../env/bin/python -m pytest -q -p no:cacheprovider \
  zatca_erpgulf/zatca_erpgulf/tests/test_journal_repository_mariadb.py
```

It accepts no externally supplied socket/host/database; missing server binaries
or blocked local-socket permissions fail rather than fall back to a live server.

## Release and next implementation gates

XML/response/context payloads are protected storage data, not diagnostic output.
Do not serialize them into logs/UI. No raw private keys, OTP or authentication
token fields are accepted, but invoices and custom gateway URLs remain sensitive.
The rehearsal schema has no application permissions, encryption at rest, audit
operator identity or retention/off-host backup implementation. Those must precede
deployment, along with a real Frappe MariaDB connection/transaction adapter and
an approved schema/customization migration. PostgreSQL is not implemented here.

Next: verified atomic signing/HTTP credential and source snapshot; controlled
chain mapping/allocation; durable outbox and lease/fencing; explicit cross-attempt
reconciliation and correction policy; protected authentic receipt capture and
transactional accepted status/PIH updates. Rehearse those services on restored
sites and pinned ERPNext 15/16 before replacing any existing live submission path.
