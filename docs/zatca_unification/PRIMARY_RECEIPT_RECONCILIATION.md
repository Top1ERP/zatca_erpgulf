# Exact local primary receipt pair reconciliation — increment 54

## Internal scope, not runtime activation

`PrimaryReceiptReconciliation` consumes an exact existing auth-free request and
its ORIGINAL encrypted retained response. It can inspect the custody/journal
pair, or explicitly redeliver that known response into LOCAL storage. It cannot
send HTTP, create a candidate/start/hold, change IDs/clock/sequence, reseal bytes,
select another epoch/key/namespace, release a hold or infer acceptance. There
is no Frappe endpoint, permissioned facade, hook/job/UI/provider installer,
DDL or runtime caller. The installed application is unchanged, and ALL authority
requests remain prohibited, including Sandbox and Simulation.

This follows the [local capture coordinator](PRIMARY_CAPTURE.md) and
[saved-source capture boundary](PRIMARY_CAPTURE_ACCESS.md); it does NOT call
either to recreate a missing response. Existing low-level single-store recovery
is unchanged. The new paired service does not silently adopt partial legacy
records made by independent custody/journal writers.

## Exact input and locking contract

The caller supplies explicit namespace, dedicated custody cipher, fresh owned
connection factory and a MANDATORY source guard. These are trusted server
dependencies, not request options or proof of provenance. A future permissioned
boundary must authorize saved source, keys, site/namespace and connection
ownership before invoking this service. Do not supply ambient Frappe handles.

Before acquiring SQL, the service rebuilds/detaches the request, validates and
authenticates the envelope, requires exact namespace/candidate/attempt/START
hash, and requires the decrypted receipt predecessor to equal that single START.
An already-UNKNOWN predecessor is not silently re-sequenced into this contract.
Wrong keys, corrupted bytes, cross-scope input or mismatched starts fail with a
static unchained error BEFORE the factory. Keep all protected original inputs.

Within ONE transaction, the guard must return literal `True` before work and
after it. Original logical-source hold and persisted deterministic request codec/
hash must already match; the service reuses capture's exact binding check. The
candidate/journal is locked before hold/request/custody selection, using the
existing capture lock order. Optional exact custody presence is selected without
continuing a repository poisoned by an exceptional missing-row load. A present
row is fully authenticated through the custody repository before comparison.

No absent/mismatched hold, request binding, unreadable record or SQL failure is
reported as a safely missing response. Source permissions/settings/rows must be
checked by the supplied guard; the types do not establish historical authority,
key custody, provider origin, permission-table atomicity or transport identity.

## Paired outcome policy

Here `before` means the exact original START, and `after` means ONLY that START
plus the exact retained original HTTP event. All outcomes are local observations
with dispatch/replay/acceptance/provenance flags false.

| Locked journal / custody | Inspection | Explicit LOCAL persist |
| --- | --- | --- |
| Exact before / absent | Pair missing observation | Store original envelope + event atomically |
| Exact after / identical envelope | Pair matched observation | Already stored; no new receipt writes |
| Exact before / identical envelope | Custody-only review | No repair or append |
| Exact after / absent | Journal-only review | No repair or reseal |
| Different valid history or different authenticated envelope | Conflict review | No overwrite or adoption |
| Missing binding, unreadable/corrupt record, SQL/cleanup uncertainty | Unconfirmed | No claim of a completed pair |

An authenticated seal of the same plaintext with a different nonce/key/ciphertext
is STILL a conflict. UNKNOWN/late/different response history is review-only; it
cannot be replaced with the caller's preferred event. Partial records require a
separately reviewed policy, not a missing-half repair shortcut.

`inspect(request, sealed)` performs no commit, append or stage. It releases locks
through rollback/close. `persist(request, sealed)` stores BOTH missing parts in
one owned transaction, or acknowledges an already identical pair without DML.
Guard rejection after the two writes rolls back BOTH. Partial/conflict review
may end a read-only transaction but never changes either half. The no-replay hold
and request binding are never created, changed or removed by this component.

Commit AND owned rollback/close acknowledgments must finish before reporting
local completion. Cleanup always attempts BOTH rollback and close, even on
interruption; non-ordinary interruption takes priority and propagates after
cleanup. Ordinary failures return a static unconfirmed state retaining the exact
input envelope, which may already have committed. There is no automatic retry,
inspection, local redelivery, transport, unlock or resealing loop. A server must
separately authorize every follow-up operation. The caller retains the original
inputs during interruption; this component generates no new response/envelope.

Protected result repr is static and pickling is forbidden. Only
`diagnostic_projection()` is suitable for a future metadata boundary, and only
after that boundary's final saved-source/ACL checks. Never log/serialize/export
the request, envelope or protected result. `local_transaction_completed` is not
remote acceptance, end-to-end durable custody or permission to issue again.

## Verification and next gates

The guarded local suite uses real encryption and synthetic SQL ownership models.
The existing private journal SQL suite exercises new temporary MariaDB instances
only: exact missing/matched pairs, atomic store/rollback, lost commit ACKs, partial
and conflicting histories/seals, corrupt bytes/request bindings, no invented
start/hold, competing local redelivery at both isolation levels, and owned-server
restart. Synthetic response status/body is not an authority validation result.
Final guarded run: **7,070 local + 773 private SQL = 7,843 passing cases in
79.89 seconds**, across the same twelve private suites (123 local + 42 private
SQL additions). An earlier combined run passed 7,821 in 79.60 seconds before
expanded negative/body cases. The initial six local failures exposed a reused
test double lacking authenticated custody retrieval, not a waived comparison;
the fixture was completed without weakening any assertion. Full verification
history is in [STATUS.md](STATUS.md).

```sh
PYTHONDONTWRITEBYTECODE=1 ../../env/bin/python tools/run_unification_rehearsal.py --private-sql
```

Increment 55 adds an internal [saved-source/owned-resource metadata boundary](PRIMARY_RECONCILIATION_ACCESS.md)
for these exact operations, with full original-seal declaration before keys and
final ACL before diagnostics. It does not install a runtime caller or providers.
Next review legacy independent writers/lost-response/partial-state policy and
audit actual retention/key/provider/namespace/lookup/
credential-epoch provenance, lost/late/unbound response review and legacy partial
writers before runtime integration. Pre-first-durable-response process loss is
not solved. Legacy retries, ICV continuity, signature/QR SDK and advance/GL/VAT
consolidation, full installed v15/v16 and isolated fictional-client acceptance
remain unfinished. Follow [SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md): code
publication or local SQL success authorizes neither live changes nor authority
calls.
