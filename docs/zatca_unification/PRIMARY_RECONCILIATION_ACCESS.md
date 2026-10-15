# Permissioned local primary pair access — increment 55

## Internal scope, not deployment

`SavedPrimaryReconciliationService` adds saved-source/owned-resource access to
[exact local pair reconciliation](PRIMARY_RECEIPT_RECONCILIATION.md). Both
`inspect` and `persist` accept an ORIGINAL protected request and envelope from
a trusted SERVER caller and return diagnostics ONLY. No browser endpoint,
whitelist, runtime caller, provider/key registration, hook/job/UI, schema, HTTP,
observer, resealer or automatic follow-up is installed. ALL authority requests,
including Sandbox/Simulation, remain prohibited; the working app is unchanged.

The caller MUST retain both original inputs independently on failure, final
denial, interruption or uncertain commit. Unlike primary capture, this operation
generates no new response/envelope requiring a new custody handoff. It cannot
recreate lost bytes. No acceptance/status, UUID/ICV, PIH, QR/signature, advance
lookup/age/allocation, GL/VAT or existing runtime retry behavior changes here.

## Reused source/access policy

A non-Guest System Manager/Administrator must operate on the exact declared
site. Both methods require quiet direct WRITE ACL on saved Sales/POS Invoice and
READ ACL on its Company and selected device/linked Company. This checks whether
the actor may write the invoice; it DOES NOT save or change invoice fields.
`ignore_permissions` cannot bypass direct ACL. The shared engine retains existing
owner/route/environment/issuing-unit/UUID/ICV/submitted-source checks and the
v15/v16-shaped quiet permission compatibility adapter. Current status is captured
for drift but is neither a pair-access gate nor remote acceptance evidence.

Actor/site/role checks precede input processing and saved reads. The request is
rebuilt/detached, structural envelope/start references are validated and target
DocType/name/namespace must match BEFORE saved lookup. Saved source/related ACL
precedes an explicit server lookup binding. No latest/search/current-credential
fallback or cross-owner historical permission bypass exists.

## Exact declaration before keys

`PrimaryReconciliationBinding` reuses capture's request/start binding: scoped
candidate context, UUID/ICV, START journal hash, attempt, encoded START event
hash, deterministic request-body hash and custody key ID. It additionally pins
the retained payload hash and the ORIGINAL full encrypted-envelope fingerprint.
All must match BEFORE the scoped key provider or owned SQL factory is invoked.

`sealed_envelope_sha256` is a domain-separated SHA-256 declaration of all six
envelope metadata fields, a length-framed deterministic ASCII JSON header, the
fixed-length nonce and exact remaining ciphertext. It requires a valid bounded
envelope but does NOT decrypt, discover keys, seal, sign, generate AAD or change
invoice/certificate/SignedProperties hashing. Changing ANY field or re-encrypting
equal plaintext produces a different declaration and cannot silently substitute
for the pinned original. Hash equality is not remote/historical authenticity.

The key provider must return exact typed `PrimaryReceiptCustodyKeys` for the
same site/namespace/key ID. The core authenticates the full retained payload and
its exact START predecessor before acquiring SQL. Wrong keys/scope/type and
forged envelopes fail before SQL. Independent trusted lookup/retainer/key origin
is a future audit requirement: constructing a declaration from supplied values
does not prove those values are historically original.

## Owned transaction and final disclosure

The service reuses the shared fresh-owned acquisition helper. Recognizable
ambient Frappe handles and raw parents are rejected without rollback/commit/close
on those borrowed handles. Arbitrary wrappers remain trusted factory obligations;
types and current permissions are not ownership/provisioning attestation.

The same exact request/envelope declaration and saved actor/source/ACL are
checked around bounded saved-row SQL locks, before and after pair work, on ONE
owned connection. Core reconciliation requires the existing exact logical-source
hold and persisted request codec/hash. No hold/start is invented or released.

Inspection rolls back/closes without commit. Explicit LOCAL persist may store
both absent response parts atomically, or recognize an already identical pair.
Partial/different/UNKNOWN pairs remain review-only with no half repaired.
Unreadable records or acquisition/commit/cleanup uncertainty return unconfirmed
diagnostics, never evidence of remote non-delivery or permission to resend.

After owned cleanup, the exact envelope binding, actor/site/role/source/ACL are
checked AGAIN. Any drift refuses even diagnostics with static translated
unchained errors. A final denial cannot undo a previously completed commit; the
caller still has the original inputs. Interruptions propagate after owned cleanup
without dropping that caller-owned material. SQL locks do not atomically lock
permission tables or establish full accounting/settings/historical snapshots.

Only `diagnostic_projection()` is returned: no plaintext, ciphertext, request,
response, invoice name/UUID, key ID, source fields or hashes. All origin/epoch/
transport/acceptance/dispatch/replay flags remain false. Declaration/resources/
service reprs are protected and pickling is forbidden. Do not log/serialize the
original input objects, convert them with `asdict` or place them in normal jobs.

## Verification and remaining gates

The guarded local suite uses real encryption and synthetic saved rows/ACL/owned
SQL models, covering both permission signatures, Sales/POS, standard/simplified,
Company/device/linked owners, exact bindings before keys, substituted seals,
wrong crypto keys, source/actor/ACL drift, cleanup/interruption, borrowed parents,
false current-status authority, metadata privacy and English/Arabic errors.
The existing private QR SQL suite composes the real pinned Unix provider and
source locks with actual pair storage/rollback, uncertain commits and post-close
denial. Keys, source data, permissions and observer responses remain synthetic.
No genuine authority or installed-v16/SDK/browser acceptance is claimed.

```sh
PYTHONDONTWRITEBYTECODE=1 ../../env/bin/python tools/run_unification_rehearsal.py --private-sql
```

The final guarded run passed **7,392 local + 871 private SQL = 8,263 cases in
96.44 seconds**, across the same twelve private suites (322 local + 98 private
SQL additions). Initial local passed 7,364 in 49.63 seconds and first combined
passed 8,235 in 95.97 seconds before added current-status/interruption cases.
No comparison, namespace, permission, rollback or ownership assertion was
weakened. Full verification history is in [STATUS.md](STATUS.md).

Increment 56 adds [writer/late-response evidence and pure bounded review](PRIMARY_WRITERS_AND_REVIEW.md),
without runtime integration. Actual single-store helpers can leave a partial
window; independent late observations are not the strict START-only pair input.
Next isolate local logging failures for received error/rejection statuses and
continue reviewing independent custody/journal writers and lost/late/unbound/partial-response policy, without
enabling automatic repair, sending or hold release. Audit independent key,
retainer, lookup, namespace, credential-epoch and provider/transport provenance
before wiring these staged components. Pre-first-durable-response process loss,
legacy retries/partial commits, ICV continuity, actual crypto/QR/advance accounting
consolidation and pinned new/upgrade v15/v16 benches remain unfinished. Follow
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md): finish development, separately
approved isolated fictional-client rehearsal, then the user's adopt/cancel and
gradual pilot decisions. Publication is not deployment or authority permission.
