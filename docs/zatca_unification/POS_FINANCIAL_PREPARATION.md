# One POS financial preparation — increment219

Development only. No live code, tenant, schema, settings, worker, credential or
authority API change. Financial formulas and supported tax-role scope remain
those of [218](POS_VAT_ACCOUNTS.md).

## Problem and resulting flow

The POS routes previously called the totals adapter and then the items adapter.
Each independently prepared the whole invoice: Company display controls, tax
templates, native rate observations, rounding controls and reconciliation were
read twice. A new Company/template observation on the second pass could change
presentation or reject an already partly assembled financial section.

The default routes now call `populate_pos_financials` from
`pos_financial_composition.py`. It selects the public integration contract and,
with the standard adapters and matching dependency bindings, calls the complete
renderer in `pos_financial_xml.py`:

```mermaid
flowchart LR
    A[Select POS adapters] --> B[Prepare and reconcile once]
    B --> C[Immutable rendering values]
    C --> D[Build totals and lines in a temporary XML root]
    D --> E[Append the complete financial section]
```

The following five entry points use this composition:

- `pos_sign.zatca_call`;
- `pos_sign.zatca_call_compliance`;
- `pos_schedule_background.zatca_call_pos_without_xml_background`;
- `pos_submit__without_xml.zatca_call_pos_without_xml`;
- `pos_debug_xml._debug_call` through its local generation function.

This staging covers financial XML nodes. It does not undo earlier party,
identity, file or ICV work and is not transaction/chain atomicity. Those existing
provenance, outbox, rollback and installed-lifecycle gates remain open.

## Immutable rendering projection

Preparation retains only explicit immutable presentation values in its result:

| Record | Values |
| --- | --- |
| PosDocumentValues | Currency, exemption text, recorded accounting VAT |
| PosItemValues | Physical name, index, original quantity/unit/code/name/description |
| PosTemplateValues | Selected ZATCA category |
| PosLine | Those item/template values plus final net, precise unit net price, VAT rate/category/reason/account and optional gross reference |
| PosFinancials | Frozen document/lines, read-only VAT-group mappings, reconciled totals, rounding and discount-display flag |

No mutable Frappe invoice or master is retained in this rendering projection.
Native reconciliation still uses the caller's actual document before emitting
XML. Stored quantity formatting, names, categories, currency labels and monetary
precision remain unchanged. Mutable/invalid presentation fields fail through the
existing typed, translated validation path; a non-standard exemption code must
be text. These malformed-input failures do not redefine a VAT rate or amount.

Both XML parts then use one projection. Later changes to the original in-memory
invoice/master objects cannot change either part of that prepared output. No
financial/global/request cache is introduced. This is not a trusted saved-source,
actor, tenant, credential or transaction snapshot and grants no authorization.
Source/settings locks and late provenance checks still need runtime integration.

## Imported integrations and standalone calls

Public two-argument allowance, tax and item adapters retain their signatures.
They remain available independently, with one preparation per standalone call.
Each public adapter module records private canonical function identities at its
own definition time. These maps contain code references only, not site data.

The compositor invokes the imported DocumentTaxTools factory. An overridden
builder/helper/factory, or distinct tax/item runtime, translator or native-rate
binding, keeps the public allowance → tax → item sequence. It never discards an
imported integration to force the shared path. Such custom composition does not
receive a guarantee of one preparation; its declared behavior stays authoritative.
Class-factory hooks still run once, including when they return standard bindings.

Returned roots and failure order are preserved for these integration paths.
The template Compliance route historically ignores an item's returned root;
its explicit `use_item_result` setting preserves that behavior. Normal paths
accept the returned item root. The standard emitters all return the original
root, so the default shared route has identical resulting XML.

The original saved invoice remains the signing/issuer source. The rendering
projection is never passed to credential selection or signing as its owner.
Supplied/signed external XML, Phase-1 QR, Sales/advance calculations and authority
response handling remain outside this change.

## Evidence and limits

**12,448 distinct offline cases across56 suites passed**, including779 new:

- 720 frozen218 comparisons:688 emitted fragments are byte-identical and32
  rejection codes remain the same. These comprise80 earlier POS inputs and640
  declared-account/category/currency/discount/inclusion/return/quantity variants;
- immutable projection and changing-second-read probes, typed malformed-input
  checks and second-line failure tests protecting the caller's XML root;
- imported selection, replacement roots, failure order, dependency distinctions
  and factory/helper hook cases;
- ten real entry-point compositions with real financial preparation and mocked
  parties, signing and transport. Each prepares exactly once and signs with
  the original document. Debug creates only a synthetic local attachment.

For accepted examples, financial master get_doc calls are exactly halved: the
plain example4→2; two different item templates6→3. This counts supplied-reader
invocations in the financial component, not SQL queries, full invoice calls,
CPU or production latency. Each independent operation prepares afresh.

The existing original240-case pre-development oracle remains separate:
91 identical,117 changed,32 blocked. Earlier financial deltas are not relabeled
as parity by this refactor. The complete218 adapter is frozen in the test-only
fixture `pos_financial_c8ae317.py`, SHA256
`43100e52ac8867e814d69835847a09eeb50929b98aa1e5e3b5121eb6cdbc2deb`.
The original and217 fixtures remain unchanged. Shared Sales emitters, VAT math,
account-specific/native legacy readers and tax-total calculators are unchanged.

The five browser suites also pass: Debug messages88, Debug lifecycle164,
Company messages108, Company form292 and device form128. No message/catalog
change is needed here; typed failures reuse the prior translated view and
English diagnostic boundary. Native16 remains pinned-source/simulation evidence,
not an installed16 or SDK acceptance result.

Evidence: `/tmp/zatca-pos-composition-219-regression-final.log`,
`/tmp/zatca-pos-composition-219-focused.log`, and
`/tmp/zatca-pos-composition-219-structure.json`. Numeric expression and source-scope
checks accompany the byte comparisons; no tenant SQL or authority API was used.

## Multi-row Item Tax Template review

The inspected installed15 detail schema contains only tax_type (Account Link)
and tax_rate. Current application fixtures put ZATCA category and exemption code
on the parent template, with no per-detail VAT/charge/exclusion role. Native
get_item_tax_map copies all those account rates, including zeros. A zero row may
be an override suppressing another invoice tax account, or belong to an actual
zero-rated/exempt VAT source. It must not be removed or replaced blindly.

Therefore the multi-row-template rejection is unchanged in this increment.
One candidate for the next increment is an optional explicit VAT Account link
on an Item Tax Template: single-row templates retain their default, while a
multi-row template declares which row owns its parent category/reason. Other
rows may be zero overrides only when corroborated by the complete invoice
account/native-rate scope. Positive charges still need separate fiscal policy.
No such field or setting has been added in219. Its selection must reach both
preflight category/account reconciliation and every affected XML path through
one shared selector; changing just the POS emitter would leave conflicting
checks and native source assumptions.

Next define explicit ownership/exclusion and non-VAT charge/deduction semantics,
verify how those declarations reach saved v15/v16 native rows, and reconcile
charge tax bases and XML groups before relaxing that guard. Keep the native FX
header boundary, source/GL/XML reconciliation, installed lifecycle, SDK and
separately approved fictional-client rehearsal in the completion plan.
