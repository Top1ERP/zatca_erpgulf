# Permissioned local receipt recovery — increment 29

## Delivered boundary, not runtime adoption

`StagedComplianceReceiptRecoveryService` authorizes one explicit retained
uncertain-commit receipt before invoking a server-owned key/resource provider.
This is an internal opt-in server service, NOT a whitelisted API, UI button,
worker, schema installer, durable queue, active CSID selector or HTTP sender.
Inputs and results are protected objects, not operator JSON or client bodies.

Resource construction accepts only the bound scope, independent bundle/archive
ciphers and a fresh OWNED non-autocommit connection factory. There is deliberately
no transport, current clock, signing-key selection, destination override or new
request identity. Provider/key/connection provenance still needs a separately
reviewed deployment; Python shape checks do not attest custody or tenant origin.
The [no-working-environment/no-authority-send restriction](SAFETY_AND_REHEARSAL.md)
remains absolute. No running Frappe site/provider or live database is involved.

## Shared saved-source policy

Capture and recovery now reuse `_SavedComplianceSourceService` rather than
duplicating saved owner, identity, read/write ACL and revision checks. Its private
selection closure and projected rows are ephemeral; do not queue/log/export them.
The existing [capture source/permission contract](COMPLIANCE_CAPTURE_ACCESS.md)
still governs Company, Sales Invoice, POS Invoice, own-device and linked-owner
selection. Read only the saved non-secret projection, not legacy credentials.

Require the bound site, non-Guest System Manager (or Administrator) and direct
permission-engine read AND write access on every selected source/device/linked
Company row. Never bypass via `ignore_permissions`, `in_test` or Document helpers.
The shared signature adapter still requires literal True and uses the reviewed
version-shaped quiet Frappe 15/16 call; this is not booted ERPNext 16 acceptance.

Validate the protected result's exact type, stage, namespace and bindings before
key acquisition. Require current saved Company/owner/source kind/environment and
CSR Tax ID to match the retained requirements, and the FULL currently selected
Compliance route to match the historical route. No latest/version/environment
or linked-owner fallback is allowed. A changed saved route or owner requires a
separately reviewed historical recovery policy; the service does not silently
remap a receipt. It does not select today's active credential.

Source rows/revisions captured HERE are recovery-time projections, not archived
generation-time evidence. This cannot prove that these rows generated the XML,
CSR or certificate. Current bindings and repeated permissions are deliberately
conservative local access checks, not source/epoch/remote attestation.

## Transaction, failure and privacy order

1. Check actor, pure protected-envelope binding, saved owner/route/CSR and every
   ACL BEFORE invoking the provider. Recheck saved ACL/revisions after it returns.
2. Authenticate both exact retained encrypted envelopes before SQL acquisition.
3. Acquire ONE fresh owned transaction. The optional low-level `source_guard`
   must return literal True. It rechecks actor/ACL and locks one to four exact
   current source rows in sorted order BEFORE bundle/start/receipt locks.
4. Authenticate the historical staged bundle, require the EXACT committed start
   envelope and append/confirm the identical receipt without overwrite/reseal.
5. Re-run the same guard after append and BEFORE commit. Denial/drift/failure
   rolls back pending work; an already committed historical row is not undone.
6. Commit AND close. Recheck current actor/saved ACL/revisions before returning
   a protected result. Revocation on close prevents result disclosure but cannot
   undo a completed commit. Caller custody of the original input is mandatory.

The [local recovery states and exact-envelope contract](COMPLIANCE_RECEIPT_RECOVERY.md)
remain unchanged: uncertainty returns the original protected input, never causes
an automatic storage retry or another authority request. If current saved/actor
access is denied, the service raises a static translated error instead of
disclosing a result. Errors are raised outside provider/parser/SQL exception
handlers; English keys have Arabic CSV translations. Interruptions propagate
after owned cleanup. The caller MUST keep its input even when no result returns.

ACL remains the ambient Frappe engine/cache/transaction, not atomically locked
permission tables or globally fresh revocation. Projected source locks protect
only their compared values during this owned transaction. A change immediately
after the final check is not prevented. No owned SQL connection/lock is shared
with Frappe or carried across a network call; there is no network call here.

Repr/pickle/privacy rules remain protected. Diagnostic source/epoch/remote/
completion/activation/dispatch/replay flags stay false. Captured HTTP rejection
or HTTP 200 is storage evidence, not remote success or final-CSID authorization.

## Verification and remaining gates

187 new local cases exercise six types/three environments/six saved source modes,
both original commit outcomes, rejected replies, all row ACL before key access,
wrong stage/scope/owner/route, provider/actor drift, stale ambient reads versus
locked SQL, precommit/postclose revocation, literal-True guards, interruption/
cleanup, protected output, Arabic error resolution and both quiet signature shapes.
Existing capture and low-level recovery tests still pass after policy extraction.

12 new guarded owned-private SQL cases exercise saved-row locks and competing
recoveries at both isolation levels, stale saved projections, before-provider/
precommit/postclose denial, unknown recovery commits and a blocked concurrent
writer released on commit. All original transport results are synthetic. Reduced
tables and fake Frappe permissions are not an installed/full-site rehearsal.
Measured totals and fixed guarded commands are in [STATUS.md](STATUS.md).

Next: audited tenant/key/owned-connection providers, durable retained-receipt
custody and lost/late-response policy, generation-time source/credential epochs,
CSR-to-issuance and actual transport provenance, outbox/chain coordination and
full isolated application/SDK/v15/v16 acceptance. No finished onboarding, fixed
historical SignedProperties digest, working-site pilot or release is claimed.
