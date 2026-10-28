# Declared rounding-method selection

Increments127/128 — 2026-10-28. Explicit DEV policy/acquisition, not installed amount calculation.

## Purpose and source

`calculation_rounding.RoundingMethodResolution(settings, override=None)` consumes
an existing typed `CalculationSettingsObservation`. It selects the Frappe method
and binds its source/version without changing the parent's bytes or discovering
a setting, currency, invoice, site or cache. The existing three-key calculation
defaults SQL profile stays unchanged: rounding method is a System Settings
dependency, not another assumed `db.get_default` precision key.

The pure policy's known caller is `tests/test_calculation_rounding.py`. Increment128
also shares its private method selector with the native/saved acquisition below;
it does not construct a full calculation observation from incomplete saved data.
All suites are explicitly included in the offline manifest. Runtime activation
remains absent until the provider/provenance and amount parity gates below close.
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

## Optional saved/native operation — increment128

`SavedCalculationDefaultsService.capture_rounding_context(invoice_name,
erp_major=..., doctype=..., rounding_override=None)` composes the SAME saved
invoice/Company READ, metadata/default context and owned rollback/close pipeline.
It returns `SavedRoundingContext`, with selected method/origin and optional
`LockedRoundingSettingRead`. It returns no invoice/child amounts and does not
claim a full calculation-settings/financial/party/tax graph. Declared15/16 and
site defaults only are accepted; other capture APIs keep their return types and
do not acquire rounding dependencies. No public RPC/provider/hook is registered.

Constructor-only server dependencies:

- `rounding_metadata_reader(scope, ("System Settings",))` supplies exactly one
  applied metadata object using `source_metadata.ROUNDING_PROFILE`. Its only
  field is `rounding_method`; existing profile names/catalogs stay unchanged.
- `rounding_cache_reader(scope)` supplies the exact effective API/cache projection
  for the system rounding method. It is an explicit trusted dependency, NOT a
  newly installed or automatically discovered Frappe cache adapter.

Without a nonempty override, require normal System Settings record READ and field
READ before all provider/SQL calls. Pin Select type/options/default and field
permission level. Compare saved value, bounded native value and supplied cache
exactly. Reuse the format reader's existing preflight/CASE/native-text checks and
metadata source reader; its private Singleton selector adds only a fixed allowlist
entry, not arbitrary caller-selected fields/SQL. No alternate transaction, generic
document reader, precision defaults key or ACL/UI engine is added.

The native payload distinguishes a stored NULL/blank row from no selected row.
Absence requires a locked nonempty-Singleton witness that projects only DocType,
never another field's name/value. A wholly empty Singleton is refused because it
can invoke document defaults. Duplicate/case-variant/oversized/unknown setting
values, native type mismatches, inconsistent metadata and cache disagreement do
not become a default method. No normal-row modified stamp is fabricated.

Rounding metadata callbacks run BEFORE the last native checks of ALL captured
sources, so a late callback cannot silently invalidate defaults/invoice/Company
metadata. Recheck rounding native rows/metadata before cleanup, and saved access/
definition and sources through close. Compare the supplied rounding cache at initial capture,
before final source checks and after close, then recheck ordinary source access.
All failures reuse one existing translated display summary; raw internal codes
remain English. Interrupts keep their priority and still release the owned handle.

A valid explicit method skips System Settings READ, field checks, metadata,
cache callbacks and SQL completely. Related native evidence is then absent and
cannot be supplied to the protected result. The old context/default APIs do not
start consulting these new dependencies merely because they are configured.

The caller-owned reader never commits/rolls back/closes or retries parent work;
failures poison that reader. The shared service owns its fresh initial rollback
and final rollback/close and refuses recognizable ambient handles. Its own pending
source changes remain observable until checked and rolled back. These boundaries
are not committed-origin or provider/namespace provenance, an atomic freeze of
SQL/normal documents/caches, or a freshness promise after disclosure.

## Remaining acquisition and integration gates

Installed15 source review also identifies a presence-sensitive next dependency:
`AccountsController.is_rounded_total_disabled` returns the invoice value whenever
its metadata HAS `disable_rounded_total`; only a missing field consults Global
Defaults. Therefore invoice zero/NULL cannot be replaced by a truthy global value.
The existing financial observation already preserves this field and its absence.
Increment129 verifies the pinned ERPNext16 controller and adds a separate pure
control plan for these priorities and the versioned disabled base effects. See
[ROUNDED_TOTAL_CONTROL.md](ROUNDED_TOTAL_CONTROL.md). Native/effective controls and
full controller/installed parity remain separate from Frappe numeric-helper proof.

`taxes_and_totals.set_rounded_total` separately checks consolidated invoices and
rounded-total field presence, then calls currency-fraction rounding. Its row-wise
tax setting comes from `Accounts Settings.round_row_wise_tax`. These inspected15
paths remain amount-integration gates; increment129 records control flow without
adopting amount logic or changing existing callers.

- Actual runtime adapter/factory/cache provenance, whole-empty Singleton/default
  policy, and composition with the remaining financial/settings/party graph.
  The pure observation alone still cannot establish native source or defaults.
- Separate currency fraction rounding, rounded-total disablement and POS controls,
  Accounts Settings row-wise tax policy, cash/payment and linked advance effects.
- Complete native/ORM/ERP15/16 amount, VAT, GL and XML parity. ZATCA fiscal/XML
  formatting is a separate policy and is not derived from an ERP setting here.
- Runtime adoption, performance/SDK evidence, then separately approved isolated
  installed fictional-Company rehearsal before an adoption/cancellation decision.

No whitelist, hook, runtime provider, frontend, installed schema/migration,
Bench/worker or authority operation is added. See [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) and
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md). Verification is recorded in
[STATUS.md](STATUS.md), separating focused, full-regression and installed evidence.
