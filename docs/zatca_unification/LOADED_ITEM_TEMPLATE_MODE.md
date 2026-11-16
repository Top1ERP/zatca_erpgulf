# Loaded invoice rows own the XML template choice — increment226

Development only, 2026-11-16. No installed source, site/schema/configuration,
invoice, Bench or worker was changed. No tenant SQL or authority API was used.
The ordinary generators execute only against synthetic records and mocked
signing/transport boundaries in this evidence.

## Problem and scope

Six ordinary Sales/POS generators and POS Debug accepted
`any_item_has_tax_template` as the financial-builder selector. A stale/default
flag could select plain builders for template rows, or template builders for
rows without templates. Sales Debug read its initially prepared document before
metadata reloaded a possibly different document. Dedicated Sales/POS Compliance
already inspected loaded rows, but duplicated their any/all/mixed logic.

The same pure policy now determines mode from the metadata builder's returned
invoice in **ten generation contexts**:

| Context | Consumers |
| --- | --- |
| Ordinary primary | sign_invoice.zatca_call, pos_sign.zatca_call |
| Ordinary legacy Sales | sales_invoice_withoutxml.zatca_call_withoutxml, zatca_background_sched.zatca_call_scheduler_background |
| Ordinary legacy POS | pos_submit__without_xml.zatca_call_pos_without_xml, pos_schedule_background.zatca_call_pos_without_xml_background |
| Dedicated Compliance | Sales and POS zatca_call_compliance |
| Local Debug | Sales and POS _debug_call |

The public parameter remains callable for compatibility; it no longer overrides
the rows in these consumers. Existing discount/tax/item functions, callback
overrides, reference/party order, classification, signer, API routes, credential
selection, attachment rules and transport behavior remain. The mode feeds both
tax and item choices. Automatic synthetic onboarding and higher-level save/submit
validators are not adopted or rewritten here; this is not a claim that every
template-related application check has been unified.

## Selection contract and side effects

`ksa_compliance/item_template_mode.py` has no imports or framework/SQL dependency.
It walks a native list/tuple once, retains the original raw field truthiness and
stops at the first mixed presence observation. It reads mapping/Document rows;
it does not trim or normalize template IDs, infer rates/categories/accounts,
load templates, allocate discounts/advances, convert currency or calculate money.

| Loaded rows | Decision |
| --- | --- |
| Every item has a truthy template value | Use existing template builders |
| Every item lacks a truthy template value | Use existing plain builders |
| Mixed presence in either order | Stop with a typed source-review error |
| Empty/absent table | Plain mode; not proof of a valid invoice |
| Invalid table/obviously invalid row shape | Stop with a static source code |

`template_vat_source.resolve_invoice_template_mode` supplies the framework error
boundary. One English canonical review/diagnostic uses fixed codes without
retaining rejected values. Display translates the new review key to Arabic;
Debug includes it in its existing comprehensive result instead of adding
another popup. Older catalogue rows remain unchanged. Linked-template existence,
actual VAT role/account/rate/category validity and financial reconciliation are
still owned by the existing builders and validators.

The check occurs **after metadata**, before invoice type, references/ICV,
financial builders, signing or transport. Compliance keeps its Company-mismatch
check before the mode decision. Debug metadata is a non-persistent preview, but
ordinary Sales metadata can already persist UUID (including its inherited commit
behavior). This bundle does not move that write, reclaim a counter, rewind a
chain or add rollback/atomicity. A failed mode check does not prove that no UUID
was previously assigned. POS/Company/counter metadata functions are unchanged.

The loaded object is not frozen source custody: templates, Company and invoice
revisions are not locked together. Debug still prepares permissions and then
loads metadata through the existing adapter. Moving the mode observation to
the returned document avoids using the first object's template flag; it does
not resolve every earlier/later source or signer-owner observation. Saved-source,
credential and transaction provenance remain release gates.

## Explicit previous/current results

When the former hint agreed with loaded rows, route markers and actual tested
financial XML remain identical. When it disagreed, the selected existing builder
family can change and therefore XML can change. Do not describe this as universal
byte parity or a new mathematical tax calculation.

Four SAR simulations give concrete examples (two lines of100 each):

| Family / saved source | Wrong old hint result | Current source-owned result |
| --- | --- | --- |
| Sales, invoice-level15%, no item templates | Template path refused | Native VAT30, payable230.00 |
| POS, invoice-level15%, no item templates | Template path refused | Native VAT30, payable230.00 |
| Sales, item templates15%/5% | Plain path payable220.00 | Template path payable220.00; no monetary delta |
| POS, item templates15%/5% | Plain path refused | Native VAT20, payable220.00 |

The input totals, item nets and tax rows are not rewritten. These are synthetic
application outcomes, not accepted authority invoices. The observation is stored
in `/tmp/zatca-template-mode-226-money.json`; the independent original240-case
financial oracle is retained, including its previously recorded review items.

## Evidence

`tests/fixtures/template_mode_generators_0cc3972.py` freezes all ten complete225
generator functions, SHA256
`ef79c872aabb8be937af20ce7829b24552f93ef71d9bcc7a905d3a9ea60fe433`.
It is test-only reference code. All ten bodies are exercised, and structural
restoration reconstructs their exact previous ASTs by restoring only the mode
decision spans. Existing builders and all other generator statements remain.

488 new cases comprise320 frozen-parent route choices,80 localized mixed-source
refusals,10 raw presence/mapping cases,4 invalid-table cases,1 lazy-read case,
72 actual financial XML comparisons and1 test recording the four literal examples.
Route comparisons use marker builders under mocked signing/transport; they are
not full financial invoices. The72 separate cases use actual financial builders
for Sales/nominal/POS, plain15%/zero and mixed item rates,15/16-shaped data,
SAR/USD and native distributed Net Total discounts. They compare XML bytes and
unchanged inputs, not SDK, GL or installed16 behavior.

Final guarded regression/UI counts, structural scope and logs are in STATUS.md.
Private SQL and whole-manifest runs are excluded. Complete installed15/16,
source/credential/transaction custody, full fiscal/GL/precision/settlement,
SDK/scanner and separately approved fictional-client rehearsal before adoption.
No passing synthetic test authorizes deployment or a tax-authority request.
