# Published-standard VAT arithmetic review — increment214

Reviewed2026-11-14. **The original and development implementations do not fully
meet the reviewed arithmetic requirements in every simulated case.** Development
fixes one mixed-rate grouping scenario; inherited Sales rounding and POS source/
rounding gaps remain. This increment adds review/tests only, with no runtime,
financial-field, configuration, schema or live-data change.

The later [group-rounding correction](GROUP_VAT_ROUNDING.md) updates the current
results. Counts and findings below describe this historical review; current
runs may replace the default temporary matrix artifacts.

## Primary reference and bounded criteria

The [official developer specifications page](https://zatca.gov.sa/en/E-Invoicing/SystemsDevelopers/Pages/E-Invoice-specifications.aspx)
currently links the19May2023 XML standard v1.2. The governing source used here is
[the linked XML Implementation Standard](https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/20230519_ZATCA_Electronic_Invoice_XML_Implementation_Standard_%20vF.pdf).

- Sections8.4/9.6: partition by VAT category and rate.
- Section9.6/BR-CO-17: derive group tax from its taxable base.
- BR-CO-14: total VAT equals category-tax totals.
- Section10: use half-up on final group/document calculations, not summed rounded
  line taxes.

These are the bounded criteria, not a transcription of the standard or a full
Schematron implementation. Findings use local test identifiers, not purported
ZATCA response/error codes. No validator rejection/severity or SDK tolerance is
inferred merely from an exact-formula discrepancy.

## Executed comparison and conclusions

The new audit reuses the exact original financial function closures from2e97708
and their original dependency graph, plus current DEV. It does not treat legacy
output as the correctness oracle. Declared category/rate/net inputs and Decimal
arithmetic independently establish the expected groups and amounts. Every emitted
line's category/rate/net is checked against those declarations. Document/master
snapshots and all save/write/message boundaries remain unchanged.

| SAR simulation, v15 format | Family | Expected VAT | Original VAT | DEV VAT | Original / DEV scoped findings |
| --- | --- | ---: | ---: | ---: | --- |
| Uniform15, invoice template | sales | 30.00 | 30.00 | 30.00 | none / none |
| Uniform15, invoice template | pos | 30.00 | 30.00 | 30.00 | none / none |
| 5/15 line overrides, invoice template | sales | 20.00 | 20.00 | 20.00 | present / none |
| 5/15 line overrides, invoice template | pos | 20.00 | 30.00 | 30.00 | present / present |
| Separate5/15 Item Tax Templates | sales | 20.00 | 20.00 | 20.00 | none / none |
| Separate5/15 Item Tax Templates | pos | 20.00 | 10.0 | 10.0 | present / present |
| Three0.03 lines at15, invoice template | sales | 0.01 | 0.00 | 0.00 | present / present |
| Three0.03 lines at15, invoice template | pos | 0.01 | 0.01 | 0.01 | none / none |
| Three0.03 lines at15, item templates | sales | 0.01 | 0.00 | 0.00 | present / present |
| Three0.03 lines at15, item templates | pos | 0.01 | 0.01 | 0.01 | none / none |
| One0.10 line at15, invoice template | sales | 0.02 | 0.02 | 0.02 | none / none |
| One0.10 line at15, invoice template | pos | 0.02 | 0.01 | 0.01 | present / present |
| One0.10 line at15, item template | sales | 0.02 | 0.02 | 0.02 | none / none |
| One0.10 line at15, item template | pos | 0.02 | 0.01 | 0.01 | present / present |
| Z0 and E0, item templates | sales | 0.00 | 0.00 | 0.00 | none / none |
| Z0 and E0, item templates | pos | 0.00 | 0.0 | 0.0 | none / none |
| Z0 and S15, item templates | sales | 15.00 | 15.00 | 15.00 | none / none |
| Z0 and S15, item templates | pos | 15.00 | 15.0 | 15.0 | none / none |

The v16-format results reproduce the same verdicts for these cases. That is
source-format simulation, not installed ERPNext16 execution.

### Findings that distinguish preservation from correctness

1. **Ordinary Sales mixed rates without Item Tax Templates: improved.** Original
   output for two100 lines at5/15 is a single S5 subtotal with taxable200/tax20.
   Its total20 matches the expected invoice tax, but its grouping and subtotal
   formula do not. Development emits100/tax5/S5 and100/tax15/S15. The new audit
   finds no discrepancy against its scoped rules for this example.
2. **Sales group rounding: inherited discrepancy in both versions.** Three0.03
   net lines at15 have group net0.09 and expected group tax0.01. Both Sales
   implementations sum per-line rounded tax0.00 and emit document tax0.00.
   Item-template and invoice-template paths both reproduce it. Line tax values
   individually rounded to0.00 do not justify changing the expected group tax.
3. **POS mixed-rate templates: inherited grouping/amount discrepancy.** For
   two100 lines in separate Standard5/15 Item Tax Templates, both emit total10,
   grouping taxable200 at the first rate5. Expected groups produce total20.
   This is why80 unchanged POS outputs in increment213 were preservation
   evidence rather than standards acceptance.
4. **POS invoice-template summary: inherited source disagreement.** With5/15
   native line overrides under invoice15, both emit detailed total30 instead
   of20. The separate SAR summary carries20 in this simulation, so same-currency
   totals also disagree. Selecting the first invoice rate for the summary does
   not establish agreement with the line groups.
5. **POS half-up boundary: inherited numerical discrepancy.** For one0.10 net
   line at15, the independent result is0.02. Both POS variants emit0.01 from
   their float/native-round expressions. Sales emits0.02 for this single-line
   control. No change to ERPNext's own accounting configuration is implied.
6. **Controls match the scoped rules.** Uniform15 invoice-template controls,
   separate Z0/E0 groups and separate Z0/S15 item-template groups match in both
   implementations. A problem demonstrated in one edge case does not establish
   that every existing customer invoice is wrong.

The complete36 input combinations each execute original and DEV. The audit finds
issues in14 original and12 development combinations; the remainder have no
findings against these particular checks. None is a full regulatory compliance
certificate. A matched overall amount can hide incorrect categories/subtotals;
an unchanged original output can preserve an inherited discrepancy.

## Scope, evidence and current code anchors

Matrix: nine input scenarios, ordinary Sales/POS, v15/v16 native tax-detail
formats, SAR, quantity1, no nonzero document adjustments, no prepayments or
payable rounding. Zero-valued allowance nodes are allowed. Nominal offset,
multiple tax-account roles, FX, phase gates, print-tax inclusion, full lifecycle,
credentials/ICV, QR/signature and all other ZATCA checks are outside this audit.

Code anchors:

- `xml_tax_data._get_tax_breakdown_without_template`: selected-rate buckets and
  per-line quantization added into bucket amounts.
- `xml_tax_data._get_tax_breakdown_with_template`: category/rate/reason grouping,
  also adding per-line quantized tax.
- `xml_tax_data._append_tax_totals`: subtotal-to-document summation.
- `pos_final.tax_data_with_template`: category-only key and first template rate.
- `posxml.tax_data`: separate native-item and invoice-rate summary calculations.
- Nominal breakdowns contain similar per-line quantization by static inspection;
  their special offsets were not assessed with this ordinary-invoice oracle.

`test_tax_standard_audit.py` adds36 local audit cases with independent literal
small-value expectations and exact input/master preservation. The final guarded
selection passed **9,929 distinct cases across50 reviewed local suites in32.47s**.
This includes tests that correctly detect the gaps; it is not9,929 successful
ZATCA validations. Log: `/tmp/zatca-tax-standard-regression-214.log`.
Manifest:184 local/57 private suites; no private SQL or whole-manifest execution.
No performance claim.

Detailed original/development findings and emitted group/line-tax values:
`/tmp/zatca-tax-standard-audit-214.json`.
SHA256: `94d311071a5242c51e4c9fa9ebc1fbe33a0d57b18b6d6bfc5150c8eb2dd1e8df`.

## Correction order before claiming conformance

Preserve the user's compatibility-review requirement. Before modifying amounts,
review the original/DEV/rule matrix and decide each intended change explicitly.
Then unify category/rate ownership, group accumulation and final rounding across
Sales/POS, and reconcile invoice VAT/ledger totals with ERPNext's rounding and
row-wise-tax settings. An XML-only adjustment that silently disagrees with the
actual invoice/accounting result is not an acceptable fix.

Re-run the original-output matrix and the independent-rule matrix together.
Validate full generated XML with an available offline SDK and on separately approved isolated
ERPNext/Frappe15/16 benches before the fictional-client rehearsal.
SDK availability, exact warning/error tolerances and full-fiscal acceptance remain
unverified here. Do not infer remote acceptance or send a submission to test it.

No live application/configuration/schema/data, Bench or worker changed. Only
public documentation was retrieved; no invoice, Compliance, CSID or other ZATCA
API request was sent. The unrelated live tooltip edit remains preserved.
