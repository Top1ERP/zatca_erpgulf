# Retire unused item-tax JSON work — increment205

Development only. Plain ordinary Sales items and the regular prefix of the
plain advance-named Sales builder now acquire `get_item_tax_detail` **once per
physical item**, rather than twice. Two unused `tax_json` assignments are
removed from the existing `create_xml_final_part.py`; template/POS paths and
monetary helpers are unchanged. No field, setting, runtime module or endpoint.

## Finding, compatibility and intentional differences

The first acquisition went through `get_tax_wise_detail`, which calculated the
same tuple again and serialized it into JSON keyed by `item_code`. Nothing read
the resulting local `tax_json`. The next statement reacquired the tuple and used
its rate. With the real adapter, both calls traversed tax rows and calculated a
line tax amount. The v15 shape also reparsed the item-wise JSON map. This did
work proportional to the same source table twice for each item.

The current loop uses the single native tuple at its required acquisition
position. Remaining amount/price/tax helpers, rate/category ownership, XML order,
advance priority, historical references, public signatures and error handlers
remain. There is no global/per-document cache, cross-row reuse or extra query.
This does not make source acquisition transactional or remove the adapter's
remaining repeated per-invoice scans.

`get_tax_wise_detail` remains public with its original signature, algorithm,
JSON text and old serialization errors, preserving potential integrations.
Its English docstring explains why the item builders no longer call it. The
`json` import remains necessary; no public dotted entry point is removed.

Removing unused work intentionally removes its source reads and incidental
failures. A valid native Decimal tax tuple is no longer rejected solely by JSON
serialization. A synthetic row without an `item_code` attribute can use its
existing description and rate sources, rather than fail at the serializer's
attribute access. These are tested deltas, not a claim that all missing codes
or arbitrary Decimal sources satisfy every fiscal/ERP validation. Required tax
reader errors still fail at the expected partial XML boundary. Each row uses
its own current result; callbacks that changed between the old two reads now
have only one read. No snapshot/concurrency guarantee is inferred from that.

## Frozen references and tests

The new hashed fixture `tests/fixtures/item_tax_reads_11a429d.py` contains the
exact parent shared loop, plain public ordinary wrapper and plain advance
wrapper from `11a429d18b161bedf57a2d96e968de7d582a5a14`. SHA256:
`219ab1bba51abb5dc36535e1cb2bafb6a6378d33e3015dfd8c9d7626f7aeac4f`.
It executes the real public serializer and real tax adapter; the removed work
has **not** been stubbed in this parent oracle.

`test_item_tax_read_cost.py` adds **96 local cases**:

- 64 parent/current complete byte and master/app-read comparisons across both
  plain builders, v15/v16 tax-detail shapes, SAR/USD, none/direct/legacy/both
  advance routes and positive/negative quantities. Ordered adapter arguments
  explicitly go from two calls to one for each item, without skipping rows.
- Eight required-reader failures on first/second items retain error text and
  partial XML, with the expected reduced call counts.
- Eight Decimal-tuple and eight missing-code cases prove the old incidental
  failure and the new successful XML against a native-data parent oracle.
- Four independent-row rate cases prevent repeated reads or cross-row caching.
- Four public JSON compatibility cases retain exact serialization and the old
  Decimal serialization error for direct callers.

The older ordinary/advance frozen fixture files and hashes remain unchanged.
Their comparison namespaces now explicitly stub **only** the retired unused
JSON dependency, so they compare remaining read order rather than insist on
retired work. This is an intentional oracle-boundary change, not evidence that
all old reads still occur. The new exact-parent suite independently executes
those old reads and proves both the reduction and the deliberate failure deltas.
No other frozen dependency is suppressed by this increment.

Final guarded selection: **7,135 distinct local cases passed across 40 reviewed
suites in 22.09 seconds**, including the 96 new cases. Existing ordinary/advance,
mixed-number, tax/party, signing/QR, routing/settings, scheduling, messages and
artifact checks also passed. Log: `/tmp/zatca-item-tax-regression-final-205.log`.
The initial affected selection passed 1,534 overlapping cases; those are not
added to the final count. Manifest is 174 local/57 private suites; no private
SQL or whole-manifest run was needed.

AST review confirms the removed variables have no loads, removes exactly the
two reviewed assignments and normalizes only the two updated docstrings. The
entire module then matches the parent, including all numeric rules, imports,
public JSON implementation, source selection and error boundaries. Each new
frozen function matches its exact parent AST. Tool:
`/tmp/zatca_item_tax_structure_205.py`; report:
`/tmp/zatca-item-tax-structure-205.json`.

## Measured component cost

A separate guarded synthetic benchmark uses simple records without read tracing
or mock instrumentation, the real tax adapter and actual item builders. It
compares the exact parent functions with current functions for 1/10/100 items,
both ordinary/advance entry points and both tax-detail shapes: 12 scenarios.
It acquires no masters, SQL, site or transport; no advance allocations are active.
Full serialized XML bytes must match on every measured render.

Each scenario has eight alternating parent/current CPU/wall samples and three
separate Python heap samples. The 100-item **median CPU** results are:

| Tax-detail shape | Builder | Parent ms | Current ms | Reduction |
| --- | --- | ---: | ---: | ---: |
| v15 | Ordinary Sales | 18.927 | 11.297 | 40.31% |
| v15 | Plain advance wrapper | 19.331 | 11.451 | 40.76% |
| v16 | Ordinary Sales | 8.073 | 5.653 | 29.97% |
| v16 | Plain advance wrapper | 8.334 | 5.824 | 30.12% |

Smaller fixtures measured 1.57–23.70% median CPU reduction in this run. Python
peak heap at 100 items was effectively unchanged (about 0.04% lower), so this
is **not** a meaningful memory-reduction claim. Measurements are local component
evidence, not installed ERPNext16, production invoice latency, end-to-end signing/
QR/submission throughput or SQL-query savings. Fixture size and table shape
matter; native acceptance and wider profiles remain required.

Benchmark tool: `/tmp/zatca_item_tax_benchmark_205.py`; full sample/median/hash
report: `/tmp/zatca-item-tax-benchmark-205.json`; summary:
`/tmp/zatca-item-tax-benchmark-205.log`. Benchmark renders are not test cases and
are not added to the 7,135 count.

## Remaining work and operating boundary

The adapter still returns an amount that these loops do not consume and still
scans invoice tables per item. A rate-only/shared-index design needs its own
source/duplicate-row/alias/read-boundary review before adoption. This increment
does not change tax math, legacy last-row rate/time policy or settlement source
provenance. Full GL/VAT/XML and multi-rate/partial/return/FX reconciliation,
first-chain/retry/credential guarantees, SDK/QR checks, installed ERPNext/Frappe
15/16 and the separately approved fictional-client rehearsal remain gates.

No live source/configuration/schema/customer data, Bench or worker changed;
no authority request occurred. The unrelated live tooltip edit was preserved.
