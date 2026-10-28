# Declared rounded-total controls: ERPNext15/16 and POS

Increment129 — 2026-10-28. Pure staged plan, not installed amount calculation.

## API, scope and sources

`rounded_total_control.RoundedTotalControl(settings, is_consolidated)` consumes
the existing typed `CalculationSettingsObservation` and an explicit Boolean
consolidation declaration. Its known caller is `test_rounded_total_control.py`,
included in the offline manifest. No runtime/service/whitelist/provider is added.
Native controls acquisition and the full amount/GL/VAT/XML parity matrix are
required before integration; an unimported staged component is not dead code.

The old financial/settings profiles and bytes remain unchanged. The old financial
header does NOT capture `is_consolidated`, so omission cannot authorize False.
The supplied flag is fingerprinted but has no native-source provenance here.
The existing header does preserve rounding adjustment, rounded-total field
presence and the invoice disable flag; settings preserve Global Defaults, exact
Currency records and the linked POS Profile.

Installed15 controller helpers are exercised with synthetic documents and mocked
lookups. Its ERPNext HEAD is `572d8530b6258231e31f294474cc1818f693d10b`;
reviewed full-file hashes are:

- accounts_controller.py: `6c0bb7a8d45fd3bc51dc22021182cb3bcb6f3e1673d95dbb7774132d32c1ee29`
- taxes_and_totals.py: `9ee39618ab4407de8b6222dfd531f7ab29ca6a14f7ce159dd12c6a12eb2da4f8`

The [official ERPNext16 controller](https://github.com/frappe/erpnext/blob/ade850bbd6a7412e9994a9637d2c5c713771632a/erpnext/controllers/taxes_and_totals.py)
is pinned at `ade850bbd6a7412e9994a9637d2c5c713771632a`. The offline ERP16 oracle
records full source hashes, original notices and the full GPLv3 license for its
attributed test excerpts. Only two small methods and a merge assignment execute
with synthetic dependencies; the full ERP16 application is not imported/installed.
Two additional Frappe16 helper excerpts use the existing pinned MIT oracle and
retain all previous source/excerpt hashes. Tests never download or execute
unreviewed network sources, connect to a site or issue an authority request.

## Guard order and dependencies

| Priority | Condition | Decision / consumed dependencies |
| --- | --- | --- |
| 1 | Consolidated and existing adjustment is nonzero | Preserve current totals; no disable/fraction/method selection |
| 2 | Rounded-total metadata field absent | No rounded-total work; no disable/fraction/method selection |
| 3 | Disable field exists on invoice | Use its exact normalized Check projection, including zero/NULL |
| 4 | Disable field absent on invoice | Require the declared Global Defaults disable field/projection |
| 5 | Selected disable value truthy | Emit versioned zero/conversion plan below |
| 6 | Rounding enabled; fraction zero/NULL | Whole-unit rounding followed by field precision |
| 7 | Rounding enabled; fraction positive | Currency-fraction step followed by field precision |

Consumed Check values support None, int0/1 and Boolean only. Exact tags remain
distinct; strings/numeric lookalikes are not silently normalized. Missing required
global metadata is unknown, not invented API None. Consolidation requires a proved
numeric adjustment declaration even if a later guard would find no rounded field.
The supported normalized adjustment types are Decimal/int/finite-float/NULL;
amounts are never converted or recalculated.

The selected fraction is from the FINAL INVOICE currency, which may differ from
Company, Global Defaults and POS Profile currency. Preserve the original numeric
tag/Decimal scale; refuse missing metadata, strings, booleans or negative fraction
configuration. Existing scalar bounds already keep accepted Decimal/int values
finite/nonzero when Frappe converts configuration to float. Floats are already
finite binary scalars, including tiny nonzero values. No new numeric range rule,
Decimal amount conversion, tax rounding or currency precision assumption is added.

Both fraction routes still consume the system rounding method: the helper ends
with `flt(value, precision)`; its remainder path also normalizes through flt.
Therefore a nonzero currency fraction cannot authorize ignoring an unknown method.
Reuse the same pure method selector as [CALCULATION_ROUNDING.md](CALCULATION_ROUNDING.md).
The plan does not compute precision or replace the versioned rounding algorithms.

## Versioned disabled behavior

| Version | Direct zero assignments | Requested Company-currency conversion |
| --- | --- | --- |
| 15 | rounded_total, base_rounded_total, rounding_adjustment | None; controller returns |
| 16 | rounded_total, rounding_adjustment | rounding_adjustment and rounded_total |

In inspected15 the early return leaves the prior base_rounding_adjustment alone.
Inspected16 requests conversion of both base values. The returned `zero_fields`
and `base_conversion_fields` record this distinction without performing writes or
calculations. A common selected method does not justify identical base effects.

## POS paths and final-document priority

The inspected15/pinned16 normal Sales/POS backend copy-field lists omit the
disable-rounded-total flag. This is a narrow source claim, not a claim about all
client scripts/defaults/UI actions. The separate [POS merge controller](https://github.com/frappe/erpnext/blob/ade850bbd6a7412e9994a9637d2c5c713771632a/erpnext/accounts/doctype/pos_invoice_merge_log/pos_invoice_merge_log.py)
explicitly copies that flag from the POS Profile to the merged invoice with cint.
Tests execute that assignment separately, then plan from the resulting invoice
field. Changing creation/merge input is different from overriding an already
captured final invoice every time its Profile/global setting differs.

Installed15 POS browser payment/cart code also reads sys_defaults for some total
choices. Browser initialization, merge history, document defaults, rounding math,
payable/advance selection and persisted accounting must be compared separately;
this component does not unify or change those callers.

## Identity, cache and closing gates

The digest binds the independently revalidated settings snapshot, declared version,
explicit consolidation flag, source tags, selected currency/method and branch/
write plan. Parent profile bytes remain untouched. Frozen results protect repr,
refuse pickle and revalidate before `require_disable_cache_match(value)`.
The comparison requires the exact consumed tagged API projection: None, boolFalse
and int0 can select the same branch without proving equal source values. Unused
cache arguments are unexamined and uncertified. No cache is read/populated/repaired.

Remaining gates: normal READ/field permissions, native/physical membership and
effective Check/currency-fraction normalization/cache provenance, extra consolidation
source proof, missing/empty Singleton defaults, row-wise tax controls, complete
amount/FX/GL/VAT/XML/QR/signature and frontend parity, installed15/16/SDK/performance,
then separately approved isolated fictional-Company rehearsal and adoption choice.
This partial plan is not complete source evidence or permission to submit.

See [STATUS.md](STATUS.md) for observed verification and
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md) for the current deployment/send ban.
