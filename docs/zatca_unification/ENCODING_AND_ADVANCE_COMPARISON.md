# Bounded metadata encoding and saved advance consistency — batch189–192

These DEV changes do not install a runtime provider, change a saved financial
amount/advance reference, migrate a schema, restart a Bench or contact an
authority. They do not establish real invoice latency or fiscal eligibility.

## 189–190: profile first, accelerate only verified private subtrees

A guarded local stage-projection case showed that repeated Python JSON fragment
encoding dominated its evidence reconstruction. The selected case was
`test_settlement_stage_projection.py -k 'keeps_exact and 15-names0-16'`.
Its baseline cProfile recorded44,069,810 calls in10.922s; canonical encoding
accounted for8.106s cumulative. This is a synthetic source-comparison profile,
not an installed transaction or an uncontended CPU benchmark.

The adopted change is deliberately narrow. `SourceMetadata` still decodes its
own bounded immutable payload, checks its shape/profile and compares the WHOLE
parent against the streaming canonical encoding before processing its fields.
Only then use the same encoder configuration to encode a field-property subtree
in one shot. Such canonical subtree bytes already occur inside that verified
parent, so their allocation cannot exceed the parent bound. The tree is private
to the constructor and no user callback gets its mutable containers. An extra
child-length check protects this invariant against future changes.

`SourceFieldDefinition` still independently checks the field name, property
types, allowed values and streamed canonical byte equality. No validation cache,
skip flag, persistent protected payload, new digest domain or wire-profile
version is introduced. `_canonical_encoder` centralizes the original JSON
configuration; `_canonical` retains its streaming aggregate bound for arbitrary
inputs. The existing fragment-consumption limit test remains applicable.

The same profiled case after this narrow change recorded36,103,442 calls in
9.155s, with6.263s cumulative canonical encoding and18,130 canonical calls
instead of31,206. A separate pure construction comparison used the same16,998
byte metadata payload for50 reconstructions, three repeats: baseline
0.5454/0.4976/0.4617s, verified-subtree0.3304/0.3409/0.3690s. The medians improved
about31.5%; this does not predict application latency or all payload costs.

Byte/boundary tests cover Arabic/non-BMP text, control escapes, typed zeros,
negative zero, Decimal scale, large defaults, invalid Password fields, reordered
properties, noncanonical/oversize parents and independent field construction.
Existing saved financial wire fingerprints must remain identical.

## 191: report saved allocation consistency without repair or relinking

`compare_saved_advances(plan, advance_context=None)` builds complete ordered
`NUMERIC_FIXED` advance rows from the already captured settlement source, then
reuses `AdvanceAggregateCalculation` and its row/root precision evidence. No
second capture, lookup, permission/default refresh or financial override occurs.
If unset16 row-currency formats need evidence, an existing matching context must
be supplied; the old kernel refuses an uncaptured format rather than guessing.

`SettlementAdvanceComparison` binds the exact same root total-advance field
proof, numeric source, method, owner and ordered rows to the validated plan.
Reapply the versioned root rounding in each consumed outstanding prefix, in
order, and compare exact result types/bits with the amount actually consumed
by the plan. Never repair stale stored total_advance, substitute a newly found
advance invoice or claim a matching amount proves historical provenance.

The metadata-only outcomes are `MATCH`, `MISMATCH` and `NOT_CONSUMED`. An internal
early exit consumes no prefix and gets the latter result, not a fictitious zero
or PASS. A cancelled aggregation remains refused by the existing primary-domain
gate. Explicit CALCULATED row overrides cannot qualify as saved consistency.
Row identifiers and historical reference names remain unchanged and protected.

This checks arithmetic consistency only. It neither searches nor authorizes
legacy matching/settlement, tax/GL/VAT, Phase1-to-Phase2 reconciliation, receipt
acceptance, UUID/ICV continuity or eligibility of a referenced Payment/Journal/
Advance Invoice. Those existing gates still apply independently.

## 192: cross-path regression and adoption gates

Exercise same-source matches in15 and16, a deliberately stale total and an
internal guard exit using NEW guard-owned TCP-disabled SQL only. Check no
further SQL/capture occurs, native data remain unchanged, old reference labels
are preserved, supplied calculated rows are rejected and a forged report
status fails reconstruction. Existing advance ceiling/rounding, financial and
late-POS source comparisons remain in the affected selection. Exact executed
counts and timings are recorded in [STATUS.md](STATUS.md).

All24 existing capture methods retain their bodies; the new comparison is a
pure explicit composer, not a registered application endpoint. Performance and
source/provenance/lifecycle/SDK/accounting acceptance remain before separately
approved isolated fictional-Company rehearsal. No working-site adoption or
authority request is authorized. See [SETTLEMENT_PLAN.md](SETTLEMENT_PLAN.md),
[ADVANCE_ROUNDING_CONTEXT.md](ADVANCE_ROUNDING_CONTEXT.md) and [PLAN.md](PLAN.md).
