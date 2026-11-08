# Co-owned Sales outstanding/POS/write-off comparisons — batch177–184

This checkpoint joins the earlier paid/guard, receivable and consumed POS source
components. It is an internal offline inspection/comparison, not an installed
calculator, posting override, source writer or dispatch authorization.

## 177: one graph, field union and owned connection

`capture_settlement_context` uses the existing owned defaults/financial service.
One numeric graph, method source and format pool capture the field union:
paid/base-paid, change/base-change, grand/base-grand, outstanding and (since180)
total advance. The fixed
payment acquisition retains its original four-field default. A validated ordered
`project_stage` gives the unchanged strict payment and receivable calculators
their original stage shapes without new captures, cache queries or SQL owners.
Reordered/missing/duplicate subsets and skip declarations are refused.

The existing graph can now be explicitly shared with invoice-rounding controls
and POS lookup inspection. Require the same policy, invoice/type and current
actor; field permissions from another actor cannot be borrowed. Retain the
original invoice object and table/row access objects. The optional POS lookup is
still an explicit inspection kind (`limit`, `default`, or no lookup), never a
requester-selected profile or an inferred controller branch.

`SavedSettlementRead` binds guarded paid, party/write-off/receivable, rounding
controls and optional POS contexts to identical financial/default/method source,
table membership and original owner. The normal POS Link definition, level and
getter are pinned even when no master lookup is requested, matched to native
metadata/values and rechecked through close. Thus normal nonnumeric Link drift
cannot hide behind an otherwise unchanged numeric view.

This declared inspection group can read settings unused by an early guard exit;
it does not claim minimum dependencies, minimum latency or an automatic runtime
source planner. Existing smaller inspection operations remain available.

## 178: checked money and branch handoffs

`OutstandingSequence` composes existing calculation objects without copying their
amount formulas. Paid remains BEFORE return/internal guards and their integer
zero reset. On continuation, payable/change/outstanding sources must match the
co-owned context. Cash-change grand/rounded values must equal the payable prefix,
and the selected paid/base-paid and change values must match their preceding
results exactly, including numeric types and float bits.

The primary rounds paid_amount once more before cash change. The current change
comparison consumes the earlier paid result; this bridge checks that second
rounding is idempotent and refuses an inconsistent handoff instead of ignoring
it. A sequence without the optional180 prefix still treats grand/advance/write-off/
base values as supplied post-prefix observations; it does not attest preceding
round/base-conversion execution.

Saved POS/return/consolidation/automatic controls and exact profile Link bind the
tail to its outstanding amount. A queried limit must equal the native consumed
limit. A return redistribution must use this payable amount, party-account
currency, processed original rows and exact native default observation. The
derived paid recalculation reuses the old shared kernel. An unused or missing
lookup and a rebound owner, currency, prefix or amount require review. Currency
units/signs and the primary allow-in-returns behavior are preserved, not repaired
or approved for accounting eligibility.

After return payment replacement, the primary recalculates paid but leaves the
earlier outstanding assignment unchanged in this call. The sequence preserves
that order and does not invent an extra outstanding recalculation.

## 179: explicit write-off followup and primary probes

`WriteOffFollowup` binds a separately invoked write-off plan to the tail's exact
automatic flag, this outstanding amount and the paid conversion rate. NULL
inactive flags remain NULL. Enabled plans retain the existing rounded write-off,
rounded base conversion and ONE required outstanding call. That second call is
not executed, and its final balance is never assumed to be zero.

Native synthetic probes execute the unchanged installed15/pinned16 outstanding,
paid and cash-change bodies. Return redistribution executes the unchanged helper
once with only a test epilogue exposing its sum/pending locals. Internal skip
uses the actual versioned invoice/transfer guard bodies. Existing per-stage
comparisons check real results, consumed precision/method traces and order.
At179 the first round/base-conversion hooks were explicit observation stubs.
Batch180–181 replaces those hooks in the synthetic probes with unchanged primary
method bodies as described below. This still does not attest a live controller.

Additional NEW guard-owned TCP-disabled SQL probes cover early field/row denial,
cross-source changes from final metadata callbacks, independent visibility after
rollback, close-time Link/permission/definition drift, wrong owners and unused
lookups. Existing paid/change cases and normal POS/rounding access regressions
remain in the affected selection. Counts are in [STATUS.md](STATUS.md).

## 180–181: source-bound outstanding prefix and primary execution probes

Add total-advance precision to the existing field union and project grand/advance
proofs onto `SavedSettlementRead.prefix`. Require the same numeric snapshot,
method, original object and ordered targets as the guarded paid/receivable group.
The overlapping grand-total proof must be identical, including its scoped cache
observation; equal resolved precision alone cannot rebind the shared field.
Write-off fields reuse their existing side metadata and precision/cache evidence;
they do not become unrelated financial header fields or require a second owner.
No old capture operation gains this extra target.

`OutstandingPrefixCalculation` consumes bounded `NUMERIC_FIXED` or explicitly
`CALCULATED` observations. Reuse the versioned field-rounding kernel for:

1. `round_floats_in(grand_total, total_advance, write_off_amount)` in primary order.
2. Source write-off rounding again, multiplication by conversion rate, then base
   write-off rounding. The second source rounding does not assign to that source.
3. Exact handoff of all seven payable inputs, including unchanged rounded totals
   and base grand total and the overwritten base write-off amount.

Compare each phase's consumed method lookups and precision calls separately.
The first phase has one method fetch plus fallback lookups for processed non-NULL
values when the setting is empty. NULL becomes0.0. Conversion subsequently uses
two independently resolved `flt` calls. Preserve NULL/integer untouched fields,
float bits, signed zero and source-before-FX ordering; do not silently substitute
an XML amount policy or force every monetary field to two decimals.

`OutstandingSequence(prefix=...)` requires this same source, exact payable values,
`CALCULATED` payable representation and the paid conversion rate. Early guard
exits cannot consume a prefix. Omitting the prefix remains an explicitly partial
old comparison, never evidence that prefix execution occurred.

The updated synthetic sequence probes execute installed15/pinned16 document
rounding and `_set_in_company_currency` bodies. Dedicated NEW private SQL cases
also exercise positive/negative tie inputs, NULL and blank method settings,
NULL money, unequal source/base precision, saved numeric binding, altered traces,
wrong owners and denied advance-field READ. Prior guards, POS limit/return
branches, internal reset and inactive NULL followup remain in the affected
selection. No controller is installed or invoked on a saved application invoice.

## Remaining adoption gates

No controller, RPC, hook, schema, cache, invoice/counter, Bench/worker or authority
request is enabled. Batch182–184 now compares one second outstanding call after
write-off, retaining changed state and derived payment identities on the original
source. It preserves the single-call order and does not guarantee zero. Complete
two-pass POS acquisition for newly required default reads and expand the primary
matrix before whole settlement adoption. See [WRITE_OFF_REENTRY.md](WRITE_OFF_REENTRY.md).
Historical advance aggregation, missing-profile policy and Mode/account/company/
currency/return eligibility, audited provider/cache/API/committed-source provenance, concurrency,
installed15/16 lifecycle, GL/VAT/XML/SDK, performance and separately approved
fictional-Company acceptance remain required. Guarded rehearsal timings are not
live invoice latency measurements. See [POS_PROFILE_ACCESS.md](POS_PROFILE_ACCESS.md),
[RECEIVABLE_CALCULATIONS.md](RECEIVABLE_CALCULATIONS.md) and [PLAN.md](PLAN.md).
