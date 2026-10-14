# Non-destructive ordinary QR attachment policy — increment 36

## Replaced behavior

At `aef51fd`, `_cleanup_qr_attachments` inspected Sales Invoice QR-field files
in creation-descending order, chose the first official-prefix file, deleted
others and sometimes cleared/relinked the saved reference. A current older QR
could lose to a newer differently phased filename. The POS path instead trusted
global File URL existence without checking the referenced invoice's ownership.

The ordinary Phase-1 generator now uses one pure policy for Sales and POS. The
descriptive helper is `_existing_qr_reference`; the old private cleanup name is
retained as a compatibility alias, with **no deletion or relinking behavior**.

## Explicit decisions

`qr_attachment_policy.decide_qr_reuse` reads a bounded tuple of six-field File
metadata mappings and the source Doctype/name, current URL and saved status.
Its frozen result contains action/static reason only, no private row/URL data.

- **PRESERVE:** the current nonempty URL matches a File row attached to this SAME
  invoice and Doctype. Preserve it regardless of filename age, phase prefix or
  attached field. Multiple same-URL rows do not require selecting/deleting a row.
  A newer official-prefix candidate never overrides the current reference.
- **REVIEW:** a current URL lacks its same-invoice File row; unlinked QR-field
  files or known `QR-`/`QR_` prefix candidates exist; saved REPORTED/CLEARED lacks
  a reference; more than 128 File rows exist; or metadata is malformed/foreign.
  Even one unlinked candidate requires explicit review, not implicit recovery.
- **GENERATE:** there is no current reference, no detected QR candidate, no
  protected Phase-2 acceptance label and no projection ambiguity. Normal payload,
  amount, image generation and caller-owned metadata staging remain unchanged.

These are operational safety decisions, NOT verification of issuance phase,
original epoch, signature, QR contents, physical existence, tax amounts or remote
acceptance. A saved acceptance label only blocks unsafe fallback; it proves no
remote outcome. Preserving an existing reference does not certify it correct.
Known filename prefixes are orphan-review hints, never authenticity evidence or
an exhaustive recognizer for every third-party QR naming convention.

## Runtime boundary in DEVELOPMENT

The helper queries File metadata scoped by BOTH `attached_to_doctype` and
`attached_to_name`, with deterministic name order and limit 129. It includes all
invoice files so QR rows with missing field links are not silently ignored.
Ordering does not rank authority. Exceeding the bound requires review rather
than assuming the uninspected remainder is safe. Unrelated non-QR files do not
block new generation within that bound.

The global URL-exists fallback was removed. A URL belonging only to another
invoice/Doctype cannot authorize reuse. No physical content/image scan, URL
normalization, remote fetch, file read, filesystem operation or directory scan
was added. Parent invocation authorization still applies: this is not a new
public endpoint or permission/tenant-provenance attestation.

PRESERVE and REVIEW do not delete any File, detach, clear/relink a QR field,
overwrite status, create an image, save an invoice or commit. REVIEW raises a
translated static message before generation; internal row/parser exceptions are
not chained into the operator message. Arabic CSV encoding correctly quotes the
English message's comma. No schema/fixture/credential/UUID/ICV/amount/advance
allocation or accounting-eligibility change occurs here.

This may deliberately stop automatic recovery of legacy dangling/unlinked
references which the former helper guessed or deleted. It is a review state,
not invoice rejection for age, and it performs no repair/migration of old records.
Do not direct users to an unreviewed recovery endpoint as an automatic bypass.

## Remaining gates

The decision observes current supplied metadata, not a serializable source lock
or durable unique generation reservation. Concurrent File/link edits remain a
caller-level transaction/concurrency gate. This is not a guarantee against all
duplicate creation or a proven durable snapshot.

Increment 36 did NOT change other writers. Increment 37 separately extends the
adapter to the [initial-advance print hook](ADVANCE_QR_PRESERVATION.md), removing
its force replacement and final-invoice cleanup. Explicit `qr_regeneration`
scans/relinking/commits and Phase-2 artifact helpers still require preservation/
access/transaction audit before claiming whole-app QR safety. Do not assume
these bounded changes cover every hook or button. Increment 38 separately adds
[saved-row access checks for recovery endpoints](QR_REGENERATION_ACCESS.md),
not a replacement for their legacy selection/re-link/commit policy. Increment 39
then replaces that button's guesses with [preservation/review only](QR_RECOVERY_PRESERVATION.md),
removing its content IO, mutations and commits while trusted recovery remains gated.

Actual physical file lifecycle, PNG decoding/validity, framework File deduplication
and installed ERPNext 15/16/browser/print behavior remain isolated-app gates.
No existing issued artifact or tenant was reconciled. The metadata observer is
not the authenticated historical original-source service needed for settlement.

## Offline evidence

Local cases cover both DocTypes, existing Phase-1/Phase-2/advance-aware/unknown
filenames, missing field links, newer competing rows, duplicate URLs, orphan/
dangling/foreign rows, no global fallback, malformed/bounded input and Arabic.
The actual generator is executed with synthetic mocked ERP/image/File operations.

Eight added cases in the existing eleventh private SQL suite exercise actual
scoped metadata queries and unchanged stored references/File projections for
preserve, orphan, dangling and foreign-URL scenarios. Synthetic parents commit
or roll back normally; the generator makes no writes in those scenarios.
There are no physical QR files, real tenant connections or authority requests.

Continue offline development, then separately approved isolated fictional-client
rehearsal. Only the user decides whole-change adoption/cancellation afterward.
