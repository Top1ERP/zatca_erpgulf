# Encrypted local retained-receipt custody — increment 49

Increment 50 adds an optional [permissioned owned-transaction wrapper](PRIMARY_RECEIPT_CUSTODY_ACCESS.md)
with ciphertext-only retrieval. It is not installed, does not attest transport/
historical provenance and does not authorize HTTP or relax this repository's rules.

## Delivered boundary, not runtime integration

`primary_receipt_custody.py` adds a protected binary codec, dedicated AES-256-GCM
cipher and immutable MariaDB repository for `RetainedPrimaryReceipt`. The stored
input can later be reconstructed exactly for the existing LOCAL persistence
primitive. No HTTP request, attempt/start creation or journal append occurs here.

The repository is not installed, registered or used by primary APIs, jobs, hooks,
buttons or an operator endpoint. The table in `rehearsal_schema.sql` is created
ONLY in fixture-owned temporary servers. No site database/configuration, customer
credential, installed source, assets, workers or authority endpoint was touched.
No accounting, advance eligibility/amounts or QR/signing behavior changes.

## Exact data and encryption

Seven bounded length-prefixed binary frames carry namespace, candidate context,
exact XML, start metadata, optional UNKNOWN metadata, response metadata and exact
response bytes. Empty HTTP body remains present bytes, not absent response.
Rehydration uses the existing candidate/event/journal codecs and rebuilds the
retained contract. Truncation, oversized frames, trailing data and noncanonical
representations fail with static errors. A valid alternative declaration is not
detectable by structural parsing alone: the plain codec is NOT authentication.

AES-GCM authenticates namespace, candidate key, attempt ID, predecessor journal
hash, entire framed-payload hash and key ID with a separate versioned domain.
Opening revalidates the envelope, verifies the tag and reconstructs/rechecks every
binding. A matching ciphertext tag proves possession of the supplied local key,
NOT that an authority sent the response or that the declared historic tenant,
source revision, certificate epoch or transport is genuine. A key holder can
construct valid observations; no remote/acceptance/replay flag is promoted.

Keys are explicit, copied caller-supplied dedicated 32-byte material, not a CSID,
signing key or discovered site secret. Independent keys from Compliance archives,
credential storage and other domains/namespaces are a provisioning requirement.
Random 96-bit nonces and domain AAD are not a global key/nonce custody solution.
The table's unique `(key_id, nonce)` rejects collisions within that table, including
across namespaces; it cannot enforce other stores, deployments or aliased key IDs.
KMS/provider permissions, key separation, volume/rotation, backups and recovery
remain separate release gates. No Python secure-erasure claim is made.

## Transaction contract

`MariaDBPrimaryReceiptCustodyRepository(connection, namespace, cipher)` receives
an explicit caller-owned transaction. It does not discover connections or commit,
roll back, close, change schema or mutate invoice/File/status/PIH/counters.

- `stage(sealed)` authenticates and checks namespace before SQL, rejects
  autocommit, then locks/loads the existing candidate journal. Only the EXACT
  retained predecessor or its identical already-recorded HTTP result is allowed.
  A missing/empty/different attempt is not implicitly created or adopted.
- One envelope is retained per namespace/candidate/attempt. A duplicate SQL clause
  writes the same key to itself, then the full authenticated stored envelope must
  equal the supplied envelope. Changed body/event or resealed identical plaintext
  is a conflict, not an overwrite. Nonce conflicts cannot silently discard input.
- `load(candidate_key, attempt_id)` selects exactly within the explicit namespace,
  bounds ciphertext reads and authenticates before returning protected ciphertext.
  There is no latest/search/list/export/delete/cleanup fallback.
- Retrieval deliberately does not reinterpret today's ERP settings or require
  today's journal to match. It preserves old evidence when a revision drifts;
  the later receipt-persistence service STILL rejects an ineligible predecessor.
- Any ordinary operation error poisons the repository and returns a static error
  without original exception context. Interruptions poison and propagate. The
  caller must roll back the WHOLE transaction and discard it after an error.

Returning an envelope is NOT a durable acknowledgment. The caller must complete
commit AND close and retain its exact envelope on uncertain outcomes; explicit
identical LOCAL redelivery can confirm storage without resealing or HTTP. The
repository has no owned transaction coordinator, permissioned raw retrieval API,
durable review-hold scheduler integration or attested transport capture.

## Crash and lifecycle limits

Actual owned-server crash tests distinguish committed from uncommitted ciphertext:
the former is recoverable on a fresh connection; the latter is absent. This is
MariaDB process/recovery evidence, not a full Python worker/browser/queue crash
test or disaster-recovery proof. The test server uses durable commit settings,
but production storage/hardware/replication cannot be inferred from that fixture.
Simulated ambiguous-commit cases exercise explicit identical local redelivery for
both actual outcomes, not real authority responses or network acknowledgments.

A response lost before the FIRST successful durable custody commit cannot be
recovered from this table. An uncertain commit may or may not have stored it.
No automatic resend is allowed by this primitive; the future coordinator must
retain a durable no-replay review hold and define lost/late-response policy.
Failure of source/permission checks after a remote response must not be treated
as proof that the remote request failed. This repository alone does not solve it.

The existing journal can still contain unencrypted XML/response bytes; this change
does not retroactively encrypt that store or migrate historical rows. Ciphertext
and metadata remain sensitive, and require access restrictions, backup protection,
retention/space limits and an approved lifecycle. No cleanup/deletion or migration
policy is activated. Python private attributes are not a hostile-process boundary.

## Offline evidence and next gate

Added **121 local + 37 private SQL cases**. The final guarded combined selection
passed **6,252 local + 547 private SQL = 6,799 cases in 58.24 seconds**, across
the same twelve owned-private SQL suites. The first corrected local run passed
6,250 in 30.40 seconds; the first combined run passed 6,790 in 58.89 seconds
before the final namespace/drift/conflicting/missing-attempt cases were added.
The guard denied external network/site initialization and allowed fixture-owned
Unix SQL only; it is process-local accidental-I/O protection, not an OS sandbox.
Actual SQL used Python 3.10/MariaDB 10.11; full installed v16, browser, SDK and
authentic authority acceptance remain unverified.

New unit cases exercise exact bytes across HTTP statuses/empty/binary responses,
optional UNKNOWN, frame bounds, AAD/tag/key/domain/payload tampering, authenticated
metadata misbinding, no SQL before validation, poisoned transactions, hidden
immutable/nonpickleable objects and unchained errors. Existing native journal SQL
tests add custody roundtrip, committed/uncommitted owned-server crashes, identical
redelivery, competing writers at both isolation levels, nonce collision, scope
isolation, corruption, conflicting responses, missing starts and later journal drift.

The first local run exposed nine exception-context leaks through a generator
contextmanager and one incorrect test assumption that a structurally valid changed
namespace must fail plain decoding. The implementation now uses a normal guarded
callback to eliminate original error context; the frame test uses invalid bytes,
and a separate test explicitly proves structural parsing is NOT authentication.
No confidentiality assertion or authentication check was weakened.

Next: a reviewed permissioned custody/owned-transaction boundary with audited key
and connection provenance, followed by exact transport-source-epoch capture and
durable no-replay holds before any primary integration. Continue to keep runtime
activation, actual v15/v16/SDK/accounting/browser acceptance, fictional-client
approval and ALL authority calls gated under the existing user restrictions.
