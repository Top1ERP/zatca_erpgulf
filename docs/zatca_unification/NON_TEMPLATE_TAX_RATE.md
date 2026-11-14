# Shared non-template rate mechanics and source map — increment212

Development only. Ordinary and nominal Sales subtotal wrappers now use one
`ksa_compliance.tax_details.resolve_non_template_tax_rate` implementation.
Native account/rate/amount rules, category/reason sources, rounding functions,
XML financial calculations, phase/settings and transport remain unchanged.

## Shared mechanics and compatibility

The pure resolver receives the wrapper's current native reader and quantizer.
It returns `(found, rounded_rate)`. A selected zero is found. Native missing
None/empty-string and native-read/selected-rounding failures retain the existing
first-invoice-tax-row fallback, including that row's default0. Exceptions from
fallback reads or rounding still propagate. Once that fallback branch is entered, it does not search later rows when the
first row rate is malformed or absent; the native reader retains its own
separate first-present-rate policy.

When no taxes exist, `(False, None)` lets each wrapper retain its original zero:
ordinary returns Decimal0.00 without calling q2; nominal calls its own q2(0).
The wrappers keep their old names/signatures, native-reader aliases and rounding
bindings. Broad catches are preserved exactly, not extended or presented as
strict numeric validation. No global cache, database lookup, account inference,
message, company-setting change or authority request is introduced.

The extraction removes duplicate policy from two active consumers without
changing their result/error/field-read/rounding sequence. It does not alter the
seven rate-only consumer bindings introduced previously or turn the full-detail
API into a different calculation.

## Current source and settings map

Category/reason declarations, rate selection and VAT account ownership must
remain separate. The current reviewed boundaries are:

| Runtime context | Category/reason source | Rate/account boundary |
| --- | --- | --- |
| Ordinary Sales subtotals, no Item Tax Template | Invoice values first; independently fall back to linked Sales Taxes template; XML category then defaults Standard | Shared native/fallback rate; no exclusive VAT-account selector |
| Nominal Sales subtotals, no Item Tax Template | Invoice category or Standard; invoice reason | Same shared rate mechanics, own rounding and SAR/OOS amounts; no template category fallback |
| Sales plain item category nodes | Invoice category directly | Native rate reader; no new subtotal-source inference |
| Sales item-template mode | Linked Item Tax Template category/reason | First template row rate or legacy15 default; does not identify a VAT row within a mixed template |
| POS plain item/summary paths | Direct POS Invoice fields | Native item rate and separate summary/first-row assumptions; untouched here |
| POS template paths | Linked Item Tax Template | First-row rate and category grouping assumptions; untouched here |
| Preflight source selector | Trimmed invoice category/reason first, template fallback; no invented category | First present invoice rate, including zero; template rate only when absent |
| Reconciliation account eligibility | Account type Tax, or blank-type Liability; unknown fallback | Conservative eligibility, not proof of VAT; not adopted to filter XML |

Evidence anchors: `xml_tax_data._get_invoice_level_zatca_tax_source`,
`_get_tax_breakdown_with_template`; `create_xml_final_part._nominal_breakdown_*`,
`_append_sales_invoice_line`; `posxml.tax_data` and `pos_final.item_data*`;
`tax_error._get_invoice_level_zatca_source`; `tax_account_policy`.
This is a map of inspected local code, not a claim that all these routes have
received new installed/browser/accounting acceptance in this increment.

Existing Company source-consistency, category/rate and tax-table switches control
validation, not VAT ownership. Canonical metadata checks are Phase-1 gated as
recorded in [TAX_PHASE_POLICY.md](TAX_PHASE_POLICY.md); direct validators and other
submit/lifecycle requirements keep their existing scope. Neither a phase setting,
a category nor an exemption reason selects a specific tax-account row.
The setup/backfill Excise-name skip and generated KSA VAT/Excise definitions are
not sufficient ownership evidence for arbitrary user-created mixed templates.
No new field, role default, migration, backfill or setup routine is added/run.

The older root-level source contract incorrectly described template-first
priority despite the original tests asserting invoice-first. It is now corrected
and explicitly documents category-default and per-route differences:
[zatca_tax_source_priority_contract.md](../zatca_tax_source_priority_contract.md).
Two tests add independent reason override and XML-default/preflight-missing
boundaries; the original five test bodies remain unchanged.

## Frozen-parent and regression evidence

`tests/fixtures/non_template_rates_8861c2a.py` freezes both complete old wrappers
from `8861c2ac7523907cf4065776b6a3ebaa85e540e4`. SHA256:
`c0badb61b7a95269084c179f4f5ae95400dff208d934ae6a8512ec5b9a55752e`.
It is test data, not an extra runtime implementation.

`test_non_template_tax_rate.py` adds144 guarded local cases:

- 96 parent/current cases across both routes, selected zero/typed/missing/
  malformed/nonfinite/failing values and four first-row fallback forms.
- 14 exception/empty cases, including the intentionally distinct empty rounding
  and propagation of fallback errors. Actual reads and rounding calls match.
- 32 actual native v15/v16 cases across both routes and SAR/USD, preserving
  selected zero, item identity, missing-source and mixed-charge limitations.
- Two actual wrapper-delegation cases preserve current reader/quantizer aliases.

Two additional existing-file source-contract tests bring the increment to146
new cases. The full reviewed selection passed **9,653 distinct local cases across
48 suites in 28.62 seconds**, including ordinary/nominal/advance XML, POS, QR,
signing, routing, phase, settings and message regressions. Log:
`/tmp/zatca-non-template-regression-212.log`. Manifest:182 local/57 private suites;
no whole-manifest, private SQL, site or authority test. No performance claim.

The structural review specializes/inlines the shared function back into each
wrapper to restore its exact old body, including the distinct empty branch.
Both frozen functions match the parent; wrapper signatures and all remaining
nodes in both consumer modules are unchanged. Removing the new pure helper
restores the exact prior native-module AST. Tool:
`/tmp/zatca_non_template_structure_212.py`; report:
`/tmp/zatca-non-template-structure-212.json`.

## Next source-ownership work and release limits

Before filtering native rates, choose an explicit VAT ownership representation
that can distinguish multiple Tax accounts and multiple roles in one template.
Review how tax child references, row mapping/copy, native item overrides and
historical blank metadata carry that declaration. An unclassified row must not
be labelled VAT solely from its name, percentage, Tax type or Liability root.
Document ambiguity instead of silently summing other charges or discarding VAT.
The role representation and any additional field remain design work, not an
implemented or defaulted configuration in this increment.

Then reconcile category source across ordinary item nodes, ordinary/nominal/POS
summaries and advance references, retaining explicit category/reason ownership
and financial reconciliation. These known differences remain open; rate-helper
parity does not resolve them. Full GL/VAT/FX/advance/rounding, SDK/QR,
first-chain/retry/credentials, installed15/16 and the separately approved isolated
fictional-client rehearsal remain mandatory before an adoption decision.

No live source/configuration/schema/data, Bench/worker or tax-authority request
changed. The unrelated live tooltip edit remains preserved.
