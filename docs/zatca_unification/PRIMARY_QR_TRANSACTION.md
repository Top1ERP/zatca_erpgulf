# Primary Sales/POS QR transaction boundary — increment 43

## Bounded development change

Sales and POS import the same `sign_invoice.attach_qr_image` function. This
increment changes only schema ownership and QR-link metadata staging in that
compatibility adapter. It does not send an invoice or activate a new provider.

The adapter no longer creates `ksa_einv_qr` while attaching an image. Both Sales
and POS fields are already declared in installation fixtures. Missing schema
now raises the existing static, Arabic-translated setup message before image,
File or metadata writes. Approved setup/migration is a separate future action;
none was executed. The existing Phase-2 default skip still happens first.

After the existing private File save, `_persist_attached_qr_metadata` stages one
field-dictionary `frappe.db.set_value` for `ksa_einv_qr`, with
`update_modified=False`, then mirrors the URL in memory and notifies the document.
It does not call invoice `db_set`/`save`, commit, rollback or schema functions.
The inspected local Frappe 15 `Document.db_set` invokes `before_change` and
`on_change`; this helper no longer enters those hooks. The inspected notification
implementation requests publication after commit, not an immediate commit.

No submission status, UUID, ICV, XML link, modified timestamp, amounts, business
fields, advance search/allocation/remaining/age/settlement or GL/VAT rules change.
The caller-supplied payload, image options, filename convention, private flag and
File attachment fields retain their existing behavior. A filename/status argument
is not evidence of acceptance, and this helper must not relabel acceptance.

## Explicitly unresolved

This section records the increment 43 baseline. [Increment 44](PRIMARY_QR_OWNERSHIP.md)
subsequently replaces this helper's global URL check and adds schema/ownership
preflight before the four primary APIs' error-persistence boundary. Concurrent
post-response errors and the other limitations below remain unresolved.

- Existing global URL existence reuse remains characterized, NOT safe source or
  ownership validation. Dangling links can still fall through to generation.
  No new source selector is activated, no file is deleted and no auto-relink
  policy is introduced in this slice.
- `allow_phase2` remains a legacy dispatch flag, not a security/provenance check.
  Payload/TLV/XML/signature/receipt validity is not established by this adapter.
- Primary reporting/clearance callers still contain independent commits and
  error handlers that may rewrite status after a local post-response failure.
  The missing-schema error, like an image/SQL error, can reach those handlers.
  This increment does NOT prevent an accepted request being misclassified by a
  caller; pre-request schema validation and receipt-aware error handling remain
  blocking integration work. Do not install this slice as a standalone live fix.
- `ignore_permissions=True` on the existing File save is unchanged; parent
  authorization/transaction boundaries still require whole-path validation.
- SQL rollback of synthetic File rows is NOT physical-file rollback/deduplication
  proof. After rollback/failure the parent must discard/reload in-memory docs.
- Current Company phase/status is not historical credential/source evidence.
  No authentic recovery/export/mixed-phase capability is enabled here.

The [automatic completion hook](PHASE2_ARTIFACT_PRESERVATION.md) remains a separate
non-mutating fallback. Do not confuse its internal REVIEW with primary caller
exceptions. Future integration must preserve acceptance evidence even if local
artifact creation fails, without manufacturing success or silently losing QR.

## Offline verification

30 new local cases execute the real shared adapter with synthetic payloads,
File/image/ERP mocks, both DocTypes, accepted/unsubmitted labels, exact metadata
field allowlist, no incidental business/status/modified-time changes, phase gates,
English/Arabic missing-schema messages, image/File/SQL/notification failures and
unchanged legacy global-URL behavior. Source assertions forbid DDL, recursive
invoice save/db_set and helper-owned commit/rollback. The POS shared function
identity and existing fixture/actual-v15 notification regressions are retained.

24 new cases in the existing private SQL suite use owned temporary InnoDB tables,
mocked File/image and actual parent transactions: both DocTypes and accepted
labels, invisibility before commit, parent commit/rollback, and File/metadata/
notification/later-parent failures with unrelated pending work. Link/status/
business/modified columns and synthetic File rows are checked from a separate
connection. No site, client database, installed ERPNext 16 or authority is used.
The first combined run failed these 24 new cases because the synthetic File
save double lacked the legacy adapter's `ignore_permissions` keyword. The double
now accepts/asserts that existing argument; production behavior was not weakened.

The full local selection passed **5,554 cases in 27.12 seconds**. After correcting
the File double, the guarded combined run passed **5,554 local + 319 private SQL
= 5,873 cases in 49.82 seconds**, across the same twelve private SQL suites.

Development only: no working source/config/schema/assets/worker/customer data or
authority calls. Complete development before separately approved NEW isolated
fictional-client v15/v16 benches and an all-change adoption/cancellation decision.
