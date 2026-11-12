# Preflight invoice/template source consistency — increment209

Development only. This corrects the source supplied to existing category/rate/
reason checks in `tax_error.py`. It adds no new tax rule, Company field, checkbox,
schema, API request, generator algorithm or persistence. The prior
[zero-rate correction](ZERO_RATE_SELECTION.md) remains uninstalled too.

## Three source conflicts corrected

The preflight selector previously:

1. Replaced an invoice's zero rate with the template rate through a truthiness
   test. A declared zero category could therefore be incorrectly assessed at 15
   while XML's native invoice rate remained 0.
2. Always used the template rate when the category came from the template,
   ignoring a present saved invoice rate. A template-derived zero category could
   be assessed at 0 while XML's invoice-level rate was 15.
3. Ignored a declared invoice exemption reason in that template-category branch,
   although the XML category/reason helper prefers it. A usable invoice reason
   could therefore still produce a missing-reason preflight rejection.

`_get_invoice_level_tax_rate(doc, *, default=0.0)` now lets the selector request
None for a genuinely absent rate. Existing one-argument calls keep their old 0
fallback and the same first-present-row/`flt` behavior. The source selector
computes `selected_rate` once: present invoice rates, including zero, take
precedence; only absence uses the template. It computes `selected_reason` once:
a declared invoice reason takes precedence, otherwise the template reason.
Both category-owner branches consume those same decisions. Category ownership
and the missing-category branch remain unchanged; no category is inferred from
a numeric rate or exemption code.

This aligns the reviewed invoice-level scenarios with the XML helpers. It does
not replace native per-item/v16 selection, tax-account filtering, multiple-rate
or template-row semantics, or a strict missing/invalid-value policy. Existing
malformed-value coercion, negative/non-finite handling and scalar precision
rules remain. In particular, this does not certify arbitrary category/code/rate
pairs or resolve every first-row versus effective-item source discrepancy.

## Actionable existing display context

When the category comes from a Sales Taxes template but the invoice supplies
a rate or reason, `source_name` now names both records using the existing key
`Sales Taxes and Charges Template {0} or Sales Invoice ZATCA fields`. A purely
template-owned case retains its old template-only label. Both keys already have
Arabic translations; no translation catalogue or new message is added.
`source_type` continues to identify the category owner, not full field provenance.
The label is operator context, not audited source/tenant/acceptance evidence.

Existing user-language translation and throw ownership remain. Tests read the
actual Arabic catalogue with a mocked translation boundary, rather than
initialize a session/site or mutate server language. These are display-key
checks, not installed browser/session evidence. No new logging or persistent
localized diagnostic is introduced.

## Rules, settings and compatibility retained

The category/rate consistency checker, exemption-presence checks, Company source-
validation setting, missing-metadata defaults and enabled-company submit gate
are unchanged. Phase decisions are unchanged; this does not resolve the broader
Phase1/Phase2 validation-policy audit. A disabled Company still exits the submit
entry before source/category rules. Explicitly disabled source consistency is
not activated by the selection fix. Other existing exemption-presence checks
retain their own gate behavior even when rate consistency is disabled.

The item-template branch and all tax-table, advance, category-rate, rounding and
message implementations remain. Source rates/reasons are read from their
existing fields; no invoice/template/Company record is edited. An early duplicate
`_ZATCA_NON_STANDARD_CATEGORIES` assignment is removed after proving its literal
set equals the later canonical exemption-category set, and no import-time read
consumes the overwritten value. Runtime category values/aliases remain the same.

## Frozen evidence and portable test lifecycle

`tests/fixtures/tax_source_d14984b.py` freezes the exact two prior source helpers
from `d14984b473f828a9510bb63c15c046fbdc09b5d3`. SHA256:
`e03faef00051fbafa21aee98b8334b46d9d108458ea94e5cb80a7ead116277ed`.
It executes the old truthiness, template-rate and template-reason decisions;
those old results are explicitly compared with the intended corrections.

`test_tax_source_consistency.py` adds **396 local cases**:

- 288 ordered source-read/master-read and metadata cases across Sales/POS,
  invoice/missing categories, template categories, zero/string/Decimal/positive/
  absent/later rates and conflicting template rates. Rate/combined-label deltas
  are explicit; unrelated metadata and acquisition order remain.
- 64 existing strict-rule results compared with actual invoice-level XML
  category/reason and breakdown helpers across four category labels, two source
  owners, zero/positive rates and synthetic v15/v16 shapes. These verify existing
  application predicates, not external legal code/category mapping.
- Four exact old false-rejection/new-pass cases and two existing rejection-message
  cases in English/Arabic. Rejections use one throw and no extra popup.
- 16 Company setting/request/metadata-presence cases, two disabled-company early
  exits and two absent-rate/template cases.
- 16 reason-priority/presence cases and two template-only context-label controls,
  both languages. Declared invoice reasons now survive template category ownership;
  genuinely missing reasons still trigger the existing rule.

The five pre-existing synthetic tests in `test_zatca_tax_source_priority.py` now
use `unittest.TestCase` with explicit translation/throw mocks instead of the
site-owning `FrappeTestCase`. Their five test method bodies are unchanged. They
can now run under the offline guard without session/site/database setup; their
original assertions were not rewritten to make the source fix pass.

Final guarded selection: **9,066 distinct local cases passed across 45 reviewed
suites in 26.06 seconds**. This includes 396 new cases and those five newly portable
older cases, plus the existing 8,665 selected cases. Log:
`/tmp/zatca-tax-source-regression-final-209.log`. Initial overlapping runs are
excluded. Manifest is 179 local/57 private suites; no whole-manifest or private
SQL run was needed. No CPU/query/heap improvement is claimed.

AST review verifies the exact optional-default change, two shared precedence
expressions, both branch bindings and reused mixed-source labels. Restoring only
those changes reproduces the parent helpers; restoring those two functions and
the proven overwritten constant reproduces the entire old module AST. Rules,
gates, all other functions and existing message text are unchanged. Both frozen
functions and all five portable test method bodies match their parent AST.
Tool: `/tmp/zatca_source_structure_209.py`; report:
`/tmp/zatca-tax-source-structure-209.json`.

## Remaining release work

Per-item versus invoice/template validation ownership, explicit category/rate/
exemption-code mapping, strict absent/malformed/unknown-category handling,
Phase1/Phase2 policy, full GL/VAT/FX/advance and scalar/rounding reconciliation,
first-chain/retry/credential guarantees, SDK/QR checks and installed ERPNext/
Frappe15/16 remain gates. The default-Standard XML fallback versus explicit
missing-category preflight policy is not changed here. Supplied metadata still
is not committed/audited source provenance. Complete development must precede
the separately approved fictional-client rehearsal and later rollout decision.

No live source/configuration/schema/customer data, Bench or worker changed;
no authority request occurred. The unrelated live tooltip edit was preserved.
