# Select the requested v15 JSON tax key — increment206

Subsequent increment207 shares native full-detail/rate-only selection and uses
rate-only in seven existing consumers; see
[ITEM_TAX_RATE_ONLY.md](ITEM_TAX_RATE_ONLY.md). Evidence below records its own
earlier boundary and measurement baseline.

Development only. The existing `ksa_compliance/tax_details.py` now folds only
the requested item key from native dictionaries parsed from v15 JSON text.
This follows [duplicate-read removal](ITEM_TAX_READ_COST.md) without introducing
another adapter, numeric policy, field, setting or public endpoint.

## Work removed and retained ownership

Previously `_v15_details` parsed each tax row's JSON and normalized/accumulated
every item entry even when `get_item_tax_detail` consumed only one key. It did
this again for every physical item. The adapter now passes its already resolved
`legacy_key` into the fold. For JSON text producing an exact native dict, the
fold selects that one entry, then uses the original normalization/accumulation
statements across tax rows. A missing key contributes no entries.

The guard is explicit: a non-None requested key, string input and an exact native
parsed dict. Direct dictionary inputs still perform the complete old fold,
including non-string keys and collisions after `str(key)`. Custom decoded dict
subclasses also retain the full fold. Calling `_v15_details(doc)` without the
optional keyword retains its complete-map behavior.

`get_item_tax_detail` keeps its public signature and `(amount, rate)` contract.
Item-code/name fallback, exact v16 child-row identity, zero/unmatched/multiple
v16 rows, item-rate/invoice-rate/legacy-rate precedence, amount fallback and
rounding/conversion helpers are unchanged. No generator caller, alias import,
XML layout, nominal policy or Sales/POS arithmetic changes. There is no cache,
source snapshot, cross-row reuse, extra SQL query or early selection of another
invoice/issuer. JSON is still parsed per requested item; repeated parsing and
v16 scanning are not solved by this bounded change.

Skipping unrelated JSON values intentionally removes their normalization work
and incidental conversion errors. Tests characterize an off-target 400-digit
amount that previously raised OverflowError even when the requested item was
valid: the selected JSON lookup now succeeds, but selecting the offending key
and explicitly requesting the full fold still fail. Direct-dict behavior also
still fails as before. This is not whole-invoice validation or authorization to
ignore errors in an item that is actually consumed by the invoice.

## Frozen parent and offline evidence

`tests/fixtures/v15_tax_reads_76d3e9f.py` freezes the exact parent `_v15_details`
and `get_item_tax_detail` functions from
`76d3e9f67734e60901f1937f4b9dea8a7b1aeac5`. SHA256:
`829ae04da3ff81e3f8f360cde614e71f2099e7d568b41074596fb96fe9a380e8`.
Their namespace uses the unchanged native helpers; the old full fold is not
stubbed or redirected to the new selector.

`test_v15_tax_key_lookup.py` adds **538 local cases**:

- 384 exact amount/rate-bit, ordered source-read and normalization-count cases
  across six value shapes, JSON/direct-dict sources, SAR/USD, code/name/missing/
  colliding item keys and four rate-precedence policies. Multiple tax rows are
  aggregated in both parent and current paths. JSON work reduces to selected
  entries only; direct-dict work retains its full count.
- Nine complete-fold/default/invalid-input cases, including duplicate JSON keys
  retaining the parser's previous last-value behavior.
- Four direct-dict non-string collision cases preserving order/aggregation.
- Two targeted off-target/requested overflow cases, five v16 authority cases,
  one custom decoder-dict case and five empty/numeric/whitespace/Unicode key cases.
- 128 actual Sales regular/legacy-advance and POS item XML, Sales/POS totals,
  nominal-rate/breakdown and Sales fallback-rate comparisons. Both native
  parent/current adapters are injected into the existing consumers; output,
  ordered source reads and master/app calls match across synthetic v15/v16,
  SAR/USD, signs and raw source forms. No saves, database writes/commits, logs
  or popups occur.

Final guarded selection: **7,673 distinct local cases passed across 41 reviewed
suites in 23.19 seconds**, including those 538 new cases. Existing ordinary and
advance/mixed-number, tax/party, signing/QR, routing/settings, scheduling, messages
and artifact checks also passed. Log:
`/tmp/zatca-v15-key-regression-final-206.log`. Earlier overlapping new-suite runs
are not added. Manifest is 175 local/57 private suites; no whole-manifest or
private SQL run was needed.

AST review restores the exact selected-entry branch to the old `parsed.items()`
loop, removes the optional private parameter/docstring and restores the one
private call. The entire module then matches its parent. Numeric helpers,
v16 branches, public signature and all other module nodes are unchanged; both
frozen functions match their parent AST. Tool:
`/tmp/zatca_v15_key_structure_206.py`; report:
`/tmp/zatca-v15-key-structure-206.json`.

## Scoped performance measurement

The guarded component benchmark uses simple records without read tracing or
mock instrumentation and the same current real item builders for both runs.
Only the native adapter binding changes between the exact parent and current
implementations. No master, SQL, site, signing or transport boundary is used;
no advance allocations are active. Every rendered XML byte must match.

Twelve scenarios cover 1/10/100 items, two Sales item entry points and two tax-
detail shapes. Each has eight alternating paired CPU/wall samples and three
separate Python heap samples. At 100 items, median CPU was:

| Tax-detail shape | Builder | Parent ms | Current ms | Reduction |
| --- | --- | ---: | ---: | ---: |
| v15 JSON | Ordinary Sales | 12.127 | 6.532 | 46.14% |
| v15 JSON | Plain advance wrapper | 11.768 | 6.484 | 44.90% |
| v16 table | Ordinary Sales | 6.113 | 6.082 | 0.50% |
| v16 table | Plain advance wrapper | 6.197 | 6.197 | Approximately zero |

The v16 differences provide no meaningful performance-gain evidence. Across
small fixtures the measured range included approximately 5% slower and 8%
faster results, so this is not a uniform speedup claim. Peak Python heap at
100 items was unchanged. Results are local item-builder measurements, not
production end-to-end invoice latency, SQL savings or installed ERPNext16.
Percentages compare the current adapter with increment205's adapter; they must
not be added to the separate increment205 reductions.

Benchmark tool: `/tmp/zatca_item_tax_benchmark_206.py`; full samples/medians and
matching XML hashes: `/tmp/zatca-item-tax-benchmark-206.json`; summary:
`/tmp/zatca-item-tax-benchmark-206.log`. Render repetitions are not test cases.

## Remaining release work

A rate-only API or per-document index still requires explicit source/read/
duplicate-key/alias policy; this bundle preserves amount calculation and avoids
introducing a second tax-selection algorithm. Repeated JSON parsing, v16 scans,
legacy last-row/time/provenance behavior, full GL/VAT/XML and partial/return/FX
settlement reconciliation, first-chain/retry/credential guarantees, SDK/QR checks,
installed ERPNext/Frappe15/16 and separately approved fictional-client rehearsal
remain gates. Matching inherited output is not fiscal or rollout acceptance.

No live source/configuration/schema/customer data, Bench or worker changed;
no authority request occurred. The unrelated live tooltip edit was preserved.
