# POS final-net financial XML — increment217

Development only, 2026-11-14. No working-site change, restart, migration, tax
authority API request or release acceptance. This increment replaces the
ordinary **POS Invoice** financial builders. Sales Invoice with `is_pos`,
advance-payment tails, Phase-1 QR, signing algorithms, credentials and supplied
external XML retain their existing implementations.

## Result and ownership

`pos_financial_xml.py` prepares a complete financial view before appending tax,
monetary or line nodes. The two document-allowance functions in `posxml.py` are
now compatibility no-ops: ERP's final line nets already include the distributed
invoice discount. Its `tax_data` and the three builders in `pos_final.py` delegate
to the shared adapter. All old public function names remain available.

The old standalone `get_tax_total_from_items`, `add_line_item_discount` and
imported aliases remain available for integration compatibility. Canonical POS
generation does not call their legacy financial algorithms. Do not adopt these
helpers in a new route. Removing public compatibility surfaces requires a wider
caller/integration review; this report does not claim all unused code is gone.

| Decision | Current source and behavior |
| --- | --- |
| Line net | Required final `base_net_amount` for SAR, `net_amount` for foreign currency; no gross-amount fallback |
| Unit net price | Absolute final net / absolute quantity, up to12 decimals, with a two-decimal line-equation check |
| VAT without item template | Existing native v15/v16 rate reader, preserving selected zero; invoice rate only when the native source is absent |
| VAT with item template | One template VAT row matching the single invoice tax account; cache repeated templates within this preparation call |
| Category/reason without item template | Invoice values first, then its linked tax template; POS Profile template only when the invoice link is absent |
| VAT grouping | Category + rate + exemption code; conflicting reasons for the same category/rate are blocked rather than creating duplicate groups |
| Group VAT | Shared Decimal half-up calculation from aggregate group net; document VAT is the sum of those groups |
| Document allowance | None; `AllowanceTotalAmount=0.00`, with final nets already discounted |
| Accounting tax total | Required recorded base VAT, explicitly labeled SAR; never relabel foreign-currency VAT as SAR or invent an FX conversion |
| Money validation | Match final nets, group VAT, gross and applicable rounded total to recorded ERP values before financial XML emission |
| Payments | Ordinary POS paid_amount is not a ZATCA advance deduction; no BT-113 is inferred from it |

Shared Sales helpers emit regular line nodes, tax totals and legal monetary
totals. POS retains its `item_code:item_name` presentation and summary-before-
detail tax-total order. No Sales/advance financial function was edited.

## Discount display and rounding settings

`Company.custom_submit_line_item_discount_to_zatca` controls presentation only.
Disabled: net price and final line net are emitted directly. Enabled: the gross
unit-price reference comes from nonzero `rate_with_margin`, `price_list_rate`,
then `rate`. Under the supported single On Net Total VAT row, only this optional
gross reference removes included VAT. Neither final line nets nor VAT undergo
another tax division or discount subtraction.

Where gross exceeds final unit net, Price/AllowanceCharge shows the effective
unit discount: **gross - allowance = final unit net**. This can include both
the item discount and ERP's allocated invoice discount. It deliberately differs
from blindly copying item.discount_amount after allocation. If gross does not
exceed net, no positive discount is invented. BaseQuantity is1. Both flag values
produce the same monetary totals; this is an explicit presentation change.

Use native `is_rounded_total_disabled()` where available. In inspected POS
schemas without a local disable field, AccountsController reads Global Defaults;
a POS Profile flag is not substituted. Preserve a consolidated invoice's saved
nonzero adjustment, following the native early-return branch. Otherwise emit
the recorded adjustment only with rounding enabled and verify rounded_total.
Zero rounded totals are observed as zero, never replaced through truthiness.
Return amounts become positive XML money and the rounding adjustment reverses
sign consistently. No native recalculation method is called.

The two POS mixed-category preflight guards now reuse the Sales native-allocation
evidence predicate. They allow ordinary, demonstrably distributed discounts;
nominal, cash/non-trade and unknown-allocation cases remain restricted.

## Differences from original deployed financial code

The original baseline remains commit2e97708 with frozen original financial
function dependencies. The240-case matrix now records:

- 91 byte-identical XML fragments;
- 117 changed fragments:69 already characterized Sales/nominal differences,
  plus48 POS changes introduced here;
- 32 POS cases blocked:16 ambiguous multiple-account cases and16 examples with
  a Standard category on zero-rate lines. Blocking is not compliance success.

All48 emitted POS fragments differ structurally, including removal of the old
header allowance and monetary/price formatting. Financial equality is assessed
separately. Selected SAR examples, unchanged ERP inputs:

| Case | Original payable | Development payable | Meaning |
| --- | --- | --- | --- |
| Ordinary invoice,15% |230.00|230.00|Same money, new consistent structure |
| Item templates5% +15%, net100 each |210.00|220.00|Separate actual rate groups instead of first-category-rate reuse |
| Invoice source with item overrides5% +15% |230.00|220.00|Group rates agree with lines and recorded VAT |
| Selected zero override with a valid Zero Rated category |230.00|200.00|No substitution of the invoice's15% for selected zero |
| Native Grand Total discount23 from230 |203.55|207.00|Final ERP nets90+90, VAT27, no second discount |

The older Net Total example with gross lines100+100 and document allowance20
could already total207 correctly. The new90+90/no-document-allowance model is a
coherent alternative; this report does not label every original difference an
error. Inclusive-price examples also change (see the original observations in
[DISTRIBUTED_INVOICE_DISCOUNT.md](DISTRIBUTED_INVOICE_DISCOUNT.md)). Differences
remain for user review before adoption.

## Unsupported or inconsistent sources

This adapter handles one configured VAT account charged On Net Total, with
different per-item VAT rates/categories. It rejects multiple invoice tax rows,
multiple tax rows in an item template, mismatched template accounts, other
charge types, nominal POS and cash/non-trade discounts. A nonzero invoice
discount requires an ERP distribution marker; its value is evidence only, not
a replacement for final net fields. Mixed sales/return signs, missing/invalid
final fields, unknown categories, inappropriate zero/positive category rates,
missing exemption codes and irreproducible unit-price precision are blocked.

Single-row/category metadata is a configured VAT source, not independent proof
of an account's ledger role. Explicit VAT/non-VAT account-role mapping, multiple
charges/taxes, FX accounting policy and nominal treatment remain release gates.
Do not interpret multiple tax accounts as percentages to add blindly.

If ERP records row-rounded VAT0.00 for three0.03 lines at15%, the group rule
gives0.01. Generation is blocked for reconciliation; the adapter neither
changes the invoice nor silently submits different tax. The reconciliation
guard is currently scoped to this POS adapter, not every Sales/advance path.

## Routes, messages and validation

The shared wrappers are used by ordinary POS generation, foreground/background
generation without supplied XML, dedicated POS compliance and local Debug XML.
Typed financial failures propagate before signing, rather than being swallowed
or wrapped into nested messages. The UI receives one translated key; canonical
error codes/details and one diagnostic remain English. Debug returns the stable
display key plus original technical detail and avoids duplicate error logs.

Published arithmetic references: ZATCA's [XML Implementation Standard v1.2](https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/20230519_ZATCA_Electronic_Invoice_XML_Implementation_Standard_%20vF.pdf),
sections8.3–8.4,9.6 and10, BR-CO-14/17 and BR-KSA-EN16931-07/11. These support
net-price/line equations, grouping and final tax rounding. This bounded review
is not an SDK/schema/signature or authority acceptance result.

Validation: **10,827 distinct offline cases across53 suites**, including343 new
POS cases and96 added ordinary-POS selector cases. Native15/16 allocation
excerpts and rounding-control methods are pinned; tax recalculation remains an
explicit simulated boundary. ERPNext16 is source/oracle evidence, not an
installed16 acceptance test. Existing generation/QR/signing/isolation suites pass.
The Debug browser suite passes76 synthetic cases with actual Arabic catalog
values, escaped unchanged technical diagnostics and one dialog per operation.

For100 synthetic lines, observed get_doc calls fell from302 to4 without item
templates, and501 to4 with a repeated item template. These are supplied-reader
call counts, not SQL query counts or production CPU/latency measurements. No
cross-request cache or long-lived prepared financial view was introduced.

Evidence: `/tmp/zatca-pos-217-regression-final2.log`,
`/tmp/zatca-pos-structure-217.json`,
`/tmp/zatca-baseline-tax-compatibility-213/results.json`,
`/tmp/zatca-tax-standard-audit-214.json`,
`/tmp/zatca-pos-master-reads-217-False.json` and `...-True.json`.
AST comparison preserves every public function name and all unlisted function
bodies in the six modified legacy modules. Original baseline fixtures remain
unchanged. Complete installed routing, transaction/ICV rollback, fiscal/XML/GL
reconciliation, SDK validation and fictional-client rehearsal remain required.
