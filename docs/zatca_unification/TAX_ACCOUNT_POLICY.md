# Reconciliation account policy and native-tax boundaries — increment211

Development only. The existing preflight account classifier now delegates to
`ksa_compliance.tax_account_policy.is_reconciliation_tax_account`. The small
`tax_error._is_tax_account` compatibility adapter retains its signature, injected
Frappe boundary, Account query fields and caller-owned cache. No XML calculation,
phase/settings gate, message, invoice, database schema or transport is changed.

## Existing policy, with explicit limits

| Account observation | Reconciliation eligibility |
| --- | --- |
| Explicit account_type Tax, ignoring case/outer spaces | True regardless of root |
| Other nonblank account_type | False regardless of root |
| Blank/absent account_type and Liability root | True |
| Known metadata with other/blank root and blank type | False |
| Missing/falsey record or reader exception | Current caller's default |
| Empty account name | False, without a lookup |

This is the inherited conservative reconciliation rule, not exclusive VAT
identity. Other taxes can also use Tax accounts; a blank-type Liability account
can represent retention or another obligation. No account-name, rate or charge-
type heuristic has been added. Missing metadata must not become evidence of VAT.

The shared implementation is pure and receives an explicit account reader.
Actual existing zero-rate, tax-amount and template/invoice reconciliation callers
continue through the compatibility adapter. No new account lookup is added to
the native XML rate reader. The separate template-category helper
`_tax_template_uses_only_non_tax_accounts` retains its distinct exact Tax-type
policy; its semantics are not silently replaced by this broader classifier.

## Unknown-account cache correction

Previously, an unresolved account cached the first caller's default. Reusing that
cache with a different default returned the first value. The cache now retains a
private unresolved-observation marker and applies each call's own default. It
still performs only one Account lookup per normalized name in a shared cache,
including lookup failures. Known results and legacy prepopulated cache values,
including None, remain authoritative. Different caches still read independently.

The cache is local and opaque, not a serializable/persisted account record or a
cross-request freshness guarantee. Existing internal callers currently use the
same default True; the corrected mixed-default contract is demonstrated locally,
not presented as a reproduced tenant incident. Unknown metadata still falls back
conservatively in those existing checks. Truthy malformed metadata still raises
its access error; only reader exceptions retain the original fallback behavior.

## Characterized native-rate gap, not repaired by this classifier

The native adapter has no VAT-account ownership selector yet:

- ERPNext 16 details match the exact item child name and sum all matched rates.
  A synthetic VAT15 row plus a freight100 row produces rate115. A deduction row
  carrying rate3/amount-3 still adds its rate to15. These are observed adapter
  results, not recommended tax values or fiscal certification.
- ERPNext 15 without an explicit item rate uses the first available invoice
  rate. Freight7 before VAT15 selects7; the explicit singleton item map VAT15
  selects15. Both order and item override behavior remain unchanged.
- Account eligibility alone cannot repair either behavior. Two distinct taxes
  can both qualify; missing accounts and legacy Liability fallback are also
  ambiguous. Applying this classifier directly to XML would guess VAT ownership.

Pinned ERPNext16 source `ade850bbd6a7412e9994a9637d2c5c713771632a`,
`erpnext/controllers/taxes_and_totals.py`, confirms that `set_item_wise_tax`
stores the supplied rate separately from the signed amount. Its
`process_item_wise_tax_details` persists `item_row=row.item.name` and
`tax_row=row.tax.name`. The tax reference is a saved child name, not an account
name or display index. This is a local pinned-source review, not installed16
execution. Cached source SHA256:
`b50607b8b7891a5e82542fe36bd61a3342d2995a1faf103a21cae8554056f5aa`.

Next work must establish declared VAT source ownership across invoice templates,
Item Tax Templates, native child references, account roles and Company settings.
Keep missing/ambiguous ownership visible; do not equate Tax account classification
with VAT selection or change XML amounts by filtering on this predicate alone.

## Evidence and remaining gates

`tests/fixtures/tax_account_7906adf.py` freezes the complete parent classifier
from `7906adfaef4a6ab849d9a383d54807fe05a0687e`. SHA256:
`54b29b55c42c1a039e1a2fc3b45a8cfc305a1cc881c2c8420e3e673c0a414785`.
It is test data, not another runtime implementation.

`test_tax_account_policy.py` adds 196 guarded local cases: 80 known-metadata
parent comparisons, 20 fresh unknown fallbacks, 30 mixed-default cache repairs,
five prepopulated caches, four empty names, four malformed records, one pure
reader/cache-scope case, 40 actual preflight field/account cases, five unknown
preflight cases and seven native v15/v16 characterization cases. Queries and
document write boundaries are mocked; no tenant database or network is used.

The final reviewed selection passed **9,507 distinct local cases across 47 suites
in 32.78 seconds**, including the 196 new cases. Log:
`/tmp/zatca-tax-account-regression-211.log`. Manifest:181 local/57 private suites;
no whole-manifest or private SQL run. No latency/CPU/heap improvement is claimed.

Structural review verifies the exact frozen parent, unchanged wrapper signature
and Account query, unchanged remaining tax-error module AST and unchanged native
adapter bytes. Tool: `/tmp/zatca_tax_account_structure_211.py`; report:
`/tmp/zatca-tax-account-structure-211.json`.

VAT ownership, broader phase/category/source policy, GL/VAT/FX/advance and
rounding acceptance, SDK/QR, first-chain/retry/credential guarantees, installed
ERPNext/Frappe15/16 and the separately approved fictional-client rehearsal remain
open. No live code/configuration/data, Bench/worker or authority request changed.
