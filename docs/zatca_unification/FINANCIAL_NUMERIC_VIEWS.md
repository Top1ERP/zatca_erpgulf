# Financial real-number getter views — increment138, 2026-11-02

## Two explicit stages, one unchanged native parent

`InvoiceNumericView` binds a complete ordered set of selected numeric getter
observations to `LockedInvoiceFinancialRead`. Select only the applied metadata's
Currency/Float/Percent/Rating/Duration fields already inside the fixed financial
header/child manifest. No request chooses arbitrary fields, rows or types.

| Stage | Required representation |
| --- | --- |
| SAVED | Exact native scalar tag, including Decimal scale, float signed zero, type and NULL |
| NUMERIC_FIXED | Non-NULL Currency/Float/Percent match precision-free flt; NULL stays NULL; Rating/Duration remain unchanged |

The latter follows the actual15/pinned16 explicit numeric-fix bodies. It is not
the Currency-fraction configuration API, where flt(None) becomes zero: numeric
fixing skips a NULL monetary getter. It is not precision rounding, quantization,
currency/VAT calculation or XML formatting. Preserve native Decimal amounts and
their hashes unchanged; no ERP document or database value is fixed or replaced.

`from_values(financial, stage=..., values=...)` requires the exact ordered tuple
of (group, saved row name, fieldname, observed value) entries, covering every
selected field of every native row. Unknown, duplicate, missing, reordered or
rebound entries are refused. Fixed observations must have the exact finite float
identity the framework conversion would yield, without tolerance. Saved values
must preserve raw type/scale/sign. No string/bool/zero repair occurs.

The conversion witness is only derived during an explicit fixed-view comparison.
A valid 64-digit native Decimal can project to float1e64, outside the unchanged
raw-float profile's bound. Encode and compare that derived finite hex value in
this separate profile instead of weakening the native contract. This is no
permission to cast/serialize a ZATCA monetary amount as that float.

`require_match` revalidates a protected view before comparing observations.
`observe_fixed(values)` validates supplied post-fix observations against the same
native parent. The caller still owns their actual in-memory stage/origin; this
comparison does not prove a controller ran or that accounting totals are correct.
The profile binds native financial/metadata/revision hashes, stage and all cells.
Repr is protected and pickle is refused.

## Optional saved acquisition on the existing service

`SavedCalculationDefaultsService.capture_numeric_context(invoice_name,
erp_major=15|16, doctype="Sales Invoice"|"POS Invoice")` returns
`SavedFinancialNumericRead` on the SAME owned financial/defaults pipeline.
The existing Administrator/System Manager and site-default policy applies.
There is no new provider dependency, callback, SQL reader/transport, transaction,
cleanup implementation, RPC, button, schema or installed runtime caller.

`NumericAcquisition` reuses FinancialGraphAccess for normal invoice/Company,
present-table (including empty table), saved-row and financial-field READ before
metadata/connection/cache acquisition. Pin selected normal field definitions,
types and permissions; compare the selected family to the native applied metadata
before SQL. A changed type cannot silently drop a field from the observation set.

Capture original and fresh saved header getters, direct saved children and
embedded child references. Require exact values/identities across those views;
do not replace an inconsistent original with a fresh equal object. Pin native
row membership/revision, every selected value and full selected definitions.
Recheck source/field/role access, metadata and getter snapshots through shared
rollback/close. Decimal-scale or signed-zero changes are drift even if ordinary
numeric equality says the value is equal.

The shared financial reader supplies native data and final source checks; this
extension issues no additional native SQL or settings/cache-provider call.
Ordinary READ/getter rechecks can still reload documents through Frappe; this is
not a no-I/O or performance guarantee. Never call precision(), numeric
fixing, tax/rounding/controller methods or save. New owned pending work is rolled
back; recognizable ambient handles retain caller ownership. Existing translated
financial summary, English internal codes and interruption priority are reused.

`SavedFinancialNumericRead` reconstructs financial/default/context binding,
the SAVED view and saved financial table graph. Missing/rebound sources or a
normalized view substituted for a saved observation are refused. This partial
result does not grant issuance or a complete PreparationContext fingerprint.

## Evidence and callers

Known callers are the optional service method and the reviewed
test_financial_numeric_view, test_calculation_numeric_access and _mariadb suites
in the offline manifest. Synthetic actual15/pinned16 numeric-fix probes cover
all five real field types, NULL, Decimal scale, signed zero and large derived
floats. The existing source profiles/SQL are not rewritten to pass these tests.

NEW guard-owned TCP-disabled SQL fixtures exercise ordinary Sales/POS and declared
15/16, both isolation levels, header/item/tax/payment/advance/deduction values,
original/fresh/ref inconsistencies, late mutations, ACL drift, metadata changes,
rollback/close and caller pending work. No working site's data is used. This is
not installed16, browser, SDK or authority acceptance evidence.

## Remaining gates

SAVED acquisition now supplies selected real-number getter equality to its native
source. Supplied fixed views are a separate representational comparison, not
complete in-memory lifecycle provenance. Next bind actual controller/caller
stages and child/lazy behavior, effective precision/cache/default/FX settings,
rounding/tax/discount/GL/VAT/advance/XML/QR/signature/browser parity and complete
worker/custody ownership. Finish provider/role/caller/dead-code/performance and
installed15/16/SDK release gates before separately approved fictional-Company
rehearsal/adoption. No live update or tax-authority request is authorized.

See [INVOICE_CHECK_LOADING.md](INVOICE_CHECK_LOADING.md),
[ROUNDED_TOTAL_ACCESS.md](ROUNDED_TOTAL_ACCESS.md), [STATUS.md](STATUS.md) and
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).
