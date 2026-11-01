# Native invoice-currency fraction — increment134, 2026-11-01

## Purpose and staging

`currency_fraction_source.MariaDBCurrencyFractionReader` reads only the final
invoice Currency's smallest_currency_fraction_value on an explicit caller-owned
transaction. `LockedCurrencyFractionRead` binds native configuration/metadata and
its precision-free flt projection to existing native financial evidence. Reuse
the existing financial bounded SQL and metadata readers; do not add another SQL
transport, settings discovery or amount calculator.

Known callers are `tests/test_currency_fraction_source.py`, its `_mariadb` suite
and increment135's `calculation_fraction_access.FractionAcquisition`, all covered
by the offline manifest. The latter composes normal Currency/field READ and
original/fresh/API comparison on the SAME saved service; see
[CURRENCY_FRACTION_ACCESS.md](CURRENCY_FRACTION_ACCESS.md). Trusted concrete API
provenance and consumed-dependency composition remain gates. Integration or
removal is required before runtime adoption. No provider, RPC, hook, frontend,
schema or authority operation is installed.

## Exact source and metadata

Derive the currency from the financial parent's invoice header, requiring its
applied field to be Link to Currency and its value to be a valid nonempty name.
Do not substitute Company, Global Defaults or POS Profile currencies. Bind the
selected Currency name exactly, including case and native modified revision;
other records and fields are not read.

`source_metadata.CURRENCY_FRACTION_PROFILE` selects exactly this one required
Currency field, with applied type Currency. Installed15 and the
[pinned official16 schema](https://github.com/frappe/frappe/blob/e8d41dd0061a32ee781caefe5d0b0d2bb7c15362/frappe/geo/doctype/currency/currency.json)
use this Currency type, with non_negative=1. Preserve all selected metadata
properties and native DocType/DocField/customization evidence. Refuse missing
metadata, unsupported applied types, missing records, case-variant identities,
negative configuration or incompatible native descriptors. No invalid/missing
source is silently replaced by zero or a different currency.

First recheck the existing financial graph on the SAME handle. Reuse its bounded
name/revision/length preflight, CASE-masked value projection, native Decimal/float
descriptors and one-row limit. Repeat metadata and financial/child checks before
returning. Payload/digest bind financial hash, metadata hash and exact Currency
record name/revision/raw scalar/type. Old financial/metadata/settings profiles
and native SQL implementations remain unchanged.

## Raw configuration and effective API projection

Preserve original native Decimal/float/NULL and Decimal scale in the private
payload. Derive a separate finite float CONFIGURATION projection matching
`flt(value)` WITHOUT precision in actual15 and pinned16. This explicit conversion
applies only to the Currency configuration; no invoice amount is cast, rounded,
quantized, recalculated or overwritten.

| Native configuration | Effective fraction | Declared route |
| --- | --- | --- |
| SQL NULL | float0 | Whole unit, then field precision |
| Numeric zero, including signed zero | Corresponding float zero | Whole unit, then field precision |
| Positive native number | Its precision-free float projection | Currency fraction, then field precision |

Reuse `rounded_total_control._fraction_branch` and existing finite scalar bounds;
do not create a second rounding policy. Accepted native numeric bounds keep the
configuration conversion finite. A large valid Decimal can project to a float
outside the raw-float scalar profile's bound; compare this derived projection
directly as an exact finite float rather than rewriting the raw scalar contract.

`require_effective_cache_match(value)` requires the exact supplied post-flt
configuration value and float type, including signed-zero identity. Raw Decimal,
int, text, bool, NaN/Infinity or a different normalized value are not that API
projection. Cache/API provenance is still the caller's responsibility; no cache
is fetched, populated or repaired. Reconstruct and validate the protected parent
before comparison; numeric equality alone must not hide a tampered zero sign.

Both routes still need the system rounding method when the existing helper
normalizes the final AMOUNT with precision. The configuration's precision-free
flt conversion itself does not consult the system method. This component neither
acquires that dependency nor authorizes skipping it for a nonzero fraction.

## Ownership, verification and closing gates

`load_for_update(financial, applied_metadata=...)` and `require_unchanged(read)`
borrow the caller's exact handle, retaining native autocommit-off checks. No
commit/rollback/close/retry or source discovery occurs. Failed reads poison the
reader, raw errors become static English codes and interrupts retain priority.
Pending caller work stays visible and belongs to the caller. Source changes,
including NULL-to-zero without revision changes, require a completion recheck;
locks are not freshness or committed-origin authority after disclosure.

Guarded tests use synthetic actual15/pinned16 helper probes and NEW TCP-disabled
private SQL only. They cover both invoice DocTypes/declared versions and RR/RC,
exact currency selection, Decimal/double/NULL, tiny/large configuration, signed
zero, metadata/descriptor/revision/parent-child drift, masking of oversized data,
pending work preservation and source/metadata/invoice locks until caller cleanup.
Complete installed16 behavior and monetary/GL/XML parity are not claimed.

Increment135 adds normal Currency record/field READ and original/API observations
in the existing owned service. Next select this source only when earlier
consolidated, rounded-field and disable guards require it, then compose the
existing method source without fabricating a full calculation
settings graph. Complete amount/FX/GL/VAT/advance/XML/signature/browser, trusted
provider, installed15/16/SDK/performance and release gates remain before separately
approved fictional-Company rehearsal/adoption.

See [ROUNDED_TOTAL_CONTROL.md](ROUNDED_TOTAL_CONTROL.md),
[INVOICE_ROUNDING_ACCESS.md](INVOICE_ROUNDING_ACCESS.md), [STATUS.md](STATUS.md) and
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).
