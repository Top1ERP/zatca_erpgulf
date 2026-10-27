# Locked locale, Currency and Singleton format sources

Increment 118 — 2026-10-27. Uninstalled caller-owned dependency reader.

## Purpose and explicit scope

`currency_format_source.MariaDBCurrencyFormatReader` reads the inputs required by
the v16 currency-format fallback in [CALCULATION_PRECISION.md](CALCULATION_PRECISION.md).
The caller authorizes an exact non-autocommit connection and supplies the effective
nonempty language, an optional ALREADY RESOLVED field currency and exact applied
format metadata. There is no language/actor/Company/currency/options discovery.

Selected values are `Language.number_format`, optionally `Currency.number_format`,
and `System Settings.use_number_format_from_currency` in `tabSingles`. Ordinary
Language/Currency rows retain their real modified timestamps. Singleton values
never acquire an invented document revision or fictional `tabSystem Settings`.

`LockedCurrencyFormatRead.context` is an independently reconstructed
`CurrencyFormatContext`, directly consumable by `FieldPrecisionResolution` or
the protected financial result's explicit `resolve_precision` method. Tests are
the current callers. No provider, normal saved-ACL acquisition, RPC, UI, hook,
worker or XML generator is installed or switched by this increment.

## Separate additive metadata profile

The existing `source-applied-field-metadata/v1` catalog, canonical payloads and
hash domain are unchanged. A separately named
`source-precision-format-metadata/v1` profile selects exactly:

| DocType | Selected field | Accepted applied type |
| --- | --- | --- |
| System Settings | use_number_format_from_currency | Check |
| Language | number_format | Data or Select |
| Currency | number_format | Data or Select |

The same `SourceMetadata`, property definitions, customization matcher and
selected metadata SQL reader handle BOTH profiles. No second Custom Field or
Property Setter interpretation is introduced. Profile identity is explicit,
pinned and checked during reconciliation; different profiles cannot be mixed
just because a DocType/field overlaps. Default projection remains legacy v1.
The old global SOURCE_FIELDS catalog is not expanded with Language or the flag.

The new profile reuses exact standard/custom/setter membership, type/virtual/
Password preflight, SQL default/value masking and raw rechecks. A custom field
or setter can only affect the selected profile's own fields. The result binds
the applied profile through its applied metadata digest as well as raw rows.
Existing SQL observation formats are preserved.

Read-only comparison against committed **8b504a8** matched legacy bytes AND
fingerprints across **44 cases** (all 22 legacy types, empty/full declarations).
Six fixed baseline hashes protect Sales Invoice/System Settings/Currency.
The existing tests exercise the broader old profile contracts too.

## Bounded data read and recheck

1. Pin the exact requested metadata family and require the new format profile,
   selected field presence and compatible types before data reads.
2. Require non-autocommit, then load/reconcile selected metadata on that same
   handle in fixed Currency/Language/System order (Currency absent if unselected).
3. Lock one exact source through an identity/revision/length preflight, then
   repeat with value projection. At most two rows are returned to detect a
   duplicate; missing/duplicate/collation-variant identities are refused.
4. Limit each native text value to **4,096 UTF-8 bytes**. The second query uses
   SQL CASE masking, so an oversized value introduced after preflight is not
   returned before drift rejection. Preserve NULL versus blank and exact text.
5. Bind each value's reported native text signature, including for NULL. Reject
   binary/nontext/lossy decoders and incompatible physical families. A changed
   NULL column from text to integer is detected in native SQL tests.
6. Recheck metadata before returning the independently pinned result. Explicit
   `require_unchanged` repeats all metadata/data reads on the SAME transaction.
   Errors poison the reader; interruptions propagate, without cleanup or retry.

The result's canonical payload is bounded to 64 KiB. Each selected metadata
component has its existing separate bounds; this is not a whole-graph/peak-memory
or execution-deadline guarantee. CASE descriptors are observations, not full
DDL/index/charset/provisioning attestation.

## Persisted Check and optional currency semantics

The increment118 default supports only a PRESENT selected Singleton row. Persisted NULL, blank
and `"0"` resolve to false, while `"1"` resolves to true; all raw distinctions
remain in the fingerprint. Other text is refused, without pretending it is valid
configuration merely because a permissive cint could produce zero.

Increment119 adds an explicit opt-in for witnessed NONEMPTY Singleton storage
with an absent Check. Raw absence has a separate payload profile; legacy present
bytes and strict defaults remain. See [CALCULATION_FORMAT_ACCESS.md](CALCULATION_FORMAT_ACCESS.md).

Unwitnessed absence is not synthesized as zero: framework Singleton loading can use new_doc
defaults when storage is empty. Existing nonempty Singleton/missing-Check and
full empty-Singleton/default hydration remain distinct. The former now has the
explicit bridge; the latter remains refused. This internal supported-subset boundary neither
imposes a ZATCA requirement nor asks an operator to change a working setting.

No Currency identity means no Currency metadata/data query. An enabled format
override still requires an explicit currency, as in the pure context contract.
When a currency IS explicitly supplied, its exact row/format is captured even
if the flag is false. This is declared dependency capture, not proof that every
selected record is consulted by each upstream branch.

## Cache comparison and transaction ownership

`require_context_match` compares an explicitly supplied typed cache/API projection
with the native context. It does not fetch, normalize, refresh, log or repair a
cache. Matching requires exact language/currency/value/normalized-Check agreement;
the caller still proves those lookup identities and their site/actor/API origin.

No commit, rollback, close, session-setting change or source write occurs in the
reader. Own pending values remain visible; unrelated parent work is neither
saved nor discarded. Existing row locks survive until explicit caller cleanup.
Native tests also demonstrate RC duplicate insertion detected by a subsequent
check; a later phantom remains possible after the last boundary.

Private result repr is protected and pickle refused. Generic dataclass/raw
property access is not a disclosure sandbox or UI/log/queue/RPC export. Static
internal errors are English; existing app-owned aggregate/display translation
remains the future permissioned caller's responsibility. No new UI message or
translation catalog is needed for this uninstalled dependency reader.

## Source inspection and remaining gates

Public schemas at pinned Frappe commit
`e8d41dd0061a32ee781caefe5d0b0d2bb7c15362` confirm the System flag is Check with
default 0 and Language/Currency number_format are Select fields:
[System Settings](https://github.com/frappe/frappe/blob/e8d41dd0061a32ee781caefe5d0b0d2bb7c15362/frappe/core/doctype/system_settings/system_settings.json),
[Language](https://github.com/frappe/frappe/blob/e8d41dd0061a32ee781caefe5d0b0d2bb7c15362/frappe/core/doctype/language/language.json),
[Currency](https://github.com/frappe/frappe/blob/e8d41dd0061a32ee781caefe5d0b0d2bb7c15362/frappe/geo/doctype/currency/currency.json).
Those public reads contacted GitHub only. Tests use synthetic schema/metadata on
a NEW guard-owned TCP-disabled server, not an installed tenant or v16 runtime.

Increment119 composes ordinary related READ, effective actor/language and invoice
currency with this reader in the existing owned service. Other field-currency
resolution and broader source adoption remain gates. Next complete
field-currency resolution and selected cache provenance. Preserve legacy v1
settings bytes. Complete native/ORM/Singleton normalization and linked graph
locking before preparation/runtime adoption. No complete source/committed-origin,
historical epoch, accounting/XML/SDK or remote acceptance is claimed.

Executed totals are in [STATUS.md](STATUS.md). No working app/site/data/config/
schema, credential, Bench/worker or authority endpoint is changed. See
[SOURCE_METADATA.md](SOURCE_METADATA.md), [METADATA_SOURCE.md](METADATA_SOURCE.md),
[DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) and [SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).
