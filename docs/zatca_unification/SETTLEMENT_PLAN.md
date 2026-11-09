# Lazy same-owner two-call settlement inspection — batch185–188

This new internal inspection is uninstalled. It reads a saved Sales Invoice's
numeric witnesses, not a newly executed totals/advance/GL calculation. It does
not run an application controller, create a child/Company/invoice, write a saved
amount, register a provider/RPC/hook, restart workers or send to an authority.

## 185: one pre-query balance primitive

`default_mop_balance` in `calculation_pos_adjustments.py` owns the unrounded
sum/pending decision shared by the existing redistribution comparison and the
new dependency planner. Retain the primary's integer empty sum, company/party
currency selection, floating-point types and no extra FX or rounding. Loyalty
is not a payment-row amount. Validate bounded/unique rows and reject a NULL
selected amount before acquiring any POS default source. This avoids copying
the branch formula into a second production calculator.

## 186: saved-numeric planning on the existing capture boundary

`capture_settlement_plan_context` adds a separate opt-in operation. Existing
capture signatures/bodies remain unchanged. `SettlementPlanAcquisition` reuses
the same financial graph, metadata/default/method/format sources, precision
proofs, owned connection and cleanup boundary as `SettlementAcquisition`.

Read first paid/header/prefix values from native `NUMERIC_FIXED` observations;
requesters cannot supply overriding amounts or flags. Compose the existing paid,
guard, prefix, payable, change, outstanding, write-off and return-paid kernels.
If the guard exits, stop. If write-off is inactive, keep only the first call.
Otherwise carry the actual planned payment effect and changed prefix/automatic
state into one second call using the existing bounded re-entry contracts.

`append_names=(first, second)` supplies optional hypothetical observation labels,
not actual allocated child names or fiscal identity evidence. They are bounded,
distinct and needed only when a replacement is planned. A needed label is never
invented. Current/retired saved-row collisions still fail. These labels cannot
be used as a real saved child name without the actual framework lifecycle and
separate row/identity provenance required by the runtime adoption gate.

## 187: related sources are authorized and read only when needed

Plan the first and, when enabled, second branch before claiming completion.
Acquire a POS limit or default source at its first use on the existing handle.
Each related master/table/child/field READ must pass BEFORE that dependency's
metadata provider or native SQL runs. Already authorized financial metadata/SQL
can precede that late related authorization. This is deliberate lazy dependency
access, not a promise that every optional related READ occurs before financial
SQL. A denied unused master/child does not block an operation that never needs it.

Native input/model validation does not refresh saved amounts after the first
calculation. Each needed profile snapshot is acquired once and can witness both
logical queries; final metadata/native/getter/actor checks still run normally.
There is no second connection/capture and no installed cached-API origin claim.

`OutstandingSequence(pos_deferred=True)` explicitly marks a first call that does
not consume the available default source. It is allowed only for a continuing
return with an enabled write-off, a prefix and that default source. The old
default remains False and still rejects unused sources. The completed
`SavedSettlementPlan` requires the second call to consume a deferred source;
an unused reservation cannot be reported as a complete plan. `lookups` records
the two logical uses independently of how many metadata/final-check SQL reads
are needed. It is not an authority validation status.

The new service resolves lazy dependencies after numeric/default proofs exist,
BEFORE final callbacks and checks of every financial/default/related source.
Any late callback or close-time drift denies disclosure and cleanup retains
the original rollback/close ownership. Display errors use the existing one-message
translated boundary; internal codes remain English. No new UI text is added.

## 188: branch/version/settings and late-source negative checks

NEW guard-owned TCP-disabled SQL cases cover first-unused/later-needed default,
first-used/later-unused default, no query on either call, repeated limit use,
ordinary cleared rows, internal guard exit and inactive NULL write-off. Include
actual15/pinned16 functions and explicit/blank/NULL/Banker's method settings.
Run unchanged primary bodies on continuous synthetic document values for the
critical late-default and repeated-limit paths. Compare hypothetical append
labels explicitly; this is not a real saved-object lifecycle proof.

Negative cases cover master/child/field denial before its provider/SQL, changes
to another source by the last POS metadata callback, and permission drift during
close. Rollback is independently visible from a new private observer connection.
Existing defaults/financial acquisition and primary POS calculations remain in
the affected selection; exact counts are in [STATUS.md](STATUS.md).

## Remaining adoption gates

Increment193 now composes saved advance rows and their same-owned precision
evidence through the ceiling, conditional reset and this bounded settlement
planner, including guarded write-off re-entry. This adds a separate internal
capture operation; it does not replace the saved-input operation or an installed
controller. See [ADVANCE_SETTLEMENT_CHAIN.md](ADVANCE_SETTLEMENT_CHAIN.md).

Batch189–192 adds a separate saved-advance consistency composer without changing
the plan's stored inputs or authorizing historical references. It also profiles
and narrows one metadata-encoding hot path while preserving byte/boundary parity.
See [ENCODING_AND_ADVANCE_COMPARISON.md](ENCODING_AND_ADVANCE_COMPARISON.md).

These are evidence-building comparisons. Profile repeated reconstruction before
placing them on a real invoice-save or UI-polling path. Broader source/branch/
rounding/accounting cases, historical advance aggregation, missing-profile and
Mode/account/return eligibility, trusted provider/cache provenance, concurrency,
installed15/16 lifecycle, GL/VAT/XML/SDK and separately approved isolated fictional
Company acceptance remain required. Working-site adoption and authority sending
remain prohibited. See [WRITE_OFF_REENTRY.md](WRITE_OFF_REENTRY.md),
[SETTLEMENT_SEQUENCE.md](SETTLEMENT_SEQUENCE.md) and [PLAN.md](PLAN.md).
