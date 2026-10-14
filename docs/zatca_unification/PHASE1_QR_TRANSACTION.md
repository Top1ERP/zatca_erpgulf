# Phase-1 QR metadata transaction ownership — increment 35

## Development change

The ordinary Sales/POS Phase-1 QR generator no longer calls `doc.db_set`,
`doc.save(ignore_permissions=True)` or `frappe.db.commit` after image creation.
It now stages exactly two fields in ONE `frappe.db.set_value` dictionary update:
`ksa_einv_qr` and `custom_zatca_status = "Phase-1 QR Generated"`, with
`update_modified=False`. It mirrors those fields on the in-memory document only
after successful SQL, then calls the existing notification method.

The generator does not commit OR roll back its caller's transaction. A failed
image/File/metadata/notification step propagates. A subsequent parent validation
failure can therefore roll back staged File/QR metadata with the parent's work,
instead of finding that the helper already committed part of the invoice.
The parent must actually propagate/handle errors correctly and own rollback.
Swallowing an exception and committing anyway is NOT made safe by this change.
After rollback, discard/reload mutated in-memory documents; SQL rollback does
not restore Python attributes.

This is a deliberate metadata-only update, bypassing full invoice/accounting and
`db_set` before_change/on_change events. It does NOT authorize bypassing normal
invoice validation or permissions at public request boundaries. Hook-dependent
customizations must be tested in the future isolated installed-app rehearsal.

## Schema ownership

Missing `ksa_einv_qr` now raises a translated error BEFORE attachment inspection
or creation; no schema DDL/custom-field creation is allowed inside this helper.
Both Sales Invoice and POS Invoice QR fields already exist as Attach Image
definitions in `fixtures/custom_field.json`. No fixture/schema definition was
changed and no fixture installation/migration was run.

An approved application setup/install/migration owns missing fields. Static
fixture presence is not proof of installed schema or successful v15/v16 upgrades.
Non-Saudi paths retain their early skip, even if the QR field is absent.

## Preserved behavior

- Same generator signature, caller routes, region checks and existing-link reuse.
- Same Arabic seller-name fallback, VAT lookup, shared explicit timestamp,
  ordinary amount formulas/text, Base64/TLV bytes, image options and filename.
- Same existing File save, public/private choice and explicit notification call.
- No advance lookup/allocation/eligibility, amount/GL/VAT calculation, UUID/ICV,
  signing, endpoint, credential, debug or Compliance logic was modified.
- Existing issued artifacts are not migrated or replayed by this increment.

The inspected local Frappe 15 `Database.set_value` accepts field dictionaries
without ORM events. Its `Document.notify_update` supplies `after_commit=True` to
the realtime publisher. A test executes that actual method with a mocked
publisher; it does NOT prove browser delivery or a full runtime transaction.
Installed ERPNext/Frappe 16 integration remains unverified.

## Caller audit and unresolved lifecycle risks

`sign_invoice` and `pos_sign` import this common Phase-1 helper. Some surrounding
paths, including the explicit `qr_regeneration.regenerate_qr` endpoint, still
commit independently. Removing those transaction boundaries requires a separate
caller-level audit; this change does not claim the whole app is commit-free.

At the increment 35 baseline, `_cleanup_qr_attachments` remained unchanged:
it chose official-prefix candidates, deleted others and could relink a selected
file. That behavior required a separate bounded change. The metadata transaction
tests alone did not approve that policy or prove issued artifact preservation.
Increment 36 now replaces ordinary cleanup with [non-destructive reference
preservation](QR_ATTACHMENT_PRESERVATION.md). Advance print and explicit
regeneration policies remain separate unfinished gates.

The actual File controller registers rollback callbacks in the inspected Frappe
15 source. Native SQL tests below mock File/image behavior and do NOT execute
those filesystem hooks, deduplication, physical deletion or restored application
lifecycle. Database atomicity alone cannot make physical files transactional.
Those are explicit isolated installed-app/rollback gates, not completed evidence.

## Verification

Local tests execute the actual generator with synthetic data and mocked File/
image/ERP operations. They cover Sales/POS one-dictionary updates, no recursive
save/transaction/schema ownership, unchanged unrelated fields/modified marker,
failure propagation, existing links, non-Saudi skip, Arabic missing-field message,
fixture declarations and inspected actual-v15 after-commit notification arguments.
The increment 34 generator characterization now expects zero ordinary commits;
its previous one-commit result describes the old `d08d38f` baseline only.

An eleventh owned-private MariaDB suite stages synthetic File and invoice rows
through the actual generator plus a tiny fake Frappe bridge. A second connection
sees neither new metadata nor File rows until the PARENT commits. Parent rollback
removes both, including failures after File INSERT/metadata UPDATE/notification
and a later failure after successful QR generation. Dirty business data is not
silently saved by a recursive invoice save. No tenant/config/site is acquired.

All changes stay on the development branch. No deployed source, working database,
worker, schema, Company or authority request changed. Finish development, then
perform the separately approved isolated fictional-client rehearsal before the
user's whole-change adoption/cancellation decision.
