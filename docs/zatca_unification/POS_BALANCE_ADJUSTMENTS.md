# POS balance suffix and return payment replacement — batch170–172

This DEV checkpoint compares the two POS branches after the outstanding amount
has been assigned, the default-payment redistribution helper, and the following
paid recalculation. It runs no profile query, payment write or authority request.
Profile/default-query answers are explicitly supplied observations. Their native
selection, permission, revision and cache provenance remain integration gates.

## 170: consolidated write-off limit and return dispatch

`PosTailInputs`, `PosLimitObservation` and `PosTailCalculation` preserve the two
inspected ERPNext15/16 conditions. Only Sales Invoice with POS enabled, a truthy
POS Profile and consolidation queries that profile's write-off limit. Convert
native numeric/Decimal/NULL through the precision-free `flt` behavior; no currency
rounding or System-method read occurs. A nonzero limit and absolute outstanding
less than OR EQUAL to it assign integer one to automatic write-off. Otherwise
retain the exact preceding flag, including NULL or one. Do not reset it to zero
or optimize away an assignment when it was already one. A negative limit remains
negative and cannot match a nonnegative absolute outstanding.

A nonconsolidated POS return calls default-payment redistribution followed by
paid recalculation regardless of whether redistribution changes any rows. That
dispatch does not require a truthy profile in the primary condition. Standalone
POS Invoice does not enter these Sales-specific branches. Query observation
distinguishes not-queried from queried-with-NULL; unused speculative lookup data
and a fabricated successful query are rejected.

## 171: exact default-payment redistribution

`DefaultMopRedistributionCalculation` starts its total at integer zero and sums
ordered payment amounts in party-account currency: invoice amount when party and
transaction currency agree, otherwise base amount. No per-row `flt`, rounding,
FX conversion or loyalty addition occurs in that summation. Selected NULL amounts
fail; unselected nullable amount fields are retained. Preserve float association,
signed zero and integer zero for an empty table.

Pending is amount-to-pay minus that row sum. Only strictly positive pending
queries `POS Payment Method` with exactly parent/profile and default=1, returning
mode_of_payment with as_dict=1. The inspected method does not add parenttype,
allow_in_returns, currency or ordering filters. Missing default result preserves
the original table. A found result replaces all rows and appends the literal
mode/pending/default-one mapping, even when the returned mode itself is NULL or
blank. Such a mapping is not proof of a valid payment account or return sign.

The comparison preserves the primary amount units: pending is inserted directly
as amount without an additional FX correction. Positive pending can arise even
with a negative return total when selected payments are more negative. Do not
silently change its sign, substitute a default, or round it here. These are
compatibility observations, not approval of every supplied accounting scenario.

## 172: one paid kernel before and after replacement

`_paid_values` extracts the existing paid arithmetic once. Saved
`PaidAmountCalculation` still validates its complete saved row membership and
current-value representation before invoking it. An AST comparison against the
committed preceding body verifies the arithmetic is identical, with only
self.rows replaced by the function's rows parameter.

`PosReturnPaidCalculation` requires that saved paid result, a return-dispatch
tail and a redistribution bound to its exact original processed rows, transaction
currency and saved profile link. A replacement needs an explicit observed NEW
row name distinct from the saved row names; a no-replacement needs no append
name. This derived plan does not pass an invented row through the old saved-row
membership check. Reuse the same kernel, parent conversion/loyalty inputs and
captured paid/base-paid precisions for the new row group.

Compare exact processed invoice/base row values, final paid totals, and consumed
precision/System-method traces. Paid recalculation happens even for a missing
default or nonpositive pending. No outstanding recalculation is invented after
this suffix: the primary controller leaves the earlier outstanding assignment
until a later caller/stage explicitly recalculates it. No row is saved, appended
or cleared by any comparison.

## Primary evidence and integration boundaries

Primary probes compile the unchanged post-assignment conditional statements from
the installed15 and pinned16 methods. The redistribution probe executes all
original statements once and adds only a test epilogue returning the actual sum
and pending locals. Mocked lookups assert exact API arguments; they do not contact
a database. Native tests acquire the preceding paid context from NEW guard-owned
TCP-disabled temporary SQL, execute the real redistribution/paid helpers on
unpersisted documents, and compare replacement, missing-default and no-query
paths in same/foreign party currency with loyalty enabled.

Native POS Profile/default-row custody is not supplied by those mocked answers.
Multiple defaults, missing/orphan profiles, selected-row provenance, company/
currency/account/sign eligibility, allow-in-returns validation and complete
rounding/guard/balance/write-off assembly remain before installed15/16, SDK,
GL/VAT/XML and separately approved fictional-Company acceptance. No installed
provider/RPC, field/schema, live code/data, Bench/worker or authority operation
is changed. Counts and limits are in [STATUS.md](STATUS.md). See
[OUTSTANDING_ENTRY_GUARDS.md](OUTSTANDING_ENTRY_GUARDS.md),
[RECEIVABLE_CALCULATIONS.md](RECEIVABLE_CALCULATIONS.md) and [PLAN.md](PLAN.md).
