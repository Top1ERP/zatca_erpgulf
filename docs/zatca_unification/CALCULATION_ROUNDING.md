# Declared rounding-method selection

Increment127 — 2026-10-28. Pure DEV policy, not installed amount calculation.

## Purpose and source

`calculation_rounding.RoundingMethodResolution(settings, override=None)` consumes
an existing typed `CalculationSettingsObservation`. It selects the Frappe method
and binds its source/version without changing the parent's bytes or discovering
a setting, currency, invoice, site or cache. The existing three-key calculation
defaults SQL profile stays unchanged: rounding method is a System Settings
dependency, not another assumed `db.get_default` precision key.

Known caller: `tests/test_calculation_rounding.py`, explicitly included in the
offline manifest. Runtime callers are deliberately absent until the native
System Settings/cache/permission boundary and amount parity gates below close.
The policy belongs beside field precision, not inside QR/XML/signature code.

The inspected control flow comes from installed Frappe15 `utils.data.rounded`
and the [pinned Frappe16 source](https://github.com/frappe/frappe/blob/e8d41dd0061a32ee781caefe5d0b0d2bb7c15362/frappe/utils/data.py).
The complete v16 file matches its previously recorded SHA-256
`b3a005c11cb6a42a92838711b509ecfff568455c54f9923070fc4e1651848284`.
Four exact MIT helper excerpts are added to the existing offline oracle; no
untrusted network source is executed or fetched by tests. Complete ERP16 is not
installed/imported. Tests execute only the reviewed excerpts with synthetic
dependencies, and actual installed15 helpers with mocked settings access.

## Selection and source binding

| Condition | Selected method | Origin | System setting consumed |
| --- | --- | --- | --- |
| Nonempty explicit override | Exact override | EXPLICIT_OVERRIDE | No |
| No override; nonempty setting | Exact setting | SYSTEM_SETTING | Yes |
| No override; absent/NULL/blank declaration | Banker's Rounding (legacy) | LEGACY_DEFAULT | Yes |

Supported method names are exact: `Banker's Rounding`, `Banker's Rounding
(legacy)` and `Commercial Rounding`. Unknown names, whitespace/case rewrites,
oversized/NUL text and malformed consumed Select values are refused with static
English codes. The supported input domain is text/NULL, narrower than Frappe's
primitive truthiness: numeric zero or False in a consumed Select does not silently
become a valid default. A valid override leaves an otherwise unknown/numeric
system value unused, matching the framework's skipped lookup.

The original settings observation is revalidated and independently reconstructed.
Its financial parent determines declared version15/16; callers cannot supply a
separate version. The digest binds the original settings hash, override, selected
method and origin. Original field absence, NULL and blank remain distinct in the
parent and tagged result even when they choose the same method. This is supplied
declaration identity, not saved/committed/permissioned source attestation.

`require_system_cache_match(value)` compares an explicitly supplied API/cache
projection exactly when the system dependency is used. Absent/NULL project to
API None; blank remains blank. A cached legacy method cannot stand in for a raw
blank merely because their selected methods agree. Under an override, the unused
cache argument is neither inspected nor certified. No cache/provider is read,
populated, cleared or repaired. Frozen results are revalidated on comparison,
have protected repr and refuse pickle; trusted code is not sandboxed.

## Selection is separate from amounts

No amount is accepted, converted, rounded or quantized by this component.
Existing native Decimal financial scalars, ERP amounts, tax totals, FX, GL,
settlement/advance allocation and XML/QR/signing paths stay unchanged.

Actual framework tests show why a single replacement rule would be wrong:
at one decimal, 1.25 becomes 1.2 with modern Banker's, 1.3 with legacy Banker's
and 1.3 with Commercial; -1.25 becomes -1.2, -1.2 and -1.3 respectively. Tests
also pin a synthetic IEEE-754 boundary where modern Banker's implementations
differ between15/16 despite the same method name. This is not a permitted-invoice
range assertion. Selecting a method cannot establish identical amount algorithms
or authorize replacing framework behavior with Decimal half-up.

## Remaining acquisition and integration gates

- Native tabSingles membership/values, metadata, ordinary related field READ,
  effective cache provenance and rechecks on the shared owned transaction.
  A missing observation field does not prove missing storage or exclude new-doc
  defaults; whole-empty Singleton policy remains open.
- Separate currency fraction rounding, rounded-total disablement and POS controls,
  Accounts Settings row-wise tax policy, cash/payment and linked advance effects.
- Complete native/ORM/ERP15/16 amount, VAT, GL and XML parity. ZATCA fiscal/XML
  formatting is a separate policy and is not derived from an ERP setting here.
- Runtime adoption, performance/SDK evidence, then separately approved isolated
  installed fictional-Company rehearsal before an adoption/cancellation decision.

No whitelist, hook, provider, frontend, schema/migration, service or authority
operation is added. See [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) and
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md). Verification is recorded in
[STATUS.md](STATUS.md); previous full-suite totals are historical, not a new run.
