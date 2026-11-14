# Declared POS VAT accounts — increment218

Development only, 2026-11-14. This extends the ordinary POS adapter from
[increment217](POS_FINAL_NET_XML.md); no site, setting, schema, invoice, worker,
credential or authority API was changed. No new configuration field is required.

[Increment219](POS_FINANCIAL_PREPARATION.md) now prepares the financial view once
for standard POS generation. The account-role and FX policies below remain;
its rendering values are frozen and totals/lines are staged together.

## Supported account declaration

Several invoice VAT accounts can now be used when **each item template contains
one VAT account** with its own explicit ZATCA category/rate/reason. Every invoice
tax account must be owned by at least one such item. Account Head rows must be
unique and use On Net Total with an additive role. A generic Account type Tax,
account name, positive percentage or whole-template category is not used to
identify other rows as VAT. An unclassified extra row is rejected even at zero.

This new branch does not mean multiple VAT components on the same item are
supported. A multi-row Item Tax Template remains ambiguous. Invoice-level
multi-account templates also remain restricted until their row roles and
non-VAT charges have an explicit fiscal representation.

The new multi-account branch follows:

```mermaid
flowchart LR
    A[Saved POS data] --> B[One template VAT account per item]
    B --> C[Native item and account rate pairs]
    C --> D[After-discount account and total checks]
    D --> E[Shared financial XML emitters]
```

`ksa_compliance/account_tax_rates.py` owns the strict, read-only rate index.
`pos_financial_xml._reconcile_vat_accounts` owns the fiscal comparison. The
existing public native rate/detail functions remain unchanged for other callers.
Neither the index nor account eligibility is an authentication, ledger-role or
tax-authority acceptance grant.

## Native v15 and v16 data

| Source | Exact selection |
| --- | --- |
| v15 | The physical item's JSON account map, then that account's invoice-row rate, as in native `_get_tax_rate` |
| v16 | Exact saved item_row + tax_row references, resolving the tax child name to the current Account Head |
| Other accounts on that item | Must resolve to numeric zero; a second applicable nonzero rate is rejected |

v15 does not use the aggregated item-code JSON amount/rate or the old singleton-
map heuristic. Duplicate item codes therefore do not join different physical
rows. Duplicate map keys and malformed selected rates are not coerced to zero.
v16 requires a nonempty, complete table of pairs, including zero observations.
Unknown physical references, duplicate pairs and partial/empty tables cannot
fall back to a stale v15 map. NOT_APPLICABLE_TAX/omitted-pair semantics remain a
separate review item. No current native-tax amount field is used as a rate.

A typical native configuration uses invoice-row default rates0 and a single
template account override on each item. Leaving another invoice-row rate15
without a zero item override really applies an extra15% in native calculation;
the new adapter reports this instead of silently discarding it. The actual saved
observations, not a guessed rate from an account label, must corroborate scope.

## Account amounts, XML groups and FX rounding

For the new branch, compare each account's required after-discount document-
currency tax with its declared line-net/category/rate groups. Compare the sum
of those observed rows with recorded document VAT. Do not substitute cumulative
tax-row total or undiscounted tax_amount, and do not treat zero as missing.
Offsetting mistakes in two accounts cannot hide behind a correct grand total.
SAR base amounts also reconcile per account and in total. Foreign base rows
must have the correct sign, but their sum is not substituted for the base header.

XML still groups by category/rate/reason, not ledger account. Two accounts with
the same category/rate share one subtotal and contribute each line base once.
If merged-group rounding differs from ERP's recorded per-account tax, generation
is blocked for accounting review rather than changing the invoice or XML VAT
silently. No new tolerance or automatic rounding adjustment was introduced.

Native `calculate_totals` converts the entire VAT total independently through
`_set_in_company_currency`. For DOC tax27 and conversion3.75, header SAR VAT is
101.25. Two account taxes13.50 each convert to50.63+50.63 under Commercial
Rounding, or50.62+50.62 under Banker's Rounding:101.26 or101.24. Both differ from
the native101.25 header. Eight controlled primary-source probes verify these
boundaries in15/16, including mirrored return observations. The XML retains
**101.25**, without a second FX conversion. Full foreign-currency ledger/precision
reconciliation remains an acceptance gate; this does not independently certify
every supplied base amount or exchange-rate setting.

Discounts remain embedded in final ERP line nets. The optional gross-unit-price
display now consults the item's own VAT row for inclusion. Other accounts must
already have zero native rates on that item. Native Net Total/Grand Total
allocation observations retain the217 money, without another header allowance.

## Compatibility and explicit numerical difference

| Evidence | Result |
| --- | --- |
|80 POS examples from217 |48 byte-identical emitted fragments and32 unchanged rejection codes |
| Original240-case oracle |Still91 identical,117 changed,32 blocked; original six financial dependencies remain frozen |
| New split-account example: two100 lines at5% and15% |Original pre-development POS payable210;217 rejects the scope;218 produces220, matching recorded ERP220 |
| Same category/rate across different accounts |One XML subtotal, with the merged base included once |
| Offsetting account errors or an unintended extra rate |One typed failure before financial XML emission |

The unsupported-scope message now describes ambiguous account sources rather
than requiring one invoice account. Codes remain stable; old display keys are
retained for historical Debug responses. New account-source/amount keys display
in Arabic for Arabic users; canonical codes and diagnostic text stay English.

Published rule reference: the official [ZATCA XML Standard v1.2](https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/20230519_ZATCA_Electronic_Invoice_XML_Implementation_Standard_%20vF.pdf),
sections8.4/9.6/10 and BR-CO-14/17, keeps VAT breakdown and document VAT tied to
category/rate aggregates. It does not prescribe ERP ledger account layout. This
is a bounded arithmetic/source review, not an SDK, signature or remote verdict.

## Validation and remaining work

**11,669 distinct offline cases across55 suites passed**, including842 new:
58 strict native-index cases and784 POS adoption/compatibility cases. The latter
include640 combinations of declared accounts, categories, SAR/USD, distributed
discount, inclusion, discount display, returns and quantities;80 frozen217
comparisons;32 controlled allocation probes; and8 native FX-boundary cases.
The Debug browser suite passes88 cases with actual Arabic catalog values; the
other four affected UI suites pass. No tenant SQL or authority API was used.

The pinned native sources remain ERPNext15 `572d8530b6258231e31f294474cc1818f693d10b`
and16 `ade850bbd6a7412e9994a9637d2c5c713771632a`. File hashes are checked before
executing the selected native methods. The16 result is source/oracle evidence,
not installed16 execution. Allocation tax recalculation and final native rounding
lifecycle are explicit mocked boundaries, not a full invoice/GL calculation.

The strict index reads each of200 native detail rows once (600 item/tax/rate
field gets); subsequent pair lookups do not rescan those rows or read amounts.
It uses no cross-request cache. This is a bounded access check, not a production
CPU, latency or SQL-query benchmark.

The complete217 POS adapter is frozen as a test-only fixture, SHA256
`fce20e4257e25de380307725c8d9b91984d3794526fecab005e10db5eb2f3812`,
with its unchanged shared Sales emitters. Original pre-development fixtures are
separate and unchanged. Evidence logs:
`/tmp/zatca-accounts-218-regression-complete.log`,
`/tmp/zatca-accounts-218-fx.log`, and the existing240-case report under
`/tmp/zatca-baseline-tax-compatibility-213/`.

Remaining: explicit non-VAT charge/deduction roles and tax bases; multi-row item
templates; omitted/not-applicable v16 pairs; broader Sales/advance source and
amount unification; trusted settings/credential/transaction provenance and ICV
rollback/concurrency; SDK and installed15/16 lifecycle evidence; then separately
approved fictional-client rehearsal. No release adoption is inferred here.
