# Primary QR ownership/pre-request guard — increment 44

## Development behavior

The shared `primary_qr_attachment.require_primary_qr_attachment` is internal,
read-only and not whitelisted. Sales/POS primary Reporting and Clearance invoke
it before their try/error-persistence boundary, so an existing link/schema
problem does not enter their legacy error-saving/503 handling. It also precedes
POS Reporting's existing pre-request XML File creation, payload reads, credential
selection, realtime messages, PIH changes and HTTP. The primary QR attach helper
rechecks after its unchanged phase-dispatch skip and before image/File writes.

It uses the existing pure non-destructive attachment policy:

- Validate source/link shape and expected Sales/POS DocType before ORM filtering.
- Query only the complete bounded same-invoice File projection: six metadata
  fields, ordered by name, at most 129 rows for a 128-row accepted observation.
  Name order is deterministic, not newest/authority preference.
- PRESERVE a current URL found in that invoice's projection, regardless of its
  filename prefix/phase/age/field link or newer competing files. This is reference
  preservation, NOT evidence that its content or phase is correct.
- REVIEW a dangling/foreign URL, an unlinked QR candidate, malformed/foreign/
  duplicate metadata, excess rows or invalid source/filter values. Raise only
  the existing static Arabic/English review message, outside policy exception
  handlers. No raw URL, row or chained policy cause is returned.
- Allow the existing primary first attachment when no reference/QR candidate is
  present. The primary adapter already supplies a payload; no historical source
  is reconstructed by this guard. Saved status is deliberately NOT evidence:
  clearance can stage CLEARED before attaching its first image. This differs
  from historical recovery, where no original still means REVIEW.

The previous global `File.file_url` existence check is removed from
`sign_invoice.attach_qr_image`. A foreign File row is not enough to preserve the
URL, and a missing owned row cannot fall through to replacement. No auto-relink,
delete, schema setup, filename priority or new recovery capability is added.
Image/payload/File privacy/filename generation for an unambiguous new attachment
and increment 43 QR-link-only staging remain unchanged.

Existing valid batch deferral remains deferred with no request. The guard also
runs for batches: invalid references/missing schema now stop before legacy local
POS XML creation instead of being ignored merely because HTTP would be deferred.
No Company batch setting is changed. POS Reporting's pre-request XML write for
valid input is legacy behavior still requiring separate transaction integration.

## Guarantees not provided

This section records the increment 44 baseline. [Increment 45](RESPONSE_PROCESSING.md)
subsequently prevents generic failure overwrites/503 writes for previously caught
local errors in the four primary response-processing paths. It does not solve
durable receipt storage, existing partial commits, retry holds or other writers.

The guard assumes authorized parent access and a loaded document; it does not
reload/lock the invoice, establish File read ACL, validate a committed revision,
authenticate a site/provider, reserve a link, or solve permission/source races.
A concurrent source change or image/File/SQL/notification failure can still occur
after HTTP; primary handlers can then overwrite receipt/status. No receipt-aware
post-response error fix is claimed. This is a blocking next step, not a deployable
standalone resolution of acceptance/unknown-outcome handling.

Other reporting/generation/existing-XML adapters and global URL helpers elsewhere
are not covered. HTTP 200/202/409 semantics, request idempotence, UUID/ICV/PIH
retry behavior, authentic epoch/receipt binding and crypto/TLV/XML validity are
not changed. Neither `allow_phase2`, a saved accepted label nor GENERATE is an
authority grant. No authentic historical recovery or mixed-phase bridge is active.

The adapter still uses its legacy private File save with `ignore_permissions`;
physical-file rollback/deduplication and installed v15/v16 lifecycle remain gates.
No advance lookup/allocation/remaining/age/settlement, discounts, totals, GL/VAT,
Compliance/Debug button, credential or endpoint configuration is modified.

## Offline evidence

104 new local cases cover both DocTypes, old/different-phase filenames/field links
and competing rows, bounded/foreign/malformed data, validation before ORM, exact
query shape, existing Arabic messages, no schema/File/link/status/transaction
writes and no global URL fallback. Both primary API operations for both DocTypes
are exercised with forbidden-call assertions before any mock HTTP/identity/PIH/
XML/error-persistence work; actual query faults propagate without error writes.
The 30 increment 43 cases remain, with the legacy global-hit characterization
replaced by an owned-row preservation regression rather than a bypass.

The first full local run had ten failures in existing HTTP/retry tests: their
legacy fixture set QR URLs without same-invoice File metadata, so the new guard
correctly stopped before mock HTTP. The retry fixture now supplies explicit
owned six-field rows; original UUID/ICV assertions remain unchanged, and added
`post.assert_called_once()` checks prevent a preflight failure being mistaken
for a tested authority rejection. No guard or ownership assertion was weakened.

32 new private SQL cases use the existing owned temporary InnoDB suite. They
cover Sales/POS, both primary operations, preserved/dangling/orphan/foreign URLs
and parent commit/rollback with pending business work. Scoped queries execute
against actual synthetic File rows; separate connections verify unchanged
QR/status/File/modified values and parent-only pending-work visibility. Preserved
cases execute the actual attach helper without sending; ambiguous cases execute
the actual primary API rejection boundary. HTTP is a forbidden mock, and ERP/
File/image operations are synthetic, not a restored client or physical lifecycle.

The final guarded selection passed **5,658 local + 351 private SQL = 6,009 cases
in 50.10 seconds**, across the same twelve private SQL suites. See
[STATUS.md](STATUS.md) for the cumulative evidence and remaining release gates.
No installed application/config/schema/assets/worker/customer data or authority
request changed. Complete development before separately approved NEW isolated
fictional-client v15/v16 rehearsals and the whole-change adoption/cancellation.
