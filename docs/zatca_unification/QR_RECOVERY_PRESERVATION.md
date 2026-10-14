# QR recovery preservation/review — increment 39

## Replaced legacy behavior, DEVELOPMENT only

The explicit QR recovery endpoint no longer picks a newest/first QR or XML,
reads XML contents, uses Debug XML as an apparent original, infers artifact
authority from filenames/status/current Company phase, clears a link or builds a
replacement from current invoice values. Its File save/re-link/image generation
helpers and BOTH explicit commits are removed, not merely hidden by the UI.

This deliberately removes speculative repair, not the need for genuine recovery.
No authenticated original-artifact provider is installed at this button yet.
Until one is implemented and verified, a missing source is REVIEW, not a reason
to invent a new image or call an authority endpoint.

## Decision and public contract

`qr_attachment_policy.decide_qr_recovery` composes the existing pure reuse
policy. It preserves its exact owned-current-reference rule and changes only
the ordinary GENERATE result into REVIEW for recovery. Ordinary issuance still
uses `decide_qr_reuse`, whose first-generation behavior is unchanged.

| Saved observation | Recovery action |
| --- | --- |
| Current URL matches an authorized File row on the exact same invoice | PRESERVE, regardless of filename/age/phase hint/field link |
| Missing/dangling/unlinked reference, even one candidate or no attachments | REVIEW; no implicit re-link or invoice-value rebuild |
| Only apparently reported/cleared/debug XML exists | REVIEW; no content read, ranking or provenance assumption |
| Draft/cancelled invoice or disabled Company | UNAVAILABLE before attachment inspection |

Malformed/foreign/unreadable/over-limit saved access observations retain the
increment 38 denial boundary. Well-shaped but policy-invalid metadata returns
REVIEW without exposing parser/row details. Projection ordering is name-ascending
for deterministic bounded inspection, NOT artifact priority. Creation is removed
from the projection: it is not needed to preserve a link or prove an original.

`get_qr_regeneration_state` keeps its signature and returns `eligible: false`,
`action` and translated `reason`. There is no current trusted generation action.
For REVIEW, the UI shows **Review QR Code** / **مراجعة رمز QR** with the reason,
not a misleading successful regeneration. PRESERVE needs no recovery menu action.
The current UI calls only the read-only state endpoint; it has no recovery POST.

The legacy `regenerate_qr(invoice_number)` POST remains callable for older clients:
it returns `status: preserved`, the unchanged current URL and translated message,
or raises the review/unavailable reason. It never returns `relinked`/`generated`.
The existing Invoice read/write and Company/File read checks remain. No File
write permission is requested because there is no File mutation. Any future
actual re-link must introduce its reviewed File write checks again, not bypass
them using this read-only implementation. No guest access is enabled.

Neither endpoint owns a transaction: no commit, rollback, savepoint, invoice/File
save, metadata update, schema change or image/content IO. Caller pending work
stays pending. A caller still owns how it handles a review exception and whether
its other work commits or rolls back; the endpoint does not decide that policy.

## Scope and limits

Preserving an owned URL does NOT certify QR bytes, physical existence, seller,
amounts, signature, historic epoch or authority acceptance. Current source/ACL
observations are not a serializable snapshot. No File repair/migration or remote
verification occurs. All-attachment ACL/bound checks remain conservative and may
require review of an unrelated unreadable attachment.

No date/time/Tax ID/Company phase is used to reconstruct a historical QR. A zero
duration or missing current time cannot trigger a new timestamp; preservation
does not need to reinterpret the old issuance clock. This is not evidence of
historical QR validity or installed browser/print behavior.

Normal Sales/POS Phase-1 generation, the initial-advance print hook, Phase-2
generation/artifact helpers, Debug XML, Compliance buttons, amount calculations,
advance search/allocation/remaining/settlement eligibility and GL/VAT are NOT
changed here. Removing a QR repair guess is not rejecting invoices for age.
Other artifact writers and physical File lifecycle still need audit.

## Offline verification

50 added local cases plus updated access regressions cover recovery versus
ordinary first issuance, orphan/empty/debug/XML inputs, preservation independent
of row order/status/time, unavailable gates, Arabic review/preserve strings,
read-only UI wiring and AST checks against content IO/writes/transaction calls.
Removed legacy reconstruction functions are replaced with forbidden-call mock
tripwires in fixtures, never real image/physical XML operations.

16 added cases in the existing eleventh private SQL suite combine two shaped
ACL signatures, preserve/orphan/dangling/debug-XML observations and parent commit/
rollback decisions. Real owned InnoDB rows prove that unrelated pending parent
work stays invisible until the parent chooses; QR/File projections stay intact.
Saved Frappe documents/ACL are mocked: this is NOT full installed ORM, physical
File, HTTP, browser or ERPNext 16 acceptance. No tenant connection is acquired.

The final guarded run passed **5,113 local + 216 private SQL = 5,329 cases**
in **45.03 seconds**; an earlier full run passed in 50.91 seconds. No build,
assets installation, service restart or schema migration was run.

Next implement an explicit authenticated original-artifact source and exact
generation/attachment plan before re-enabling recovery mutations; review other
Phase-2 artifact writers separately. Finish development, then separately approved
isolated fictional-client rehearsal and the user's whole-change adoption or
cancellation decision. No working environment or authority request is authorized.
