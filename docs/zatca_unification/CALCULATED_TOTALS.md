# Current calculation inputs and aggregate comparisons — batch148–150

This DEV checkpoint covers two explicit arithmetic stages using the existing
owned financial/defaults/rounding context. It neither installs a runtime provider
nor executes an ERP controller against a saved document. All test data is
synthetic; native tests use NEW TCP-disabled guard-owned MariaDB subprocesses.

## 148: distinguish current rows from saved values

`calculated_totals.CalculationRows(financial, table, representation, values)`
binds complete ordered `items` or `advances` observations to one existing
`LockedInvoiceFinancialRead`. Row identities, membership, order, present numeric
field metadata, types and bounded finite inputs are checked. The digest includes
the entire native source hash, table, representation and tagged values.

`NUMERIC_FIXED` must exactly equal the saved precision-free numeric projection.
`CALCULATED` permits explicitly observed changed values. It does **not** prove
that earlier discounts, mapped discounts, tax-inclusive conversion or other
controller steps produced those values. No conversion, source guessing,
tolerance, stale-source repair or implicit saved/current equivalence is used.
Integer/float values retain exact type and float bits; bool/Decimal/nonfinite
inputs are refused. Only advance allocated amounts permit NULL.

The existing saved-stage comparison remains strict. Calculated header sums
cannot be certified by passing them off as saved header values. Its trace
validator is shared with the new comparisons rather than copied. Protected
representations and refused serialization avoid exposing financial values.

## 149: calculate_net_total comparison

`NetTotalsCalculation(source, rows)` requires one root stage containing exactly
`total`, `base_total`, `net_total`, `base_net_total`, in controller order, without
skips. Each complete item supplies `qty`, `amount`, `base_amount`, `net_amount`,
`base_net_amount`. Accumulators start at float0.0 and add left to right, matching
ERPNext. Decimal, `fsum` or reordered summation would change cancellation and
rounding. `total_qty` is accumulated without the four money-field rounding calls.

The comparison exposes before/after totals and quantity. `require_match` checks
complete ordered results, exact value types/float bits, raw setting lookup traces
and root-owned precision calls. It reconstructs the bound source and derived
values first, including signed-zero checks. The existing versioned rounding
kernel and captured field precision/method are reused.

Installed15 and pinned16 `calculate_net_total` method bodies are compared on
synthetic objects using actual15/pinned16 `round_floats_in` helpers. Controller
constructors, hooks, database saves and later tax/GL behavior are not invoked.
An empty financial invoice remains refused by the existing source contract.
The raw controller's empty-list zero totals are characterized separately and
do not authorize an invoice without items.

## 150: calculate_total_advance aggregation prefix

`AdvanceAggregateCalculation(source, rows)` requires the root `total_advance`
rounding context and a complete advance-table observation. It models only the
noncancelled prefix: round each allocated amount using **direct child-row**
precision, sum those results with Python's int0 start, and round the root total.
Legacy zero-precision results can remain integers, affecting cancellation.
NULL allocated amounts return float0.0 before any method lookup.

Each non-NULL row's `flt` and the root `flt` omit an explicit rounding-method
override in ERPNext; they each look up the raw System method. The comparison
checks those calls and direct row/root precision traces in their exact order.
An empty advance table has int0 sum, no row-precision calls or row-currency
fallback dependency, and only the root method lookup. Cancelled controller
behavior is characterized as skipping the entire calculation; cancelled sources
are outside this prefix comparison.

This stage resolves fresh direct-row precision from captured metadata/defaults.
It does not claim to attest an active row's precision cache. A consumed16
direct-row currency-format fallback is explicitly refused until its exact source
is captured; parent-owned precision must not substitute for it. Empty tables
do not consume that dependency. Root field precision retains the existing
captured owner/cache/format policy.

The subsequent invoice limit, currency conversion, paid/outstanding/write-off,
advance matching, settlement references and XML/VAT treatment are outside this
prefix. No old advance invoice is rewritten, relinked or submitted.

## Version evidence and integration boundaries

Pinned ERPNext16 source excerpts extend the existing GPL oracle alongside its
full license, source URL, revision and file SHA. Added methods are
`calculate_net_total`, `calculate_total_advance`, `_calculate` and
`calculate_item_values`; earlier excerpt content is unchanged. The inventory
records16's mapped-discount step before net totals and item skip fields, versus
15's withholding/cleanup flow. Equal net-total bodies do not imply full tax-flow
equivalence across versions.

No new financial-source manifest, SQL reader, public capture API, RPC, hook,
writer, frontend message or authority endpoint is introduced. Existing localized
aggregate error presentation remains the service boundary. English internal
codes contain no protected selected values.

Before runtime integration, bind actual current-stage/controller identity,
earlier arithmetic, direct-row cache/currency provenance, transaction/actor and
installed15/16 behavior. Complete discount/tax/GL/VAT/advance/XML parity, worker
and custody integration, unused-code review, performance and SDK gates remain.
Only after development completion and separate approval may a fictional Company
rehearsal and gradual adoption/cancellation decision follow. No authority request
or live-environment change is authorized by this checkpoint.

See [ROUNDING_STAGE.md](ROUNDING_STAGE.md), [PLAN.md](PLAN.md),
[STATUS.md](STATUS.md) and [SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).
