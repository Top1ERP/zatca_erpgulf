# Saved child financial READ composition

Increment 123 — 2026-10-28. Explicit uninstalled development operation.

## API and responsibility

`SavedCalculationDefaultsService.capture_child_context(invoice_name, parentfield,
erp_major=..., doctype=...)` acquires saved child links, native financial data and
calculation defaults on the existing single owned transaction. `parentfield` is
limited to the five declared financial table names; an invalid/None name never
falls back to financial-only capture.

The constructor's optional `child_metadata_reader(scope, (child_doctype,))`
must return exactly that type's narrow child-currency metadata. No request
supplies a provider, Meta, connection, language, Company, currency or child name.
The operation uses the SAME administrative actor/site policy, saved READ engine,
quiet v15/v16 permission-signature adapter, acquisition/rollback/close boundary,
message aggregation and final disclosure checks as the other capture operations.

`calculation_child_access.py` contains the saved graph/field guards and protected
result. It owns no SQL connection, cleanup or UI service. Its only acquisition
caller is the existing defaults service. `child_currency_source.py` remains the
shared native link reader and `child_field_currency.py` the pure currency policy.
No second precision formula, provider registration, RPC, hook, button, migration
or installed entry point is introduced.

## Authorize the entire returned financial graph

The financial parent reads multiple child tables, so authorizing only the table
whose own links are requested is insufficient. The new operation therefore:

1. Performs the existing normal saved invoice and Company READ before providers
   or SQL, with the current actor/site/role checks.
2. Selects all present declared financial tables from the saved parent metadata.
   Validates exact Table/options/type binding and ordered child identities.
3. Invokes normal quiet child READ using a parent-bound table permission probe,
   including empty tables. The probe contains the already saved/authorized
   parent and exact parentfield; it creates no document or saved child. The
   framework's child permission engine checks parentfield/permlevel and parent
   permission. It is not a substitute for checking actual saved child rows.
4. Loads each actual saved child through the shared normal READ mechanism and
   compares its identity, parent/type/field, index, nullable revision and own
   currency/Company values with the saved parent's child view. No document
   `ignore_permissions` flag or `check_permission` shortcut grants access.
5. Checks field READ levels for the fixed financial header/child projections and
   the own links retained in the saved graph. Normal document/table READ alone
   does not imply access to every higher-level field. Use the saved parent's
   `Meta.get_permlevel_access("read", user=actor)` as the ordinary field filtering
   mechanism does; preserve the framework's Administrator exception.
6. Pins selected field presence/levels and table/row membership, then calls the
   explicit metadata dependencies. Before opening SQL, require financial and
   narrow link metadata to describe exactly the field/table graph already
   authorized. A provider cannot add a previously unguarded table/field.
7. On the owned handle, acquire native financial/child/default evidence and
   require saved/native membership, order, revision and selected own links to
   agree. Absent own link fields require saved get() == None; their physical
   absence is proven separately by the native reader.
8. Recheck normal READ, graph/field metadata, selected native data, declared
   providers and defaults/cache at the shared callback boundaries. Roll back and
   close the owned handle, then repeat saved graph/ACL checks before disclosure.

The protected result binds every returned financial table's saved row membership,
order and revision, not just the target table. Nullable historical child revisions
remain NULL rather than receiving fabricated dates. Empty optional tables retain
their permission boundary and cannot acquire invented rows. Mandatory invoice
items remain subject to the existing financial contract's nonempty requirement.

Other capture methods keep their existing APIs, providers, result formats and
policies. These added child/field checks apply to this explicit operation; they
are not a claim that all old financial/runtime paths already use this graph.
Promoting the guard to the final common runtime pipeline remains a release gate.

## Result operations and limits

`SavedChildCalculationRead` binds the existing permissioned financial/default
parent, native child evidence and all saved financial tables. `sources` is a
derived target-table view, rechecked on reconstruction. Its methods:

- `resolve_currency(row_name, fieldname)` delegates to the pure direct-child
  policy, without accepting an unpermissioned caller-supplied Company proof.
- `resolve_precision(..., currency_context=...)` delegates to the same existing
  precision policy. Supplied contexts are pure declarations, not automatically
  authorized/captured related Currency/Language/System evidence.
- `require_field_currency_match(..., row_entry=..., parent_entry=...)` compares
  explicit tagged cache slots without reading, filling or clearing any cache.

Own child Company, Currency/Language/System formats and trusted cache-key/slot
providers still need composition on the same service. A child field requiring an
own-Company lookup cannot borrow the invoice Company or use an unpermissioned
Company proof through this wrapper. Saved capture still has no implicit in-memory
`parent_doc.currency` fallback. A matching numeric precision does not prove the
field currency or source identity is correct.

These ephemeral results are protected from ordinary repr/pickle export, not
sandboxed against trusted in-process code. Normal permission metadata/caches and
SQL are not atomically frozen; results may become stale after cleanup. This is
not complete native/ORM/accounting parity, committed source origin, a complete
preparation graph or permission to build/sign/send/retry an invoice.

## Version and display evidence

Tests invoke the actual installed Frappe15 child permission helper and an unchanged
Frappe16 helper excerpt pinned to commit
`e8d41dd0061a32ee781caefe5d0b0d2bb7c15362`, using synthetic parent/meta/ACL dependencies.
The existing MIT-attributed oracle includes `permissions.py` under SHA256
`ae3c1285b87094fef39c27c4a5f73c258da11f955ce45169ca6b4996558f6bd8`.
It checks the v16 computed-table lookup and renamed quiet flag without importing
or claiming a full installed ERP16 runtime.
[Pinned Frappe16 source](https://github.com/frappe/frappe/blob/e8d41dd0061a32ee781caefe5d0b0d2bb7c15362/frappe/permissions.py).

The field-level guard follows the locally inspected Document field-read filtering:
parent permission levels also determine accessible child fields. It checks fixed
selected names rather than silently removing a financial input and calculating
from incomplete data. Installed framework/customization/cache provenance and
both complete ERP runtime rehearsals remain gates.

Nested permission/provider failures remain muted inside the operation. One
existing translated financial summary is displayed; Arabic is used for Arabic
display, while internal codes remain English. No new translation strings or
retained raw error payloads are introduced.

## Verification and safety

Focused evidence and final guarded regression counts are recorded in
[STATUS.md](STATUS.md). Cases cover both quiet ACL signatures, actual15/pinned16
table permission behavior, all returned tables/rows, empty tables, field levels,
saved/native mismatches, metadata graph drift before SQL, late revocation,
callbacks/cleanup, one Arabic summary, protected result reconstruction, native
rollback and preservation of the user's pending ambient work.

All sources are synthetic. Native checks use NEW guard-owned TCP-disabled SQL
fixtures only. No installed app, site/configuration/schema/data, Company,
credential, Bench or worker changes. No authority requests, including Sandbox/
Simulation. No financial amount conversion, quantization, GL/VAT/XML/QR/signing
or onboarding behavior is activated.
See [CHILD_CURRENCY_SOURCE.md](CHILD_CURRENCY_SOURCE.md),
[DIRECT_CHILD_CURRENCY.md](DIRECT_CHILD_CURRENCY.md),
[DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) and
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).
