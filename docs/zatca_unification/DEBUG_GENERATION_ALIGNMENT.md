# Debug classification and Sales item selection — increment225

Development only, 2026-11-16. No deployed source, site/schema/configuration,
invoice, Bench or worker was changed. No tenant SQL or authority API was used.
Mocked execution of ordinary generator functions is not a live submission.

## Findings and resulting behavior

Sales Debug used an outer `handle_b2c_simplified` flag. Explicit Phase2 plus a
GPOS unique ID, or Background scheduling without a bypass, could set that flag
without checking the actual customer. Inside the generator it selected the
simplified builder before checking an explicit Compliance sample. Thus a B2B
invoice or a requested standard sample could produce simplified Debug XML.
The ordinary primary Sales generator did not have this scheduling classification.

`invoice_type_xml.populate_invoice_type` now composes the existing type builders
for ordinary Sales/POS and Debug Sales/POS. It selects an explicit validated
sample first, then an original Sales advance when eligible, then the actual
customer's B2C/standard branch. The actual functions in `createxml`/`posxml` remain
unchanged, including their flags, codes, export rules, note precedence and
inherited POS limits. No new interpretation of legal invoice codes is introduced.

| Sales Debug situation | Previous224 | Current225 |
| --- | --- | --- |
| B2B ordinary + Background | Simplified388 | Standard388 |
| B2B credit + GPOS unique ID | Simplified381 | Standard381 |
| Explicit sample4 + original ordinary invoice + Background | Simplified388 | Standard381 from the selected sample |
| Explicit sample5 + original credit + forced simplified branch | Simplified381 | Existing simplified-debit sample383/0211000 |
| Original advance, ordinary selector0 | Existing advance386 | Same existing advance386 |
| No forced branch, valid selector | Existing original/sample type | Same existing builder/type |

These are **intentional Debug type/header changes**, not edits to the saved
invoice or to the original ordinary generator. A type change necessarily changes
the generated Debug XML/hash/signature; this is not universal byte parity.
Scheduling no longer selects a Sales Debug type. The public
`bypass_background_check` parameter remains callable for compatibility and has
no Debug classification effect. Existing GPOS XML/QR checks and existing-artifact
notices remain; no saved QR/XML is used as the new Debug file's source.

POS Debug retains its B2C-only ordinary-document rejection callback; an explicit
sample can still select one of the six sample types. Ordinary primary POS retains
its existing standard branch. This bundle does not expand POS fiscal support or
change ordinary POS debit-note handling. The shared compositor binds imports at
invocation time, passes returned roots onward and keeps sample/advance short
circuit reads. It is not a permission, issuer or immutable-source object.

## Validate the Debug selector before identity or XML generation

After existing saved-source/permission preparation, Debug normalizes selector0
and the six existing sample codes using the common submission contract. Integers
and surrounding whitespace are accepted consistently. Bool, float, missing,
empty, unrecognized and structured inputs return one static review before preview
identity, type/party/financial builders, signing or File creation. Rejected values
are not stored in the new exception or interpolated into its message.

The result and log remain English. The app-owned review notice has Arabic display
translation through the shared presenter, preserving one comprehensive dialog.
The existing permission envelope, private attachment checks, message mute scope,
UUID/ICV preview rules, signing source and File persistence routines are unchanged.
Existing non-selector error families keep their previous boundaries.

## Select Sales item builders once in ordinary and Debug generation

`sales_item_xml.populate_sales_items` shares the **primary ordinary Sales** choice:

1. Observe installed apps, legacy copy presence and complete direct-allocation
   schema using the existing reader and short-circuit order.
2. A direct row with the original truthy invoice/allocated-total observations,
   or an installed legacy extension with a copy, selects the matching advance
   item builder. Direct reference processing retains priority inside that builder.
3. Otherwise select the existing ordinary item builder. The caller's item-template
   flag selects the existing template variant, and replacement roots propagate.

This is not an advance finder, a new schema capability implementation, a numeric
allocation validator or a second calculation. It performs no FX, discount, VAT,
rounding or settlement math. It neither changes advance eligibility nor edits an
old advance, payment, GL row or allocation. Dedicated Compliance, legacy background/
without-XML generators and automatic synthetic onboarding are not adopted here.

The old Debug ordinary item builder already appended direct386 references.
Therefore this change is **not a repair of missing direct advance references**.
It aligns builder selection and custom integrations with ordinary Sales. Actual
normal-native item XML comparisons, including direct/legacy/both sources,
template/plain, SAR/USD, return signs and15/16-shaped rows, verify byte and amount
parity. Nonstandard UOM/source types, read failures and custom overrides may retain
the selected advance builder's existing stricter behavior; no new coercion is used.

## Evidence and limits

`tests/fixtures/debug_generation_8905036.py` freezes the complete224 ordinary
Sales/POS generator and both Debug implementation bodies. SHA256:
`8d9443ff4580c5939037ab026e5cd1132c025425483f3f1cfc018ec31a49efe2`.
It is test-only source evidence, not a runtime fallback. New tests separate exact
ordinary-generator parity, intentional Debug type changes, actual financial-item
bytes, source refusals and framework permission/signing/transport mocks.

The financial calculators, XML type builders, cryptographic/QR algorithms,
credential/API selectors, counter/UUID persistence and shared artifact/permission
engines remain unchanged. Current and original financial oracles are independent.
All previous financial differences still need their existing review; passing a
new frozen-parent test does not erase those differences.

Final guarded regression, focused/UI counts and structural scope are recorded in
STATUS.md:16,352 cases across66 reviewed suites, including642 new; focused642
and529 existing generation/isolation cases pass, plus1,204 browser cases. These
are application assertions, not authority validations; repeated runs are not
summed. The original240 financial matrix remains91 identical/117 changed/
32 blocked.26 earlier Python reference fixtures and351 other tracked runtime
files are byte-identical to224. No private SQL or whole-manifest run is included.
Tests do not establish installed ERPNext16/Desk behavior, signed UBL/
SDK/scanner acceptance, full GL/fiscal or credential/transaction custody. Complete
those gates before separately approved isolated fictional-client rehearsal; never
deploy this branch or send an authority request based on these synthetic results.
