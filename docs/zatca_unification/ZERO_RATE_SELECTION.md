# Preserve selected zero and group non-template rates — increment208

Development only. The two zero-discarding Sales/nominal consumers identified in
[ITEM_TAX_RATE_ONLY.md](ITEM_TAX_RATE_ONLY.md) now preserve selected zero rates.
Their non-template breakdowns also separate different rates rather than label
all tax with the first rate. No field, Company setting, dependency, schema, UI
message or authority endpoint is added.

## Source absence is distinct from zero

`get_item_tax_rate(doc, item, *, default=0.0)` extends the existing API with an
optional missing-source default. Omitting it keeps the prior rate contract;
`get_item_tax_detail` is unchanged. The default is used only at the existing
empty-v16/no-invoice-rate or absent-v15-rate exits. A populated v16 table's
unmatched result remains authoritative zero under the existing selector policy,
so it cannot activate fallback to stale v15/invoice data. Matched zero, invoice
zero and item overrides also remain zero.

The two helpers request `default=None` and accept any returned zero. Their
existing invoice fallback, quantizers, initial tax-table gate and broad exception
fallback remain. Positive selected rates still take precedence over invoice
rate 15. `None`/empty/failed lookups still follow the previous fallback path;
zero no longer takes that path.

This is source-presence handling, not strict input validation. Existing present-
but-malformed number coercion to zero remains, as do native unmatched-table and
non-finite policies. Neither the default nor a returned zero proves source
completeness, an allowed tax category or invoice eligibility. Strict source/
completeness and malformed-input validation remain release work.

Existing two-argument callers and full-detail aliases still work. Overrides of
the imported rate getter in the two helpers must accept the new `default`
keyword; tests explicitly do so rather than let a TypeError get swallowed by
legacy fallback. There is no new cache, second rate-selection algorithm or
implicit Company/device/credential substitution.

## Correct per-rate subtotals

Both `_nominal_breakdown_without_template` and
`_get_tax_breakdown_without_template` now accumulate one bucket for each selected
quantized rate, in first-seen order. Repeated nonadjacent rates share a bucket.
The same original per-line net sources and tax-rounding expressions remain.
Nominal rows retain their separate SAR tax accumulator and existing final OOS
offset. Ordinary XML keeps existing summary, legal/payable and prepaid/rounding
ownership. Empty tables retain the old zero bucket; homogeneous ordinary
invoices retain their initial aggregate net source.

For example, line net 1.01 at5% and2.03 at15% produces separate subtotals1.01/0.05
and2.03/0.30. A zero first line at net 1.01 plus a 15% second line at net 2.03 now
keeps zero on the first line and emits a separate 2.03/0.30 subtotal, rather than
substituting the invoice rate and retaining only a first-rate summary.

`_new_tax_rate_bucket` in the existing `xml_tax_data.py` supplies shared empty
accumulators, preserving field order and optional SAR storage. Both builders
use it for regular and empty buckets. It performs no rate selection, rounding,
validation, I/O or persistence. Template branches and all other runtime functions
are unchanged. Non-finite values use a stable diagnostic grouping key because
NaN does not equal itself; this does not certify or broadly repair such inputs.

The invoice-wide declared category/reason is retained in each bucket. The code
never infers S/Z/E/O from a numeric rate. Mixed **categories** still use the
existing Item Tax Template route; mathematical mixed-rate fixtures are not
proof that every category/rate combination is valid. Category/rate/exemption
validation, per-line versus group rounding acceptance, stored SAR totals and
full GL/VAT/SDK reconciliation remain gates. No accounting value or historical
issued artifact is repaired to make an XML example pass.

## Frozen evidence and tests

`tests/fixtures/zero_rate_consumers_cc4918b.py` freezes the exact two old helpers
and two old breakdown functions from
`cc4918b4b8c9f6cfe66538abbaed7ecaff7dfc7b`. SHA256:
`11ec5d35448644f86bfde04028be4547538c789d2cee28c2aed66c88e89270d7`.
The reference executes the old zero-discarding condition and first-rate bucket;
it has not been rewritten to hide the defect.

`test_zero_rate_selection.py` adds **330 local cases**:

- 48 missing-source/default and authoritative-zero cases covering v15 item,
  invoice, legacy and malformed-present normalization; v16 matched/unmatched/
  empty/null/later-rate behavior; and identity-preserving arbitrary defaults.
  The ordinary omitted-default API still matches the full tuple's rate.
- 14 helper-boundary cases for None/empty/failure fallback, native/Decimal zero
  and positive rates, explicitly checking the `default=None` call.
- 12 exact pre-fix/new-helper cases across v15 override and v16 matched/unmatched
  zero, two currencies and both helpers: old15 becomes selected0.
- 128 literal bucket cases across eight zero/positive/mixed/repeated-rate
  patterns, synthetic v15/v16, SAR/USD, signs and ordinary/nominal. Expected
  taxable/tax/SAR values are independent literals, not computed through the
  grouping implementation.
- 24 homogeneous-positive/empty breakdown output and ordered-read comparisons
  against the exact parent, plus 24 complete tax-XML byte comparisons.
- 64 actual tax-XML cases verify one subtotal per rate, retained nominal OOS
  offset, legal/payable totals and consistent ordinary item/subtotal tax sums.
- 16 category/reason forwarding cases prove zero does not infer or overwrite
  declared classification. These are metadata tests, not exemption validation.

Older four zero-conflict cases now assert the repaired zero result. Historical
native-rate overrides accept the optional keyword so remaining-read comparisons
still execute their intended dependency. No prior frozen fixture/hash changed.

Final guarded selection: **8,665 distinct local cases passed across 43 reviewed
suites in 24.59 seconds**, including 330 new cases. Existing Sales/POS items,
advance/Decimal, full/rate-only tax, tax/party, signing/QR, routing/settings,
scheduling, messages and artifact cases also passed. Log:
`/tmp/zatca-zero-rate-regression-final-208.log`. Initial overlapping runs are
excluded. Manifest is 177 local/57 private suites; no whole-manifest or private
SQL run was needed. This is a correctness change; no CPU/memory/query saving is
claimed from bucket allocation or the preserved initial net read.

AST review restores only the optional missing default in the native module and
reproduces the entire parent AST. Each helper differs only by requesting None
and accepting zero. Both breakdowns retain the exact old line-tax expressions
and net acquisition calls; bucket bindings are checked independently. Outside
those four reviewed functions, the new shared bucket helper/import and the
native default extension, the runtime module ASTs are unchanged. All four frozen
functions exactly match the parent. Tool:
`/tmp/zatca_zero_rate_structure_208.py`; report:
`/tmp/zatca-zero-rate-structure-208.json`.

## Remaining acceptance

This closes the selected-zero replacement and first-rate-only mathematical
breakdown defects. It does not complete category/rate/exemption validation,
strict input/source presence, GL/VAT/FX/advance reconciliation, legacy reference
provenance, first-chain/retry/credential guarantees, SDK/QR checks or installed
ERPNext/Frappe15/16 evidence. The separately approved fictional-client rehearsal
and later rollout decision remain required after completed development.

No live source/configuration/schema/customer data, Bench or worker changed;
no authority request occurred. The unrelated live tooltip edit was preserved.
