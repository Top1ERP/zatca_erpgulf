# Shared ordinary Sales item builder — increment201

Increment202 extends shared regular-line emission to the advance-named wrappers
with explicit compatibility layouts. Their acquisition and legacy reference
tails remain separate. The historical exact-body AST evidence below applies to
increment201; current cross-layout/failure evidence is in
[ADVANCE_ITEM_EMISSION.md](ADVANCE_ITEM_EMISSION.md).

Development only. The regular-line implementation behind `item_data` and
`item_data_with_template` is now shared inside the existing
`create_xml_final_part.py` module. No new runtime module, public API, schema,
installed source or authority request is introduced.

## Implementation and caller boundaries

Both existing public builders retain their signatures and distinct original
error handlers. Their try bodies delegate to the private
`_append_sales_invoice_item_lines(..., has_template=False/True)` implementation.
All generator imports, template selection, item/advance dispatch and surrounding
header/tax/signing/artifact behavior remain unchanged.

The shared implementation keeps the original ordered work:

1. Acquire the item template/rate, or perform the existing plain tax-detail calls.
2. Use the existing line-net, quantity, Decimal and high-precision price helpers.
3. Append the same regular line children and attributes in the same order.
4. Read category at its original position: plain category can be reread by the
   existing conditional chain; the template category is captured once.
5. Append the existing direct-advance reference lines after the complete item loop.

The plain branch's redundant legacy `get_tax_wise_detail` call is retained in
this parity extraction, including its original input reads/error behavior. Its
removal needs a separate measured change; source consolidation is not itself a
query/CPU/memory/latency improvement. Net/price/tax helpers, rounding, currency
fallback, rich-text cleaning, zero quantity and unknown-category behavior are
unchanged. A duplicate Decimal import was consolidated with the same bindings.

Existing direct allocations still use the current original-advance lookup,
numbering, authoritative date/time checks and duplicate-reference handling.
Historical dates are not replaced with today's date. These tests do not add
advance eligibility, relinking, allocation or GL guarantees.

## Why the legacy advance wrappers remain separate

`item_data_advance_invoice` and `item_data_with_template_advance_invoice` keep
their original implementations. Their legacy Advance Sales Invoice tails use
last-loop rate/template values, and their regular prefix differs in unit-value
coercion and attribute-construction timing. This bundle does not erase those
differences, reset legacy data, repair historical references or add a fallback
to a different issuer. POS's item implementations also remain separate.

Main Sales generation still selects the advance-named wrapper when its existing
direct-allocation condition is true. That branch is not migrated to the new
ordinary body by this bundle; its unchanged AST is part of the structural check.

The current shared ordinary builders can already append direct references;
consolidating their regular body does not replace the caller's distinction
between the independent direct-allocation and legacy-copy routes. Full item/
advance/runtime consolidation remains a release task.

## Frozen reference and verification

`tests/fixtures/sales_item_builders_499d56d.py` contains the two exact prior public
builder definitions from `499d56db5ed360a91edb50ed8e02364dcb146e7e`. It is intentional
test reference data, not unused runtime code. The parity fixture verifies its
SHA-256 before compiling it with explicit synthetic dependencies; no Git,
subprocess, site initialization or runtime hook loads it. Current primitive
helpers are shared by both comparisons and are separately checked unchanged.

**544 new local cases** compare full XML bytes, ordered source/master reads and
error type/message/partial XML against that reference:

- 512 combinations across template/plain, SAR/USD, v15 JSON/v16 child tax-detail
  shapes, zero/positive/fraction-producing/negative quantities, four categories,
  no/direct advance and present/absent Company-currency declaration.
- NULL net fallbacks, HTML/name/code fallback, unknown category, missing template
  rates and empty items.
- Existing advance reference preservation without duplicate creation or an
  unnecessary original-invoice fetch, plus injected/missing-field failures.

These are synthetic input records and mocked master reads. Tax/rate/price and
direct-reference functions run locally, including a 2020 advance date. No stored
invoice is edited, no real SQL/Company is created and no request is sent.
Successful serialization is not fiscal approval of every characterized input.

The final guarded selection passed **6,145 distinct local cases across 37
reviewed suites**, including those 544 new cases and existing advance-reference,
document-tax, party, signing/QR, source/issuer, Debug/Compliance, settings,
scheduling, messages and artifact-preservation regressions. Initial overlapping
runs are not added to that count. Final log:
`/tmp/zatca-sales-item-regression-final-201.log`. The manifest is now 171 local/
57 private suites; this was neither a whole-manifest nor native SQL run.

Structural review specializes the shared implementation for each literal
template flag and compares its complete body to the corresponding old try body:
both ASTs match exactly. Public signatures/error handlers and all other functions,
including direct-reference and legacy advance builders, match the old AST.
The frozen reference definitions also match the original AST. Tool:
`/tmp/zatca_sales_items_structure_201.py`; report:
`/tmp/zatca-sales-item-structure-201.json`. Runtime source is **48 lines shorter**;
the reference fixture and tests are not counted as runtime source. This is a
maintainability/source-size measure, not a production performance claim.

## Release limits

Complete Sales/POS/advance arithmetic and GL/VAT/XML/QR reconciliation, legacy
retirement, first-chain/retry/credential guarantees, SDK validation, installed
ERPNext/Frappe 15/16 lifecycle and separately approved fictional-client rehearsal
remain required. No live deployment, customer-data change, Bench/worker action
or authority request occurred. The unrelated live tooltip modification remains.
