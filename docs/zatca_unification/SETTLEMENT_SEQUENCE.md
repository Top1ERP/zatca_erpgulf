# Co-owned Sales outstanding/POS/write-off comparisons — batch177–179

This checkpoint joins the earlier paid/guard, receivable and consumed POS source
components. It is an internal offline inspection/comparison, not an installed
calculator, posting override, source writer or dispatch authorization.

## 177: one graph, field union and owned connection

`capture_settlement_context` uses the existing owned defaults/financial service.
One numeric graph, method source and format pool capture the seven-field union:
paid/base-paid, change/base-change, grand/base-grand and outstanding. The fixed
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
it. Post-prefix grand/advance/write-off/base values remain supplied observations;
their preceding round/base-conversion execution is not attested here.

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
The first round/base-conversion prefix hooks are explicit observation stubs, so
these are checked handoffs rather than full controller/prefix execution proof.

Additional NEW guard-owned TCP-disabled SQL probes cover early field/row denial,
cross-source changes from final metadata callbacks, independent visibility after
rollback, close-time Link/permission/definition drift, wrong owners and unused
lookups. Existing paid/change cases and normal POS/rounding access regressions
remain in the affected selection. Counts are in [STATUS.md](STATUS.md).

## Remaining adoption gates

No controller, RPC, hook, schema, cache, invoice/counter, Bench/worker or authority
request is enabled. Verify prefix rounding/base conversion and the second
outstanding pass, historical advance aggregation, missing-profile policy and
Mode/account/company/currency/return eligibility before whole settlement
adoption. Audited provider/cache/API/committed-source provenance, concurrency,
installed15/16 lifecycle, GL/VAT/XML/SDK, performance and separately approved
fictional-Company acceptance remain required. Guarded rehearsal timings are not
live invoice latency measurements. See [POS_PROFILE_ACCESS.md](POS_PROFILE_ACCESS.md),
[RECEIVABLE_CALCULATIONS.md](RECEIVABLE_CALCULATIONS.md) and [PLAN.md](PLAN.md).
