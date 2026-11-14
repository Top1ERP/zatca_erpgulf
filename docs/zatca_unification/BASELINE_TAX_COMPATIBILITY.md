# Original-baseline financial compatibility review — increment213

Development evidence only, 2026-11-14. User priority: preserve stable existing
results and report differences for review; a previously intentional change is
not automatically accepted. The user preferred simulation over selecting real
customer invoices. This increment changes tests/documentation only, with no
additional financial implementation, account filtering, setting or migration.

The subsequent [published-standard audit](TAX_STANDARD_AUDIT.md) separately
checks correctness. It exposes inherited rounding/POS gaps despite some exact
original/DEV matches; the preservation evidence below is not a standards verdict.

## Which original implementation is compared

Baseline `2e97708e115e31c675182647d10829d6175e7449` predates the unification
work. Its six financial-source files also match the currently installed live
source at `ba51f2587763a4e9db045f57e1b8ee2bc29ea77c` byte for byte. This was
verified by reading those source files, not by executing a live invoice or
assuming that a recent development parent represents the original application.

The comparison freezes complete original function closures and constants from:

- `ksa_compliance/tax_details.py`.
- `zatca_erpgulf/xml_tax_data.py`.
- `zatca_erpgulf/create_xml_final_part.py`.
- `zatca_erpgulf/posxml.py` and `pos_final.py`.
- `zatca_erpgulf/createxml.py` discount helpers.

The test loader binds the original import graph explicitly, including the
original native tax reader, original XML/exemption helpers and POS discount
helper. It never substitutes current financial helpers into the baseline oracle.
Synthetic Frappe master reads and framework utilities are explicit boundaries.
No site is initialized and no tenant data, credentials or authority API is used.

All80 complete original functions and selected original constants match the
pinned source ASTs. The import-free test-data fixtures and per-source hashes
are recorded in `tests/fixtures/financial_baseline_2e97708/manifest.json`.
Manifest SHA256:
`bd710681f766f8cf6b5ca06e9abe6962c5a51b2e7010d147a0de59e0899e257f`.
Two inherited trailing spaces outside string literals were normalized in a
test reference; all original function ASTs remain exact. These are actively
loaded test references, not alternate runtime modules/hooks.
Structural proof: `/tmp/zatca_baseline_structure_213.py`; report:
`/tmp/zatca-baseline-structure-213.json`.

## Simulation matrix and exact observed results

Ten named input cases cross ordinary Sales, nominal Sales and POS; v15 JSON and
v16 child-table formats; SAR/USD; and no/distributed document discount. Each
case uses the same document and linked-master values on both implementations,
with complete source snapshots checked after each rendering. The v16 ordinary
invoice-template15 control exercises the empty-native-table invoice fallback.
The invoice-template15, combined15/5 and invoice-template0 controls explicitly
have neither Item Tax Template nor item_tax_rate overrides; their copied invoice
rows come from the simulated invoice-level template. This is source-format
simulation, not execution of ERPNext's whole tax-calculation lifecycle.
Company line-item-discount display is0 and print-tax inclusion is0. Other flag
combinations and installed runtimes are not asserted by this matrix.

The test compares exact unsigned financial XML bytes: discount nodes, tax totals
and subtotals, monetary totals, item lines, rates, categories, reasons, prices,
attribute values and node order. This does not compare a complete signed invoice
with identity/timestamp/certificate/QR, nor certify that every stress input is a
valid regulatory combination. It is not SDK or actual-client acceptance.

| Family | Compared | Byte-identical | Different |
| --- | ---: | ---: | ---: |
| sales | 80 | 48 | 32 |
| nominal | 80 | 48 | 32 |
| pos | 80 | 80 | 0 |

All240 comparisons pass their *characterization* assertions. That means176 are
byte-identical and64 expose the documented pre-existing development differences;
it does **not** mean240 equivalent outputs or that the64 differences are approved.
The four difference patterns repeat across both Sales families, formats,
currencies and discount modes. All80 POS financial fragments match the original.

The following ordinary-Sales examples each use two100 net lines, with no
prepayment or rounding adjustment:

| Scenario (ordinary Sales, v15, SAR, no discount) | Original XML tax | DEV XML tax | Original / DEV payable | Financial XML |
| --- | ---: | ---: | --- | --- |
| Invoice template15; no item template | 30.00 | 30.00 | 230.00 / 230.00 | identical |
| Invoice template with15 and5 tax rows | 30.00 | 30.00 | 230.00 / 230.00 | identical |
| Item templates with15 and5 tax rows each | 30.00 | 30.00 | 230.00 / 230.00 | identical |
| Separate item templates5 and15 | 20.00 | 20.00 | 220.00 / 220.00 | identical |
| Item overrides5 and15; invoice template15 | 20.00 | 20.00 | 220.00 / 220.00 | DIFFERENT; review pending |
| Item overrides0 then15; invoice template15 | 30.00 | 15.00 | 230.00 / 215.00 | DIFFERENT; review pending |
| Item overrides15 then0; invoice template15 | 30.00 | 15.00 | 230.00 / 215.00 | DIFFERENT; review pending |
| Both item overrides0; invoice template15 | 30.00 | 0.00 | 230.00 / 200.00 | DIFFERENT; review pending |
| Item templates0 | 0.00 | 0.00 | 200.00 / 200.00 | identical |
| Invoice template0; no item template | 0.00 | 0.00 | 200.00 / 200.00 | identical |

## Differences requiring the user's decision

These observed changes trace to increment208 (`d14984b`), not to the shared
mechanics extraction in212. They remain development-only and unapproved here:

1. **Selected zero retained instead of replaced by invoice15.** For0/15 line
   overrides, XML tax changes30 to15 and payable230 to215. Reversing the line
   order gives the same monetary difference. For two explicit zero overrides
   under invoice15, XML tax changes30 to0 and payable230 to200. These align with
   the supplied line-rate amounts in this simulation; that alone is not user
   approval, evidence about actual invoices, or a universal tax-policy decision.
2. **Different positive rates get separate subtotals.** For5/15 overrides, tax20
   and payable220 are unchanged. The original single subtotal has taxable200,
   tax20 and percent5; development has taxable100/tax5/percent5 and
   taxable100/tax15/percent15. Thus equal totals do not imply identical XML.
3. **Item-template zero and invoice-row zero controls remain unchanged.** Zero
   is not a universal change: the original fallback already retained it in these
   supplied configurations. Both original and DEV tax remain0/payable200.

No automatic rollback, legacy-behavior toggle, VAT-row filter or additional
financial correction is applied. Review whether each difference is acceptable
before changing or adopting the corresponding behavior. Future refactors must
retain original-baseline evidence, not only compare consecutive DEV revisions.

## Multiple tax rows: preserve behavior without guessing VAT ownership

With two15/5 tax rows in the **invoice-level** template, v15 selects the first
rate15 in this input and both versions emit tax30. With a populated v16 native
child table, both sum15+5 and emit tax40. That v15/v16 distinction already exists
in the original implementation; it is not a new change introduced by development.

With two15/5 rows in each **Item Tax Template**, both versions use the first
item-template row and emit tax30 in both formats. Separately linked5/15 item
rate templates also match the original in the compared fragments. No second
row is newly dropped, newly summed or reclassified by this increment.

The simulation's raw invoice taxes sum40 for the combined15/5 case. XML tax30
in some original paths is an observation to review in context, not proof that
VAT is missing: the second tax row's fiscal role has not been declared. General
ERP tax totals can contain other taxes/charges. Conversely, summing both rates
is not automatically a valid VAT decision. Do not add VAT-account filtering or
assume that every account in a category-labelled template is VAT. The user has
not authorized changing either source policy based on this stress case alone.

## Test scope, artifacts and release status

`test_baseline_tax_compatibility.py` adds240 local cases and independent literal
ordinary-Sales tax/payable expectations. Source/master snapshots remain equal;
document save/db_set, DB commit/set_value and popup/log boundaries stay uncalled.

The final reviewed selection passed **9,893 distinct local cases across49 suites
in34.18 seconds**, including these240 characterization cases. Log:
`/tmp/zatca-baseline-regression-final-213.log`. Manifest:183 local/57 private
suites; no whole-manifest, private SQL or tenant run. The240 affected comparisons were
repeated after fixture-whitespace normalization with the same176/64 outcome;
this adds no distinct cases. No performance claim.

Machine-readable results and480 original/development financial fragments are at
`/tmp/zatca-baseline-tax-compatibility-213/`. `results.json` records original and
DEV rates, amounts, categories, exemption codes, subtotals, monetary totals,
line values, raw input totals and each difference's pending-review status.
Results SHA256: `5b8fc626275acd423fde18532f9b7a7e68c3c8e6ddb5b89c8d8608fc2bb36e4f`.
Artifacts are synthetic and local; no real customer XML or credentials are
committed. Re-run the reviewed local test to regenerate temporary evidence.

Full phase/settings/GL/VAT/FX/advances, print-tax inclusion, rounding/prepayment,
first-chain/retry/credential, SDK/QR, installed ERPNext/Frappe15/16 and separately
approved fictional-client rehearsal remain release gates. These results do not
approve rollout or resolve all existing tax-source ambiguity.

No live application/configuration/schema/data, Bench/worker or tax-authority
request changed. The unrelated live tooltip edit remains preserved.
