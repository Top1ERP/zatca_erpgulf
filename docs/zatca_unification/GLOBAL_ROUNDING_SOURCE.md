# Native global rounded-total Check — increments130/131, 2026-11-01

## Purpose and staging

`global_rounding_source.MariaDBGlobalRoundingReader` reads only
`Global Defaults.disable_rounded_total` on an explicit caller-owned transaction.
It produces `LockedGlobalRoundingRead`, retaining raw storage/presence and the
normalized int API projection. It reuses the existing bounded Singleton text SQL
and metadata reader, rather than adding another SQL transport or settings engine.

Known callers are `calculation_global_rounding_access.GlobalRoundingAcquisition`
and `tests/test_global_rounding_source.py` with its `_mariadb` suite. Increment131
composes this dependency into the SAME saved calculation service as an explicit
inspection operation, with separate local/private-SQL access suites. All suites
are in the fixed offline manifest. No runtime provider, RPC, hook, frontend,
schema, document defaults or authority operation is installed. This stage must
not become an independent submission or automatic repair path.

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
They never commit/rollback/close/retry. Read/recheck errors poison the reader;
interrupts retain priority. Own pending work remains visible and belongs to the caller. In READ
COMMITTED, equal-effective-value phantom insertions still require the completion
recheck; locks are not a promise that sources cannot change after disclosure.

## Shared permissioned inspection — increment131

`SavedCalculationDefaultsService.capture_global_rounding_context(invoice_name,
erp_major=..., doctype=...)` returns `SavedGlobalRoundingContext`. This is an
explicit inspection of the global setting in an authorized saved invoice/Company
context. It does NOT select that global setting as the active invoice source,
return a disabled/rounding branch, construct a complete calculation observation,
or compute amounts. Declared versions15/16 and site defaults only are supported.

Server-only constructor dependencies are
`global_rounding_metadata_reader(scope, ("Global Defaults",))` and
`global_rounding_cache_reader(scope)`. The former supplies exactly one narrow
metadata object; the latter supplies the exact int get_single_value projection.
Neither adapter is automatically installed or discovered. Existing capture APIs
do not consult these dependencies merely because they are configured.

The common service requires its existing actor/role, invoice and Company READ,
then normal Global Defaults record READ and field-level READ BEFORE any metadata,
cache or connection callback. Bind Check type/options/default and permission
level, and recheck them through cleanup. GlobalRoundingAccessRow carries ONLY
Singleton identity: no fake modified stamp or document-default value. The normal
document getter is never used to inspect this field's value. This is intentional:
an empty stored Singleton can have a normal in-memory document default of1 while
the verified single-value API result is0. Requiring those two views to agree would
reject valid storage or substitute the wrong API.

`_SingletonSettingAcquisition` shares ordinary ACL, definition/provider checks,
bounded native reader composition, cache sampling and final rechecks with the
existing System rounding-method acquisition. Concrete internal classes fix the
field, profile, reader, source projection and cache comparison. No caller-selected
settings map, second ACL/SQL transaction/cleanup/UI engine or default fallback is
added. The existing method override still skips its unused System dependency.

| Concrete dependency | Normal saved-value comparison | Supplied cache/API comparison |
| --- | --- | --- |
| System rounding Select | Exact document Select value equals native text/NULL | Exact consumed text/NULL |
| Global rounded-total Check | Identity/field access only; no document-default substitution | Exact native-derived int0/1 from get_single_value |

Use ONE fresh owned connection, initial rollback and final rollback/close in the
parent service. Finish metadata/cache callbacks before the last native checks of
ALL acquired sources. Check native values/presence/metadata, saved source revisions
and access; compare API cache at capture, before final source checks and after
close, then recheck ordinary source access. Failures reuse the existing single
translated display summary, with static English internal codes. Interrupts keep
priority and parent messages remain intact. No persistent log/source writes occur.

The native tests cover same-handle pending edits and rollback, ambient handle
rejection/pending work preservation, wholly empty Singles, equal-effective RC
phantoms, late cross-source callback edits and access loss through real cleanup.
These checks are not an atomic freeze of SQL/documents/caches or proof of provider
origin; trusted callbacks can have effects outside the reader's knowledge.

## Active invoice composition and removal gate

### Standard schema evidence for the next selection step

Inspected installed15 at `572d8530b6258231e31f294474cc1818f693d10b` and official
16 schema JSON at `ade850bbd6a7412e9994a9637d2c5c713771632a` agree on these four
selected definitions, without implying that their whole schemas are identical:

| Standard DocType | is_consolidated | disable_rounded_total | rounded_total / rounding_adjustment |
| --- | --- | --- | --- |
| Sales Invoice | Check present | Check present | Currency present |
| POS Invoice | Absent | Absent | Currency present |

A Sales Invoice using is_pos still has the Sales Invoice schema. A separate POS
Invoice therefore needs a different presence-aware path, not an is_pos-based
override of the final Sales Invoice Check. Applied site Custom Fields/Property
Setters can change the effective definitions: these upstream baselines do not
prove a tenant's current Meta, physical columns or original document values.
Do not infer is_consolidated=False from the old financial snapshot's omission.

| JSON source | Full-file SHA-256 |
| --- | --- |
| Installed15 sales_invoice.json | `5bc7467cc031f98df8476579ada32e50764ccbeadb0c6d0147146dbfa748355d` |
| Installed15 pos_invoice.json | `fbc29b6d3f6acf3a6b38e3d4a406ae6b3ec30860a48174f04903fe3630b6ac2c` |
| [Pinned16 sales_invoice.json](https://github.com/frappe/erpnext/blob/ade850bbd6a7412e9994a9637d2c5c713771632a/erpnext/accounts/doctype/sales_invoice/sales_invoice.json) | `e4071fb4132dc9d09141fd497c8faea1ff6e9dbf871aa09e6c662a6b61e7dff7` |
| [Pinned16 pos_invoice.json](https://github.com/frappe/erpnext/blob/ade850bbd6a7412e9994a9637d2c5c713771632a/erpnext/accounts/doctype/pos_invoice/pos_invoice.json) | `29230bc0ee4863b870b7990936228ab24732ee90dea7777e7d3c7c5a745034e6` |

These files were parsed as data only, not imported, installed or turned into a
runtime schema assumption. They add no test/application dependency or copied
unused source file to the repository.

Normal selected-field READ and owned cleanup composition are now implemented for
this explicit inspection. Runtime provider/cache provenance remains open. Active
invoice selection must still prove consolidation, rounded-field presence and the
invoice Check before selecting Global Defaults ONLY when that invoice field is
absent. Do not call the new inspection unconditionally from ordinary invoice
issuance or claim that it resolves the invoice's disable policy.

Next compose native invoice controls, with their optional physical column
membership, narrow metadata and overlap checks against existing financial
evidence. Preserve old financial profile bytes instead of silently adding the
missing is_consolidated declaration. Prove normalized Check values separately
from raw native values, including NULL, and bind the actual invoice currency's
fraction plus existing method acquisition. Keep those operations in the current
owned service and authorize only consumed related dependencies before providers.

Native consolidation and invoice Check normalization, Currency fraction capture,
row-wise tax controls, complete amount/FX/GL/VAT/XML/QR/signature parity, installed
15/16/SDK/performance and release evidence remain separate gates. See
[ROUNDED_TOTAL_CONTROL.md](ROUNDED_TOTAL_CONTROL.md), [PLAN.md](PLAN.md),
[STATUS.md](STATUS.md) and [SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).

Increment132 supplies the native invoice-control side of this gate, preserving
optional physical membership and raw financial overlap while separately deriving
normalized Check getters. See [INVOICE_ROUNDING_SOURCE.md](INVOICE_ROUNDING_SOURCE.md).
Normal selected-field READ, original getter/cache provenance and consumed-source
selection still require composition into the existing owned service.
