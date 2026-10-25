# Durable pre-build no-rebuild holds

Increment 99 — 2026-10-25. OFFLINE development only. No installed schema,
Company field, live hook/worker, HTTP client, authority operation or deployment.
The new owned service is opt-in and uninstalled, not a migration of legacy
Sales/POS. All invoice XML and enrollment/credential declarations in tests are
synthetic and NOT cryptographically signed or authority-validated.

## Why the earlier one-shot handle was insufficient

[Increment 98](ISSUANCE_PREPARATION.md) stages an exact original and chain head
in the caller's transaction. Its in-memory flag cannot survive a worker crash,
and rollback can leave no row to stop a fresh builder. Keep that caller-owned
service for explicit local characterization, but do not present it as durable
pre-build custody or use it as a fresh-worker retry mechanism.

`PreparationHold` adds a bounded versioned encoding of the frozen predecessor,
preparation context and supplied canonical UUID BEFORE any XML exists. The
context codec is shared with the existing candidate store, not copied into a
second settings/credential decoder. Each hold has a supplied opaque ID and a
recomputed ticket fingerprint; neither is authenticated enrollment provenance.
Protected handles reject pickling and keep XML/PIH out of their representations.

## Explicit owned local workflow

`HeldIssuancePreparation` owns two NEW private connections from an explicit
trusted factory. Never supply a borrowed Frappe request/worker connection, and
never place uncommitted ERP parent work into this service's transaction.

1. Authorize and stabilize the saved source through the future outer adapter.
   In the first owned transaction, lock an existing explicit chain, check its
   source key and active hold, freeze the ticket, require the source/ACL/settings/
   epoch guard and insert a STRICT pending hold. Commit AND close successfully.
   A failed/unconfirmed commit or close means NO builder invocation.
2. Recheck the guard, invoke the supplied LOCAL builder once outside SQL locks,
   keep its exact returned candidate before later checks, recheck the guard,
   validate context/UUID/ICV/PIH and require literal True from protected custody.
   Recheck the guard again. There is no authority request or signer default here.
3. In a second owned transaction, recheck the guard, compare the exact saved
   ticket and predecessor, record exact XML plus next chain head, and mark that
   hold completed atomically. Recheck the guard, commit and close. Only then
   return the local staged chain result. No HTTP acceptance is inferred.

No counter or PIH advances merely because a pending ticket was reserved. The
head advances with the exact generated original, independent of authority HTTP
status. Until then, other sources on that same registered chain are blocked
rather than guessing a predecessor. No configurable polling/sleep was added.

The repository remains caller-transaction-only: no commit/rollback/close or
installation occurs there. The owned coordinator reuses the existing explicit
owned-transaction helper. Every failure keeps the original pending hold if its
first commit succeeded; there is no expiry, automatic release, background retry,
UUID replacement, repair or second builder call.

## Storage constraints and cooperating writers

The PRIVATE REHEARSAL SQL adds `zatca_preparation_hold_v1` only. It is not run by
any installer, patch, migration or site request. It retains one permanent saved-
source identity per explicit namespace, one UUID per environment, one candidate
key and at most one ACTIVE hold per chain. Completion clears only the active
chain marker; it does not delete the immutable ticket or saved-source hold.

The conservative logical source hash binds doctype, Company and invoice name,
not UUID, issuance version, environment, unit, certificate, source digest or route.
Changing those declarations cannot create a new build opportunity. This is an
internal no-rebuild safety policy, NOT a new ZATCA rule. Namespace provisioning,
renames and document aliases need audited server-owned mappings; a hash or
caller-selected namespace is not a security boundary.

Both previous internal chain entry points (`begin_preparation` and `record`)
now honor recorded active-chain and permanent-source holds. Their guard uses
two bounded unique-index point lookups, not a history-wide OR/sort. Only the
held repository's exact-ticket validation can call the private matching-hold
completion primitive. Private Python methods are not a sandbox against arbitrary
SQL, and legacy application generators remain separate, unmigrated writers.

## Unknown results and reconciliation

The protected owner retains its initial ticket/hold and exact candidate, including
on final commit/close failure. Fresh local reconciliation may call
`complete(exact_hold, exact_original)` through a separately owned transaction:

- Pending row plus unchanged predecessor: stage the SAME exact original, head
  and completion together; never regenerate XML, UUID, signature or QR.
- Completed row: compare the stored original bytes/context and manifest. Exact
  redelivery returns the CURRENT head without another increment or rewind,
  including after later invoices. Different bytes require review.
- Corrupt/missing ticket, indexed mismatch, unexpected predecessor or an unbound
  partial original: refuse; no speculative repair, release or adoption.

A worker crash after the first commit, builder failure with no returned original
or process loss before durable original custody leaves a pending no-rebuild hold.
That prevents silent duplicate generation, but does NOT recover the missing
original or establish that building never happened. A later operator-review and
authenticated custody/recovery facade is still required. There is deliberately
no public release/reset button or automatic timeout workaround in this increment.

## Acceptance limits and tests

The owned factory is supplied, not authenticated site/namespace/connection proof.
The source guard's True acknowledgment is not an implemented ERP adapter or
normal ACL proof. The custody callback is not an installed encrypted vault.
Source/settings/credential epochs must be verified against a committed saved
ERP source, and all live writers must be coordinated before adopting this flow.
Callbacks must remain local and must not change repository transaction ownership.

Local tests cover strict ticket codecs, bounded/canonical input, permanent source
binding, private/frozen objects, owned commit/close-before-build ordering, six
source guard boundaries, static failures, literal custody acknowledgments,
recursive-use poisoning and absence of automatic replay. Private native tests
cover visibility before building, direct/unheld writer refusal, strict reservation,
new-unit/UUID conflicts, final commit uncertainty, exact reconciliation,
source drift, private SQL crash/restart, two-worker build/completion contention
under both supported isolation modes, autocommit refusal, corruption and partial
original refusal. These tests do not constitute installed ERPNext 15/16 testing,
SDK/authority acceptance, advance accounting parity or measured runtime speed.

Remaining gates: audited source/tenant/connection/normal-ACL adapters, encrypted
original custody and operator review after a missing original, exclusion/mapping
of all legacy writers/counters, whole-worker integration and installed v15/v16
rehearsal. Do not replace a live invoice event with an independently committed
operation on uncommitted parent data. Follow [SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md):
complete development first, separately approve isolated fictional-company tests,
then decide adoption/cancellation and any gradual pilot. Authority requests remain
prohibited even if a future rehearsal or deployment is approved.

Final guarded verification: **14,552 local + 2,098 private SQL = 16,650 passed
in 178.58 seconds**, across fourteen private SQL suites. This increment adds
**92 cases**: 55 local ticket/owned-owner cases and 37 native hold cases. The
expanded targeted chain SQL suite passed **76 cases in 3.34 seconds** before the
final point-lookup guard refinement; the full combined run verifies that final
refinement too. All nine Node VM scripts passed **1,444 cases**. An initial
native launch was not executed because automatic permission review timed out;
the permitted single retry succeeded with the same offline guard. No assertion,
ACL, network, site or cryptographic restriction was waived.
