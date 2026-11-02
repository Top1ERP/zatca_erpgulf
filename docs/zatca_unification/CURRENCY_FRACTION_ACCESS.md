# Permissioned invoice-Currency fraction — increment135, 2026-11-01

## Operation and ownership

`SavedCalculationDefaultsService.capture_currency_fraction_context(invoice_name,
erp_major=15|16, doctype="Sales Invoice"|"POS Invoice")` is an optional, uninstalled
local inspection. It uses the existing owned financial/defaults pipeline, its
message aggregation/translation and cleanup. It does not calculate amounts,
select an active rounded-total policy, register an RPC/provider or contact ZATCA.
There is no new SQL owner, ACL framework, fallback-currency search or UI action.

The server explicitly supplies `fraction_metadata_reader(scope, ("Currency",))`
and `fraction_cache_reader(scope, invoice_currency)`. The first returns exactly
the selected applied Currency metadata. The second returns the already consumed
post-flt `get_value` configuration projection, a finite float. Arbitrary callbacks
are not sandboxed: installing/auditing concrete providers remains a separate gate.
Existing operations do not invoke these optional dependencies.

## Access before acquisition

Reuse `FinancialGraphAccess` to authorize the invoice, Company, all present
financial tables (including empty ones), every returned saved child and selected
fields. Reuse the ordinary related-record READ engine for the exact invoice
Currency and `require_field_read` for its fraction field. All these checks precede
metadata/cache/connection callbacks. Administrator/System Manager and fixed site
defaults remain the existing inspection policy; this is not a cashier endpoint.

Bind the original and freshly loaded invoice's identity/revision, selected full
Link definition, field permission level and actual currency. Require Link to
Currency and equality with the financial metadata/header. Do not substitute POS,
Company or Global currencies. Bind the related Currency identity/revision,
selected full fraction definition and field level on initial and fresh objects.
Do not read its normal document fraction getter: a document default or ORM value
cannot replace the distinct consumed database API projection.

## Native, API and late checks

Reuse `MariaDBCurrencyFractionReader` on the SAME fresh owned handle. Its existing
bounded metadata/record selection preserves native Decimal/float/NULL and exact
revision while deriving only the configuration's precision-free float. Compare
that projection to the server callback exactly, including signed-zero identity.
Invoice financial values are neither converted nor rounded.

Metadata/cache callbacks run before the final native checks of all captured
defaults, Company, financial rows and selected Currency sources. The fraction
extension's `require_unchanged` deliberately calls no trusted metadata/cache
callback after those checks. Recheck normal access and the original/fresh objects
through cleanup; compare the API projection again after close before disclosure.
There is no freshness or atomic cache/SQL guarantee after return. A callback's
new effects after a completed transaction are not a committed-origin proof.

The existing pipeline rolls back a fresh owned connection before acquisition
and at cleanup, closes it, never commits and refuses recognizable ambient handles
without cleaning them. Pending caller work remains caller-owned. Failures use one
existing localized financial summary and static internal English codes. Interrupts
retain priority. No customer, invoice, field or settings write is installed.

## Protected result and callers

`SavedCurrencyFractionContext` reconstructs the saved financial/defaults parent,
native fraction and financial table graph, then binds exactly one normal Currency
access row, native revision and invoice currency. Dropped/rebound sources are
refused. Representation is protected and serialization is refused. This partial
inspection supplies no certificate, issuance, dispatch or acceptance authority.

Callers are the service's explicit capture method and the reviewed local/private
SQL suites `test_calculation_fraction_access` and `_mariadb`. The module is not
installed in a live hook. Native internals and configuration projection remain
documented in [CURRENCY_FRACTION_SOURCE.md](CURRENCY_FRACTION_SOURCE.md).

## Remaining integration

Compose the consumed dependency plan in this same service: first consolidated,
rounded-field and disable guards, then fraction and final rounding-method sources
only when needed. Avoid acquiring unused settings or assembling independent
transactions as one purported snapshot. Planned selection must cover:

| Earlier condition | Additional control dependencies |
| --- | --- |
| Consolidated invoice with an existing effective nonzero adjustment | Preserve the controller's adjustment; no global/fraction/method lookup for this skipped path |
| Rounded-total field absent | No global/fraction/method lookup for this skipped path |
| Invoice disable Check field present | Its getter/API projection wins, including normalized zero; do not fall back to Global Defaults because the value is false |
| Invoice disable Check field absent | Read and prove the Global Defaults single-value projection |
| Effective disable value true | No Currency fraction; v15 returns without method, v16 still needs System method for zero base conversion |
| Effective disable value false | Exact invoice Currency fraction, then final amount-rounding method for BOTH zero and positive fractions |
| Explicit nonempty rounding-method override in a reviewed caller | Reuse the existing override policy and skip unused System method access |

Increment136 implements this selection as a separate optional inspection on the
SAME service; see [ROUNDED_TOTAL_ACCESS.md](ROUNDED_TOTAL_ACCESS.md). Its retained
adjustment getter proves only the controller's zero/nonzero guard against native
evidence, without converting money or claiming amount equality. This standalone
fraction inspection still does not read normal money getters. Full amount/getter/
cache parity and runtime adoption remain gates.

Amount/cache/FX/GL/VAT/advance/XML/QR/
signature/browser parity, concrete provider/role review, caller/dead-code and
performance audits, SDK and installed15/16 evidence remain release gates. Separate
fictional-Company rehearsal approval precedes adoption; authority requests remain
prohibited. See [STATUS.md](STATUS.md), [PLAN.md](PLAN.md) and
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).
