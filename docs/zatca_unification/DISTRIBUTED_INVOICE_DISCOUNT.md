# ERP-distributed invoice discounts — increment216

Development only. The source of monetary values is the ERP-calculated line net,
not a fresh allocation of the invoice discount inside the ZATCA application.
This increment verifies that contract against pinned15/16 allocation methods and
relaxes two ordinary Sales mixed-category guards only when native allocation
evidence exists. It does not modify ERPNext, stored invoices or POS calculations.

## Authoritative amounts and discount modes

Use `net_amount` for document-currency net values and `base_net_amount` for the
existing SAR/company-currency path. An inclusive-price line's final net already
excludes tax; do not divide it by the tax factor again. Both Net Total and Grand
Total discount modes can produce allocated net values. The header discount must
not be subtracted again when those values are the chosen XML line basis.

The current Sales XML already follows this model. The actual financial builders
are executed in the new tests: final line nets feed tax groups and monetary
totals; no document AllowanceCharge is added, and AllowanceTotalAmount stays0.
The high-precision unit net price is derived from final net amount/quantity.
Do not rely on a rounded `net_rate` if multiplying it by quantity does not
reproduce the already calculated line total.

The native allocation observations include these two-line examples, each with
initial net100 per line:

| Discount basis | Header discount | Final line nets | Model VAT | Model payable |
| --- | ---: | --- | ---: | ---: |
| Net Total,15% | 20 | 90.00 +90.00 | 27.00 | 207.00 |
| Grand Total,15% | 23 | 90.00 +90.00 | 27.00 | 207.00 |
| Grand Total,15% | 20 | 91.30 +91.31 | 27.39 | 210.00 |
| Net Total,Z0/S15 | 20 | 90.00 +90.00 | 13.50 | 193.50 |
| Grand Total,Z0/S15 | 21.50 | 90.00 +90.00 | 13.50 | 193.50 |

VAT/payable columns are independent test observations filled after the native
allocation/net-total stage. The whole ERP tax recalculation is not executed by
this probe. They are not claimed as installed-site accounting evidence.

## Runtime change and preserved boundaries

`createxml._has_erp_distributed_discount` is an allocation-evidence predicate,
not a monetary calculator. For the new mixed-category exception it requires:

- A document discount, nonempty items and present selected net fields, including
  a legitimate zero net value.
- A nonzero native `distributed_discount_amount` marker and the existing
  line-net-model check; tax-inclusive price differences or a custom flag alone
  are insufficient.
- Exclusion of the native cash/non-trade Grand Total workflow.

The two predicates in `sign_invoice.zatca_background` and
`zatca_background_on_submit` now permit ordinary mixed-category discounts under
that evidence. Previously they rejected them despite ERP allocation and XML
omission of a second document allowance. Nominal restrictions remain unchanged.

Unknown/legacy missing markers, missing nets and unsupported allocation still
retain the original rejection. The existing exception bodies/messages and all
other entry-point statements remain. No new popup, language key or log is added.
The inherited error text is not new evidence of a ZATCA prohibition: this change
addresses an application restriction, not an authority ban on multiple groups.

The pre-existing single-category Grand Total/manual-flag behavior remains; the
stronger predicate is not a universal rewrite of every discount gate. The tests
explicitly show that setting `custom_zatca_use_line_net_amounts` can activate the
older model without proving native allocation. Do not interpret that override
as accounting/source evidence or as resolution of the216 review's limitations.

## Native source observations and exceptions

Four original controller methods are loaded from hash-verified local sources:
`apply_discount_amount`, `get_total_for_discount_amount`,
`_set_in_company_currency`, and `calculate_net_total`. Framework numeric kernels
use actual15 helpers or the already reviewed pinned16 helper excerpts, under
explicit Commercial/Banker's Rounding and precision2 boundaries.

- ERPNext15: `572d8530b6258231e31f294474cc1818f693d10b`.
- ERPNext16: `ade850bbd6a7412e9994a9637d2c5c713771632a`.
- File/method hashes: `tests/fixtures/discount_controller_sources.json`.

No new ERPNext controller source is vendored or executed as a module. Only the
four reviewed methods run with synthetic documents/precision/settings. Their
post-allocation `_calculate` boundary runs net-total aggregation only; initial
item/tax extraction, percentage-to-discount conversion and complete tax/GL
recalculation remain outside this probe. Pinned16 source must be staged locally
at the documented temporary cache path before running that format's cases;
absence is an explicit skip, never an automatic network fetch. This run had no
skips and does not claim an installed16 environment.

For Grand Total20, the second line's net is91.31 in both versions, while its
native distribution marker is8.71 in the pinned15 method and8.69 in16. The
rounding-adjustment expressions differ. The marker is useful as presence
evidence but must not be subtracted again or used to reconstruct final net.
With quantity3 the native rounded net_rate also fails exact reconstruction;
the existing XML price calculation from final net/quantity preserves the line.
No upstream method or marker value is repaired by the application.

Cash/non-trade Grand Total discounts return without native line distribution.
They are kept outside the new exception and require their own supported source/
accounting policy. Inclusive price differences alone cannot prove allocation.
Actual charges, mixed-sign allocation, full nominal100%, source-account roles
and all rounding/currency/settings combinations remain broader review gates.

## POS findings: migrate the complete financial path

Sixteen current-POS observations use native allocated inputs. The existing code
retains gross/pre-allocation line values and a header allowance. Some Net Total,
non-inclusive results match the expected payable through that alternative
representation; differing line bases alone do not prove every old POS XML wrong.

However the Grand Total23 examples with source payable207 demonstrate:

| POS source | Non-inclusive XML payable | Inclusive XML payable |
| --- | ---: | ---: |
| Invoice-level template | 203.55 | 180.55 |
| Item Tax Templates | 203.55 | 238.05 |

Both formats reproduce these observations. Net Total20 inclusive cases also
produce184/241.50 in those two paths instead of207. These are synthetic cases,
not assertions that every actual customer document has the same problem.

Do not fix only POS LineExtensionAmount: the old allowance/monetary logic would
remain and could discount the already allocated net a second time. The next
migration must coordinate final line values, unit-price/line-discount settings,
VAT groups, allowances and monetary totals. Company line-item-discount display
is0 in these POS observations; its enabled behavior is not declared supported
by this review. POS runtime code is intentionally unchanged in this increment.

## Tests, compatibility and next work

`test_distributed_invoice_discount.py` adds283 local cases:

-256 native-allocation/Sales-XML combinations: invoice/item templates where
  applicable, two discount bases, mixed Z0/S15, two primary source versions,
  two framework rounding methods, inclusive/exclusive prices, quantities1/3
  and SAR/USD. All preserve source/master values and avoid second allowances.
- Two native cash-workflow exclusions and two versioned-marker observations.
- Five stronger-evidence/nominal rejections and two legacy override observations.
-16 current-POS characterization cases, not POS correction/acceptance.

The complete parent guard statements are frozen in
`tests/fixtures/discount_guards_c2de512.py`, SHA256:
`6de55b3ba22c40a798fbbff0544eeade14550c9548980f7cfc46647eb786e4f4`.
The frozen statements match the parent ASTs. Structural restoration of the two
mixed predicates and removal of the new import restores the entire previous
sign_invoice AST. Removing the new evidence helper restores createxml. Existing
Sales/POS XML math and customization definitions remain byte-identical.
Tool: `/tmp/zatca_discount_structure_216.py`; report:
`/tmp/zatca-discount-structure-216.json`.

Final guarded selection: **10,388 distinct local cases across52 reviewed suites
passed in47.10 seconds**, including283 new cases and explicitly characterized
POS/override limitations. Log: `/tmp/zatca-distributed-discount-regression-final-216.log`.
Manifest:186 local/57 private suites; no whole-manifest, private SQL or tenant
run. Data observations: `/tmp/zatca-distributed-discount-216.json`.
No CPU/query/heap improvement or full compliance claim.

Next: coordinate POS monetary/source migration, close the ERP row-rounding/XML
reconciliation gap recorded in [GROUP_VAT_ROUNDING.md](GROUP_VAT_ROUNDING.md),
and complete accounting/FX/nominal/advances, SDK/QR, installed15/16 and the
separately approved fictional-client rehearsal gates. Preserve existing field/
settings behavior or explicitly report its intended delta before adoption.

No live source/configuration/schema/data, Bench or worker changed. No invoice,
Compliance, CSID or other authority request was sent. The unrelated live tooltip
edit remains preserved.
