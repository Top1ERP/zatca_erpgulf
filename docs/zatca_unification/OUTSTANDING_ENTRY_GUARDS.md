# Outstanding entry: return/internal decisions and paid order — batch167–169

This DEV checkpoint inspects the saved fields used by the primary outstanding
entry condition and compares that entry together with the real paid stage.
Comparison stops before ordinary balance rounding. It does not run saved invoice
controllers, calculate GL, redistribute payments or contact an authority.

## 167: native Check/Link controls

`source-invoice-outstanding-guards-metadata/v1` selects `company`, `is_return`,
`is_pos`, `return_against`, `update_outstanding_for_self`, `is_internal_customer`
and `represents_company` for Sales/POS Invoice. `LockedOutstandingGuardsRead`
specializes the existing root-control reader and has its own payload domain.
Physical presence/absence, metadata, descriptors, raw values, original revision
and overlapping financial cells/declarations are checked on the same handle.

The common reader now accepts a fixed Link declaration alongside its existing
Check/Currency policy. An absent Link target in that declaration means a Link
to the source DocType itself: Sales returns reference Sales Invoice and POS
returns reference POS Invoice. Company links remain literal Company targets.
This is class configuration, never a request-selected SQL field/target. Existing
control profiles keep empty Link declarations and their prior bytes/domains.

Preserve raw NULL/blank text and canonical Check values separately from normalized
Check projection. POS's absent update/internal/represented-company fields are
proved absent and require getter None; never invent them or treat POS as Sales.
Invoice fields are the source of this condition, not freshly fetched Customer or
Company master properties. Link target proof is not reference-existence proof.

## 168: saved READ and exact entry decision

`capture_outstanding_guard_context` uses the existing owned saved-financial/
defaults service, with trusted optional `outstanding_guard_metadata_reader`.
Normal record/table/row/field READ precedes providers. Compare original/fresh
selected metadata, levels, getter values and native controls through cleanup.
The common financial/default context is still read; this operation acquires no
numeric-fix getter, rounding-method source, precision or field-currency cache.
It installs no RPC, provider registration or new failure presenter.

`OutstandingGuardInputs` and `OutstandingGuardDecision` compare supplied controls.
`from_saved` reconstructs the protected saved read before deriving inputs. Pure
inputs alone are not saved-origin or accounting-eligibility evidence. Preserve
the primary order and Boolean short circuit:

1. Sales Invoice calls `calculate_paid_amount` first, even if it will reset the
   outstanding amount immediately afterwards. POS Invoice skips this base paid
   call; its separate document lifecycle remains outside this comparison.
2. A return with truthy reference, false update-for-self and false POS flag skips
   ordinary balance calculation. Its successful conjunction short-circuits the
   internal-invoice test. Keep exact reference truthiness, including whitespace.
3. Otherwise call `is_internal_invoice`. For Sales this calls the document's
   `is_internal_transfer`: internal-customer flag AND represented company exactly
   equal to billing company. No trimming, cross-company substitution or master
   lookup is introduced. POS's wrapper returns false without that document call.
4. A skipped balance assigns integer zero to outstanding and returns. Otherwise
   continue to the first `round_floats_in` boundary. Float zero is not an exact
   observation of the controller's integer-zero reset.

## 169: one owned paid/guard composition

`capture_guarded_payment_context` uses the same numeric root, original owner,
native financial/default sources and owned SQL transaction for payment and guard
evidence. `SavedGuardedPaymentRead` requires exact financial/table/owner identity;
it never composes two independent service captures. Existing payment/loyalty/
currency/method/precision rules stay in their preceding shared implementation.

`GuardedOutstandingEntry` binds that source and its `PaidAmountCalculation`, then
derives the guard decision from the bound controls. Observations must match
processed payment rows, invoice/base paid totals, planned table clearing,
precision/System-method traces, full paid/internal/terminal call order, reset and
continuation. Reject changed owner IDs, reordered guard snapshots, foreign
decision objects and altered output types. No assignments or recursion run here.

Primary tests execute the installed15 and pinned16 paid/outstanding/internal
method bodies on unpersisted synthetic documents. The terminal rounding hook
raises a private boundary before later POS Profile or accounting work. Successful
guard branches observe the actual integer-zero assignment. Source-free logic
probes stub paid only; the native co-owned matrix executes the real paid body
and verifies it before inspecting the reset/continuation. The oracle retains
the upstream file SHA, notices and GPL license for `is_internal_transfer`.

## Remaining assembly and validation

Ordinary balance rounding/conversion, payable/outstanding suffix and automatic
write-off comparisons already exist as separate stages. Full assembly must bind
their intermediate observations on a shared complete preparation context and
honor this entry's continuation decision. Consolidated POS Profile write-off
limits, default-mode return redistribution, standalone POS validation, complete
recursive/accounting flow, reference/master provenance, GL/VAT/XML reconciliation,
installed15/16 and SDK acceptance remain gates before fictional-Company rehearsal.

All tests use local synthetic objects or NEW guard-owned TCP-disabled temporary
SQL. No live code/config/schema/data/worker or authority operation is changed by
this development checkpoint. The separately user-approved Glassline invoice
status correction remains a distinct operational action; it is not deployment
of this branch. Counts and prior-control byte parity are in [STATUS.md](STATUS.md).
See [RECEIVABLE_CALCULATIONS.md](RECEIVABLE_CALCULATIONS.md) and [PLAN.md](PLAN.md).
