# Exact auth-free primary observation coordinator — increment 52

## Delivered scope and non-activation

`PrimaryCaptureCoordinator` composes the existing strict logical-source hold,
exact journal and encrypted receipt custody over three owned SQL transactions.
It invokes an explicitly supplied OBSERVER once, not an installed authenticated
HTTP adapter. Tests use synthetic observers only. No sender, API/whitelist,
Frappe hook, job, permission endpoint, site/key/credential discovery or runtime
provider is registered. No authority endpoint, including Sandbox, was called.
No working source/configuration/schema/assets/workers/customer data was changed.

This is a low-level protected server primitive, not an operator JSON endpoint or
permissioned raw export. A reviewed server must authorize scope, saved source,
keys, epoch, owned acquisition and observer before use. The mandatory supplied
guard is a dependency, not evidence that permissions/provenance were really
checked. No existing primary API, scheduler or real invoice uses this coordinator.

## Exact request and response declarations

`PrimaryCaptureRequest` rebuilds/detaches an exact started journal and derives a
deterministic version-1 JSON byte body containing exactly `invoiceHash`, `uuid`
and Base64 of the candidate's EXACT XML bytes. Sorted keys/fixed separators/ASCII
encoding are part of that local codec. UUID/digest come from the same immutable
candidate; XML is not normalized, resigned or regenerated. The body SHA-256 and
codec are saved in a strict new request-binding row WITH the start and hold.
Only hashes/codec/identities are added, not another plaintext body/auth copy.

The body can be reconstructed from archived XML using codec 1, then checked
against the stored hash. Serializer drift or a changed request binding cannot
silently pass preflight. This does not archive authorization headers or prove
that the body reached any remote server. `invoiceHash` is the existing observed
digest declaration, NOT a new cryptographic validation. No certificate hashing,
SignedProperties/signature, QR, accounting or advance calculation was changed.

The request deliberately has NO credentials or headers. Its URL/epoch/source are
still declarations from the candidate. A future approved adapter would have to
bind authentic material and use these exact bytes, not reserialize with `json=`;
it is not implemented, approved or activated here.

`PrimaryObservedResponse` supplies exact bounded bytes, status, UTC receipt time,
event ID, optional request ID AND declared request-body hash/attempt ID. These must
match the pinned request; constructing the retained journal also rejects a reused
event ID or receipt time before the start. An independent nested request snapshot
is handed to the observer. This limits accidental mutation, not malicious Python.
A dishonest observer can fabricate matching correlation: TLS/transport/authority
origin, credentials, historic source and acceptance remain UNVERIFIED.

## Owned lifetime and states

1. **Reservation transaction:** guard, strict atomic first-event/hold reservation,
   strict request-binding insert/readback, guard, commit AND close. Any error or
   unknown acknowledgment prevents observer invocation. The start/hold/binding
   roll back together when no commit occurred; a lost acknowledgment can instead
   leave them durably spent.
2. **Preflight transaction:** guard, exact hold/request-binding checks, require the
   journal still equal the original start, guard, commit AND close. Any uncertainty
   prevents observation but does not release the prior hold. No SQL lock survives
   the callback. No same-call retry, resume or existing-reservation adoption exists.
3. **One observer invocation:** return an independent complete typed response.
   Errors/malformed values mean unknown, not remote rejection. A complete but
   unbound response is retained privately for review, never forced into a receipt.
   A bound response becomes an exact retained HTTP event and is sealed ONCE.
4. **Receipt transaction:** guard, recheck hold/request binding and exact eligible
   predecessor, stage the SAME encrypted envelope and append the SAME event in
   the SAME owned transaction, guard, commit AND close. Failure after custody or
   after event append rolls both back if not committed. Lost commit/close
   acknowledgment retains the exact response/receipt/envelope, with no second
   observer or reseal.

| Returned state | Observer calls | Protected recovery material |
| --- | --- | --- |
| `RESERVATION_UNCONFIRMED_NO_OBSERVER` | 0 | Exact request; reservation may or may not exist |
| `PREFLIGHT_FAILED_NO_OBSERVER` | 0 | Request and previously spent durable hold |
| `OBSERVER_OUTCOME_UNKNOWN_NO_REPLAY` | 1 | Request; no complete trusted-shape observation |
| `RESPONSE_UNBOUND_NO_REPLAY` | 1 | Complete supplied response, no forced receipt |
| `RECEIPT_PREPARATION_UNCONFIRMED_NO_REPLAY` | 1 | Response and exact retained receipt |
| `RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY` | 1 | Response, receipt and original sealed envelope |
| `RECEIPT_CAPTURED_OBSERVATION_NO_REPLAY` | 1 | Same protected material after local commit/close |

These are local observations, NOT authority acceptance/dispatch/replay states.
All provider/historic-source/epoch/transport/remote/acceptance/dispatch/replay
verification/authorization flags stay false. A 200/202/409/4xx/5xx or success-like
body does not change that. No automatic UNKNOWN event/time/ID is invented on an
observer failure. No hold is expired, released or reset by any response.

Results and request/response/coordinator objects have hidden reprs and reject
pickle. Diagnostics show only static states/flags, not identifiers, bytes, URL,
keys or callback errors. Never log/asdict/queue/operator-export protected objects.
Argument errors are static unchained codes. BaseException interruptions propagate
after owned cleanup; an interruption during the observer has no open owned SQL
transaction but leaves the earlier hold spent.

## Limits before integration

Added **164 local + 39 private SQL cases**. The final guarded combined run passed
**6,804 local + 687 private SQL = 7,491 cases in 73.32 seconds**, across the same
twelve owned-private SQL suites. First local passed 6,777 in 35.91 seconds; first
combined passed 7,460 in 67.64 seconds. Expanded negatives/competing coordinators
passed 7,491 in 70.21 seconds before final import organization. No test failure
required relaxing reservation, correlation, guard, custody or rollback assertions.
The guard denied external network/site initialization and allowed fixture-owned
Unix SQL only; it is process-local accidental-I/O protection, not an OS sandbox.

Actual private SQL tests check committed start/hold/body binding from independent
connections while the observer sees ALL coordinator handles closed, atomic
ciphertext/journal storage and rollback after a real append, both commit outcomes
with synthetic acknowledgment loss, pre/post-observer request/journal drift,
unknown-codec reservation rollback, guards and same/different-candidate races.
No new message/UI/translation is installed: these are internal states/codes only.

The factory MUST supply fresh owned non-autocommit connections and own failed
acquisition cleanup. This low-level coordinator does not recognize every possible
borrowed Frappe handle, authenticate provider/site/namespace origin or implement
a saved-ACL/key-custody facade. The previous optional pinned provider and saved
access primitives are not automatically registered by composition here. Permissions
can change after locks close; a future permissioned wrapper must also control
result disclosure after closure. A trusted callback/guard is not a process sandbox.

Current stored source/epoch declarations and digest do not prove historical tax
amounts, signature validity, Production certificate lifecycle or remote delivery.
No installed v16, actual TLS/HTTP adapter, browser/worker crash, SDK golden or
authority acceptance is established. Synthetic 388/381/383/386 fixtures exercise
classification/transaction behavior, not valid advance settlement/GL/VAT examples.

A process loss before the FIRST durable encrypted receipt commit can still lose
the response; the start/request/hold survive but do not prove remote failure.
If UNKNOWN or a different response arrives concurrently, the original response
is not silently resequenced or attached to another revision; retain and review it.
Paired exact receipt reconciliation, lost/late policy and authenticated transport
attestation remain separate work. An uncertain result is not permission to call
`capture()` as a retry; strict reservation prevents reuse of an existing start.
The existing live retry paths/partial parent commits are NOT fixed or activated
by this module. Historical renames/aliases/scopes still need controlled mapping.

Increment 53 adds the internal [permissioned saved-source/resource boundary](PRIMARY_CAPTURE_ACCESS.md)
with metadata-only output and mandatory protected-result handoff before final
ACL checks. It does not install a durable retainer, observer or transport.
Next: paired exact-attempt custody/journal reconciliation and audit credential/source/
epoch/transport provenance and paired reconciliation before any runtime adoption.
Complete isolated v15/v16/SDK/accounting/browser acceptance and the fictional-client
decision first; ALL authority calls remain prohibited without separate approval.
