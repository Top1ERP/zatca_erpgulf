# Native global rounded-total Check — increment130, 2026-10-30

## Purpose and staging

`global_rounding_source.MariaDBGlobalRoundingReader` reads only
`Global Defaults.disable_rounded_total` on an explicit caller-owned transaction.
It produces `LockedGlobalRoundingRead`, retaining raw storage/presence and the
normalized int API projection. It reuses the existing bounded Singleton text SQL
and metadata reader, rather than adding another SQL transport or settings engine.

Known callers are `tests/test_global_rounding_source.py` and its `_mariadb` suite.
Both are in the explicit offline manifest. No runtime service/provider, RPC, hook,
frontend, schema, document defaults or authority operation is installed. This
stage is retained for composition into the SAME saved calculation acquisition
service, after the invoice/consolidation/fraction and normal-access gates close.
It must not become an independent submission or automatic repair path.

## API-specific absence and normalization

The actual installed15 `Database.get_single_value` and the
[pinned Frappe16 method](https://github.com/frappe/frappe/blob/e8d41dd0061a32ee781caefe5d0b0d2bb7c15362/frappe/database/database.py)
read a selected Singles value and cast its Check field. A missing selected row
becomes int0 even when the entire Singleton is empty; this method never invokes
`new_doc` or applies the metadata field default. This differs from loading a
whole Singleton document. Do not reuse the system-document rounding reader's
nonempty witness rule for this different API.

| Selected raw storage | stored | API projection |
| --- | --- | --- |
| Missing row | false | int0 |
| Stored SQL NULL | true | int0 |
| Stored empty string | true | int0 |
| Stored text 0 | true | int0 |
| Stored text 1 | true | int1 |

These source identities remain distinct in the payload/digest. Only canonical
Check storage above is accepted; Frappe's broader cint/sbool coercions do not
authorize silently repairing malformed configuration. Bool, text and float cache
lookalikes are not the exact int API projection. The actual15 method and reviewed
16 excerpt are exercised with synthetic queries, including genuine local cache
hits and stale cache disagreement. No installed ERP16 runtime is claimed.

The existing MIT test oracle adds only the exact `get_single_value`, `cast` and
`sbool` excerpts; all earlier excerpts, full-file hashes and license remain.
The pinned database file SHA-256 is
`dc9fe0620ab7ceb300bee2b5da5c247d8979727139c785bb591e0a54e3bebf15`.

## Native evidence and comparisons

`source_metadata.GLOBAL_ROUNDING_PROFILE` selects only this Check definition.
Legacy metadata/financial/default profiles retain their catalogs and bytes.
Require the applied Check definition and matching native DocType/DocField/custom
field/Property Setter evidence. Metadata defaults remain bound evidence, without
becoming the selected value. Missing metadata is refused, not treated as int0.

The shared private selector permits the exact Global Defaults/field pair only.
Preflight byte lengths, CASE masking, native text descriptors, exact identities,
duplicate refusal and LIMIT2 use its existing transport. No other Singleton field
name/value or nonempty witness is projected. No fictitious modified timestamp is
attached. Existing format/System/Company selectors keep their prior behavior.

`require_cache_match(value)` revalidates the result and compares a supplied int0/1
exactly, without fetching, populating or refreshing a cache.
`require_control_match(RoundedTotalControl)` also revalidates the declared plan
and requires its CONSUMED global origin and exact normalized int tag. Invoice,
preserve-consolidated and absent-rounded-field branches refuse unused global
evidence. Raw NULL and boolFalse declarations cannot stand in for normalized int0.
This is one dependency comparison, not proof of the rest of a supplied graph.

`load_for_update(applied_metadata=...)` and `require_unchanged(read)` use the SAME
borrowed autocommit-off handle, checking metadata and presence/value changes.
They never commit/rollback/close/retry. Read/recheck errors poison the reader; interrupts retain
priority. Own pending work remains visible and belongs to the caller. In READ
COMMITTED, equal-effective-value phantom insertions still require the completion
recheck; locks are not a promise that sources cannot change after disclosure.

## Integration and removal gate

Before runtime use, compose normal invoice/Global Defaults record and field READ,
definition/permission-level pinning, API/cache/provider provenance and cleanup
rechecks in the existing owned service. Select Global Defaults only if the
invoice's disable field is absent, respecting the earlier consolidation and
rounded-field guards. Do not add a second acquisition/ACL/UI service or synthesize
a complete settings observation from this partial result.

Native consolidation and invoice Check normalization, Currency fraction capture,
row-wise tax controls, complete amount/FX/GL/VAT/XML/QR/signature parity, installed
15/16/SDK/performance and release evidence remain separate gates. See
[ROUNDED_TOTAL_CONTROL.md](ROUNDED_TOTAL_CONTROL.md), [PLAN.md](PLAN.md),
[STATUS.md](STATUS.md) and [SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).
