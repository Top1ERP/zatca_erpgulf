# Permissioned encrypted local receipt custody — increment 50

## Internal boundary, not activation

`SavedPrimaryReceiptCustodyService` protects the increment 49 custody repository
with saved-source ACL, exact server declarations, scoped keys and owned connection
acquisition. It exposes NO whitelist/button/hook/job, automatic sender, plaintext
export, sealer, credential activation, schema installer or live provider binding.
Only synthetic tests compose it with the optional Unix provider from increment 48.
The working application/configuration/schema/assets/workers and authority APIs
remain untouched. Advance eligibility, amounts, accounting, signing and QR
generation are unchanged.

The service requires an explicit site/storage scope, exact saved-row lookup,
scoped key provider and fresh owned connection factory. These are trusted server
dependencies, never operator/request JSON. Their origin, namespace provisioning,
key custody and historic source/epoch/transport authenticity still need audit.
The interface has no latest-attempt/record search fallback; a malicious or wrongly
configured server lookup is not made trustworthy by returning a valid declaration.

## Shared policy and acquisition

The existing saved archive engine is reused with the private primary-receipt
policy: current same-site System Manager/Administrator, invoice WRITE, Company/
device/linked-owner READ, submitted saved source, exact owner/route/UUID/ICV.
`ignore_permissions` flags/document shortcuts do not replace direct ACL calls.
Both storage and retrieval require WRITE because this is a protected recovery
capability, not ordinary invoice reading. No invoice is edited by that requirement.
Existing QR/advance metadata inspection keeps its READ/accepted-status policy.

`PrimaryReceiptCustodyBinding` extends the previous exact predecessor/attempt/
response-event declaration with full framed-receipt hash and custody key ID.
The lookup receives saved projections, not a receipt to echo. Actor/source/ACL
and supplied envelope scope/metadata are checked BEFORE the key provider. The
typed key resource must match the same scope/key ID; source/ACL are rechecked
after key acquisition and before SQL. The returned protected ciphertext must
authenticate/decode to the exact candidate/context/epoch, UUID/ICV, predecessor,
attempt and response-event digest. Full cryptographic binding follows key
acquisition; a caller's metadata alone is not authentication.

Two extracted helpers in `primary_receipt_access.py` now serve both the existing
journal-persistence boundary and this service: exact retained binding, and owned
connection acquisition. The latter rejects recognizable ambient Frappe/raw parent
handles without touching them, clears only a fresh owned handle and attempts both
rollback/close on failed owned acquisition. Permission denial during acquisition
remains a translated denial after cleanup, rather than a generic storage failure.
Arbitrary handle ownership is still a trusted-provider obligation, not proven by
Python duck typing; the optional pinned provider narrows that boundary in tests.

## Storage and retrieval lifetimes

- `stage(invoice_name, sealed, doctype=...)` accepts the ORIGINAL protected
  envelope only. It never seals/reseals, invents an event/time/attempt or sends
  HTTP. Authentication and exact declarations precede acquisition; saved SQL
  projections are locked/rechecked around immutable custody staging in the SAME
  owned transaction. Commit AND close are required for the local stored state.
  Acquisition/SQL/commit/close uncertainty returns the SAME supplied envelope as
  `CUSTODY_COMMIT_UNCONFIRMED_NO_REPLAY`, subject to final source/ACL recheck.
- `load(invoice_name, doctype=...)` uses the server-declared exact candidate/
  attempt and keys, not caller-chosen record IDs. It locks/checks saved SQL rows,
  authenticates and rebinds the stored receipt, then rolls back/closes the owned
  read transaction. Only after final saved-source/actor/ACL recheck can it return
  `CUSTODY_READ_OBSERVATION_NO_REPLAY`, containing CIPHERTEXT ONLY. Cleanup
  uncertainty refuses disclosure. There is no read commit or plaintext/XML/QR
  payload in the result or diagnostic projection.

Results/resources/bindings/service are redacted and nonpickleable. Diagnostic
projections contain static local states/flags, not identities, keys or bytes.
All provider/historic-source/epoch/remote/acceptance/dispatch/replay flags remain
false. Failures are static unchained English/Arabic messages; original provider/
driver/parser errors are not presented to the operator.

Caller-owned original envelope custody remains MANDATORY even if an interruption,
revoked permission or source change prevents result return. A late denial cannot
undo a committed historical ciphertext. A response lost before its first durable
commit remains lost; no receipt table or current permission proves remote failure.
No durable retry hold, queue lifecycle, attested transport capture or raw export
capability is installed by this increment.

## Historical drift and evidence limits

Added **302 local + 44 private SQL cases**. The final guarded combined run passed
**6,554 local + 591 private SQL = 7,145 cases in 63.05 seconds**, across the same
twelve private SQL suites. The first corrected combined run passed 7,109 in
62.96 seconds before the last authenticated-binding/status cases were added.
The guard denied external network/site initialization and allowed fixture-owned
Unix SQL only; it is process-local accidental-I/O protection, not an OS sandbox.
Actual SQL uses Python 3.10/MariaDB 10.11; no tenant connection was selected.

The underlying repository can preserve/retrieve encrypted evidence independently
of today's journal. This permissioned boundary additionally requires the current
saved source/owner/route to match the explicit historical declaration. Drift is
review, not permission to choose a different certificate/attempt or reconstruct
an envelope. Permission checks are repeated but permission-table revocation is
NOT atomically locked with SQL. Source locks serialize the bounded projections,
not all tax/accounting fields or proof of historic preparation.

Unit tests use synthetic v15/v16-shaped quiet permission engines and saved rows.
Private SQL tests exercise actual pinned Unix connections/marker checks and source
locks, separate write/read sessions, denied access before keys/DB credentials,
stale ambient versus actual SQL, both real commit outcomes with a synthetic lost
acknowledgment, exact local redelivery and post-close denial preserving committed
ciphertext. All certificates, keys, actors, bodies and identities are synthetic.
No installed ERPNext 16, browser, true transport receipt or authority acceptance
is proven by this matrix or a successful local state.

The first run had 266 setup errors because the new test module omitted an imported
fixture dependency; all existing 6,252 local cases passed. The next run found four
new acquisition-time denial-classification failures (access was already refused).
The shared owned-acquisition helper now preserves redacted permission denial after
cleanup; existing source/QR/advance regression assertions were not relaxed.

Next gate: audit server key/lookup/connection provenance and integrate exact
transport/source/epoch capture with durable no-replay review holds. Do not connect
primary APIs/schedulers before closing pre-first-commit loss/partial-parent-commit
and later-retry policy. Full isolated v15/v16/SDK/accounting/browser acceptance,
fictional-client approval and separate authority-send authorization remain gates.
