# Native invoice rounding controls — increment132, 2026-11-01

## Purpose, callers and staging

`invoice_rounding_source.MariaDBInvoiceRoundingReader` reads optional invoice
controls on an explicit caller-owned transaction. `LockedInvoiceRoundingRead`
binds them to an existing `LockedInvoiceFinancialRead`, matching selected native
metadata, physical columns and the original invoice revision. It reuses the
financial reader's bounded SQL projection; no second generic SQL reader, amount
calculator, settings resolver or transaction/cleanup engine is introduced.

Current callers are `tests/test_invoice_rounding_source.py` and its `_mariadb`
suite, both in the reviewed offline manifest. Retain this stage for composition
into the SAME saved calculation service with ordinary selected-field READ and
normal document/API observations. Integration or removal is required before
runtime promotion; it is not evidence of a completed source graph or an installed
invoice hook, RPC, provider, XML/QR/signing or submission path.

## Selected definitions and native binding

`source_metadata.INVOICE_ROUNDING_PROFILE` selects exactly four optional fields
for Sales Invoice and POS Invoice. Existing profile names/catalogs/bytes stay
unchanged; notably, is_consolidated is not silently added to financial/v1.

| Field | Supported applied type | Native evidence / interpretation |
| --- | --- | --- |
| is_consolidated | Check | Raw absent/NULL/int0/int1, plus separate normalized getter |
| rounding_adjustment | Currency | Original native Decimal/float/NULL or proved absence |
| rounded_total | Currency | Original native Decimal/float/NULL or proved absence |
| disable_rounded_total | Check | Raw absent/NULL/int0/int1, plus separate normalized getter |

Other applied types and noncanonical Check storage are refused until a separate
compatibility policy proves their meaning. No strings, bools, float lookalikes,
int2 or negative Check values are silently repaired. Currency amounts are never
cast, rounded, quantized or compared to a recalculated amount.

First recheck the financial snapshot on the SAME handle, acquiring table metadata
locks before inspecting physical membership. A fixed four-column information-
schema projection must match the applied metadata exactly, including canonical
column names. Missing/orphan/case-variant columns fail; do not infer false from
the old snapshot's omission. Other column names and values are not discovered.

Reuse the financial reader's identity/length preflight, CASE masking, native type
signatures and one-row bound. Match before/full reads and repeat the column
inspection. Recheck selected metadata and the original financial graph, including
its children. Bind metadata hashes, financial hash, original modified timestamp,
column membership, raw tags and native descriptors into the protected payload.

The three fields overlapping financial/v1 must have the SAME applied definitions,
raw tagged values AND native descriptors as that parent. The additional
is_consolidated column has its own selected evidence. The original financial and
metadata profiles are retained byte-for-byte, without synthesizing a full
normalized invoice or changing original Decimal scale.

## Raw values versus normalized Check getters

`normalized_checks` carries only the two selected Check getter projections;
`consolidated` is their derived Boolean consolidation flag. The raw fields remain
in the private payload and the old financial parent stays unchanged.

| Proved native condition | Raw source tag | Supplied saved-document getter expected |
| --- | --- | --- |
| Field and column absent | absent | None |
| Present SQL NULL | null | int0 |
| Present int0 | int0 | int0 |
| Present int1 | int1 | int1 |

Only proved absence or a normalized zero yields consolidated=False; the old
financial snapshot alone cannot establish this. Absence/NULL/int0 keep different
source identities even when the effective consolidation is false.

`require_check_cache_match(mapping)` revalidates the protected result and requires
EXACTLY those two getter keys and exact primitive types. It does not fetch/warm/
repair a document or cache. An absent field's unexpected in-memory attribute is
not a saved getter proof; boolFalse and float0 are not the normalized int0.
This compares supplied Check observations only, not amount/ORM equivalence or
provider origin. Actual installed15 and pinned16 numeric-fix helpers are tested
with synthetic documents; the complete ERP16 runtime is not installed/imported.

## Ownership, drift and remaining composition

`load_for_update(financial, applied_metadata=...)` and `require_unchanged(read)`
never commit, roll back, close, retry or discover a site/connection. Autocommit-off
and existing financial-reader checks remain mandatory. Native/metadata/schema/
revision/child drift poisons this reader; driver errors use static English codes
and interrupts keep priority. Caller pending work remains visible and belongs to
the caller. Locks last until caller cleanup and are not a promise of freshness
after disclosure. Cache comparison does not grant committed-origin authority.

Private-SQL tests use NEW guard-owned TCP-disabled databases only. They cover
both invoice DocTypes/declared15/16 and RR/RC, optional memberships, Check NULL/
zero/one and noncanonical values, physical/schema conflicts, bounded oversized
values, pending edits without modified changes, parent-work preservation and
value/metadata locks through caller rollback. No tenant data or tax-authority
request is used.

Next require ordinary invoice/table/field READ and bind initial authorized normal
document getters, metadata and permission levels in the existing owned service.
Then choose consumed dependencies in controller guard order: consolidation and
existing adjustment, rounded-field presence, invoice Check presence, conditional
Global Defaults, then actual invoice Currency fraction and method. Keep cache,
provider and all-source rechecks through cleanup; do not attach an unconsumed
global source or claim that raw financial scalars are a complete ERP projection.

Complete amount/FX/GL/VAT/XML/signature/browser parity, provider provenance,
row-wise tax settings, installed15/16/SDK/performance and release evidence remain
before a separately approved fictional-Company rehearsal/adoption decision.
See [GLOBAL_ROUNDING_SOURCE.md](GLOBAL_ROUNDING_SOURCE.md),
[ROUNDED_TOTAL_CONTROL.md](ROUNDED_TOTAL_CONTROL.md), [STATUS.md](STATUS.md) and
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).
