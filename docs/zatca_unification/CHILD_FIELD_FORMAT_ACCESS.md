# Saved child field, own Company and versioned format context

Increment 124 — 2026-10-28. Explicit uninstalled DEV acquisition operation.

## API and shared pipeline

`SavedCalculationDefaultsService.capture_child_field_context(invoice_name,
parentfield, row_name, fieldname, erp_major=..., doctype=...)` selects one field
of an already saved and authorized financial child row. Providers remain trusted
constructor dependencies. No caller supplies a Company, currency, format context,
lookup proof, handle or provider. A missing/foreign row or unselected field fails
before provider callbacks/SQL; it cannot fall back to another invoice or row.

`calculation_child_format_access.py` contains the selection/Company guards and
protected result. The existing child acquisition still authorizes every returned
financial table/row/field; the existing defaults service still owns its one SQL
transaction, rollback/close and one translated display summary. `FormatAcquisition`
adds an explicit child selection scope, retaining its invoice/Company behavior.
There is no second transaction, metadata reader, precision formula or cleanup/UI
pipeline. No provider, whitelist, hook, button or runtime caller is installed.

## Source selection and acquisition order

1. Use the existing saved invoice/Company administrative READ policy and full
   financial table/row/field guard. Select the exact requested saved row/field.
2. Require Currency field type and one of the reviewed options. Pin type/options/
   precision with tagged scalar declarations so textual/numeric precision values
   cannot silently become equivalent. Pin the saved invoice currency separately.
3. For `currency`, select the nonempty own row currency or the saved invoice
   currency. For `Company:company:default_currency`, require the own row Company
   link, normal saved Company READ, exact Link -> Currency default field and its
   field READ level. Pin its real revision and default-currency value. Never
   substitute the invoice/credential Company or an in-memory parent_doc.
4. Under version16, authorize the exact selected Currency, effective Language and
   System Settings plus their selected format field READ levels. Pin locale,
   normalized Check value and related record revisions using the shared format
   policy. Under version15, do not acquire those unused format dependencies.
5. Only after ALL related permissions are checked, call format/child/financial
   metadata providers. Child metadata acquisition is explicitly deferred for this
   operation; old capture operations keep their existing constructor behavior.
   Before SQL, require financial/narrow/selected field metadata to agree with
   the authorized graph and pinned definition.
6. On the same fresh owned handle, capture native financial/child evidence. If
   selected, use the existing Company currency reader with the captured Company
   DocType metadata; require exact own Company identity, currency and revision.
   Match fresh native child-field resolution before reading selected formats.
7. Capture defaults and, for version16, existing format source/cache projections.
   Recheck providers, native sources, related READ/field levels, locale and saved
   selection through cleanup before protected disclosure. Never refresh caches,
   write settings or query another currency on a mismatch.

The Company DocType metadata is shared across Company records. The selected
Company RECORD may differ from the invoice Company; its separate saved/native
identity/revision/value proof must agree. No linked signing-owner policy is used.

## Versioned precision and protected result

The operation accepts only site-scoped defaults (`__default`), matching the
existing field-precision policy. User/global default scopes are refused before
providers/SQL instead of returning an unusable precision result or changing
framework precedence.

`SavedChildFieldRead` binds the existing saved child/financial/default result,
exact row/field, optional saved/native own Company and optional related format
evidence. It rejects missing/rebound evidence, unexpected Company proofs for
plain-currency fields, incorrect format currency and non-site defaults. Its
protected representation and pickle refusal do not sandbox trusted process code.

`resolve_currency()` delegates to the existing native/pure child policy.
`resolve_precision()` delegates to the same shared versioned precision resolver:

- Version15 uses its captured site defaults/number-format rules with no
  CurrencyFormatContext, related format metadata/cache or locale SQL queries.
- Version16 uses the selected captured Currency/Language/System context. A
  disabled currency override preserves the resolved currency while using locale
  precision. A different child currency cannot reuse its parent's currency format.

`require_field_currency_match(row_entry=..., parent_entry=...)` compares explicit
tagged field-cache slots. `require_cached_precision_match(value)` separately
compares numeric precision. Equal digits cannot establish the correct currency.
Neither method reads/fills/clears a framework cache. Actual field/precision cache
provider identity/sampling and runtime adoption remain later integration gates.

## Refusals and remaining work

This operation deliberately requires a fresh resolved currency. An own-Company
option without its own Company link is unresolved; it does not guess a parent
Company or trust a previously inherited cache. The lower-level child context and
pure policy remain available for configured precision that does not consume a
resolved currency. An authorized locale-only acquisition for unresolved currency
is not added here and must not query Currency(None).

Normal permission metadata, caches and SQL are not atomically frozen. Provider/
cache/namespace/installed-schema provenance, source staleness after cleanup,
whole-empty Singleton policy and complete native/ORM/accounting/XML parity remain
gates. The new field scopes are not automatically applied to old runtime paths.
Complete installed v15/v16, SDK, performance and release/rollback evidence is still
required before a separately approved isolated fictional-Company rehearsal.

No amount recalculation, Decimal-to-float conversion, quantization, FX, GL/VAT,
XML/QR/signature or onboarding behavior changes. ERP precision acquisition is
separate from ZATCA's individual monetary/XML formatting rules.

## Verification and safety

Focused guarded runs passed **116 local + 42 native SQL = 158 new cases**.
The local suite's first 98 cases passed in 71.00s; eight additional fallback/
metadata/cache cases in 8.75s and ten scope/disabled-format cases in 4.90s. The native
suite passed 42 cases in 59.00s. Full guarded regression totals are in [STATUS.md](STATUS.md).
Coverage includes Sales/POS, declared versions15/16, different row/invoice/Company
currencies, own Company isolation, empty own currency fallback, normal document/
field READ before all callbacks/SQL, metadata disagreement, locale and access
drift through close, native no-timestamp changes/rollback, reconstruction and
independent currency-versus-precision cache checks.

Tests use synthetic sources and NEW guard-owned TCP-disabled private MariaDB only.
No installed application, site/configuration/schema/data, Company, credential,
Bench or worker changes. No authority request occurs, including Sandbox/Simulation.
See [CHILD_CALCULATION_ACCESS.md](CHILD_CALCULATION_ACCESS.md),
[FIELD_CURRENCY_ACCESS.md](FIELD_CURRENCY_ACCESS.md),
[DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) and
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).
