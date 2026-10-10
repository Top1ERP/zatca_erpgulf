# Single-use Compliance capture scaffold — increment 24

## Delivered boundary, not a deployed trusted transport

`compliance_capture.py` adds an internal two-transaction coordinator. It accepts
explicit server-owned connection/clock/transport dependencies, obtains the exact
staged version, derives the authentication header from that encrypted version,
reserves an exchange identity, closes the first transaction before invoking its
transport dependency once, then stores a bound immutable response.

There is NO default HTTP sender, Frappe provider, permissioned capture endpoint,
runtime button adoption, schema installer, active selector or live API call.
Tests use a fake transport even when they use real private SQL. Supplied callbacks
are not proven trusted transport, clock, source or CSR issuance provenance. All
source/epoch/remote/completion/dispatch/activation/replay authority remains false.

The low-level coordinator is NOT an operator boundary. The calling server must
enforce tenant/role/saved-source permissions and reviewed transactional settings
before construction/invocation. Increment 23's inspection service is read-only;
it does not grant permission to call this collector or supply its dependencies.

## Why reservation differs from idempotent archive preparation

Increment 22's `prepare` accepts exact encrypted-envelope redelivery. That is
correct for storage, but is not permission to send the request again. The new
`reserve_request` uses a strict INSERT with the existing namespace/exchange/
sequence primary key. ANY existing identity or nonce collision fails closed,
including an identical envelope. A duplicate poisons the repository transaction;
the whole transaction must be rolled back and the handle discarded.

No DDL change is required. The committed request row is also the conservative
single-use reservation. Existing observational rows block coordinator dispatch;
they cannot be adopted retroactively as permission to send. The first successful
commit consumes the identity, even if a crash/clock/preflight error prevents HTTP.
This sacrifices automatic retry to avoid duplicate sends after ambiguous outcomes.

The guarantee is one coordinator transport-dependency invocation per retained
namespace/exchange identity. It is NOT one invocation per invoice UUID, step,
device, account or onboarding flow. Another explicit identity is another attempt;
cross-attempt policy/outbox/leases remain gates. The callback itself could retry or
ignore arguments: the coordinator cannot prove what an unreviewed dependency did.
Privileged deletion of reservation rows is not detected by this store; protected
durability, access, backup/recovery and cross-attempt policy are deployment duties.

## Transaction and material order

1. Validate exact requirements/namespace/request/route/identity before acquiring
   storage. Obtain explicit UTC time from the supplied clock, never a hidden clock.
2. Encrypt the start once. Acquire a fresh OWNED non-autocommit connection. Load
   and authenticate the exact staged slot/version; compare full manifest bytes.
3. Open the SAME stored bundle at preparation time, not historical audit time.
   Validate local certificate validity, exact certificate/key, Company/owner/
   source kind, Compliance purpose and exact stored route against the request.
4. Strictly reserve the encrypted start in that transaction. Commit AND close
   must return successfully before proceeding. Neither SQL locks nor this owned
   connection are carried across the transport invocation.
5. Reopen the same exact envelope at a fresh clock time. Recheck local certificate
   validity and an explicit 30-second maximum preparation age; backwards time
   or stale preparation leaves a spent reservation without sending.
6. Construct a protected request whose body is the original validated JSON bytes
   and whose Authorization is derived from the stored snapshot, not a caller
   header. Invoke the explicitly supplied transport callable once.
7. Require an exact bounded response object: integer HTTP status 100–599 and
   bytes up to the existing 8 MiB bound, including b"". Get explicit UTC receipt
   time, revalidate request/type/response binding and encrypt the receipt once.
8. Acquire a SECOND fresh owned non-autocommit connection, append the bound
   immutable receipt, commit and close. Return protected recovery material with
   metadata-only diagnostics. A received rejection is stored, not called success.

The factory MUST NOT return a shared Frappe transaction or borrowed connection:
unlike the repositories/operator inspection service, this coordinator owns its
acquired connections and explicitly commits/rolls back/closes them. Factory
ownership and database origin cannot be established by a Python shape check.
Failed acquisition cleanup belongs to the factory. SQL failure triggers
best-effort whole rollback and close; commit or close uncertainty never triggers
HTTP. Cleanup failure cannot establish successful resource release.

The stored route and Company declarations are checked for consistency, not
against a current atomic Frappe settings/permissions snapshot. Local certificate
validity is not trust/revocation, remote authorization or an active epoch. Exact
CSR key equality still does not prove this CSR caused issuance of this certificate.

## State and unknown-outcome behavior

| State | Meaning | Automatic resend |
| --- | --- | --- |
| PREPARATION_UNCONFIRMED_NO_SEND | Validation/storage/duplicate/commit/close stopped preparation | Never |
| DISPATCH_PREFLIGHT_FAILED_NO_SEND | Committed start exists, but fresh material/time check failed | Never |
| TRANSPORT_UNKNOWN_NO_REPLAY | No complete timed/bound receipt; start remains spent | Never |
| RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY | Response obtained; receipt storage/commit/close uncertain | Never |
| RECEIPT_CAPTURED_OBSERVATION | Both transaction calls completed; supplied response stored | Never |

`RECEIPT_CAPTURED_OBSERVATION` is not a PASS indicator or verified remote receipt.
HTTP 401/400/empty bodies can be captured successfully as rejected/unconfirmed
observations. Existing strict assessment supplies the nested diagnostic outcome.

On receipt persistence failure, `ComplianceCaptureResult` retains the EXACT
encrypted receipt and response privately for explicit reviewed persistence
reconciliation, not another HTTP call or resealing. The local SQL tests reconcile
that same ciphertext both when the original commit happened and when it did not.
No automatic reconciler, late-response adoption or durable recovery queue exists.
Process loss after HTTP but before receipt commit can lose the in-memory receipt,
leaving only the spent request. Review remote outcome; do not infer acceptance or
retry from that reservation. Unknown prepare commit cannot cause HTTP in that
invocation, and a committed start blocks later attempts using the same identity.

BaseException paths release acquired SQL resources where possible and propagate;
the coordinator does not turn process termination into permission to replay.
Errors from SQL/providers/transport are reduced to static states. Bad input uses
a static internal error outside its exception handler, without secret-bearing
exception chaining. Future operator adapters must translate and safely render it.

## Transport and privacy gates

The protected request exposes its original body, destination and derived headers
only to the trusted server transport dependency. It is frozen, hidden from repr
and unpickleable. Response/result/cipher/credential material are likewise never
queued, logged, rendered raw or serialized with vars/asdict/custom serializers.
Diagnostics do not return the URL, tax ID, CSR, certificate/token/password, private
key, request ID, invoice UUID, raw bodies, nonce or ciphertext. Python memory
erasure and resistance to a server administrator holding keys are not provided.

A future approved transport must verify TLS/hostname and destination policy,
disable redirects/retries/ambient proxy or authentication discovery, preserve the
exact prepared body/header and bound response reading/time. The request asks for
identity content encoding; the adapter must define/reject unexpected encodings
rather than silently treating decompressed text as original wire bytes. The
[Requests prepared-request/TLS/streaming guidance](https://requests.readthedocs.io/en/latest/user/advanced/)
describes these mechanisms for a future adapter; this increment does not install
one or claim those network protections were exercised. Actual wire header/body
and TLS/source attestation are not captured by supplied callback results.

## Verification and next gate

137 new local cases cover six types/three environments, exact snapshot-derived
headers and original bodies, two transaction boundaries, duplicate reservation,
failures before/after commit, close errors, transport/clock unknowns, local validity/
age checks, static source/route/version binding, response bounds/empty bodies,
protected recovery envelopes, process interruption/cleanup, privacy, no discovery
and no replay callbacks.

17 new owned-private MariaDB cases cover committed visibility/no held locks before
fake transport, actual competing collectors at both isolation levels, pre-existing
observations, strict duplicate/rollback behavior, ambiguous first/second commits,
exact receipt persistence reconciliation and owned-server crash recovery. No
tenant socket/host override or real network sender is used by this fixture.

The selected suite passes **3,424 local + 106 private SQL = 3,530 cases**.
Private split: 25 journal, 30 bundle/service, 34 archive/service, 17 capture cases.
Increment 25's [opt-in HTTPS adapter](COMPLIANCE_HTTPS.md) adds 191 local and four
private SQL cases, reaching **3,615 + 110 = 3,725 cases**, with synthetic HTTP
pools only. It is not a default/deployed transport or trusted provenance collector.
Commands are in [STATUS.md](STATUS.md). No real OTP/CSID/HTTP, SDK/golden signature,
browser, restored Frappe application, or ERPNext 16 runtime was tested.

Next: reviewed tenant/key/owned-connection providers, permissioned transactional
source binding, integration of the new opt-in adapter with actual TLS/transport evidence,
CSR issuance provenance and explicit unknown-outcome reconciliation. Then rehearse
v15/v16 sites before proposing epoch activation or runtime adoption. Key/schema/
off-host recovery review, pilot approval and prior live-change notice are required.
