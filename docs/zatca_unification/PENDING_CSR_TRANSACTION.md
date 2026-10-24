# Owned pending CSR save coordination — increment 90 (development only)

## Scope and non-activation

`PendingCSRStagingTransaction.save` optionally completes local pending-envelope
storage on **one newly owned concrete-provider connection**. It is internal,
single-use and uninstalled: no whitelist, button, wizard, hook, scheduler, schema
installer, authority client, key generation/resealing or active credential write.
Existing `SavedPendingCSRService.stage`/`inspect` retain caller-owned transaction
behavior, including no automatic commit/rollback/close.

The coordinator reuses the permissioned saved-source/cipher/repository path via
a protected completion handoff. There is no second source/ACL/amount/XML/signing
policy. The handoff is server-only, not an RPC callback parameter or plaintext
export. The older capture transaction helper is not adopted: this lifecycle needs
exclusive lease ownership, fresh pre-commit checks, post-close disclosure checks
and explicit unknown-outcome/cleanup behavior, not a transport transaction.

## Ownership before acquisition

The server supplies the exact scope, trusted lookup and an exact
`UnixPendingCSRResourceProvider` instance. No arbitrary connection/factory or
ambient Frappe parent can be provided. The coordinator exclusively claims a NEW
lease using an internal object-identity token before source processing. Claiming
does no IO; ordinary saved-source/role/row ACL checks still precede login/keys/SQL.

A pre-used or other-claimed lease is refused **without cleanup of its resources**.
Claimed acquisition is available only through the matching internal owner path;
ordinary direct calls cannot steal the lease. Failed preflight consumes this
in-memory coordinator/claim but opens no connection. Reentrant calls poison the
outer coordinator even if a callback swallows the inner failure. There is no
automatic reacquisition, retry or claim release for reuse.

These are trusted-code lifecycle checks, not a Python capability/security sandbox
or durable cross-process idempotency hold. Do not share or manually manipulate
the lease/coordinator/raw handle while coordination is running. The caller must
retain its exact original sealed draft independently of all results/errors.

## One owned transaction

After normal saved-source authorization and staging:

1. Pin copied source-binding/manifest and exact encrypted-envelope fields rather
   than relying on a provider-owned mutable interpretation.
2. Re-read the exact server lookup and compare scope, manifest, source/backing
   hashes and key ID; recheck visible source/actor/normal row ACLs.
3. In the same staging connection, recheck locked source/backing state and reload
   and authenticate the exact stored envelope. Recheck source/binding again.
4. Attempt ONE commit through the pinned provider, then ONE close. The provider
   rechecks its socket/peer/session/registration/key-ID before commit.
5. After close, recheck visible source/actor/permissions and the exact lookup before
   returning metadata. No SQL or new connection is acquired after closure.

Success returns `PENDING_CSR_TRANSACTION_COMPLETED_OBSERVATION` with
`local_transaction_completed=True`, only after commit/close/checks return normally.
All source/epoch/storage/remote/activation/dispatch/renewal proof/authority flags
remain false. It is an observed local lifecycle completion, **not authority
acceptance, valid issuance, active credential selection or future send permission**.

| Boundary outcome | Local behavior |
| --- | --- |
| Pre-acquisition denial | No login/keys/SQL or cleanup of other resources |
| Acquired stage/pre-commit check fails | Attempt rollback and close only the newly owned handle; no commit |
| Commit raises or is interrupted | Outcome may already be durable; attempt owned rollback/close, never retry commit |
| Commit returns, close fails | Refuse success; do not retry close or claim rollback undoes the commit |
| Post-close source/permission denial | Refuse disclosure without attempting to undo committed history |

Acquisition-failure cleanup remains the provider's responsibility; it is not
repeated by the coordinator. For acquired pre-commit/commit failures, BOTH owned
rollback and close are attempted, preserving the original interruption or giving
cleanup interruptions priority over ordinary failures. Cancellation propagates
without a popup. Cleanup is an attempt, not proof that a failed close actually
released every resource; uncertain closure needs review, not speculative retry.

## Messages and privacy

Child stage/guard/cleanup popups are muted in request scope. One comprehensive
redacted failure is displayed outside child catches, with Arabic applied only at
display time. App message keys, result states and internal error codes stay English.
Both failure messages explicitly preserve ambiguity and the original envelope;
they never assert that nothing was stored. No new log or raw driver/key/source
exception export is added. Repr/pickle are restricted; explicit Python field reads,
serialization and trace locals still need protected diagnostic/field custody.

## Limits and next gates

Rechecks are **observations**, not atomic permission-table locks or authoritative
credential epochs. After-return changes, cached/stale ambient permission/source
reads, malicious/side-effecting trusted callbacks, raw-handle interference and
missing-row/isolation/ABA effects remain limitations. SQL locks cover the defined
current rows/backing state before commit; after close only visible source/lookup/
ACLs are rechecked, not encrypted backing rows through a new connection.

Provisioning/lookup/actual-key/tenant provenance, field-level custody, nonce policy,
source/permission integration, unknown-outcome reconciliation and all credential
writers still require review. A reviewed new coordinator may redeliver the exact
original envelope idempotently through the repository; this code never schedules
that, creates new IDs/material, activates a certificate or authorizes HTTP retry.

Increment 91 adds a separately owned [read-only exact-original local review](PENDING_CSR_REVIEW.md),
not automatic redelivery or proof of a prior commit. Exact historical binding
provisioning, independent provenance/epoch and reviewed conflict/absence policy
remain necessary before request/receipt/activation integration. Installed
ERPNext/Frappe 15/16, browser/Desk, SDK and remote acceptance remain unverified.
Full development precedes separately approved fictional-Company rehearsal and
adoption/cancellation or gradual active-client decisions. No live/tenant/authority
operation occurs in this increment.

## Offline evidence

Only `pending_csr_transaction` joins the fixed local manifest. The existing owned
private pending suite composes actual Unix provider/service/cipher/repository
transactions with mocked Frappe rows/ACLs on its temporary TCP-disabled database.
Synthetic tests check both permission signatures, owner/environment/Password
profiles, exact pre-commit source/backing/binding/envelope drift, interruption and
cleanup priority, lease ownership, reentry, Arabic/single-popup and privacy behavior.

The local-only guarded runner passed **13,771 cases in 83.21 seconds**, including
63 new local cases. No offline/normal-permission/crypto/transport assertion was
waived; native transaction outcomes are verified separately, not guessed from mocks.

Final guarded combined: **13,771 local + 1,905 private SQL = 15,676 passed in
163.16 seconds**, across thirteen owned-private SQL suites, including **81 new
cases** (63 local + 18 native SQL). Native tests verify actual committed visibility,
rollback of source/backing/envelope drift together, pre-commit revocation, real
commit-before/commit-after ambiguity, post-close acknowledgment failure and late
permission denial with committed rows retained. All nine standalone Node VM
scripts passed **1,444 cases**. No offline/ordinary-permission/crypto/transport
guard was waived; no live/tenant or authority operation occurred.
