# Ordered field-rounding stage — combined batch145–147

This DEV checkpoint connects existing saved field proofs into one bounded stage
and compares its output with actual framework method executions on synthetic
objects. It does not execute a controller on an ERP document or install a writer.

## 145: one owned target-document read

`SavedCalculationDefaultsService.capture_rounding_stage_context(invoice_name,
fieldnames, erp_major=..., doctype=..., parentfield=None, row_name=None,
do_not_round_fields=None)` returns protected SavedRoundingStageRead.

Select one root invoice or one saved child row. `fieldnames` is an explicit,
ordered, nonempty tuple of at most64 unique present Currency/Float/Percent names
inside the financial manifest. Preserve that order. Do not accept None/empty as
an empty operation: Frappe interprets them as its default field sequence, which
may contain fields/order outside this partial captured manifest. Duplicates and
explicit nonnumeric fields allowed by general Frappe are outside this domain.

Version15 supports no skip argument; None here means omission. Version16 accepts
a bounded tuple of names to skip, including unrelated names with no effect.
Skipped selected values have no precision/format/cache acquisition. The known
System rounding method is still read before processing, including all-skipped
stages. Unknown method strings remain outside the source contract's domain.

RoundingStageAcquisition reuses one NumericAcquisition graph/native view and one
RoundingAcquisition on the SAME owned defaults/financial service. Per-field
FieldRoundingAcquisition policies share those objects. A local pool reuses each
needed invoice/Company/party format source; distinct scope keys remain separate.
Every consumed field-currency cache is observed before any format provider can
warm another selected slot. Shared metadata/native rechecks run once per source,
while individual owner/precision/currency slot checks remain per field.

No independent capture calls are combined. No new SQL reader, ACL engine,
cleanup path, public RPC, hook or provider is installed. Normal ORM checks and
per-field reconstruction still have a cost; this is not a complete performance
benchmark or a promise of minimal API-cache callbacks. The native query-count
test compares two fields with one on small guarded fixtures, not a live workload.

## 146: ordered before/after comparison

SavedRoundingStageRead pins numeric/context/default/method/version, one target
document, explicit field order, skip selection, original owner observation and
each non-skipped field's existing SavedFieldRoundingRead. Source consistency,
exact result type/float bits, protected repr and refused serialization remain.

`require_stage_match(before, after, setting_trace=..., precision_trace=...,
input_stage="SAVED"|"NUMERIC_FIXED")` compares complete ordered supplied data:

- Before/after tuples contain every selected field, including skipped fields.
  SAVED preserves native type/scale/sign/NULL. NUMERIC_FIXED uses the previously
  characterized precision-free projection; NULL still stays NULL at that point.
- Processed values must match the existing versioned field result exactly.
  A processed NULL becomes float0.0. A skipped field keeps its before-stage type,
  value and NULL representation. No tolerance or Decimal/float equivalence.
- Precision traces contain only processed fields in exact order, with the root
  owner's parentfield argument and exact integer return value.
- Setting traces retain the raw API value, not just the effective method name.
  A present known method needs the upfront read. Raw None/blank causes rounded()
  to look it up again for each processed non-NULL numeric input; NULL's flt
  conversion returns before that lookup. All-skipped stages still read it once.

The function does not read/set a document or execute a controller. These are
trusted caller-supplied snapshots/traces; equality does not attest that a caller
actually ran the method, used an original object or acquired evidence atomically.
Owner IDs remain ephemeral observations, not durable/active identity proof.

## 147: actual framework comparison and source checks

The reviewed tests execute installed15 and pinned MIT16 round_floats_in bodies
using unpersisted synthetic root/child objects. Only precision/System dependencies
are synthetic projections from the captured proof. No controller hooks, saved
ERP document, site, Redis, authority endpoint or complete16 runtime is invoked.

Cover Sales/POS, both declared versions, native/fixed representations, None/
blank/known methods, root and parent-owned child precision, NULL, skips and
ordered trace/result refusal. Guarded SQL checks cover same-query-count capture,
same-scope source sharing, distinct invoice/base formats, all-skipped unused
dependencies, late changes to either field/default/method and caller-owned work.
The final counts and actual limitations are recorded in STATUS.md.

## Remaining integration gates

Batch148–150 adds a separate explicit current-input comparison for net totals
and the advance aggregation prefix. It preserves this saved stage's strict
input equality and does not close active-stage provenance or complete fiscal
parity. See [CALCULATED_TOTALS.md](CALCULATED_TOTALS.md).

The new batch is staged and read-only. An installed provider must still bind the
actual active controller and transaction, its current calculation stage (which
may have changed amounts since saved native input), default field order/outside-
manifest fields, complete permission/caller identity, cache/API provenance and
committed/durable origin. Complete tax/discount/GL/VAT/advance/XML parity and
whole-worker/custody/security/performance/installed15/16/SDK reviews remain.
No authority send or working-site rehearsal is authorized by this checkpoint.

See [FIELD_ROUNDING.md](FIELD_ROUNDING.md),
[OWNER_CURRENCY_AND_CACHE.md](OWNER_CURRENCY_AND_CACHE.md),
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md) and [PLAN.md](PLAN.md).
