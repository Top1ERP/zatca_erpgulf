# Non-destructive Phase-2 completion hook — increment 42

## Removed behavior in DEVELOPMENT

`phase2_artifacts.ensure_phase2_sales_invoice_artifacts` previously reconstructed
XML/QR from saved response text, preferred a nonempty `clearedInvoice`, reused
an invoice filename prefix by creation order, deleted QR files of another
prefix, and sometimes replaced a QR link or changed CLEARED/REPORTED status.
Those heuristics did not establish artifact origin, epoch, content or identity.

The hook no longer performs ANY of those operations. Its response parser,
prefix-reuse File saver and stale-file deletion helpers are removed, not hidden
behind a UI flag. The event entry point and `None` return remain for compatibility;
hook registrations are unchanged and no schema/install/build action ran.

This is the automatic local completion/fallback hook, NOT the primary request
adapter. Sales and POS clearance code already has its own XML/QR creation after
the response, and Reporting has original-request attachment paths. Those primary
adapters, HTTP/credential logic and image-generation functions are unchanged.
Inspection of their source is NOT installed-app or authority acceptance evidence.

## Preservation/review policy

The existing Sales-only, submitted and CLEARED/REPORTED gates remain. Other
DocTypes/states skip before File lookup. A malformed non-string saved status
also skips safely rather than invoking `.upper()` on an invalid object.

For an eligible source, `assess_phase2_qr_reference` validates source/link shape,
then reads a bounded same-invoice six-field File metadata projection, ordered
by name (not authority/age). It uses the same recovery policy as the explicit
button:

- PRESERVE the current URL if it matches a same-invoice owned File observation,
  regardless of phase prefix, age, field link or newer competing files.
- REVIEW missing/orphan/dangling/foreign/malformed/ambiguous/over-limit metadata.
  Empty metadata does not authorize generation; an XML-looking name is no source
  of truth. Even a present matching URL does not prove physical/QR validity.

The helper returns static diagnostic action/reason, an optional translated Arabic/
English review message and false mutation/authentication flags. It does not return
private URLs, identities, XML, QR payload, current credentials or raw response.
Source validation precedes ORM filtering; the query never uses a filename LIKE
pattern or global URL existence check.

The hook intentionally discards that diagnostic and returns `None`: it does not
raise a nominal REVIEW exception, emit a modal/log, save a review state or modify
the invoice. A missing original must not itself abort the parent after a possible
accepted request. The diagnostic is currently internal, not persisted or exposed
through a new endpoint/UI. The existing separate QR review UI remains unchanged.
Real database lookup errors still propagate; this does not solve durable receipt/
unknown-outcome or parent error-handling problems.

No content read, response decoding, image creation, File mutation/deletion,
link/status/XML-field update, recursive save, notification, commit, rollback or
DDL exists in this hook. Parent work stays under parent transaction ownership.

## Incomplete functionality and remaining risks

The legacy method name now describes a compatibility entry point, NOT a promise
that missing XML/QR will be automatically created. Historical/local completion
requiring a trusted original remains gated until the authenticated source and
exact artifact plan exist. No missing original is invented or migrated. This
tradeoff must be included in the future isolated whole-app acceptance rehearsal.

The helper assumes parent authorization; it is not a public saved-row ACL
boundary. Metadata observations do not authenticate an original or serialize
source/permission epochs. It does not assess XML completeness or validate seller,
amounts, timestamp, signature, QR tags or remote acceptance. Preserving a Phase-1
named current reference does NOT certify it correct for a Phase-2 invoice.

`_extract_qr_payload_from_xml` and its local-name helpers remain unchanged because
Sales/POS clearance also imports them. The normal `attach_qr_image` path still has
separate global URL reuse/schema/File/link behavior and callers with independent
commits. These need deliberate source/access/transaction integration; this change
does not claim all QR writers are safe or fully unified.

Advance search/allocation/remaining/age/settlement rules, GL/VAT/amounts, ordinary
Phase-1 QR, initial-advance QR, Debug XML and Compliance buttons are unchanged.
No credential, identity/counter or acceptance field is repaired or downgraded.

## Offline evidence

61 new local cases execute the actual hook and helper with synthetic File rows
and forbidden-call mocks. They cover accepted labels, old/differently phased QR,
newer competitors, unknown field links, missing/foreign/duplicate/malformed/bounded
observations, invalid source identity, unchanged gates, poisoned saved-response
access, absent field/Arabic and propagated SQL faults. Source assertions forbid
artifact/transaction mutations; the existing shared-extractor regression remains.

16 new cases in the existing QR private SQL suite cover preserve/orphan/dangling/
foreign-URL observations, both accepted labels and parent commit/rollback. Actual
owned InnoDB rows prove QR/status/File metadata preservation and that unrelated
pending parent work is neither committed nor discarded by the hook. ERP/File/
image behavior is mocked; no physical File or installed ERPNext 16 is exercised.

The final guarded selection passed **5,524 local + 295 private SQL = 5,819 cases**
in **48.95 seconds**. The local-only run passed in 26.61 seconds.

Continue offline development with the primary QR attach path/source/transaction
boundary next. No working configuration/source/schema/assets/worker/customer data
or authority request changed. Finish development before separately approved new
isolated fictional-client rehearsal and whole-change adoption/cancellation.
