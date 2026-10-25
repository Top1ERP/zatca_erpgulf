# One-shot pinned issuance preparation

Increment 98 — 2026-10-25. OFFLINE development only. This is an internal,
uninstalled caller-transaction service, not a Sales/POS hook, RPC, signing
implementation, authority client or installed ERPNext 15/16 integration.

## Scope

`IssuancePreparation` connects the [explicit issuing chain](ISSUING_CHAIN.md) to
one supplied local builder. Before invoking it, the repository validates the
declared Company/seller/environment/credential epoch, locks an EXISTING declared
head and checks the logical issuance key for an existing original. Missing
registration is an error, never permission to initialize/reset a legacy chain.
An existing original requires review before a builder runs, even if the caller
proposes a new UUID or changes the source/settings snapshot.

The frozen `PreparationTicket` binds the predecessor, complete preparation
context and canonical caller-supplied UUID. Its next ICV and PIH derive only
from that predecessor. There is no UUID allocator, discovery of current settings,
manual initialization field, schema installer or background job here.

The sequence inside ONE caller-owned transaction is:

1. Lock/preflight the explicit chain and source key; freeze the ticket.
2. Require literal `True` from the explicit saved-source/ACL/settings/epoch guard.
3. Invoke the supplied builder at most once with that ticket. It must be local;
   no authority request may occur while this chain lock is held.
4. Keep an exact `PreparedIssuanceCandidate` result on the protected handle BEFORE
   later checks/callbacks. Recheck the guard and compare exact context, UUID,
   next ICV and PIH. Reject drift rather than rewriting the returned XML.
5. Hand ticket plus exact candidate to protected custody; require literal `True`.
6. Recheck the guard, stage the original and next head through the shared atomic
   repository, and recheck the guard once more.
7. Return the staged chain state. The caller alone decides/owns commit and any
   parent work; a returned state is not a commit receipt or a dispatch grant.

Only one call is allowed per preparation handle. Missing callbacks, false/truthy
non-boolean acknowledgments, recursive use, builder/guard/custody exceptions or
repository errors poison the handle and repository. A callback cannot catch a
recursive-use error to restore the outer operation. Exceptions use static English
codes and do not include driver errors, XML, credentials or raw callback details.
No UI messages were added; a future permissioned UI must use the shared translated
aggregate presenter rather than exposing these protected objects.

## Ownership, uncertainty and limits

The constructor requires an explicit concrete repository; it never discovers a
tenant/site/namespace/connection. The service does not begin, commit, roll back,
close or reconfigure the supplied connection. Callbacks are trusted internal
server code and MUST NOT alter its transaction lifecycle. Same-handle commits
inside callbacks are NOT detected. The future outer adapter must authenticate
tenant/connection ownership, authorize normal source/settings access BEFORE
acquiring these locks, exclude independent legacy writers and bound the worker
lifecycle. The guard here only compares a callback acknowledgment; it is not an
implemented ERP source adapter or proof of permission/provenance.

Likewise `retain(...)=True` is not proof of durable/encrypted custody. This change
adds no vault, independent pending identity reservation, durable preparation hold
or crash-recovery provider. The source digest and registration/epoch remain
declarations; observed digests/certificates are NOT signature verification, SDK
validation or remote acceptance. Identity/version ownership must be established
by a reviewed server adapter, not arbitrary caller-provided issuance versions.

If anything fails after building, keep the exact ticket/original and roll back
the WHOLE parent transaction. Do not rerun the builder in another fresh service
merely because a key is absent after rollback. An unknown commit also requires
fresh exact-original reconciliation, never regenerated UUID/signature/QR. The
existing `record(ticket.predecessor, exact_original)` comparison supports that
explicit local review; it is not automatic replay permission. A builder failure
without a returned original, or a process death before durable custody, remains
an unresolved outcome requiring a future durable preparation hold/recovery
policy. The in-memory one-shot flag cannot coordinate fresh processes.

## Rehearsal

Local tests use mocked DB boundaries and synthetic unsigned XML: source/type/
environment ticket matrices, frozen/private handles, exact acknowledgments and
callback order, early scope/epoch/UUID/existing-key/exhaustion refusal, builder
identity/context drift, four late-source boundaries, caught recursive calls,
redacted failures and transaction ownership. Synthetic advance code `386` tests
identity plumbing only, not advance settlement/accounting/XML regulatory parity.

Owned-private MariaDB tests cover parent/head/original commit/rollback, exact
custody ordering, all four source-guard failures, unknown commit acknowledgment,
missing registration and two-worker preparation under READ COMMITTED and
REPEATABLE READ. A competing same-source operation cannot build a second
original after the first commits. A different source waits BEFORE building and
then observes the committed predecessor and next ICV. Contention timeouts are
test assertions only, not a new production polling/sleep policy.

Installed v15/v16, authenticated enrollment, legacy-chain migration/renewal,
real signing/QR, authority validation, actual transport and whole-worker
integration remain separate acceptance gates. No working site or authority
request is part of this increment. Follow [SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md)
before any fictional-company rehearsal, deployment or pilot.

Final guarded verification: **14,497 local + 2,061 private SQL = 16,558 passed
in 179.70 seconds**, across fourteen private SQL suites. This increment adds
**110 cases**: 98 local preparation cases and 12 native transaction/concurrency
cases. The targeted chain SQL suite passed 39 cases in 2.48 seconds. All nine
Node VM scripts passed **1,444 cases**. An initial route-drift test replaced a
path segment absent from its synthetic URL and therefore did not change it; the
fixture now actually changes the path and asserts the difference. No production
guard, assertion or timeout was waived, and no working site or authority was used.
