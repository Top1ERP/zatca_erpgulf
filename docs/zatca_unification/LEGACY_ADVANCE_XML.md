# Shared legacy advance reference tails — increment203

Subsequent increment204 repairs finite native Decimal/float multiplication; see
[LEGACY_ADVANCE_NUMERIC.md](LEGACY_ADVANCE_NUMERIC.md). Evidence and the unfixed
behavior described below record increment203 before that intentional change.

Development only. The two Sales advance-named item builders now share the
repeated tax-subtotal and category/item/zero-price emission in the existing
`create_xml_final_part.py`. No runtime module, field, setting or endpoint is added.
This follows [regular-line sharing](ADVANCE_ITEM_EMISSION.md); it does not replace
advance discovery, archived-source selection, settlement accounting or issuance.

## Boundary and evaluation order

The callers still own regular items, direct-allocation priority, installed-app
and copied-row checks, first legacy master selection, line numbering, reference
ID/UUID/date and their distinct time policies. They also retain the exact
legacy `TaxAmount` assignment between two shared emission steps:

1. `_append_legacy_advance_tax_subtotal` creates the zero line tax/rounding totals
   and the taxable subtotal, then returns that subtotal.
2. The original caller statement computes/assigns its tax amount using the last
   regular item's rate. It resolves the amount/rate before currency/node
   creation, exactly as before.
3. `_append_legacy_advance_line_details` emits categories, item name and zero
   price. The plain path reads its document category twice; the template path
   reads/caches the last template category once at its original boundary.

Keeping step 2 in the callers matters: moving a rate argument earlier would
change where an empty regular-item table fails and what partial XML remains.
Deferring it into a closure would also change an unbound local error into a
free-variable error. Neither change is needed for this extraction. The actual
numeric statement, public handlers/signatures and surrounding statements remain.

There is no new tax-rate default, historical relink, midnight repair, identity
allocation, status write, GL entry or attempt to submit a reference. Direct
allocation still short-circuits the legacy branch under its original condition.
The two time/coercion policies remain explicit in their respective callers.

## Offline evidence

The existing hashed frozen two-wrapper fixture from `03b4982` remains unchanged.
The advance parity suite now contains **621 cases**, including **196 new cases**:

- 168 legacy amount/category combinations: plain/template, SAR/USD, synthetic
  ERPNext 15/16 tax-detail shapes, seven zero/positive/negative/Decimal/invalid
  amount values and three categories, including the inherited unknown-category
  fallback. Expected old failures are compared, not treated as valid invoices.
- 10 missing-field cases: legacy amount/code/name/unit and the existing early
  template-category failure boundary.
- 12 currency-read failures covering each of the first legacy line's six
  currency accesses, with complete partial XML and read-order comparison.
- Four category-lookup and two targeted legacy multiplication failures. The
  multiplication test supplies a synthetic rate and bypasses the redundant
  plain JSON encoding in both old/new code solely to reach that fault site.

Read tracing additionally covers legacy amount/code/name/reference/UUID/date/
time attributes. Every comparison checks exact serialized bytes, exception type
and message, attribute/get/master/app-read order and absence of writes/popups.
Existing empty regular tables, direct-over-legacy priority, historical dates,
last-loop rate/template, time and mixed-row cases continue to run.

Final guarded selection: **6,766 distinct local cases passed across 38 reviewed
suites in 23.38 seconds**. This includes all 621 advance cases and the existing
ordinary Sales, direct advance reference, tax, party, signing/QR, routing,
settings, scheduling, messages and artifact checks. Log:
`/tmp/zatca-legacy-tail-regression-final-203.log`. Initial overlapping runs are
excluded. Manifest remains 172 local/57 private suites; no whole-manifest or
private SQL run was needed.

Structural review specializes the two internal template branches and inlines
both helpers. Renaming only their equivalent local XML nodes reproduces the
**entire original module AST** at parent
`57a3b5b11623abf67b069c138dd19f2d051a3f1f`. It checks the exact call bindings and
unchanged frozen fixture too. Tool: `/tmp/zatca_legacy_tail_structure_203.py`;
report: `/tmp/zatca-legacy-tail-structure-203.json`. Runtime source is eight lines
shorter including English invariant explanations. This is maintainability
work, not a measured CPU/query/memory/production-latency improvement.

## Known behavior still requiring resolution

The characterization exposes the inherited plain-path `Decimal` amount ×
`float` rate failure. Template integer-rate fixtures retain Decimal arithmetic;
that difference does not establish a supported ERP field-type policy. This
bundle preserves both behaviors. A future monetary change must reconcile the
actual field/source contracts and fiscal outputs instead of adding an implicit
conversion here. Matching prior failures is a compatibility result, not a fix
or acceptance of those inputs.

The last regular item's tax rate/template still drives legacy reference tax.
Legacy missing/invalid-time fallbacks and copied-reference provenance also
remain unresolved, as documented in [ADVANCE_REFERENCE.md](ADVANCE_REFERENCE.md).
Actual multi-rate/partial/return/FX settlement, GL/VAT/XML reconciliation, original
artifact/acceptance binding, SDK/QR checks, installed ERPNext/Frappe 15/16 and the
separately approved fictional-client rehearsal remain release gates.

No live source/configuration/schema/customer data, Bench or worker changed.
No authority request occurred. The unrelated live tooltip edit was preserved.
