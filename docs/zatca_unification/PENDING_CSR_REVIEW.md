# Read-only pending CSR outcome review — increment 91 (development only)

## Purpose and ownership

Increment 94 adds a separate [owned source-binding pair review](PENDING_CSR_BOUND_REVIEW.md)
which reads stored history only through its new owned lease and never invents
missing historical agreement. The envelope-only API below is not replaced.

`PendingCSRStagingTransaction.observe` reviews an independently retained original
sealed draft on a **separately supplied fresh owned lease**. It does not call
`save`, `stage`, `commit`, key/CSR generation, resealing, activation or HTTP. It is
internal and uninstalled, not a new Company button, whitelist or automatic
recovery job. Existing caller-owned stage/inspect and owned-save behavior remain.

The caller must retain the same original namespace, draft/flow IDs, manifest,
key ID, nonce and ciphertext after a failed or interrupted save. A new lease and
coordinator are required; the failed owner is never reused. Fresh ownership uses
the same concrete pinned Unix provider, acquisition checks and cleanup policy as
the [owned save coordinator](PENDING_CSR_TRANSACTION.md).

## Shared checks and exact observation

The existing saved-source service supplies the complete role/site/actor and normal
target READ+WRITE/related Company READ policy. No historical-access exception,
permission bypass or alternate owner/environment lookup is introduced. The exact
server binding must still match current source revision/configuration, schema,
source/backing hashes, owner, environment, manifest and storage key ID. Source or
credential changes fail closed; this review cannot repair their historical link.

The repository authenticates the retained original even when no row exists, then
performs a bounded exact namespace/draft-ID locked SELECT. It returns only:

| Observation | Meaning at the checked transaction boundary |
| --- | --- |
| `EXACT_OBSERVED` | The authenticated stored envelope equals every original field |
| `ABSENT_OBSERVED` | The exact SELECT returned no row; not a caught error |
| `CONFLICT_OBSERVED` | A different, internally valid authenticated envelope occupies that draft ID |

Resealing identical plaintext is a conflict, not exact redelivery. Stored bytes,
manifests, digests and material are never exported by this review. Corrupt rows,
unknown keys, invalid tags, timeouts, malformed results or SQL errors fail without
an observation. Errors poison the repository; real absence/conflict do not.

Before releasing locks, the shared completion guard rechecks current source,
permissions and exact server binding, locked source/Password backing state, and
the same exact/absent/conflict classification. Conflicting contents are never
adopted as the original. Stability means classification stability, not identity
of the other conflicting envelope. Exact comparison always uses the original.

The owner attempts one rollback of its read transaction, then one close, followed
by current visible source/permission/binding checks. Only then does it disclose
`PENDING_CSR_LOCAL_REVIEW_OBSERVATION`, `envelope_observation` and
`local_read_transaction_closed=True`. It does **not** report a save completion.
All epoch/provenance/storage/remote/activation/dispatch proof/authority flags stay
false. Cleanup failure withholds metadata; uncertain rollback/close is not retried.
Both cleanup operations are attempted where appropriate, with interruption
priority. The ambient Frappe transaction is never committed, rolled back or closed.

## Presentation and limits

Child source/SQL/cleanup messages are muted. One comprehensive redacted failure
is translated only for display, including Arabic; English keys/states remain.
Interruption propagates after owned cleanup without a popup. No new logs or raw
driver/source/key diagnostics are exported. Protected input and trace locals
still require field/log custody; this is not a Python security sandbox.

This is a current local observation, **not proof of a prior commit outcome**, a
permanent absence guarantee, historical binding discovery, permission-table lock,
authoritative credential epoch or remote status query. The original transaction
may still be in flight; a lock wait fails unconfirmed rather than proving absence.
Isolation/missing-row behavior, source caches, ABA, out-of-band writers, trusted
callback side effects and post-close changes remain limitations. No second SQL
connection is opened after close to claim continued backing-state identity.

None of the three observations authorizes retry, replacement, new IDs/material,
remote submission, issuance or activation. Historical binding provisioning,
independent tenant/key/source/epoch provenance and an explicitly reviewed policy
for resolving conflicts or absence remain gates before issuance integration.
Installed ERPNext/Frappe 15/16, Desk/browser, SDK and authority acceptance remain
unverified. Finish development before a separately approved isolated fictional
Company rehearsal and later adoption/cancellation decisions.

## Offline evidence

Only existing fixed-manifest local/private suites are extended. Synthetic cases
cover exact/absent/resealed conflicts, invalid original/corrupt stored data,
source/backing/binding/observation drift, both permission signatures, Password
profiles, cleanup/interruption/reentry, single-popup Arabic display and no writes.
Owned temporary TCP-disabled MariaDB cases verify real visibility after ambiguous
save commits, read-only outcomes, corruption rejection, rollback of injected test
mutations and lost cleanup acknowledgments. Runtime stage/commit methods are
trapped during native review. No tenant, live application or authority is touched.

The local-only guarded runner passed **13,838 in 81.98 seconds**. Final guarded
combined: **13,838 local + 1,925 private SQL = 15,763 passed in 166.97 seconds**,
across thirteen private suites, adding **87 cases** (67 local + 20 native SQL).
The four existing native ambiguous-save/late-denial cases also exercise fresh
read-only review of the unchanged original. All nine Node VM scripts passed
**1,444 cases**. No resource/ordinary-permission/crypto/transport assertion was
relaxed, and none of these tests represents installed v15/v16 or remote acceptance.
