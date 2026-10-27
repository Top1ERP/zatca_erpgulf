# Company currency and parent-document child-field precision

Increment 120 — 2026-10-27. Uninstalled read/precision composition.

## Delivered behavior

`capture_base_currency_context` is an explicit operation on the SAME
`SavedCalculationDefaultsService` pipeline used for invoice-currency capture.
It selects the invoice's own Company, reads its authorized `default_currency`,
confirms that link and revision on the owned SQL transaction, and captures the
selected currency's format. Invoice currency is preserved separately; it is
never overwritten or substituted for Company currency.

`SavedFieldCurrencyRead` is the shared protected result implementation for both
currency scopes. The increment119 name `SavedInvoiceCurrencyRead` remains a
compatibility alias, not a second class/policy. Existing constructor calls and
invoice-currency operation retain their default behavior. No runtime caller,
hook, button, provider, schema or migration is installed by this increment.

## One source, permission and transaction pipeline

1. Use existing saved invoice/Company READ and the administrative actor/site
   policy. Pin the invoice currency and source Company. For Company scope, read
   its default currency through the same quiet normal saved READ mechanism.
2. Require READ on the exact selected Currency, Language and System Settings
   before callbacks or SQL acquisition. Keep effective locale and saved source
   rechecks from [CALCULATION_FORMAT_ACCESS.md](CALCULATION_FORMAT_ACCESS.md).
3. Acquire one fresh owned transaction and read the native invoice/children.
   Require their Company and invoice currency to match the authorized saved
   selection. Company scope then reads the exact Company currency link using
   the already selected Company metadata before looking up currency formats.
4. Match Company SQL link/revision with the saved Company and read formats,
   defaults and selected caches on that SAME handle. Never choose a signing/
   linked credential Company or use the invoice currency as a missing-link fallback.
5. After callbacks, recheck source/financial/default/format/Company data and
   metadata plus normal READ, locale and saved link guards. Preserve one shared
   rollback/close/display boundary and late disclosure checks. Never commit,
   save a setting, update an invoice or refresh a cache.

Native tests modify the Company currency without its modified timestamp and
confirm rejection. A stale saved Company link is refused before a Currency data
query. Other cases demonstrate rollback of callback edits, surviving Company locks
and preservation of the user's pending parent work.

## Company SQL evidence

`company_currency_source.py` holds a narrow reader and independent protected
`LockedCompanyCurrencyRead`. It requires exact legacy Company metadata with
`default_currency` declared Link -> Currency. It rechecks that metadata on the
same transaction, then reuses the format reader's fixed bounded text projection,
length preflight, SQL CASE masking and native text signature validation.
No duplicate low-level value decoder or customization interpretation is introduced.

The record binds exact Company name, native currency text, real modified value,
physical result signature and selected metadata digest. Reconstruction checks
those fields and derives a normalized revision; blank/NULL/invalid links, wrong
types/options, identity or preflight drift are refused. The reader never takes
cleanup ownership or retries after failure. Errors remain static English codes.

The shared result requires this proof's Company and revision to match its
financial saved-source parent, its metadata to equal the captured Company
metadata, and its currency to equal the selected format lookup. Repr is protected
and pickle refused. Raw object properties remain a trusted-code boundary, not
UI/log/queue/RPC export or independent source/committed-origin attestation.

## Explicit field-currency profiles

Supported definitions are matched by their captured options, never field-name
prefixes or a guessed Company. Invalid, missing or unrelated options are refused.

| Captured currency scope | Accepted Currency field options | Native source |
| --- | --- | --- |
| Invoice | currency | Saved and native invoice currency |
| Company | Company:company:default_currency | Source invoice Company and locked Company default-currency proof |

`resolve_precision(fieldname)` selects a root field. The new explicit
`resolve_precision(fieldname, parentfield="items")` selects the declared child's
metadata while retaining the PARENT document as the currency source. The child
table must be present, with its exact captured Table/options/type binding.
Other captured child tables use the same explicit parentfield mechanism.

This matches `invoice.precision(fieldname, parentfield)` in the inspected framework:
the child's DocField is passed to get_field_precision with the parent document.
It does NOT claim the same behavior as `row.precision(fieldname)` on an independent
child document. Child-local currency/Company fields, missing parent links and
framework parent-cache inheritance need their own source evidence and remain gates.

Local installed ERPNext15 JSON confirms Company default_currency is Link/Currency,
ordinary item amount options are currency, and base_amount/base_grand_total use
the explicit Company option. Tests compare fresh field-currency semantics in
actual installed Frappe15 and the pinned Frappe16 helper, using synthetic sources.
The small get_field_currency excerpt is added to the existing MIT-attributed
oracle under its unchanged pinned full-file hash. No v16 bench is imported/run.

## Existing field-currency cache

The framework can return an existing `frappe.local.field_currency` entry without
reading the changed Company link. Tests reproduce that behavior in both inspected
helpers. `require_field_currency_match(fieldname, cached, parentfield=...)` compares
ONE supplied cached currency with the fresh captured scope using exact string
type/value. It never populates, clears or repairs framework cache entries.

This check is separate from the existing precision-cache comparison: equal numeric
precision alone cannot prove that the cached currency is correct. The callback/
cache API's identity and provenance still need a trusted provider before adoption.

## Limits and next work

No financial Decimal-to-float conversion, amount recalculation, FX lookup,
monetary quantization, GL/VAT/QR/signing/XML or authority request is changed.
ERP precision settings are separate from ZATCA's per-field XML formatting rules.
Existing source/metadata/default/format payloads and their hash formats remain
unchanged; Company-link evidence uses its own versioned payload.

The new operations remain explicit v16/site staging paths, not ordinary production
user authorization. Next complete direct child-document currency/cache semantics,
other effective settings and wholly empty Singleton policy, then native/ORM and
accounting/XML parity with a complete linked/permission/transaction source graph.
Source/provider/cache/namespace provenance, installed ERP15/16, SDK and authority
acceptance remain gates. Read locks and final checks are not a simultaneous cache/
ACL freeze, and observations may become stale after cleanup.

All tests use synthetic sources; native tests use NEW guard-owned TCP-disabled
SQL fixtures. No working application/site/data/config/schema/credential/worker/
Bench or authority operation occurs. Executed totals are in [STATUS.md](STATUS.md).
See [CALCULATION_PRECISION.md](CALCULATION_PRECISION.md),
[DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) and [SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).
