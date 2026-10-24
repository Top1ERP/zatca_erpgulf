# Permissioned initial pending CSR pair capture — increment 93 (development only)

## Purpose and non-activation

Increment 94 adds [owned exact-original pair review](PENDING_CSR_BOUND_REVIEW.md)
after unknown completion, with no external historical lookup, recapture or retry.
Initial creation and existing envelope-only review APIs remain unchanged; no
runtime provider/button/schema is activated.

`SavedPendingCSRService.stage_new_bound` captures the original source declaration
from current authorized/locked observations and stages a **new envelope/history
pair**. `PendingCSRStagingTransaction.create_bound` optionally completes that
operation using the existing exclusively claimed fresh concrete lease and one
commit/close. No preexisting historical binding is required or consulted.

These are internal, uninstalled methods. No Company button, whitelist, worker,
runtime schema/provider, key generation, resealing, active credential write,
certificate issuance, renewal or authority HTTP is activated. Existing stage,
inspection, save and read-only review semantics remain covered. No separate
authorization, provider/cleanup or storage implementation is introduced.

## Shared authorization before original capture

The constructor still takes the existing server-supplied dependencies for API
compatibility; initial capture deliberately never invokes its historical lookup
callback. Trusted resources remain server dependencies, not request-selected
site/namespace/key/connection values. Providers/callbacks are not a Python sandbox.

The shared engine requires current site/non-Guest System Manager or Administrator,
normal saved target READ+WRITE and related Company READ. Administrator, `in_test`
and ignore-permission flags do not bypass row ACLs. Company or own-key device must
be selected explicitly; linked-company devices, invoice/abbreviation fallback and
unknown flags are not adopted as new key owners. Both quiet permission signatures
continue through the same compatibility adapter.

The retained envelope's canonical manifest must match the exact saved target,
Company, purpose, source kind/revision, environment and configuration digest before
resource acquisition. It must use the configured scope and the explicitly pinned
resource key ID. Input is copied; raw configuration, key or CSR is not returned.

After scoped acquisition and fresh source/actor/ACL checks:

1. Match bounded locked source rows in the same non-autocommit transaction.
2. Capture defined opaque encrypted Password backing state without decryption.
   Recheck current source/ACLs, then construct the copied original binding from
   this observation, source schema/hash, manifest, scope and pinned key ID.
   No placeholder password digest or caller-supplied original source hash is used.
3. Recheck backing state/source/ACLs before calling repository `create_bound`.
4. Authenticate/store/read back the exact new pair, reload its paired binding,
   and recheck locked source, backing state and visible source/permissions.

Caller-owned staging returns `PENDING_CSR_BOUND_CREATION_UNCOMMITTED`; it owns no
commit, rollback or close. It exposes only the existing manifest diagnostic
projection and observation flags, including `original_source_binding_observed`.
No source/backing digest, original record or plaintext/ciphertext is exported.

## Strict creation, not recapture or retry

The new repository `create_bound` shares increment 92's implementation but requires
a completely absent pair. Even an exact existing pair is refused with a static
internal `binding_exists` code. Unbound envelopes/orphan history remain refused.
This prevents initial capture from manufacturing new history for an old identity,
including when current visible state happens to equal old values after ABA.

It uses plain INSERTs, bounded locked readback and exact pair validation. A race
after absent reads fails rather than adopting another writer's envelope. An error
poisons the repository/service; the owner must roll back the whole transaction.
No ID regeneration, replacement, automatic retry or historical migration occurs.
Existing `stage_bound` remains an exact supplied-declaration redelivery primitive;
initial capture never switches to it when creation is refused.

## Owned completion and unknown outcomes

The existing single-use coordinator/provider ownership and cleanup policy applies.
Its final same-connection guard rechecks normal ACLs/source, encrypted backing,
the exact captured original binding and authenticated retained envelope, then
source/backing/ACLs again. Only one commit and close are attempted. After close,
current visible source/actor/permissions are checked before metadata disclosure.
No SQL or borrowed/new historical lookup is performed after closure.

Success is `PENDING_CSR_BOUND_TRANSACTION_COMPLETED_OBSERVATION` with
`local_transaction_completed=True`. Every source/epoch/storage/remote/activation/
dispatch/renewal proof/authority flag remains false. It is observed local lifecycle
completion, not independently verified committed history or remote authorization.

Pre-commit failure attempts owned rollback/close. Commit ambiguity may already
have persisted **both** records; rollback is not compensation. Close uncertainty
or late denial withholds success without undo/retry claims. Original interruption
priority, owned-only cleanup, no double acquisition, reentry poisoning and one
comprehensive display-only translated failure remain shared. English contract
keys stay English; existing Arabic messages are reused with no raw diagnostics.

## Limits and next gate

This removes dependence on a fabricated preexisting binding for NEW local custody.
It does not establish a monotonic authoritative credential epoch, atomic permission
snapshot, independent committed source/vault/tenant provenance or capture time.
Missing-row/isolation/ABA, caches, trusted callback side effects, out-of-band writers
and post-close changes remain limitations. Opaque Password comparison is not
decryption, key validity or a secret-export authorization. Repr/trace/field/log/
backup custody and database append-only privileges still need separate review.

Next provide a reviewed, separately owned committed-pair lookup/review lifecycle
using exact retained identities and current normal permissions, without borrowing
a closed connection or recapturing history after an unknown result. Review source/
key/tenant/epoch provenance before request/receipt/activation integration. Existing
legacy field conflicts and initial/renewal policy remain unactivated release gates.
Installed ERPNext/Frappe 15/16, Desk/browser, SDK and remote acceptance remain
unverified. Finish development before separately approved isolated fictional-Company
rehearsal, adoption/cancellation and gradual active-client decisions.

## Offline evidence

Only the reviewed `pending_csr_creation` suite joins the fixed local manifest;
native composition extends the existing owned TCP-disabled private SQL suite.
Tests exercise both owner/permission signatures, all environment declarations,
Password schema/backing profiles, early denial/manifest mismatch, exact/orphan
identity refusal, final source/backing/binding/envelope/permission drift, unknown
commit/close/interruption/late denial, reentry and Arabic single-popup behavior.
Every initial path traps historical lookup, demonstrating that no existing binding
is consulted. Native tests observe pair visibility, explicit caller rollback/
commit, original backing-state preservation and both-record commit ambiguity.

The local-only guarded run passed **13,941 in 83.53 seconds** (57 new local cases).
Final guarded combined: **13,941 local + 1,974 private SQL = 15,915 passed in
188.19 seconds**, across thirteen private suites, adding **82 cases** (57 local +
25 native SQL). All nine Node VM scripts passed **1,444 cases**. No resource/
ordinary-permission/crypto/transport assertion was waived; no live/customer/
authority operation occurred. Installed v15/v16 and remote acceptance remain
unverified.
