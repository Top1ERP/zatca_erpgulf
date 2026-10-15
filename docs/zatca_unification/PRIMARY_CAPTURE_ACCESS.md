# Saved-source local primary capture access — increment 53

## Scope and non-activation

`SavedPrimaryCaptureService` is an INTERNAL, metadata-only permission boundary
around the [auth-free local coordinator](PRIMARY_CAPTURE.md). There is no
whitelist, HTTP/auth adapter, default observer, queue/UI/hook, provider/key
registration, schema installer or runtime caller. No authority endpoint was
called, including Sandbox/Simulation. The installed application is untouched.

This increment adds no DDL and does not alter cryptography, QR builders, invoice
totals, advance lookup/age/allocations, accepted status, PIH/ICV allocation or
existing scheduler/retry policy. It is not an onboarding test button or a fix
for the customer's historical signature error. Overall development is unfinished.

## Exact access and resource boundary

The shared saved-source engine requires a non-Guest System Manager or
Administrator on the exact declared site. Direct quiet document ACL requires
WRITE on the saved Sales/POS Invoice and READ on Company and any selected device
or linked Company. `ignore_permissions` does not bypass those checks. Compatibility
tests exercise both v15/v16 permission signatures, not a complete installed v16.

The supplied request is rebuilt/detached using the coordinator contract. Its
DocType/name must match the target before saved rows are acquired. An explicit
server lookup declares scope/context, UUID, ICV, exact START journal hash,
attempt, encoded START-event hash, exact request-body hash and custody key ID.
Every field must match before scoped resources or SQL acquisition. Current
invoice status is neither acceptance proof nor permission to invoke transport.

The scoped resource provider MUST return typed custody keys, an explicit observer
and an explicit result-retention callback. No dependency discovery or no-op
retainer is supplied. Scope/type/key-ID checks do NOT prove key custody, route
origin, historical credential epoch or provider authenticity.

The coordinator acquires three fresh owned handles through the shared acquisition
helper. Recognizable ambient Frappe handles/raw parents are rejected untouched.
Actor/role/site/source/owner/ACL are rechecked around exact bounded saved-row SQL
locks and before observer entry. Saved invoice status/revision is included in
drift checks, not used as acceptance authority. All owned handles are closed
before the observer. Locks do not span it; permissions are not locked atomically.
No full accounting-row or permission-table snapshot is claimed.

## Preserve protected outcomes before refusing disclosure

An observer can return a complete response immediately before ACL/source drift.
A post-observer permission exception must not discard those original bytes.
The observer wrapper therefore checks BEFORE entry, not after return. The core
retains/seals the response; subsequent guards can block local SQL persistence.

For EVERY normal coordinator result (including unconfirmed/no-response states),
the facade invokes `retain(scope, result)` BEFORE final disclosure checks. Literal
`True` is required. This is an explicit trusted server callback receiving the
exact protected result, never a browser callback. An acknowledgment is NOT
proof of durable storage. Successful output is diagnostics only, including
`server_custody_acknowledged=True` and
`server_custody_durable_verified=False`; no XML, response, ciphertext, names or
identifiers are returned. All provenance/acceptance/dispatch/replay flags stay
false. A final ACL/source failure refuses even those diagnostics. It cannot undo
already committed hold/history/ciphertext; retained server custody is separate.

If the retainer returns anything except literal `True`, raises an ordinary
exception, or is interrupted, `PrimaryCaptureHandoffRequired` transfers the exact
result to the TRUSTED SERVER OWNER in `.result`. Its static translated string
and hidden repr contain no protected data; pickling is forbidden. `.interrupted`
records a non-ordinary interruption during handoff. This special carrier replaces
that interruption deliberately so recovery ownership is not silently lost. It
MUST be caught at a future internal supervisory boundary, kept protected and
escalated for manual reconciliation, NEVER logged, converted with `asdict`, JSON
exported, placed in a normal job or shown as a user payload. It is not a resend
capability, and no automatic retry/reseal/release is permitted. There is no such
activated supervisory boundary or durable retainer installed in this increment.

Interruptions BEFORE a normal coordinator result exists still propagate after
owned cleanup. The observer contract MUST keep the original complete response
until explicit custody acknowledgment, including those interruptions. Tests
demonstrate that obligation with in-memory synthetic custody; neither the type
nor this facade enforces actual durability. Process death and the interval before
the first durable encrypted receipt commit remain open loss/review gates. No
end-to-end durable capture or transport attestation is claimed.

## Verification and remaining gates

The guarded selection tests exact request/target/binding/resource checks; both
permission signatures; Sales/POS and standard/simplified owner combinations;
actor/revision/ACL drift; original-response retention; literal handoff ACK,
interruption and protected recovery; ambient-parent rejection; Arabic messages;
and absence of active endpoint/transport wiring. The existing private QR SQL
suite now also composes the real pinned Unix provider, source locks, three
transactions, encrypted custody and journal append on newly owned temporary
MariaDB only. Source data, keys, permissions and observer responses are synthetic.

Run from the independent development worktree:

```sh
PYTHONDONTWRITEBYTECODE=1 ../../env/bin/python tools/run_unification_rehearsal.py --private-sql
```

The final guarded run passed **6,947 local + 731 private SQL = 7,678 cases in
73.71 seconds** (143 local + 44 private SQL additions), across the same twelve
private suites. Earlier runs passed 6,923 local in 39.44 seconds and 7,654 combined
in 72.68 seconds before the final request/status/interruption cases. No assertion
was weakened. Further verification history is in [STATUS.md](STATUS.md). No genuine
authority acceptance, installed v16, browser switch, SDK signature validity or
advance GL/VAT reconciliation is established by these tests.

Next review paired immutable custody/journal reconciliation for exact attempts
under uncertain commits, missing/late/unbound responses and source drift WITHOUT
transport, new identities or hold release. Audit namespace/key/lookup/credential
epoch/provider/observer custody and provenance before any authenticated adapter
or runtime integration. Legacy partial commits, retries, ICV continuity, full
amount/advance/crypto tests and pinned new v15/v16 benches remain gates. Follow
the [offline-first rehearsal policy](SAFETY_AND_REHEARSAL.md); neither publication
nor test success authorizes a live change or authority call.
