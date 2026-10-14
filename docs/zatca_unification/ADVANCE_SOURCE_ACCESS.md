# Permissioned advance archive metadata — increment 33

## Internal boundary

Increment 41 extracts common projection/access/lock/owned-cleanup orchestration
into [the shared archive inspection engine](QR_SOURCE_ACCESS.md). Advance entry
points/messages, Sales-only/type386/marker checks remain, and the old local/SQL
regressions run unchanged. This does not adopt the observer in settlement or
change advance lookup/allocation/age/remaining/accounting eligibility.

`advance_source_access.ArchivedAdvanceInspectionService` inspects one saved Sales
Invoice through explicit server dependencies. It is NOT whitelisted, registered
as a hook, called by a builder or deployed. It returns **metadata only**, never
original/returned XML, copied reference values, keys, certificate text or tokens.

The constructor accepts a server `CredentialStorageScope`, historical lookup
provider and owned connection factory. The inspection method accepts only an
invoice name (Sales Invoice only): it cannot select a site, namespace, version,
context or connection. The shared engine's explicit Doctype keyword cannot
enable POS in this advance-only adapter.
The lookup receives private saved-row projections, not an entire credential DTO.
Providers must not log those projections or make requests.

## Access and source checks

1. Require the configured site and a non-Guest current System Manager or
   Administrator. Check the saved Sales Invoice and Company with the direct
   permission engine, not `Document.check_permission`/`ignore_permissions`.
2. Resolve current saved Company/device/linked-Company ownership through the
   shared metadata-only owner policy. Every encountered saved row gets read ACL
   checks before historical lookup or storage acquisition. No write permission
   or invoice mutation is required for this metadata-only operator service.
3. Capture bounded, non-secret field values and `modified` revisions. The standard
   advance marker wins whenever metadata contains it, including zero; the custom
   alias is used only when standard metadata is absent. Missing schema fails,
   without installing columns or guessing a marker.
4. Require the lookup's exact typed binding to match saved invoice/Company/Tax ID,
   environment, opaque issuing-unit reference, UUID/ICV, submitted advance marker,
   current owner and configured endpoint. Saved REPORTED/CLEARED must agree with
   the declared operation but is NOT used as independent acceptance evidence.
5. Acquire a NEW OWNED DB-API connection. Reject recognizable `frappe.db`/existing
   raw ambient handles WITHOUT rollback/closure. Initially roll back the owned
   handle to clear prior uncommitted observations, require autocommit OFF, and
   lock sorted saved source projections before the exact journal read.
6. Compare SQL row names exactly, independently of a case-insensitive SQL name
   collation; compare projected values/revisions before and after selection.
   Reconstruct the pinned journal and apply increment 32's endpoint/clock policy.
7. Always attempt rollback AND close on the owned handle, including failures or
   interruption. There is no commit. Recheck actor/ACL/revisions after closure
   before returning the metadata projection. Cleanup failure prevents disclosure.

Ambient Frappe reads/ACL occur repeatedly; the service never commits, rolls back
or closes the shared Frappe transaction. Permission tables/cache are NOT locked
atomically by the separate source-row transaction. Post-close edits/revocation
cannot be globally excluded; these checks are not an authorization capability.

The quiet shared permission adapter handles the inspected Frappe 15/16 signature
forms. This is not actual installed v16/application acceptance. Normal service
failures are redacted outside handlers and translated, with Arabic CSV keys.
Interruptions propagate after owned cleanup rather than becoming success.

## Remaining trust and adoption gates

Providers are uninstalled server dependencies, not provenance attestations.
Site/namespace construction and connection identity checks cannot prove database
origin, protected lookup custody, a stable chain mapping, issuance-version source
epoch or authentic remote capture. Unrecognizable borrowed aliases remain a
provider audit responsibility; returning one violates the owned-handle contract.
The provider must clean up failed acquisition itself.

Current ownership/routing drift fails closed. A separately reviewed historical
access policy is needed before inspecting records after Company/owner/route
changes; there is no latest-record/credential fallback. Only owner identity is
compared with the historical credential declaration, NOT the current active
certificate or secret. Historical credential verification remains unfinished.
Saved row `modified` is a current comparison marker, not the historical source
snapshot digest or a complete business-data/GL/accounting epoch.

No verification/settlement/dispatch/replay flags are set true in the report, even
after permission checks and SQL reconstruction. Real transport origin, signature,
digests, XSD/SDK, accounting parity and installed ERPNext 15/16 must be verified
separately. This service does not export source bytes to a settlement pipeline.
Phase-1 QR-only and retired legacy records need explicit missing-original policy;
they cannot be reconstructed from midnight/current settings or fictitious journals.

## Offline evidence and acceptance order

Generated-data tests cover three environments, both operations, Company/device/
linked ownership, both marker spellings, ACL/role/site rejection, source changes,
revocation during lookup/acquisition/read/close, recognizable borrowed handles,
redacted failures, cleanup/interruption, non-pickling and Arabic messages.

A tenth private SQL suite exercises actual saved-row/journal locks and committed
reconstruction, stale ambient metadata versus actual SQL revision/UUID/name-case
changes, and initial rollback of uncommitted receipts/source edits. Its tables
and responses are entirely synthetic on a new TCP-disabled temporary server.
No installed tenant or working Company was accessed or changed.

Development must finish before separately approved isolated fictional-client
rehearsal. The user then decides to accept ALL changes or reject them; no decision
has been made now. See [DUMMY_REHEARSAL_DECISION.md](DUMMY_REHEARSAL_DECISION.md).
No authority sending or working-environment deployment is authorized.

Increment 34 adds [missing-original review and bounded QR observations](ADVANCE_SOURCE_GAP.md).
It does not bypass this metadata boundary, change eligibility or implement an
authoritative Phase-1-to-Phase-2 bridge/source recovery.
