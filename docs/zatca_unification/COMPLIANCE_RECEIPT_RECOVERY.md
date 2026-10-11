# Explicit local receipt persistence recovery — increment 28

## Purpose and authorization boundary

`ComplianceReceiptRecovery` handles one narrow case: a complete bound response
was retained, but receipt commit or connection close was not confirmed. The
original commit might have happened. Recover the EXACT retained ciphertext;
never make another authority request to resolve this local storage uncertainty.

This is an internal, opt-in primitive, NOT a permissioned operator service,
whitelisted endpoint, UI button, durable recovery queue or runtime integration.
The caller must separately authorize the tenant, role and saved owner and supply
reviewed keys and a fresh owned non-autocommit connection factory. No Frappe
provider, schema installer, default connection or credential selector is added.
The current [no-working-environment/no-authority-send mandate](SAFETY_AND_REHEARSAL.md)
still applies. Development fixtures contain synthetic data only.

Increment 29 adds a separate [permissioned internal saved-source service](COMPLIANCE_RECEIPT_RECOVERY_ACCESS.md),
not a public endpoint or installed provider. The low-level primitive alone still
does not authorize operators or establish provider/source/remote provenance.

## Input and transaction contract

Only an exact `ComplianceCaptureResult` in state
`RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY` is accepted. Validate its original stage,
namespace, exchange, staged version, response and observation bindings. Decrypt
and authenticate the retained start and receipt before acquiring any SQL handle;
their plaintext must match the retained observation and exact request history.
Malformed/wrong-scope/unauthenticated inputs raise a static, unchained internal
error. A future operator adapter must translate and redact errors before display.

Acquire ONE fresh owned transaction. Authenticate the exact referenced staged
bundle at its historical preparation time, compare its manifest, lock the start
and require equality with the EXACT retained start envelope. The repository's
optional `expected_start` argument enforces this stronger ciphertext check.
A missing, corrupt or resealed start cannot be recreated/adopted. Lock order
remains bundle, start, then receipt; no schema change is needed.

Increment 29 adds an optional explicit `source_guard(connection, result)` before
append and again before commit. Literal True is required. Its saved-source
service locks current projected source rows BEFORE bundle/archive locks in this
same transaction, and repeats ambient ACL. Default low-level callers retain their
existing behavior. A guard failure returns the unchanged uncertain input after
rollback/close, without any send or retry. ACL is not atomically attested.

Append the EXACT retained receipt. If an identical receipt already exists,
confirm it without replacement; a different/resealed/corrupt receipt conflicts.
Commit AND close must return successfully before advancing the protected result
to `RECEIPT_CAPTURED_OBSERVATION`. All original envelope/observation/response
objects remain unchanged. Both states are local storage observations, not PASS,
verified remote acceptance, Compliance completion or CSID activation authority.
Every existing diagnostic provenance/authority flag remains false, including for
HTTP 200. HTTP rejection observations can be stored without becoming success.

On SQL/acquisition/commit/close failure return the SAME original protected result.
Do not retry automatically. The caller may separately review and explicitly
redeliver that exact input; unknown commit is safe either way because identical
ciphertext storage is idempotent. Interruptions propagate after best-effort
rollback/close. Capture and recovery share the same owned-transaction cleanup
helper. Failed acquisition cleanup belongs to the factory; shape checks do not
prove tenant origin, ownership or successful resource release.

## Deliberately excluded behavior

- No transport dependency, clock discovery, new request identity, resealing,
  new signature, current/active credential selection, request retry or CSID write.
- Historical bundle authentication does not check today's certificate validity
  and grants no right to use that certificate for a new send.
- Preparation/transport-unknown results and already-captured results are rejected.
  A missing response cannot be fabricated or fetched from another attempt.
- Protected objects are not UI/queue/export payloads; do not log or serialize
  them with `vars`, `asdict`, pickle or custom serializers. Repr/diagnostics omit
  raw requests/responses, certificates, credentials, keys and ciphertext.
- If process loss destroyed the in-memory receipt before durable storage,
  this primitive cannot recover it from the spent reservation. Durable recovery
  queue/late-response policy, cross-attempt coordination and actual source/CSR/
  transport/epoch provenance remain separate gates.

## Verification

67 local cases cover six types/three environments, both possible initial commit
outcomes, rejected responses, exact ciphertext/idempotence, conflicts/corruption,
autocommit rejection, cleanup, repeated uncertainty, interruptions, privacy,
historical credential authentication and no transport/clock/resealing invocation.

13 guarded owned-private SQL cases cover both isolation levels and competing
recoveries, missing/resealed/corrupt rows, unknown initial/recovery commits,
autocommit rejection and a crash/restart of ONLY the fixture-owned process.
All transport results are synthetic. Commands and measured totals are in
[STATUS.md](STATUS.md). No tenant, SDK/golden signature, live TLS/authority,
full Frappe application or ERPNext 16 runtime acceptance is claimed.
