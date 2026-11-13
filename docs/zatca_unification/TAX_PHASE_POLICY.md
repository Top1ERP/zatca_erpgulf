# Canonical tax-metadata hooks respect explicit Phase-1 — increment210

Development only. The normal Sales/POS save and before-submit tax hooks now
share one tax-metadata coordinator. It skips that group only when the existing
Company phase resolver explicitly returns `Phase-1`. It preserves Phase-2 and
unknown/blank-phase behavior, item-value checks and the full remaining submit
body. No live field update, migration, Company change or authority request.

## Finding and selected boundary

Both `validate_negative_item_values_on_save` and `validate_sales_invoice_taxes`
previously called this same five-step sequence for every enabled Company:

1. Advance payment invoice category/rate structure.
2. ZATCA tax source presence.
3. Category/exemption reason and optionally source consistency.
4. Opt-in zero-rate category validation.
5. Tax table reconciliation.

Thus an ordinary Phase-1 invoice with ERP tax rows could still be rejected for
missing `taxes_and_charges` or ZATCA category fields in an existing Item Tax
Template. The same happened for an advance-marked Phase-1 document. These are
application tax-metadata restrictions; skipping them here does not change tax
amounts or assert legal correctness of any invoice.

`_validate_tax_metadata_for_phase` now owns the sequence. The public hooks still
load their Company and apply the existing general enablement check, then run
`validate_positive_item_values_for_zatca` before calling the coordinator. The
phase is resolved through the existing runtime helper and field-alias policy.

| Context | Canonical hook behavior |
| --- | --- |
| Explicit Phase-1 | Keep item-value validation; skip the five tax-metadata calls |
| Phase-2 | Execute the exact previous metadata sequence and bindings |
| Blank/None/unknown phase | Execute the previous sequence; do not silently downgrade to Phase-1 |
| Company disabled | Keep the original early return before phase/metadata checks |
| Save without Company or unsupported save DocType | Keep its original early return |
| Phase read failure | Propagate after item-value checking; never assume Phase-1 |

The preferred `custom_phase_1_or_2` field retains schema precedence over legacy
`phase_1_or_2`. A preferred field that exists but is blank/None does not allow a
legacy Phase-1 value to bypass checks. Schema absence permits the existing legacy
fallback. Whitespace is trimmed by the same resolver; casing/unknown values are
not newly guessed or normalized.

Save still omits the source-consistency keyword at the category validator; submit
still passes True explicitly. Validator order, original module callback bindings,
Company/event arguments and exception propagation are retained. No cross-request
cache, alternate phase interpretation or second validation implementation.
The old save docstring is corrected to describe the metadata work it already did.

## What still runs and what this does not gate

Item-value validation still respects its own configured Strict/Warn/Disabled
policy. The rest of before-submit remains unchanged: customer/export, POS/machine,
Company/Cost Center, item-template existence, ordinary tax-information and
mixed-template checks, return/debit references and legacy advance-copy checks.
For example, a configured Cost Center requirement and the existing missing-tax-
information rejection still apply in Phase-1. This is not a blanket Phase-1
validation bypass or evidence that every remaining submit requirement has been
classified correctly for each phase.

Lower-level validators remain unchanged and callable as before. The phase gate
is in the two audited canonical hooks, not a blanket change to direct/manual
calls or custom server scripts. Template DocType hooks and other lifecycle/
accounting/artifact/QR/transport hooks are not changed. Broader Phase1/Phase2 and
custom integration audit remains a release gate.

## Settings descriptions and translation

Development definitions for the existing Company source-consistency and tax-table
settings now explain this normal-flow phase scope. Source consistency remains
an enabled before-submit consistency rule, not a switch for all save checks.
Existing names/types/defaults and all setting implementations stay unchanged.
Two Arabic catalogue entries are appended; all old bytes/keys are retained for
sites whose stored descriptions have not been updated. Descriptions remain
English metadata with Arabic display translation. No runtime message, popup or
log is added. Catalog/AST checks are local evidence; installed UI rendering is
not claimed. No customization/setup routine was executed on any site.

## Frozen-parent and offline evidence

`tests/fixtures/tax_hooks_30570cf.py` freezes both complete parent hook functions
from `30570cfa8f5ecc3d396b66733b74e5d0c6dbb255`. SHA256:
`8ef703f7aa2021fd68c01ab1514d4abb153bca44cf7f8c109aae932caed5494c`.
The old metadata calls and complete submit body execute against explicit mocked
masters/callbacks, not a parent implementation rewritten to contain the gate.

`test_tax_phase_policy.py` adds **245 local cases**:

- 144 exact parent/current sequence cases across two hooks, Sales/POS, events,
  nine primary/legacy/schema/value phase combinations and enabled/disabled
  Companies. Only the five metadata calls are removed for explicit Phase-1;
  non-phase master loads and remaining submit behavior match.
- 48 selected callback failures preserve order/errors for Phase-2 and unknown
  phases. Phase-1 still fails on the item-value callback; skipped metadata
  callbacks cannot block it.
- 24 real Phase-1 ordinary/item-template cases and 12 real advance-marked Phase-1
  cases show the exact old missing-source/category rejection and new success
  under all three reviewed Phase-1 alias forms. ERP tax rows remain present;
  no claim is made for every ERP/GL advance lifecycle.
- Six real Phase-2/unknown cases retain missing-source rejection. Four real
  negative-item cases retain their original Phase-1 error.
- Two phase-read faults, two missing-Company exits, one unsupported save DocType,
  one configured Cost Center and one existing tax-information requirement.

The actual alias resolver executes against explicit synthetic metadata through
mocked Frappe boundaries; this is not an installed v15/v16 schema guarantee.
No tests invoke a site, tenant SQL, setup/migrate, QR attachment write or transport.
Document save/db_set and database write/commit boundaries remain uncalled.

Final guarded selection: **9,311 distinct local cases passed across 46 reviewed
suites in 28.90 seconds**, including 245 new cases. Existing source/zero/mixed-rate,
Sales/POS, advance/Decimal, phase1 QR/address, signing/QR, routing/settings,
scheduling, messages and artifact checks also passed. Log:
`/tmp/zatca-tax-phase-regression-final-210.log`. Initial overlapping selections
are excluded. Manifest is 180 local/57 private suites; no whole-manifest or
private SQL run was needed. No CPU/query/heap improvement is claimed; phase
resolution adds a metadata read and deployed cost is not measured here.

Structural review specializes/inlines the shared coordinator separately for save
and submit, restoring the exact prior hook ASTs after removing the explicit
Phase-1 guard. It retains item-value checks and the complete submit body, and
reproduces every other runtime node after removing the helper/import and updated
save docstring. Both frozen functions match their parent AST. A separate AST
comparison verifies only the two staged field descriptions changed in setup,
and the previous Arabic catalogue is an exact prefix with two entries appended.
Tool: `/tmp/zatca_tax_phase_structure_210.py`; report:
`/tmp/zatca-tax-phase-structure-210.json`.

## Remaining effective-rate and release work

The initial per-item validation review found that native tax details may include
non-VAT charge rows; adopting extra effective-rate checks without resolving
VAT-account/source ownership could introduce false rejections. This bundle
therefore closes the concrete canonical phase boundary first. VAT versus other
charge selection, per-item versus global classification, strict category/code/
rate/missing-value policy and remaining phase-specific submit/template/lifecycle
checks still require review before broader validator adoption.

Full GL/VAT/FX/advance and rounding reconciliation, first-chain/retry/credential
guarantees, SDK/QR checks, installed ERPNext/Frappe15/16 and the separately approved
fictional-client rehearsal remain required before any rollout decision.

No live source/configuration/schema/customer data, Bench or worker changed;
no authority request occurred. The unrelated live tooltip edit was preserved.
