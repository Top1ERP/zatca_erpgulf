# One bounded outstanding re-entry after write-off — batch182–184

This is an uninstalled offline comparison on the existing co-owned settlement
source. It neither saves an invoice nor invokes a live controller, worker,
accounting hook or authority transport. It does not complete the release plan.

## 182: retain processed or replaced payment rows

`PaidAmountCalculation(prior=...)` permits one derived paid calculation. The
original `prior=None` path retains exact saved-table membership checks. A prior
must be the initial paid result or its first `PosReturnPaidCalculation`, from
the same source and with identical conversion-rate/loyalty inputs. The new
representation must be `CALCULATED`; it cannot claim native saved-row identity.

For POS rows, re-use the preceding processed amounts and names. For ordinary
Sales invoices, retain a prior table-clear effect; do not resurrect the original
saved rows. A non-POS return retains its unchanged original row inputs. Reuse
the existing `_paid_values` arithmetic once per calculation, including loyalty
in company currency; never carry paid totals forward as if they were row sums.

Bound ancestry before reconstruction. A prior derived paid result or a return
wrapper around one cannot authorize a third paid re-entry through this API.
`PosReturnPaidCalculation.pin()` preserves its existing exact outputs, and new
append names cannot collide with current rows OR retired saved-row names.
No child record or identifier is actually allocated by these models.

## 183: pass exact in-memory state, not a new saved-source capture

`WriteOffReentry` accepts an enabled `WriteOffFollowup` from the first sequence
only. Require the bound first prefix. Keep rounded grand/advance and untouched
rounded/base totals from that prefix, then replace source/base write-off inputs
with the existing write-off plan's exact amounts. Retain the original source,
conversion rate, automatic flag and the actual prior payment effect/row inputs.
Disabled or NULL automatic flags do not authorize a recalculation.

`OutstandingSequence(reentry=...)` composes the same existing paid, guard,
prefix, payable, change, outstanding and POS comparisons for that one later call.
Require exact derived rows/headers/prefix inputs and the newly assigned flag.
Compare numeric tags, not dataclass equality alone: +0.0 and -0.0 compare equal
in Python but remain distinct handoff observations. Ordinary first calls cannot
silently consume derived rows, and a re-entry cannot omit its prefix or skip a
previously continuing guard. No first/last invoice, ICV, UUID or PIH is changed.

An already consumed POS read may be unused in the second call. If a required
second-call read was never captured, supplied default observations cannot replace
that missing source. In particular, a first return can skip the default query,
then require it after write-off changes the amount to pay. That path currently
requires review. The two-pass acquisition planner must supply that source on
the same owned transaction before this group can be adopted as a whole service.

## 184: unchanged primary bodies on continuous synthetic document state

The test probe carries the first actual synthetic document's values and child
objects into the second observation wrapper. Execute installed15/pinned16
`calculate_write_off_amount`, which calls the actual outstanding body exactly
once; retain real method/precision traces for the write-off and all existing
stages. This is not a saved application's object/lifecycle identity proof.

Cover limit-enabled POS, foreign return with a replaced payment, an ordinary
invoice with cleared rows, an inactive NULL flag, and a newly required uncaptured
default query. The latter query is reached in actual primary code and stopped
by the synthetic source-missing observer; no made-up source value is returned.
The foreign-return example leaves a nonzero outstanding just as the primary
does. Never force zero, invent a further outstanding call after its return tail,
or invoke write-off recursively to make the comparison appear successful.

Negative probes cover changed headers/rows/flag/base-prefix inputs, native-mode
mislabeling, third ancestry, retired row-name reuse, detached derived entry and
signed-zero header changes that dataclass equality alone would miss. Existing
paid/change and return-paid comparisons remain in the affected test selection.
Exact executed selections and counts are recorded in [STATUS.md](STATUS.md).

## Remaining gates

Complete two-pass conditional POS acquisition, including first-unused/later-needed
default sources on one owner. Test the expanded branch/version/rounding/currency
matrix, profile repeated evidence reconstruction and do not infer invoice-save
latency from private rehearsal timings. Historical advance allocation, payment
account/return/company eligibility, cached/provider provenance, concurrency,
installed15/16 lifecycle, GL/VAT/XML/SDK and separately approved isolated fictional
Company acceptance remain open. Authority requests and working-site adoption
remain prohibited. See [SETTLEMENT_SEQUENCE.md](SETTLEMENT_SEQUENCE.md) and
[PLAN.md](PLAN.md).
