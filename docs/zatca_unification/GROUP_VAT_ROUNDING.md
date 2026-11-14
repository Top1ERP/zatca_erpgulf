# Final VAT group rounding — increment215

Development only. Ordinary and nominal Sales breakdowns now compute tax once
from each complete group's net base through `ksa_compliance.vat_math.vat_from_group`.
This addresses the Sales discrepancy demonstrated by the published-standard
audit. No native rate/account selector, category/reason precedence, per-line VAT
builder, POS calculation, setting, schema, invoice or live process is changed.

## Implemented boundary

The four active calculators are the ordinary and nominal breakdowns, each with
and without Item Tax Templates. They retain existing net/currency acquisition,
category/rate/reason keys, first-seen order, empty-group behavior and return
shapes. Instead of accumulating quantized line VAT, they accumulate the existing
line net observations and finalize group tax with Decimal half-up to two decimals.
Nominal code separately accumulates SAR base-net observations before finalizing
that stream. It adds no extra output fields. Existing nominal OOS offsets and
monetary semantics remain unchanged.

The helper is pure and has no Frappe/site dependency. Native Decimal values never
pass through float; other numeric inputs use decimal text. It does not select
VAT accounts, infer categories, alter percentage precision/selection or add
strict nonfinite validation. Net acquisition still uses the established rounded
line-net values. Line VAT amounts remain independently rounded as before.
See [TAX_STANDARD_AUDIT.md](TAX_STANDARD_AUDIT.md) for the verified primary
reference and the distinction between line and group arithmetic.

## Explicit observed changes

| Input to a single15% group | Prior group VAT | Corrected group VAT |
| --- | ---: | ---: |
| Three0.03 net lines, SAR | 0.00 | 0.01 |
| Net lines1.01 and2.03 | 0.45 | 0.46 |
| Two100 net lines | 30.00 | 30.00 |
| One0.10 net line | 0.02 | 0.02 |

Zero-rate controls remain0.00. Negative/return input amounts retain the existing
positive XML representation. Different-rate/category source policy is unchanged.
The old1.01/2.03 line VAT sum0.45 remains a valid observation of separately
rounded line amounts; it no longer forces document/group VAT to that same sum.

For the existing240 original-baseline comparisons,171 financial fragments now
match byte for byte and69 differ. Five additional differences are tightly
asserted: nominal USD invoices with distributed discount, under uniform15%
or the selected first15% item/template scenarios, change SAR VAT101.26 to101.25.
The test restores that single SAR TaxAmount text to its old value and requires
all other XML bytes to match the original. The pre-existing64 differences remain
explicitly characterized. All80 POS fragments remain identical because POS
implementation is not changed in this increment.

No blanket approval of69 differences or every category/source combination is
claimed. No legacy source fixture was rewritten to disguise a difference.

## Accounting reconciliation remains a blocking release gate

The positive simulations supply invoice VAT amounts matching the corrected group
results and verify XML agreement with those amounts. Every original invoice and
master field remains unchanged. This is not evidence of all installed ERPNext
row-wise-tax or rounding configurations.

A separate negative case supplies a self-consistent row-rounded ERP invoice with
three0.03 lines, recorded invoice/tax-row VAT0.00 and gross0.09. The corrected
breakdown produces VAT0.01. The test detects and records that mismatch; it does
not pretend the invoice was reconciled. There is **not yet a universal runtime
reconciliation guard** that prevents this example from proceeding.

Therefore this arithmetic correction must not be installed/piloted alone. Before
rehearsal, establish a scoped VAT-account/source mapping and reconcile group VAT
with actual invoice/tax-row/accounting totals and row-wise-tax settings. Do not
automatically change user settings or stored invoice amounts, suppress the
mismatch, or assume every tax/charge row is VAT. The upcoming validation must
surface a single localized outcome and retain English internal diagnostics.

For foreign nominal invoices, supplied base-net observations are not proof of
ERPNext's installed currency/error-diffusion policy or of a universal SAR
conversion rule. This increment retains the existing base-net ownership and
changes its rounding boundary. ERP/SAR accounting conversion reconciliation is
still required; a fabricated matching base-tax field is not installed evidence.

## Frozen-parent and test evidence

`tests/fixtures/group_rounding_d3286d5.py` freezes five complete prior functions
from `d3286d50cfc76a0b26cb43579e96d3625e2e96cb`: the bucket constructor and four
calculators. SHA256:
`8a9994d918974098dc2f9aebe9b592169acfdafd762c0ce461d194897fea386d`.
The frozen code is test data only and its original ASTs remain exact.

`test_group_vat_rounding.py` adds176 cases:

- Fifteen scalar/type cases with independent literal half-up values.
-160 ordinary/nominal, template/plain, SAR/USD, v15/v16-format and sale/return
  combinations, with literal before/after amounts, stable master reads, exact
  source snapshots and actual XML monetary results.
- One explicit unresolved ERP row-rounding mismatch case.

The original-baseline and zero/rate suites retain their frozen originals and now
assert the small, documented deltas. The ordinary standards audit now has no
scoped Sales findings in its nine scenarios across both formats. Eight POS
combinations retain the already documented findings; they are not marked fixed.
Nominal special offsets, role selection and FX regulatory semantics have not been
run through that ordinary-SAR oracle.

Final reviewed selection: **10,105 distinct local cases across51 suites passed
in34.08 seconds**, including176 new cases and intentional mismatch/finding
characterizations. Log: `/tmp/zatca-group-rounding-regression-215.log`.
Manifest:185 local/57 private suites; no whole-manifest/private SQL/site run.
No CPU, query-latency or peak-memory improvement is claimed.

Structural review restores the four prior calculator bodies and removes the new
imports to recover both entire previous consumer ASTs. Native tax details,
preflight/accounting validators, POS sources and customization definitions remain
byte-identical. The new helper contains no float bridge or Frappe dependency.
Tool: `/tmp/zatca_group_rounding_structure_215.py`; report:
`/tmp/zatca-group-rounding-structure-215.json`.

Current synthetic audit/baseline artifacts are copied to
`/tmp/zatca-group-rounding-215/standard-audit.json` and `baseline.json`.
Earlier report documents retain their historical counts; default temporary
matrix files can be overwritten by a later reviewed run.

## Next work

Add the accounting/source reconciliation boundary, then replace POS category-only
and first-rate assumptions with verified category/rate groups and final half-up
arithmetic. Preserve POS net/inclusive-price and discount/settings behavior through
explicit adapters and original-output comparisons. Complete nominal/FX/advances,
SDK/QR, installed15/16 and the separately approved fictional-client rehearsal
before adoption. This increment does not certify the complete application.

No live source/configuration/schema/data, Bench or worker changed. No invoice,
Compliance, CSID or other authority API request was sent. The unrelated live
tooltip edit remains preserved.
