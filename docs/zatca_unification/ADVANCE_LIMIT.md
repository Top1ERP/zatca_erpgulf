# Advance ceiling and write-off inputs — batch158–160

This DEV checkpoint compares `calculate_total_advance` through its ceiling check,
optional write-off reset, and ordered downstream calls. It does not implement
paid/outstanding/write-off recursion, settle/relink advances, write an invoice or
send to ZATCA. All current inputs are explicit supplied observations.

## 158: native write-off side profile

`source-invoice-write-off-metadata/v1` selects `write_off_amount`,
`base_write_off_amount` and `write_off_outstanding_amount_automatically` on
Sales/POS Invoice. Currency/Check definitions, physical presence/absence,
descriptors, raw values and original revision are checked. Currency values retain
native type/scale/sign/NULL; normalized Check projection stays separate.

`LockedWriteOffRead` / `MariaDBWriteOffReader` share the existing bounded invoice
control projection/metadata/failed-session engine via fixed class configuration.
No new SQL transport, connection owner, cleanup or schema writer exists. Existing
financial/root-control profiles and domains remain byte-compatible; the write-off
profile has a distinct domain. Its inherited `consolidated` projection is false
and is not a settlement control. Only its declared Check is used here.

## 159: one owned source context

`SavedCalculationDefaultsService.capture_advance_limit_context(invoice_name,
erp_major=..., doctype=...)` returns protected `SavedAdvanceLimitRead` on the
existing owned service. Its trusted optional constructor dependency
`write_off_metadata_reader` supplies applied write-off metadata. The existing
owner/advance-party/format/cache providers retain their roles.

Reuse one numeric graph, native financial read, method source and advance group.
The root stage explicitly selects `total_advance`, `grand_total` and
`base_grand_total`; this is a declared inspection group, not a minimal-dependency
claim. Project its total-advance field into the existing advance context instead
of performing an independent capture. Normal record/table/row/field READ covers
the graph plus write-off fields and parent party currency before providers.

Pin initial/fresh write-off getters and levels, transaction currency and native
party currency, and recheck through cleanup. Only a foreign-party branch reads
the existing base-write-off precision slot. Never call `precision()` or refresh
a cache. The captured source binds complete ordered advance rows and their
existing direct-row precision/party evidence.

Fresh base-write-off precision uses the shared versioned resolver on the new
profile. If16 needs currency formats, reuse an already captured root field format
with exactly matching options, including its native Company/party/API evidence.
Observe the base-write-off field-currency slot before format callbacks and check
it independently; an existing NULL/blank slot cannot be replaced implicitly.
Unsupported custom combinations without a matching captured format fail closed.
Do not substitute root transaction currency or a parent-owned child precision.

## 160: exact ceiling comparison

`AdvanceLimitCalculation(source, aggregate, representation, values)` requires the
same co-owned advance group and a complete ordered header observation:
`grand_total`, `rounded_total`, `conversion_rate`, `write_off_amount`.
NUMERIC_FIXED must match the saved precision-free projection exactly.
CALCULATED permits observed changed values without attesting their earlier
arithmetic or active controller origin. Bool/Decimal/text/nonfinite monetary
inputs are refused; rounded total/write-off permit NULL. No silent conversion,
recalculation or tolerance equates saved/current observations.

Preserve the controller's operation order:

1. Choose truthy rounded total, otherwise grand total, including negative totals
   and zero/negative-zero fallback behavior.
2. For party currency equal to transaction currency, subtract precision-free
   `flt(write_off_amount)` and round with grand-total precision.
3. For a foreign party currency, round the converted write-off separately, then
   subtract it from the rounded converted total. Version15 uses `grand_total`
   precision for that total; version16 uses `base_grand_total` precision. Do not
   commute subtraction, merge rounding or use the saved base-total amount.
4. Block only when the computed ceiling is positive AND aggregate advance is
   strictly greater. Exact equality is allowed by this check. Nonpositive
   ceilings skip this particular rejection; that is not fiscal approval.
5. Only after a passing check may the automatic flag plan an integer-zero reset
   of write-off, followed by outstanding and write-off calls in that order.
   The ceiling still uses the OLD write-off value. No reset/write occurs here.

`require_match` reconstructs the bound source/aggregate, checks exact result
type/float bits, decision/reset booleans, and ordered root precision/System-method
traces for this ceiling suffix. Prefix aggregation traces belong to the existing
aggregate comparator. Tests clear prefix observations at `total_advance`
assignment, observe the actual local `invoice_total`, and stub only downstream
methods. Actual15/pinned16 controller bodies and numeric helpers execute on
unpersisted synthetic documents, never saved controllers or invoice hooks.

## Remaining integration gates

This comparison does not validate conversion-rate eligibility, tax/GL/VAT/XML,
advance matching, historical relinking, payment/loyalty/change handling or complete
settlement. The supplied current amounts, active controller/cache/provider/actor/
namespace/transaction provenance and durable committed origin remain external.
Performance/source-sharing checks are bounded synthetic evidence; no live latency
or all-field cost claim is made. Complete installed15/16, SDK, worker/custody/
dead-code and fiscal parity gates precede separately approved fictional-Company
rehearsal and gradual adoption/cancellation.

LIVE and authority endpoints remain untouched. Native tests use NEW guard-owned
TCP-disabled temporary SQL only. Old-source byte parity and final selected test
counts are recorded in [STATUS.md](STATUS.md). See
[ADVANCE_PARTY_CURRENCY.md](ADVANCE_PARTY_CURRENCY.md) and [PLAN.md](PLAN.md).
