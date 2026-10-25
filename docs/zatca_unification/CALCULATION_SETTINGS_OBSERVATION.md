# POS, currency and global calculation-setting observations

Increment 108 — 2026-10-25. Pure PARTIAL declarations, not a calculation engine.

Increment 109 adds explicit applied-field/base-field metadata adaptation, including
the raw Meta/default-field distinction. It does NOT resolve defaults or prove
Property Setter provenance; see [SOURCE_METADATA.md](SOURCE_METADATA.md).

## Delivered dependency boundary

The component pins an independent issuing-settings/financial parent and requires
an exact supplied record graph:

- System Settings and Global Defaults as explicit Singleton identities.
- Currency records referenced by invoice, source Company, Global Defaults and
  optional POS Profile; equal references are deduplicated.
- The POS Profile explicitly referenced by the invoice, when present.
- The Sales Taxes and Charges Template referenced by that profile, separately
  from any template referenced directly by the invoice.

A missing POS-profile template does not authorize substituting the invoice
template. Wrong Company/template/child ownership, missing/extra records or
metadata, unknown types and malformed canonical structures fail closed.
No record discovery, Frappe, SQL, defaults/cache lookup, clock, FX lookup,
normalization, rounding, document writes or HTTP occurs.

## Data captured, not interpreted

System Settings records timezone, country, date/time/number formats, float/
currency precision and rounding method. Global Defaults records Company/
currency/country/rounded-total declarations. Currency records name/enabled,
fraction/units/smallest circulating fraction and display format/symbol flags.

POS Profile records Company, disabled/currency/country/customer/address/cost
center, tax template/category, discount/rounding/price-change/partial-payment/
pricing controls and write-off/income/expense/change-account references.
Its ordered POS Payment Method rows record mode, default flag and return
allowance. The profile's referenced tax-template header and ordered taxes reuse
the existing tax observation contract.

All raw typed NULL/blank/zero/scale/schema distinctions remain. Invoice time,
amounts, selected currency and conversion rate are not rewritten when settings
change. An invalid/missing POS Profile, disabled Currency or unfamiliar timezone
can remain an OBSERVATION, not permission to submit or proof of fiscal validity.
No implicit profile/currency/tax fallback or effective precision is selected.

## Singleton storage is different

System Settings and Global Defaults are represented by name equal to DocType
and an explicit Singleton marker. The capture checks metadata storage kind and
NEVER asks these documents for modified/creation. The payload refuses a
fabricated normal-row revision. Ordinary Currency/Profile/Template records
retain their explicit modified values.

Read-only local v15 source inspection confirms Singleton metadata and the
database Singles-reader boundary. A future committed reader must address
tabSingles field membership/values/locking and schema separately, not query a
fictional tabSystem Settings or assume a normal parent revision. No such SQL
reader or installed schema change is provided by this increment.

## Bounds and shared code

Limits: eight exact records (two Singletons, up to four currencies, Profile and
Template), 128 POS payment rows, 512 template tax rows and 2 MiB for the new
streamed canonical payload. Parent components have separate bounds; this is
not a whole-family/peak-memory guarantee. Explicit child metadata is required
only for present Profile/Template records, including empty tables.

Template capture/validation helpers are shared with tax_dependency_observation;
no second VAT source selector or altered invoice-tax profile is introduced.
A read-only comparison against committed source verifies identical old bytes
AND fingerprints across 20 variant/version/DocType cases. Four fixed old-tax
fingerprint goldens now protect that contract during helper refactors.

Protected results retain independent parent objects and canonical bytes,
redact repr and refuse pickle. Raw data may contain sensitive business/PII
values. Generic dataclass serialization is not a security sandbox; no UI/RPC/
queue/log export or secret/credential-field discovery is provided.

## Important remaining gates

This is NOT effective precision, timezone validation or the full source hash.
Local v15 get_field_precision uses effective field precision and defaults;
rounding paths also differ between framework helpers, Decimal and existing
Sales/POS/XML code. Therefore raw Singleton/Currency values alone cannot prove
calculation parity.

Still required: effective DocField/Custom Field/Property Setter metadata,
default scope and cache provenance, Site/User timezone context where relevant,
physical v15/v16 normalization, linked advance evidence, authorized committed
capture and complete actual amounts/XML/GL/VAT/QR/signature parity. Other Profile
references (party/address/accounts/payment modes) are pointers here, not proof
of their referenced records or active branch use.

No runtime controller/provider/UI/schema is installed or replaced. Do not use
this PARTIAL digest as PreparationContext.source_snapshot_sha256 or return True
as the complete custody/recovery evidence guard. Declared v15/v16 fixtures are
not installed compatibility or SDK/authority acceptance.

Tests cover each setting/row value, singleton storage without fake revisions,
zero/blank/schema distinctions, all four currencies, differing invoice/profile
templates, ordered payments, strict Company/identity/child binding, malformed
payloads/bounds/privacy and unchanged invoice time/amounts under timezone changes.
See [STATUS.md](STATUS.md), [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) and
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md). No working environment or
authority requests, including Sandbox/Simulation, are authorized.
