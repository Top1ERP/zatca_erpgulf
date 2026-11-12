# Shared native rate-only selection — increment207

Development only. Seven Sales/POS item, total and nominal/fallback consumers now
use `get_item_tax_rate` when they discard the amount returned by the full-detail
API. Both APIs use one `_resolve_item_tax` implementation in the existing
`ksa_compliance/tax_details.py`. No field, Company setting, dependency, schema,
RPC endpoint or UI message is added.

## Shared implementation and ownership

`get_item_tax_detail(doc, item)` retains its signature, full amount/rate tuple,
ordered source reads and numeric behavior. `get_item_tax_rate(doc, item)` returns
the native selected rate. Both call the same private selector with explicit
internal modes; this is not an operator setting or caller validation bypass.

For a finite rate, rate-only mode skips `_line_tax_amount`: its currency/net
field search and Decimal multiplication/quantization produced an amount these
consumers never used. Each consumer keeps its own actual amount calculation and
rounding. There is no cache or cross-item reuse; every lookup resolves current
sources using the same key/row/rate precedence.

The shared selector deliberately retains **payload amount conversion**, including
v16 matched detail amounts and the existing v15 selected payload fold. Invalid
payload conversions must not become silently accepted because the caller wants
only a rate. For a non-finite rate, `_rate_without_line_amount` executes the
original line calculation before returning the rate. This preserves inherited
Infinity rejection where the old amount calculation rejected it; removing that
calculation unconditionally could otherwise make POS emit Infinity. Existing
NaN/missing-net behavior is characterized, not newly certified or broadly fixed.
No source is reacquired to make this check.

| Consumer | New rate-only sites | Actual math retained |
| --- | ---: | --- |
| `create_xml_final_part.py` | 3 | Nominal rate helper, shared ordinary item loop and plain advance regular prefix retain their amount/price/category/reference ownership |
| `xml_tax_data.py` | 2 | Sales per-line tax total and nominal/fallback rate helper keep their own rounding/fallback rules |
| `posxml.py` | 1 | POS item tax total keeps its signed arithmetic |
| `pos_final.py` | 1 | POS item XML keeps its existing amount/price/profile/Company policy |

The old imported `get_item_tax_detail` aliases remain available in all four
consumer modules for integrations; English import comments make that deliberate.
Overrides of a consumer module's imported getter must now target
`get_item_tax_rate` for rate-only generation; retaining the old alias does not
preserve interception of those new calls. Supported integration review remains
a release gate. The public `get_tax_wise_detail` JSON helper still uses the full API and keeps its
contract. One obsolete POS amount-variable comment is removed. Public builders,
handlers, entry paths, source/issuer/reference policy, signing/QR, identity,
scheduling, artifacts and dispatch remain unchanged.

Finite rate lookup is not line-amount validation: malformed net amounts can now
leave a standalone rate lookup successfully while the actual caller still owns
its amount validation/math. Tests characterize this intentional skipped-work
boundary. Payload amount conversion and non-finite rate handling are retained
separately. No returned rate is a fiscal/acceptance capability.

## Native/full API and consumer evidence

`tests/fixtures/item_tax_detail_cf26483.py` freezes the exact prior full selector
from `cf2648388039e652da9ee279acbe12c33348c700`. SHA256:
`8cddf9e41c9cc1892a5dbfb8b6f8147277eb9089eaa2e541c24194d75fc99a8d`.
Its old full calculation is actually executed; it is not redirected to rate-only.

`test_item_tax_rate_only.py` adds **662 local cases**:

- 384 v15 full-API exact value/type/bit and source-read comparisons, then
  rate-only comparisons removing only the reads observed inside the retired
  line calculation. Six payload shapes, JSON/direct dict, SAR/USD, four key
  cases and four rate policies are covered. Finite rate-only calls are required
  not to invoke the amount primitive.
- 64 v16 matched/zero/unmatched/blank-name/multiple/empty/None/absent table cases,
  two currencies and missing/zero/positive/negative net values. Full reads match
  the parent; rate-only retains payload reads and skips the recorded line math.
- Four invalid-net cases preserve full-API errors while finite rate-only returns
  the selected rate; two invalid payload-amount cases still fail in both APIs.
- Twelve non-finite rate cases preserve old full/rate error or result behavior
  with/without net values for both tax-detail shapes.
- 192 actual Sales/advance/POS item XML, Sales/POS total and nominal/fallback
  consumer comparisons across v15/v16 shapes, SAR/USD, signs and finite/Infinity/
  NaN rates. Each consumer runs against the exact full parent-derived rate and
  the new rate API. Complete output/type or error text/type and master/app calls
  match. Every Infinity consumer case retains its original rejection.
- Four native-zero/consumer-fallback cases characterize an inherited policy
  conflict described below; they do not endorse its fiscal behavior.

Older ordinary/advance frozen files/hashes remain. Their tuple-shaped dependency
now explicitly bridges to the rate-only API for remaining-read comparisons;
the already retired JSON dependency remains suppressed. The old item-cost suite
now checks two full parent calls versus one current rate call and zero current
full calls, preserving public JSON checks. The v15 consumer comparison namespace
suppresses only its now-unused line calculation. These are intentional oracle
boundary updates: the new exact full-selector and consumer cases independently
exercise the old calculation and prove the retained/retired behavior.

Final guarded selection: **8,335 distinct local cases passed across 42 reviewed
suites in 23.68 seconds**, including the 662 new cases. Existing item, advance,
Decimal bridge, tax/party, signing/QR, routing/settings, scheduling, message and
artifact checks passed. Log: `/tmp/zatca-rate-only-regression-final-207.log`.
Initial/overlapping runs are excluded. Manifest is 176 local/57 private suites;
no whole-manifest or private SQL run was needed.

Structural review specializes the shared selector for full-detail mode and
reproduces the **exact old full-function AST**. Removing the two small wrappers,
rate helper and math import restores the rest of the native module unchanged.
At all seven consumers, restoring only the original tuple assignment and import
reproduces each entire parent module AST. Each discarded amount binding has no
loads. The frozen function matches its exact parent AST. Tool:
`/tmp/zatca_rate_only_structure_207.py`; report:
`/tmp/zatca-rate-only-structure-207.json`.

## Scoped component measurement

The separate guarded benchmark uses the same current real item builders in both
runs and simple records without read tracing or mocks. One binding derives a
rate through the exact full parent API; the other uses the new rate API. Every
rendered XML byte matches. There are no master/SQL/site/signing/transport calls
or active advance allocations.

Twelve scenarios cover 1/10/100 rows, two Sales item entry points and both tax-
detail shapes. Eight alternating CPU/wall samples and three separate Python
heap samples are retained per scenario. At 100 items, median CPU was:

| Tax-detail shape | Builder | Full parent rate ms | Rate-only ms | Measured reduction |
| --- | --- | ---: | ---: | ---: |
| v15 JSON | Ordinary Sales | 6.338 | 6.096 | 3.82% |
| v15 JSON | Plain advance wrapper | 6.111 | 5.939 | 2.82% |
| v16 table | Ordinary Sales | 5.855 | 5.716 | 2.37% |
| v16 table | Plain advance wrapper | 5.788 | 5.627 | 2.78% |

These are modest measurements from one local component run, not a broad
production speed guarantee. Peak Python heap was effectively unchanged. The
stronger structural result is removal of one unused line-tax calculation per
finite lookup in these consumers. Percentages are not additive to earlier
bundles and do not measure full invoice submission or installed ERPNext16.

Tool: `/tmp/zatca_item_tax_benchmark_207.py`; raw samples/medians/matching hashes:
`/tmp/zatca-item-tax-benchmark-207.json`; summary:
`/tmp/zatca-item-tax-benchmark-207.log`. Render repetitions are not test cases.

## Concrete remaining policy issue and release gates

The native selector preserves authoritative zero rates. However, the inherited
`_nominal_tax_rate_without_template` and
`xml_tax_data._get_item_tax_rate_without_template` explicitly reject zero as an
effective row rate and fall back to the first invoice tax rate. A selected zero
with invoice rate15 therefore still yields15 in these consumers, both before
and after this change. Four tests freeze that conflict without correcting it.
Next review must distinguish absent/invalid rate from authoritative zero and
reconcile nominal/mixed-rate rules and actual XML/GL behavior. Do not infer
whole-system zero-rate correctness from the selector's contract or these parity
results. No fiscal policy change is smuggled into rate-only optimization.

Repeated v15 JSON parsing/v16 scanning, full GL/VAT/XML and partial/return/FX
settlement reconciliation, legacy last-row/time/source provenance, first-chain/
retry/credential guarantees, SDK/QR checks, installed ERPNext/Frappe15/16 and
separately approved fictional-client rehearsal remain required.

No live source/configuration/schema/customer data, Bench or worker changed;
no authority request occurred. The unrelated live tooltip edit was preserved.
