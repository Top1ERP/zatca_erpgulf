# Atomic primary start and logical-invoice no-replay hold — increment 51

## Scope: a local prerequisite, not an activated retry solution

`primary_attempt_hold.py` adds an immutable repository that appends one explicit
first attempt event and reserves one logical-invoice hold in the SAME explicit
caller-owned transaction. No runtime path, API, worker, hook, scheduler, permission
endpoint or provider installation uses it. The table in `rehearsal_schema.sql` is
created only in owned temporary test servers. No live/customer source, schema,
configuration, assets, workers, counters, invoice/File/accounting data or authority
request was changed. No transaction or transport is discovered or opened here.

The existing candidate/journal key includes chain and issuance version. This
additional hold instead identifies an exact saved logical source within ONE
explicit storage namespace: document type, Company name and invoice name, with
a versioned purpose-specific canonical hash. It deliberately excludes issuance
version, chain/unit, environment/URL/operation, UUID/ICV, source digest, declared
epoch/owner/certificate and invoice classification. Changing preparation metadata
must not silently create a fresh dispatch opportunity for that same logical source.

These are declarations, not attested ERP identities. Namespace reassignment,
renames/aliases, changed Company/document type/name or cross-bench/cross-tenant
mapping can change the key. Audited stable historical identity/provisioning is
still required; this is NOT a global duplicate-invoice detector. No working
environment is mapped to this storage and no legacy rows are migrated/backfilled.

## Reservation contract

`MariaDBPrimaryAttemptHoldRepository(connection, namespace)` uses fixed SQL and
an explicit caller transaction. It never commits, rolls back, closes, reconnects,
allocates identity, gets a timestamp, sends HTTP or installs schema.

1. `reserve(started_journal)` accepts only an exact typed journal containing ONE
   explicit ATTEMPT_STARTED event. Candidate/event codecs rebuild all existing
   contracts before SQL, detecting tampered derived fields or non-start history.
   No candidate/event/time is invented from an invoice status or mutable settings.
2. Autocommit is rejected. The candidate must already exist and its saved journal
   must be EXACTLY empty. An old already-started journal without a hold is review,
   not permission to reconstruct a reservation after a possibly historical send.
3. The existing repository locks the candidate and appends the supplied first
   event under its empty-journal CAS. The SAME connection then performs a STRICT
   hold insert: no duplicate/upsert acceptance. Unique source/candidate/attempt
   keys and a candidate foreign key protect the local transactional relationship.
4. The hold is read back under lock and must match exact namespace/source/candidate/
   manifest/attempt/started-journal hashes. Any failure poisons the repository and
   the caller must roll back the WHOLE transaction and discard it. This includes
   rolling back a newly appended start when a different candidate loses the
   logical-source unique-key race. No partial success is returned.

Returning a hold does NOT establish commit, ownership, an authorized lease or
permission to dispatch. Future coordination must use an audited fresh owned
connection, guard source/keys/epoch, commit AND close before considering any
transport, and impose the remaining transport/lifecycle policy. A raw caller that
ignores rollback or executes arbitrary SQL is outside this trusted-writer contract.
Ordinary errors are static with no original exception context; interruptions
poison and propagate. No protected identifiers/bytes appear in repr/diagnostics,
and both the hold and repository reject pickle.

## Inspection and conservative no-release policy

`load(started_journal)` is exact local INSPECTION only. It verifies the saved
candidate and original first event, then compares the full original hold. It has
no search/latest/current-configuration fallback, repair or acquisition capability.
Repeated reserve fails EVEN for identical committed input. An uncertain commit
must not be converted into another reservation/send by reading back an existing
hold. Absence of a local row is also NOT evidence of remote non-receipt or a
dispatch grant: legacy/untracked activity and misprovisioned scope remain possible.

Later UNKNOWN or HTTP events do not release/delete/expire/update the hold.
Neither status 200 nor 4xx/5xx, elapsed time, certificate renewal or a later
candidate version enables another reserve. Diagnostic dispatch/replay/acceptance/
provenance/commit-verification flags remain false. The repository has no clock,
expiry, release, clear, override or status-based unlock method.

This is a conservative blocking primitive, NOT a complete operational policy for
correction after rejection, cancellation, reconciled retry, certificate rotation
or recovery of lost/late receipts. Such decisions need separate reviewed source/
history/authority evidence and explicit workflows. No automatic or manual unlock
is installed here. Primary APIs/schedulers remain unmodified, so this does NOT
yet prevent their existing runtime replay paths or remove legacy partial commits.

## Offline evidence and limits

Added **86 local + 57 private SQL cases**. Final guarded combined run:
**6,640 local + 648 private SQL = 7,288 passing cases in 66.43 seconds**, across
the same twelve owned-private SQL suites. The first local run passed 6,625 in
34.05 seconds; the first combined run passed 7,261 in 63.74 seconds before the
last classification cases were added. No failing test/assertion required relaxing
the reservation/identity/rollback contract. The guard denied external network/site
initialization and allowed owned Unix SQL only; it is process-local accidental-I/O
protection, not an OS sandbox.

Unit tests cover Sales/POS, standard/simplified and codes 388/381/383/386, rebuilt
start validation, strict repeat rejection, changed preparation versus stable
logical key, explicit different source separation, later UNKNOWN/HTTP retention,
static errors, poisoned transactions, privacy and no transaction/transport effects.
These synthetic classification fixtures are NOT full SDK-valid signed invoices,
credit/debit/advance accounting examples or genuine authority acceptance evidence.
No advance age/lookup/allocation/remaining/settlement calculation was changed.

The existing owned-private journal suite tests actual atomic visibility/rollback,
committed/uncommitted database crashes, source-key races between same/different
candidate versions at REPEATABLE READ and READ COMMITTED, changed preparation
with fresh UUID/ICV/event/attempt identities, corruption/autocommit rejection,
and refusal to backfill a legacy start. In the losing version race, its newly
appended journal event is verified rolled back; the winner's hold is unchanged.
The new identities deliberately avoid relying on pre-existing UUID/ICV uniqueness
to claim that the logical hold works.

SQL is fixture-owned MariaDB 10.11/Python 3.10 only. No actual Frappe/ERPNext 16
boot, browser/worker crash, physical power-loss/storage guarantee, tenant/provider
origin or attested transport is established. Existing source/permission/QR/advance/
custody regressions continue to run. No new public message or UI translation is
needed: this repository exposes static internal codes only, not an operator API.
No Compliance/debug/onboarding test is routed here; purpose/namespace isolation
and historical-source mapping remain prerequisites before integration.

Next: bind a reviewed owned/permissioned reservation coordinator to the exact
prepared request and retained response, with explicit unknown/lost-response policy.
Do not wire runtime senders before key/source/epoch/transport provenance, durable
custody and rollback/review lifecycle gates are satisfied. Full isolated v15/v16/
SDK/accounting/browser acceptance, fictional-client approval and separate authority
send authorization remain prerequisites under the existing user restrictions.
