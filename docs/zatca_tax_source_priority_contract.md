# ZATCA tax-source priority contract

Current development contract, reviewed through increment219 on 2026-11-14. It replaces
older prose that incorrectly placed Sales Taxes and Charges Template values above
explicit invoice values. The original five tests already required invoice-first
behavior; their bodies are preserved. See the scope map and remaining work in
[NON_TEMPLATE_TAX_RATE.md](zatca_unification/NON_TEMPLATE_TAX_RATE.md).

## Separate the questions

Category, exemption reason, rate, account ownership and financial amount are
separate decisions. A category is not evidence that every account in the same
table contains VAT. The current application has no universal row-level VAT-role
selector. This contract describes existing runtime behavior and its known gaps;
it is not a declaration that every generator has been unified or fiscally
certified.

## Ordinary Sales Invoice subtotal sources

1. With Item Tax Templates on every item, each linked Item Tax Template owns
   its category, reason and first tax-row rate. Invoice-level overrides do not
   replace these item-template values. Existing default15 for an empty template
   remains an inherited behavior requiring strict-source review.
2. Without Item Tax Templates, an explicit invoice category takes priority over
   the linked Sales Taxes and Charges Template category. The invoice reason
   independently takes priority over the template reason. These two fields need
   not come from the same record. XML uses Python truthiness, not a new trimming
   or normalization policy.
3. If neither source supplies a category, the ordinary XML subtotal helper uses
   Standard. This rendering fallback does not satisfy preflight's requirement
   for an explicitly declared category; preflight retains source_type missing.
4. The preflight selector trims declared text and does not invent a category.
   Its first present invoice rate, including zero, takes priority over the
   template-rate fallback. These text/default distinctions from XML remain
   visible; they are not silently normalized by the rate consolidation.
5. Mixed presence of Item Tax Templates remains rejected by the existing
   category validator. Explicit Phase-1 skips the canonical five-validator
   metadata group, not every lower-level/direct or submit check. See
   [TAX_PHASE_POLICY.md](zatca_unification/TAX_PHASE_POLICY.md).

For example, blank invoice category plus template Zero Rated and an explicit
invoice reason selects the template category and the invoice reason. When both
categories are undeclared, ordinary XML renders Standard while the preflight
source remains missing. Two additional local tests preserve these distinctions.

## Rates are selected independently

The ordinary and nominal non-template rate wrappers now delegate their common
read/fallback mechanics to `tax_details.resolve_non_template_tax_rate`:

- A present native zero is retained. Only None/empty-string or a native-read/
  selected-rounding failure enters the existing first-invoice-row fallback.
- A fallback read/rounding failure propagates. No tax rows leaves the wrapper's
  original empty-document zero behavior intact.
- Native v15 item-map/first-rate and v16 exact-item-child/all-matched-rate rules
  remain. A populated v16 table with an unmatched item remains authoritative zero.
- The shared policy does not exclude freight, retention, excise or other taxes.
  Tax-account eligibility is not a VAT-role selector. See
  [TAX_ACCOUNT_POLICY.md](zatca_unification/TAX_ACCOUNT_POLICY.md).

## Boundaries still needing unification

Ordinary Sales subtotals use the invoice/template fallback above. Plain Sales
item-category nodes currently read the invoice category directly. Nominal plain
subtotals use the invoice category or Standard and the invoice reason; they do
not perform that template fallback. POS ordinary financial XML now uses the
217 adapter's consistent invoice/template fallback and final ERP nets. Its218
multiple-account branch requires one explicit template VAT account per item,
complete account coverage and native per-account rate observations before
account/total reconciliation. This does not change the older generic rate API
or make every XML node/source policy universal. Nominal OOS-offset behavior and
advance references retain their separate rules. See
[POS_VAT_ACCOUNTS.md](zatca_unification/POS_VAT_ACCOUNTS.md).

Non-standard-category reason and category/rate validators retain their existing
settings, rules and localized display behavior. The shared helper adds no rule,
message or persisted diagnostic. The backfill helper intentionally declines an
Excise name inference; that safeguard does not identify VAT rows in a mixed
invoice/template. No setup/backfill operation was executed.

## Standard POS preparation lifetime — increment219

The five normal POS generation/Compliance/background/Debug paths now prepare
financial values once and share an immutable rendering projection across totals
and lines. This changes read lifetime, not category/rate/amount priority. Private
XML staging prevents a failed emitter leaving a partial financial section on the
caller's root. Standalone public adapters still prepare independently. Imported
integration hooks or distinct runtime/rate/translation bindings keep their
original public composition. Original saved-source signing ownership is unchanged;
the rendering view is not an authorization/credential context. See
[POS_FINANCIAL_PREPARATION.md](zatca_unification/POS_FINANCIAL_PREPARATION.md).

## Local evidence and maintenance

`test_zatca_tax_source_priority.py` contains the five original source/grouping/
mixed-template tests and two additional fallback-boundary tests, all without an
installed-site dependency. `test_tax_source_consistency.py` covers existing
preflight rate/reason overrides and language/settings behavior.
`test_non_template_tax_rate.py` adds complete frozen-parent rate comparisons,
read/rounding failures and native15/16 examples. The documented guarded runner
uses explicit reviewed local files; site test settings and tenant data are not
part of this work.

Any change to category, reason, rate or account-source behavior must update the
applicable source map, this contract and corresponding tests. Preserve the
separate missing-source/default and category-versus-account distinctions.
Installed ERPNext/Frappe15/16, full fiscal/SDK and the separately approved
fictional-client rehearsal remain release gates. No production readiness or
remote acceptance is inferred from these unit tests.
