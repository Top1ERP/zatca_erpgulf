# Consumed rounded-total settings — increment136, 2026-11-02

## Optional operation and reuse

`SavedCalculationDefaultsService.capture_rounded_total_context(invoice_name,
erp_major=15|16, doctype="Sales Invoice"|"POS Invoice")` composes the existing
invoice controls, Global Defaults, Currency fraction and System rounding method
on the SAME owned financial/defaults transaction. This is a partial inspection
and dependency plan. It does not calculate, normalize, zero, convert or write an
invoice amount, build XML, register a provider/hook/RPC or authorize issuance.

Reuse `InvoiceRoundingAcquisition` and its one authorized financial graph.
`FractionAcquisition` now accepts an internal existing financial graph; its
independent operation still constructs one. The composed operation does not call
other capture APIs or combine observations from independent transactions.
Singleton acquisitions, source readers, cleanup, permissions, translation and
single financial failure summary remain shared. No new provider configuration
is introduced: only the existing selected dependencies are required.

The shared `_initial_branch`, `_disable_source` and `_disabled_fields` helpers
in `rounded_total_control` serve both the older declaration-only plan and the
new native-bound plan. Old declaration profile bytes/goldens remain unchanged.
Do not construct a fake complete CalculationSettingsObservation from a partial
selection. Fraction routing and final method choice reuse their existing helpers.

## Ordered acquisition

1. Authorize the saved invoice/Company, financial tables/rows/fields and selected
   controls using existing normal READ engines. Capture original/fresh Check
   getters and, only when consolidated, the adjustment getter guard witness.
2. Consolidated with a nonzero adjustment preserves the controller's current
   values; otherwise absence of rounded_total ends this work. Neither branch
   selects Global Defaults, Currency fraction or System method sources.
3. A present invoice disable Check wins even at zero/NULL-normalized-zero. Only
   its absence selects normal Global Defaults record/field READ and metadata.
4. On the fresh owned handle, read native financial/controls and any selected
   global value. Validate their normal/API projections. A disabled result has
   the existing versioned zero/base-conversion plan, without assignments. In v15
   the early return requires no method; v16's zero base conversion DOES require
   the System method, but no Currency fraction.
5. If enabled, authorize exact invoice Currency and System record/field READ
   before their own metadata/cache/native reads. Reuse the existing financial
   graph. Both zero and positive fractions require the final amount-rounding
   method. No unused language/POS/Company-currency lookup is introduced.
6. Complete ALL trusted metadata/cache callbacks before final native checks of
   EVERY captured source. Recheck normal access and original/fresh getters
   through shared rollback/close, then compare selected API values before return.

Conditional related permissions are checked before that dependency's acquisition,
not before unrelated earlier authorized SQL: the global value that decides
whether Currency/System are needed is first proved natively on the SAME handle.
A missing/denied/invalid required dependency fails closed; it never supplies a
default zero, invents an absent field or silently switches currency/method.

The inspected v16 [conversion helper](https://github.com/frappe/erpnext/blob/ade850bbd6a7412e9994a9637d2c5c713771632a/erpnext/controllers/taxes_and_totals.py#L290)
calls precision-flt even on disabled zero totals. The
[Frappe16 rounded helper](https://github.com/frappe/frappe/blob/e8d41dd0061a32ee781caefe5d0b0d2bb7c15362/frappe/utils/data.py#L1160)
reads System method before any algorithm's zero shortcut. The existing pinned
oracle now includes the exact GPL-attributed conversion excerpt, retaining its
full-file hash and all older excerpts/licenses. Tests execute actual15/pinned16 flt:
four method reads for successful v16 zero conversion; none for v15 early return.
An unknown method fails v16 even for zeros. A stubbed conversion alone cannot
establish these consumed dependencies. This evidence is not a full ERP16 install.

Recognizable ambient handles retain their owner's pending work and are refused
without cleanup. New owned handles receive initial/final rollback and close,
never commit. Source mutation, lost permissions and interruptions follow the
existing pipeline's cleanup and message behavior. There is no atomic cache/SQL/
permission freeze or promise of freshness after disclosure. Trusted callbacks
and concrete provider provenance still require audit.

## Adjustment witness is only a branch proof

Regular saved-document loading in inspected Frappe15 retains database numeric
values; other document processing can normalize numeric types. Do not force a
Decimal money value through float just to choose a settings branch. For a
consolidated invoice, retain the exact finite numeric/NULL getter tag on both
the original authorized object and fresh normal reads. The native adjustment
and that getter must agree on zero/nonzero truthiness. Metadata absence needs
an observed None getter. Nonconsolidated paths never read that unused getter.

Different nonzero numeric values can satisfy the same controller guard. This
witness intentionally does NOT certify amount equality, a normalization stage,
rounding, tax/accounting parity or a completed source fingerprint. The native
amount and getter tag remain separate and unchanged. Full amount/ORM/cache
equivalence is a required gate before using this plan in a runtime writer.

## Protected results and callers

`RoundingDependencyPlan` independently reconstructs native controls and only the
required global/fraction/method observations, binds the guard witness and
financial parent, and fingerprints the selected branch and versioned field plan.
Missing required and extraneous unused dependencies are refused. Its original
native Check tags remain in controls; selection uses their proved API projection.

`SavedRoundedTotalContext` reconstructs the existing saved invoice/global/
fraction/method contexts and requires identical financial/context/default/site/
actor/version bindings. This is composition of same-transaction observations,
not independent capture operations. Repr is protected and pickle is refused.

Known callers are this optional service method and the reviewed
`test_calculation_rounded_total_access` and `_mariadb` suites. No button, installed
runtime adapter or background worker calls it. Separate method override behavior
remains in the existing explicit rounding inspection; this controller-oriented
operation has no new override input.

## Remaining gates

Complete amount/ORM/cache/precision/FX/GL/VAT/advance/XML/QR/signature/browser parity,
concrete provider and cashier-role review, whole-worker/custody integration,
caller/dead-code and performance audits, SDK and installed15/16 evidence remain.
Increment137 proves selected Check differences between ordinary scalar loading
and explicit numeric fixing; native NULL now binds an observed saved None without
normalizing it. See [INVOICE_CHECK_LOADING.md](INVOICE_CHECK_LOADING.md). This is
not the full controller/child/lazy/amount/precision/cache normalization bridge.
Only completed development precedes a separately approved isolated fictional-
Company rehearsal and adoption/cancellation decision. No live change or authority
request is authorized here. See [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md),
[STATUS.md](STATUS.md) and [SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).
