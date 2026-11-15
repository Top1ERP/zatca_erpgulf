# Sales currency, rounding and credit-note controls — increment222

Development only, 2026-11-15. No working site, schema, configuration, invoice,
worker or authority API was changed. Public static ZATCA documentation was read;
no invoice, Compliance, CSID, Sandbox or Simulation request was sent. No extra
custom field or dependency is introduced. These are financial simulations and
pinned native-method probes, not installed16, SDK or authority acceptance.

## Standards and deliberately bounded changes

The [ZATCA XML Implementation Standard v1.2](https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/20230519_ZATCA_Electronic_Invoice_XML_Implementation_Standard_%20vF.pdf)
provides the checked criteria:

- Section9.2 and BR-CO-16: amount due is tax-inclusive total minus prepayment,
  plus the rounding amount. BT-114 must therefore retain its algebraic direction.
- BR-KSA-F-04, pp68–69: the listed monetary values include TaxTotal/TaxAmount
  and must use the positive document representation. That list does not require
  taking the absolute value of PayableRoundingAmount.
- BT-111 is the VAT amount in accounting currency; BR-KSA-EN16931-02 specifies
  SAR as the VAT accounting currency. Its amount is not recomputed from a sum
  of independently rounded account-row conversions in this bundle.

The implementation direction below is inferred by combining these XML equations
with ERPNext's signed return observations. The standard does not prescribe an
ERP field named is_return, Company chart layout or a native rounding API. No
claim of complete Schematron/SDK conformance follows from these scoped checks.

## Exact previous/current outcomes

| Source observation | Prior221 output | Current output |
| --- | --- | --- |
| Credit grand=-230, adjustment=-0.25, rounding enabled | XML payable229.75 | XML payable230.25 |
| Credit grand=-230, adjustment=+0.25, rounding enabled | XML payable230.25 | XML payable229.75 |
| Credit foreign accounting VAT=-112.50 | SAR TaxAmount=-112.50 | SAR TaxAmount=112.50 |
| Consolidated saved adjustment=+0.25, later disable flag1 | Adjustment omitted | Saved adjustment retained, like the native early-return rule |
| Native method consumes Global Defaults when local field absent | Sales assumed local enabled fallback | Sales follows the native method's result |
| Foreign legacy helper says USD, Company says SAR | Could select base amounts under a USD currency label | Refuse; do not repair invoice/helper or substitute Company |
| SAR invoice has an explicit non-SAR helper | Legacy helper policy could proceed | Refuse the explicit conflict |
| Valid foreign helper SAR and Company SAR | Existing financial XML | Byte-identical valid-context output |

ERP amounts, native tax rates, final distributed nets and recorded FX remain
unchanged. Normal invoices with a negative accounting VAT source are not silently
normalized by the credit-specific change; complete ordinary-source reconciliation
and all fiscal variants still require separate release validation.

## Shared native rounding selection

`ksa_compliance/native_rounding.py` now owns the small native control decision:

1. Preserve a consolidated saved nonzero adjustment before reading later controls.
2. If present, call the document's native is_rounded_total_disabled method.
3. Otherwise use the caller's local flag and explicit missing-field policy.

The reader is framework-free. It does not read Global Defaults, a Currency,
Company or POS Profile directly, and does not calculate a new rounded total,
fraction, conversion or adjustment. The native controller owns metadata/global
resolution. POS reuses its finite numeric/error policy and strict missing-source
refusal. Older partial Sales helper inputs without a method/flag retain their
legacy enabled fallback; that fallback is not evidence for a complete invoice.

The old POS helper read a present disable flag twice. The extracted policy uses
one observation, while preserving the stable-source result/error and lazy order
of other dependencies. Seven frozen-parent cases prove the result/error and
exact one-read difference. This is not a SQL, CPU or latency benchmark, nor a
trusted source snapshot. A customized getter that changes between two immediate
reads now supplies its first observation; no cross-source atomicity is claimed.

`xml_tax_data._get_payable_rounding_amount` uses that decision and reads the
saved document-currency adjustment. Only a return changes its direction. It does
not take an absolute value of BT-114. Nonfinite/malformed controls receive one
typed translated review message and an English diagnostic; the plain tax wrapper
now preserves that typed error instead of wrapping it again.

## Currency bindings and accounting VAT

Foreign Sales always validates its helper against the original Company's
currency, including legacy templates and invoice-level tax sources without the
optional VAT selector. Explicit conflicting SAR helper declarations also enter
the same binding. Company is still observed once per affected builder context,
with no global cache or source mutation. Primary Sales/nominal/advance builders
continue to receive their local rendering view, while reference and signing
services retain the original source owner.

Ordinary SAR invoices with an absent/valid SAR helper keep their prior fast path
unless selected-VAT verification separately checks Company. A Company currency
conflict hidden by that legacy SAR path remains a broader source/entry-point gate;
this is not universal Company-currency repair or support for non-SAR base books.
Partial public inputs without Company keep their existing compatibility boundary.

Only the ordinary foreign credit's accounting TaxAmount is normalized to a
positive magnitude. Detailed VAT groups, document nets/tax, independent recorded
base conversion, line prices, nominal OOS offsets and advance reference tails
are unchanged. The prepayment helper remains the existing strict direct-allocation
source: its credit magnitude is subtracted once before signed rounding. Eight
cases mock that allocation observation; they do not claim settlement/GL provenance.

## Evidence and release limits

600 new offline cases include512 native15/pinned16 control/XML combinations:
local-field versus Global Defaults, enabled/disabled, consolidated/unconsolidated,
ordinary/return, SAR/foreign, plain/item templates and both adjustment directions.
Actual inspected AccountsController methods execute with explicit mocked default
reads. Complete tax/GL/save lifecycle and native total recalculation are not run.
The source pins and licenses are retained in the existing controller oracle.

Additional cases cover old/new literal money and signs, seven POS control/read
comparisons, eight localized invalid-rounding outcomes,36 currency-conflict
refusals,24 valid-context byte comparisons and eight credit-prepayment examples.
Previous snapshots are test-only:

- `monetary_controls_e47f266.py`, SHA256
  `f6763978a4f7fbaec2f3822d7170c629c6c388705ad4b4d4fb5733497b2846f0`;
- `currency_context_e47f266.py`, SHA256
  `8ec0deba6b2729b9493cef61a9f077e9ac20a9f1a9d6937632cb2e24aa8beba2`.

Synthetic master fixtures now supply Company.default_currency=SAR where the
native Company observation was omitted. Original and DEV oracle runs receive
the same augmented inputs; earlier frozen files remain untouched. The group
rounding oracle checks the new single Company read explicitly, then retains
exact previous template-read ordering and all numeric assertions. No expected
financial discrepancy is hidden by removing an assertion.

Focused new controls600, existing group176 and native-reader662 pass. The
final guarded run passes14,001 distinct cases across60 suites in65.79s, including
600 new. After a test-only refinement of credit-prepayment source signs, the
final focused600 pass again; no runtime change followed the broad run. Six
browser suites pass1,192 synthetic cases: Debug108, Debug lifecycle164, Company
messages108, Company form292, device128 and template VAT392. Manifest194 local/
57 private; no whole-manifest execution. Original240 remains91 identical/117
changed/32 blocked, preserving earlier review items. AST restoration confines
ordinary tax-builder changes to typed error propagation and accounting-credit
sign handling. POS only changes its shared-control adapter. All24 earlier
reference fixture files and shared VAT/native-rate/discount/FX math remain.
Evidence: `/tmp/zatca-money-222-regression-final.log`,
`/tmp/zatca-money-222-focused-final.log`, `/tmp/zatca-money-222-structure.json`. No whole-manifest or
private SQL run occurs. QR source mapping and signing code, endpoints,
credentials and UUID/ICV/PIH policy are unchanged. Newly generated QR values and
hashes follow the changed XML through the existing code; no stored artifact is
rewritten. Current QR amount-field choice
(especially BT-112 versus BT-115 with rounding/prepayment and foreign sources)
remains a separate standards/SDK review; this bundle does not certify that
inherited mapping. Phase-1 QR amount policies also retain their earlier scope.

Errors occur before signing in the fiscal component; this does not prove earlier
party/identity/counter staging is atomic or rolled back. Full source/settings/
credential and transaction custody, saved rounding/GL reconciliation, remaining
nominal/non-VAT charge/legacy SAR variants, installed15/16 lifecycle, SDK and the
separately approved fictional-client rehearsal remain release gates. No live
adoption or universal completion is implied by passing expected-refusal tests.
