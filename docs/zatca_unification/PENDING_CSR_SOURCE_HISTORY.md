# Original pending CSR source-binding storage — increment 92 (development only)

## Delivered boundary

Increment 93 adds [shared permissioned initial capture and owned completion](PENDING_CSR_INITIAL_CAPTURE.md)
using the new strict `create_bound` mode. It never consults historical lookup or
adopts an existing identity. Existing low-level pair APIs below remain unchanged;
no runtime provider/button/schema is installed.

`MariaDBPendingCSRRepository.stage_bound(binding, original)` stages a **new exact
envelope and its original supplied source declaration in the same caller-owned
transaction**. `load_binding(scope, context)` loads only that exact authenticated
pair's restricted declaration. Neither method owns commit, rollback, closure,
connection acquisition, retries, SQL installation or saved-source authorization.

This is internal storage infrastructure, not a newly activated onboarding path.
No Company button, whitelist, worker, installed schema, runtime provider or
existing save/review coordinator is connected to it. Existing envelope-only
`stage`/`load`/`observe` and permissioned service/coordinator APIs retain behavior.
No key/CSR is generated or reencrypted, no active credential is written, and no
authority call is made. Source/ACL/epoch provenance remains a separate gate.

## One shared declaration, not a second access policy

The existing `PendingCSRSourceBinding` and its error type move to
`pending_csr_binding.py`, reexported unchanged by `pending_csr_access`. Constructor
arguments and identity/type checks remain compatible. Source schema 2 is shared
with the saved-source fingerprint rather than independently versioned by two
policies. The scope/manifest are copied rather than retaining provider-owned
mutable interpretations. Protected repr/pickle behavior remains.

`PendingCSRBindingRecord` stores canonical bounded bytes containing:

- binding/source schema versions;
- declared site/namespace, entire canonical manifest and selected storage key ID;
- original saved-source aggregate and opaque Password backing-state hashes;
- a domain/length-bound SHA256 over **all five exact envelope fields**.

The exact-envelope digest binds namespace, manifest bytes, key ID, nonce and
ciphertext. Resealing identical plaintext does not match the original. Strict
decoding rejects unknown/missing/duplicate keys, malformed types/base64, old or
boolean schema versions, invalid hashes, noncanonical encoding and overlong
content. No automatic schema upgrade or legacy binding recalculation exists.

## Pair creation, exact redelivery and no backfill

Within one non-autocommit connection:

1. Copy/validate the supplied declaration and original envelope; authenticate the
   original material before SQL writes. Require namespace/manifest/key agreement.
2. Lock/read the exact namespace/draft ID in the envelope and source-binding tables.
3. If both are absent, issue **plain INSERTs**, then bounded locked readback of
   both. Never use a duplicate-key no-op for new-pair creation: a concurrent
   envelope-only insert after absent reads must fail, not acquire invented history.
4. If both exist, authenticate and compare the original envelope and entire
   canonical record. Accept only an exact existing pair, with no SQL write.
5. If only one exists, reject it as unpaired. Never backfill history from current
   settings, replace a conflicting binding, reconstruct an orphan, or clear data.

The table primary key is namespace/draft ID; redundant slot/flow/site/record hash/
envelope hash columns are checked against the decoded record. Reads are bounded.
Loading also requires the exact declared site/namespace and full context (owner,
Company, purpose, environment, revision, flow, preparation time and draft ID), and
re-authenticates the corresponding envelope before returning the declaration.
There is no latest/owner/environment fallback or raw material return.

Every operation error poisons the shared repository, preserving existing static
driver-code normalization and cancellation behavior. **The owner must roll back
the entire transaction**, including an envelope inserted before a later history
write/readback failure. Repository success is not a commit confirmation. This
code neither cleans a caller's unrelated work nor guesses an unknown commit.

## Privacy, limits and next integration gate

The record contains restricted business metadata and low-entropy source/backing
fingerprints. It is **not anonymous or secret-free diagnostic output**. No new
RPC/result/log/export exposes it. SQL account grants, at-rest/backup/log custody,
field access and migration/recovery policy still require review. Repr/pickle are
guardrails, not a Python sandbox or protection against explicit serialization.

Its SHA256 is unkeyed. Coherent out-of-band modification of records and hashes
is not independently detected. Application immutability is not a database grant,
append-only audit service, authoritative source snapshot, timestamp, credential
epoch, tenant/key attestation or proof of who originally captured the settings.
No fresh source/ACL check is silently added to the low-level repository; those
remain the shared permissioned service's job. Durable preservation of a supplied
declaration is not proof that it was captured correctly or from committed rows.

Next integrate reviewed initial source/binding provisioning with the existing
owned save/review lifecycle without a second access policy, ambient parent use,
post-close borrowed lookup or automatic adoption of old unbound drafts. Establish
independent source/key/tenant/epoch evidence and a clear committed-lookup ownership
policy first. Review unknown/conflicting pairs before issuance/receipt/activation.
Installed ERPNext/Frappe 15/16, Desk/browser, SDK and authority acceptance remain
unverified. Finish development before the separately approved isolated fictional
Company rehearsal and later adoption/cancellation decisions.

## Offline evidence

Only the reviewed `pending_csr_binding` suite joins the fixed local manifest.
The existing owned private pending suite installs the accompanying SQL **only in
its temporary TCP-disabled test server**. No app fixture/patch/hook installs it.
Synthetic tests cover codec/type/identity/canonicality/privacy checks and bounded
pair operations. Native tests cover pair visibility/rollback, exact redelivery,
immutable settings/site binding, orphan rejection, corruption, readback failure,
lock timeout, a real competing envelope-only insert after absent reads, and
composition with the existing saved-source stage/inspection policy using one
explicit caller transaction. Such fixture provisioning is not runtime adoption.

The first local guarded run passed **13,884 cases in 85.45 seconds**, adding
46 local cases. Final guarded combined: **13,884 local + 1,949 private SQL =
15,833 passed in 168.92 seconds**, across thirteen private suites, including
**70 new cases** (46 local + 24 native SQL). All nine Node VM scripts passed
**1,444 cases**. No resource/ordinary-ACL/crypto/transport assertion was waived;
this does not establish installed v15/v16 or remote acceptance.
