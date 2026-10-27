# Explicit field precision across Frappe 15 and 16

Increment 117 — 2026-10-27. Pure resolution; no accounting or XML rounding change.

## Delivered and known callers

`calculation_precision.FieldPrecisionResolution` resolves one selected field's
fresh `doc.precision` meaning from independently pinned applied metadata and
calculation defaults. `SavedCalculationFinancialRead.resolve_precision` selects
only its already captured invoice/child metadata and site defaults, then calls
this component without another SQL/ORM/cache lookup. It revalidates the protected
financial/context parents first. Company/unrelated types are not substituted.
These remain explicit internal operations, with tests as their current callers;
no runtime generator, hook, button, worker or provider is switched.

This is a precision setting, not an amount, rounding algorithm or XML formatting
rule. Raw Decimal values and existing financial/metadata/default snapshot bytes
stay unchanged. Do not round every money/price/rate field to this result or use
this component to certify GL/VAT/ZATCA compliance.

## Inspected source, not guessed version labels

- Local installed Frappe **15.103.0**, source commit
  `7b430f5eec8c0537f2f0cde9d30e175ae9068647`. Tests invoke its actual
  `get_field_precision`, `BaseDocument.precision`, number-format map and
  `Database.get_default` with synthetic dependencies only.
- Public Frappe `version-16` commit resolved on 2026-10-27:
  **`e8d41dd0061a32ee781caefe5d0b0d2bb7c15362`**. Five files were downloaded
  into an owned /tmp directory for read-only inspection. Exact helper excerpts,
  full-file SHA256 hashes, commit identity and MIT license are retained in
  `tests/frappe16_precision_oracle.json` for offline reproduction.
- Tests execute ONLY those small excerpts with synthetic DB/settings/locale/
  currency dependencies. Dependency imports are replaced by injected functions;
  control flow is preserved. The dataclass decorator for the extracted
  `NumberFormat` class is restored. No complete v16 module/runtime is imported:
  its Document file includes Python syntax newer than the current Python 3.10.

Primary sources:
[v16 field precision](https://github.com/frappe/frappe/blob/e8d41dd0061a32ee781caefe5d0b0d2bb7c15362/frappe/model/meta.py),
[v16 configured precision](https://github.com/frappe/frappe/blob/e8d41dd0061a32ee781caefe5d0b0d2bb7c15362/frappe/utils/data.py),
[v16 locale lookup](https://github.com/frappe/frappe/blob/e8d41dd0061a32ee781caefe5d0b0d2bb7c15362/frappe/locale.py),
[v16 format map](https://github.com/frappe/frappe/blob/e8d41dd0061a32ee781caefe5d0b0d2bb7c15362/frappe/utils/number_format.py),
[v16 document cache](https://github.com/frappe/frappe/blob/e8d41dd0061a32ee781caefe5d0b0d2bb7c15362/frappe/model/document.py).
Another patch/revision needs revalidation; helper-level evidence is not installed
ERPNext 16 or end-to-end accounting acceptance.

## Priority and significant differences

The selected field must belong to the existing explicit source metadata profile.
An absent selected field returns None. Non-Currency/Float/Percent fields also
return None, matching the document precision entry point rather than calling
`get_field_precision` indiscriminately for every field type.

| Trigger | Inspected Frappe 15 | Inspected Frappe 16 |
| --- | --- | --- |
| Truthy field precision, including string `"0"` | Field precision converted with cint | Same |
| Numeric field precision `0` or blank | Continue to defaults | Same |
| Float/Percent without truthy explicit precision | Site float precision or fallback 3 | Same |
| Currency default string `"0"` | Fallback to site number format | Keep precision 0 |
| Currency default nonnumeric nonempty text | cint zero, then site format | Keep cint result 0 |
| Currency default missing/NULL/blank | Site number format, default two | Effective locale format, optional Currency format override |
| Unknown selected number-format spelling | Framework fallback two | Refuse unknown format |

The int/float parsing fallback applies to small primitive precision SETTINGS
only, never invoice money. Typed metadata distinctions such as integer 0 versus
string `"0"` are preserved. Supported results are integers 0..64 or None; negative/
oversized precision and unsupported source types fail with static errors rather
than being clamped. This is an explicit supported subset, not an endorsement of
malformed settings or every permissive framework conversion.

The resolver accepts only `__default` rows, because the inspected helper calls
`db.get_default` with that implicit scope. It does not select merged user/global
defaults. It reuses the existing row fold and matches the DB API's first-truthy
list rule; ambiguous false-first lists are refused instead of guessed/coerced.

## Version 16 explicit currency/locale declarations

The v16 fallback requires a `CurrencyFormatContext` with the effective nonempty
language, supplied Language number-format value, normalized boolean system
`use_number_format_from_currency`, already resolved field currency and supplied
Currency number-format value. NULL and blank are retained. An enabled Currency
override requires an explicit currency; the component never performs a nameless
Currency lookup or resolves `df.options`/parent/Company links speculatively.

Locale selection is Language format, then site default, then `#,###.##`.
An enabled nonempty Currency format overrides the resulting locale format.
The locale format is validated FIRST, as in the inspected upstream code; a valid
Currency override cannot hide an invalid locale format. Explicit field/default
precision does not need a locale fallback context. V15 refuses a v16 context.

This context is a trusted SERVER declaration, not a request/user override or proof
of committed/cache/API origin. Its fields and the selected raw defaults/metadata
are pinned into a separate versioned fingerprint; equal precision does not erase
dependency differences. It is protected in repr and refuses pickle. Generic raw
property access is still not a disclosure sandbox or permitted log/RPC payload.

## Existing document cache

Both inspected versions cache `doc.precision` on the document by parentfield/main
and fieldname. A settings change does not refresh an existing cached value.
`require_cached_match` compares ONE explicitly supplied cached result with fresh
resolution using exact type/value. It refuses bool/float/string substitutes,
stale values and corrupted resolution objects. It never reads, fills or clears
the framework cache. Tests demonstrate an actual cached 2 remains 2 after the
supplied defaults change to 4 and that the mismatch is detected.

## Remaining gates

No Singleton, Language, Currency, field-currency or timezone reader is added by
increment117 itself. Increment118 supplies an explicit caller-owned reader and
separate format metadata profile; see [CURRENCY_FORMAT_SOURCE.md](CURRENCY_FORMAT_SOURCE.md).
The existing calculation-settings v1 profile does not capture the new v16 system
flag or Language record. Compose the new explicit reader with permissioned acquisition before
claiming a complete v16 settings graph; do not silently change old profile bytes.
Provider/cache/normal-ACL/source provenance and late drift must be bound to that
acquisition. Precise document currency resolution, native/ORM parity, rounding
method selection, actual GL/VAT/XML fixtures and installed v15/v16 remain gates.

Executed evidence is in [STATUS.md](STATUS.md). No site, live source, service,
schema, credential or authority request is changed. See
[CALCULATION_FINANCIAL_ACCESS.md](CALCULATION_FINANCIAL_ACCESS.md),
[DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) and [SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).
