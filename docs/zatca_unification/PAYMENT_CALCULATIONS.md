# Sales Invoice paid amount and cash change — batch161–163

This DEV checkpoint adds read-only comparisons for the base controller's
`calculate_paid_amount` and `calculate_change_amount`. It covers Sales Invoice,
including its `is_pos` flag and returns. Standalone POS Invoice has an additional
`validate_change_amount` path with write-off and account checks; this checkpoint
does not substitute Sales Invoice rules for that path.

## 161: one owned payment context

`SavedCalculationDefaultsService.capture_payment_calculation_context` reuses the
existing owned numeric graph, financial/default read, method source and ordered
root precision stage. It selects `paid_amount`, `base_paid_amount`,
`change_amount` and `base_change_amount` explicitly. This is a bounded inspection
group, not a claim to acquire only the branch's minimum dependencies.

An optional trusted `payment_controls_metadata_reader` supplies the distinct
`source-invoice-payment-controls-metadata/v1` profile: `is_pos`, `is_return`,
`redeem_loyalty_points` and `loyalty_amount`. Its reader specializes the shared
root-control reader. Overlapping financial declarations and raw cells must agree;
native money/NULL/Check values remain separate from normalized flag projection.
No existing financial profile, payload domain or SQL connection owner changes.

Normal document/table/row/field READ and original/fresh metadata/getter checks
precede providers and continue through rollback and close. Numeric graph binding
alone cannot prove a categorical Cash decision: separately bind each payment's
`type` across original direct children, parent references and fresh reads, then
compare the complete ordered tuple to native rows. Missing type means no Cash
match, never an inferred cash payment. Changed values without a timestamp change,
lost permissions or replaced precision caches fail the existing aggregated,
localized presentation. There is no public RPC or installed provider registration.

## 162: paid amount

`PaidAmountCalculation` accepts protected source evidence, an explicit
`NUMERIC_FIXED` or `CALCULATED` representation, complete ordered payment amounts,
conversion rate and loyalty amount. Saved projections must match exact
precision-free native numeric projections. Calculated inputs are observations;
they do not prove earlier arithmetic or execution in a live controller.

Preserve the primary controller's order in both versions:

1. Start invoice/base accumulators at float zero.
2. For `is_pos`, apply precision-free `flt` to each payment amount, multiply by
   precision-free conversion rate, then accumulate left to right. Do not round
   each payment or converted row with currency precision.
3. Ordinary non-POS sales plan clearing the payment table. Non-POS returns keep
   the rows but do not add them to paid totals in this method. No rows are cleared
   or written by the comparison.
4. Enabled nonzero loyalty amount is already in company currency: add it directly
   to base paid and divide by precision-free conversion rate for invoice paid.
   A zero/NULL rate with active nonzero loyalty is refused. Zero loyalty avoids
   that division. Conversion-rate business eligibility is a separate gate.
5. Round paid and base paid independently with their captured field precisions.

Observed processed row amounts/base amounts, final totals, planned clearing and
ordered precision/System-method calls must match exact numeric types and float
bits. Retained but unprocessed return rows are not reported as touched rows.

## 163: cash change

`ChangeAmountCalculation` binds the paid result from that same context. Select
truthy rounded/base-rounded totals independently, otherwise grand/base-grand
totals. Start both change values at float zero. Only a non-return Sales Invoice
with paid strictly greater than the chosen total and a remaining exact `Cash`
payment type enters the rounding branch. A zero-valued Cash row still qualifies;
lowercase `cash`, card-only payments, equal paid, cleared rows and returns do not.

Subtract invoice/base totals from their respective paid amounts before separate
captured precision rounding. Observe exact results and only the precision and
method lookups actually consumed. Signed zeros, negative totals, NULL rounded
fallbacks, cancellation-sensitive summation and missing raw method values remain
explicit test cases. The comparison does not grant payment or invoice authority.

## Evidence and remaining gates

Primary comparisons execute the installed ERPNext15 method bodies and pinned
ERPNext16 bodies from commit `ade850bbd6a7412e9994a9637d2c5c713771632a`, with the
actual/pinned Frappe `flt` helpers. The pinned full-file SHA and existing GPL
notice/license are retained in the test oracle. These two method ASTs are equal
between the inspected versions; installed ERPNext16 acceptance is still pending.
Tests execute only unpersisted synthetic controller objects. Private SQL tests
use newly created, guard-owned, TCP-disabled temporary MariaDB servers.

Complete outstanding/write-off recursion, standalone POS Invoice validation,
advance matching/relinking, tax/GL/VAT/XML reconciliation, durable provider/cache
provenance, SDK checks and installed15/16 acceptance remain integration gates.
There are no live app/site/schema/cache/worker changes or authority requests.
Counts and limitations are recorded in [STATUS.md](STATUS.md). See
[ADVANCE_LIMIT.md](ADVANCE_LIMIT.md) and [PLAN.md](PLAN.md).
