# Receivable suffix and automatic write-off — batch164–166

This DEV checkpoint shares saved write-off/party acquisition and compares the
arithmetic suffix of `calculate_outstanding_amount`, plus the ordered updates and
single downstream call of `calculate_write_off_amount`. It does not close the
entire outstanding controller, accounting settlement or POS Invoice lifecycle.

## 164: shared write-off access and precision

`WriteOffInputsAcquisition` owns normal/native binding of the existing write-off
side profile, transaction currency and party-account currency on the enclosing
service's connection. `WriteOffStageMixin` shares preparation, native reads,
getter checks, pre-format cache observation and cleanup rechecks. Both the old
advance-ceiling acquisition and the new receivable acquisition use it; there is
no parallel SQL owner or copied side-field lifecycle.

`resolve_write_precision` extracts the existing side-field precision policy.
Observe the original field's precision slot without calling `precision()` and,
only when required, its field-currency cache before format callbacks. Reuse a
co-owned root field's format with exactly matching options. Missing matching
format evidence or an inconsistent cache is refused; transaction currency is
never substituted for company/party currency. The old advance-ceiling path
still consumes only the foreign-party base-write-off precision. Its public
result, financial profile/domain and ordered advance behavior stay unchanged.

## 165: one owned receivable context

`SavedCalculationDefaultsService.capture_receivable_context` uses existing
write-off/owner-currency metadata dependencies. A fixed root stage selects
`grand_total`, `base_grand_total` and `outstanding_amount`, with both write-off
precision slots and their required formats. This is a declared inspection group,
including inactive automatic-write-off cases, not a minimum-read/cost claim.

`SavedReceivableRead` binds native financial/default/method evidence, side fields,
party identity/revision, exact return getter/native tag and both side precisions.
Original/fresh getters, field READ, metadata, precision containers and currency
cache slots are rechecked through rollback/close. The shared service retains one
localized failure presentation and English internal codes. No RPC, runtime
provider, invoice event, Company/credential operation or writer is installed.

## 166: payable, outstanding and write-off comparisons

`PayableAmountCalculation` accepts a complete ordered observation AFTER upstream
rounding and base conversion. Same-party currency chooses truthy rounded total,
otherwise grand total, subtracts advance and precision-free write-off, then
rounds with grand-total precision. Foreign-party currency independently chooses
base-rounded/base-grand total, rounds that total first, subtracts advance and
precision-free base write-off, then rounds again with base-grand-total precision.
Advance is already in party-account currency here: do not multiply it again.

`OutstandingAmountCalculation` binds that payable result and explicit paid/base
paid/change/base-change observations AFTER their preceding stages. Select paid
and change by party currency; returns use local integer-zero change regardless
of the supplied change fields. Preserve subtraction/addition order and final
outstanding-field precision. This does not certify upstream payment aggregation,
change calculation, field rounding or historical advance matching.

`WriteOffCalculation` accepts an observed canonical automatic flag, outstanding
amount and conversion rate. When enabled, round outstanding with write-off
precision, multiply that ROUNDED amount by the rate, round with base-write-off
precision, then plan exactly one outstanding recalculation. Disabled cases plan
no amount assignments or downstream call, including zero/NULL unused inputs.
The comparison writes nothing and does not execute recursion.

NUMERIC_FIXED requires the exact saved precision-free numeric projection;
flags reuse the existing saved Check matching policy, including native NULL
versus a canonical int-zero getter, without changing the raw source snapshot.
CALCULATED accepts bounded supplied current observations without attesting their
origin. This includes an observed automatic flag changed by earlier POS logic;
the flag observation does not prove the POS Profile limit decision. Bool,
Decimal, text, nonfinite numbers, reordered fields and tampered result/source
observations are refused. Results compare exact numeric types/float bits and
ordered consumed precision/System-method traces, without tolerances.

NULL values require separate precision and method traces: `flt(None, precision)`
still receives a precision argument but bypasses the rounding-setting lookup.
Consequently a foreign NULL base total has two precision calls and one rounding
lookup; an enabled NULL outstanding write-off also has two precision calls and
only the final base rounding lookup. Preserve the inspected legacy rounding
asymmetry for negative ties instead of inferring results by negating positives.

## Verification boundaries and next integration

Primary probes execute installed15 and pinned16 bodies with actual/pinned `flt`
helpers. The oracle retains the full-file SHA, notices and GPL license. The
outstanding probe records the preceding paid/round/base-conversion hooks as
stubs, then stops at the actual outstanding assignment, before POS Profile
queries or default-mode-of-payment redistribution. It reads the primary frame's
actual payable local. The write-off probe observes both assignments before a
single downstream stub. A separate real primary conversion probe verifies
round-before-FX and preservation of its original source amount.

Full return/internal-transfer eligibility, consolidated POS write-off limits,
return payment redistribution, complete recursive assembly, standalone POS
validation, GL/VAT/XML reconciliation, source/provider/cache provenance and
installed15/16/SDK acceptance remain gates. Tests use only synthetic documents
and NEW guard-owned TCP-disabled temporary SQL. No live app/site/schema/data/
config/worker change or authority request occurs. Counts are in
[STATUS.md](STATUS.md). See [PAYMENT_CALCULATIONS.md](PAYMENT_CALCULATIONS.md),
[ADVANCE_LIMIT.md](ADVANCE_LIMIT.md) and [PLAN.md](PLAN.md).
