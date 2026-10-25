# Explicit invoice tax-template dependency observations

Increment 105 — 2026-10-25. Pure offline development; uninstalled.

## What this adds

The [invoice-owned financial profile](FINANCIAL_SOURCE_OBSERVATION.md) records
template REFERENCES, not their contents. This opt-in component adds the exact
referenced Sales Taxes and Charges Template and Item Tax Template records,
including each ordered taxes child table, schema presence and modified value.

Selection comes from an independently validated/pinned financial observation.
No current document, cache or browser value can add a template after selection.
The caller supplies an exact keyed record set and explicit child metadata.
Missing/extra records, wrong identity/child ownership/schema, duplicate SQL
child identities and wrong Company bindings fail closed with static errors.
A missing template does not permit automatic fallback to invoice fields.

Both invoice and item template dependencies are included, regardless of which
existing XML branch currently uses them; shared item references are deduplicated.
Mixed item-template usage is OBSERVED, not accepted as fiscally valid. Dictionary
input order is irrelevant; child row order remains significant. No selection
precedence, amount calculation, rounding or invoice/template mutation occurs.

## Captured data and bounds

The allowlisted template header records Company, disabled/default flags, tax
category and custom ZATCA category/exemption fields, distinguishing schema
absence from NULL, empty, zero and false. Sales template taxes reuse the existing
invoice tax-column profile. Item template taxes record tax_type and tax_rate.
Child Table options, parent/parenttype/parentfield, idx and identity are checked.
Empty tables still record schema and remain observations, not a tax-validity
grant. Company equality is an explicit conservative LOCAL capture policy, not
a statement of tax-authority requirements.

The component's canonical payload binds profile, invoice-owned financial hash
and sorted exact records. Scalar encodings, streaming JSON bounds and ordered
child capture/validation are shared with the invoice-owned profile, without a
wire or meaning change to that earlier version. Limits are 128 unique
referenced templates, 512 tax rows total and 2 MiB for the additional canonical
payload. The independently retained financial component can itself be up to
2 MiB. No complete-family memory or payload budget is claimed.

The protected result pins an independent financial object and immutable
canonical bytes; no mutable document/meta references are retained. Direct
construction revalidates source and exact dependencies, not only a hash string.
Repr is redacted and pickle refused. Generic dataclass serialization is still
NOT a security sandbox: raw fields may contain sensitive business data and are
not logging/UI/RPC/queue payloads.

## What remains unproven

This is still PARTIAL. Do not use its digest as the complete preparation source
hash or return True as the full custody/recovery evidence guard. It does not
prove committed database state, stable metadata, ordinary ACL, tenant/site
origin, physical-schema compatibility, accounting/tax correctness, credential
epoch, signature or authority acceptance. Supplied records/metadata remain
trusted-server declarations requiring a separate authorized committed reader.

The ERP major comes from the declared financial profile. Synthetic v15/v16
labels do not establish installed-version support. No Frappe, database/file/
clock access, record loading, provider installation, UI, XML generation,
credential resolution, commit or HTTP exists here.

The existing invoice-versus-template tax-source precedence discrepancy remains
explicitly open. This component preserves BOTH values; it does not silently
choose one, rewrite old tests or modify the runtime tax contract. A later
parity-focused change must resolve that discrepancy with financial/XML fixtures.

Next complete party/address/Company/device/POS-profile/time/precision and linked
advance evidence, a versioned full dependency manifest, authorized committed SQL
capture/locking, type normalization, then actual accounting/XML parity and
installed-version rehearsal. None is implied by matching these fingerprints.
No runtime caller or default verifier adopts this partial profile.

## Verification

Synthetic tests cover exact dependency sets, duplicates and input ordering,
every declared header/tax field, changes without invoice/parent timestamps,
membership/order/schema, zero rates with conflicting invoice/template values,
missing/extra/wrong-owner records, corrupt financial/payload reconstruction,
bounds/privacy/no writes and independent pinning.

A read-only comparison against the previously committed invoice profile passed
20 variant/version/DocType comparisons with identical bytes AND fingerprints.
Four immutable fingerprint goldens now protect the original profile during the
shared-child helper refactor. Existing financial tests remain unchanged in
meaning. Executed totals: [STATUS.md](STATUS.md).
Operational restrictions: [SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).
No live/environment or authority request is authorized, including Sandbox.
