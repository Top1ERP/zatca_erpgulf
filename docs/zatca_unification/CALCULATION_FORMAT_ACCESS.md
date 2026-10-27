# Permissioned invoice-currency format acquisition

Increment 119 — 2026-10-27. Uninstalled composition in the existing owned service.

Increment120 extends this SAME pipeline with Company-currency evidence and
explicit parent-document child-field precision. The shared result is named
SavedFieldCurrencyRead; SavedInvoiceCurrencyRead is its compatibility alias.
See [FIELD_CURRENCY_ACCESS.md](FIELD_CURRENCY_ACCESS.md) for supported scopes and
remaining direct child-document currency/cache gates.

## Delivered operation and scope

`SavedCalculationDefaultsService.capture_currency_context` adds one explicit v16
operation. It composes native financial/default reads with related Currency,
Language and System Settings READ and the format SQL reader on ONE new owned
transaction. Existing defaults-only, metadata-only and financial-only methods
keep their result types, dependencies, messages and read scope.

`calculation_format_access.py` contains the related projection/policy/result.
The existing service still owns acquisition, rollback/close, exception priority
and one translated display summary. No second ACL/transaction/presentation engine
is introduced. The helper uses the same saved-record mechanism and exact parent
actor/site/role policy; it never calls the connection factory itself.

The current scope is the invoice's own currency, effective `frappe.local.lang`,
declared ERP major 16 and SITE `__default` precision settings. No request supplies
language, currency, arbitrary metadata types or dependency callbacks. The two
new optional constructor dependencies are trusted server functions:

- `format_metadata_reader(scope, types)` returns the exact three format-profile
  metadata declarations, separately from legacy financial metadata.
- `format_cache_reader(scope, language, currency)` returns a typed projection
  from the exact intended framework cache/API sources. Matching does not prove
  that callback's site/API provenance; provider registration remains a gate.

No hook, RPC, button, worker or runtime provider is installed. These remain
administrative staging/diagnostic operations, not a new permission policy for
ordinary production Sales/POS users. Runtime authorization needs separate review.

## Sequence and normal permissions

1. Check the existing saved invoice/Company READ and administrator/System Manager
   policy. Validate v16/site scope, select the current effective language and
   read the saved invoice currency through the same quiet normal READ mechanism.
2. Require ordinary related READ on the exact Currency, Language and System
   Settings documents before format metadata/cache or SQL acquisition. Ignore
   Document ignore-permission flags; preserve inspected v15/v16 ACL signatures.
3. Pin exact related values and ordinary revisions. System Settings has NO
   invented modified timestamp. Recheck effective locale and invoice currency,
   including changes without an invoice modified-time change.
4. Pin format and financial metadata, acquire/clear one fresh owned handle and
   lock the common saved source projections. Load native invoice/children and
   require their currency to match the authorized selected currency BEFORE
   reading its format data.
5. Read formats on that SAME handle; match exact normal saved projections,
   Language/Currency revisions and supplied cache. Read selected site defaults
   and repeat cache/applied metadata checks. No refresh or coercive repair occurs.
6. After callbacks, recheck saved source/default/financial/format SQL, related
   normal access/values/revisions, locale and currency. Pin the result, attempt
   both owned rollback and close, then recheck current visible access/source
   before disclosure. Never commit or retry.

Recognizable ambient handles are still refused without rollback/close of parent
work. A callback's owned edits are rolled back on failure; an independent writer's
committed changes are not claimed to be undone. Source/cache/ACL are not atomic
across all boundaries, and results can become stale after cleanup.

## Protected result and precision consumer

`SavedInvoiceCurrencyRead` independently pins the existing financial result,
ordered related saved projections and locked format result. The selected invoice
currency, related lookup identities, raw values/normalized Check and ordinary
Language/Currency revisions must agree. Direct reconstruction rejects unbound,
corrupt, wrong-order or mismatched parents; Singleton revision must remain None.
Repr is protected and pickle refused. Raw dataclass/property access is not a
permitted UI/log/queue/RPC export or a disclosure sandbox.

`resolve_precision(fieldname)` accepts only root Currency fields whose captured
options explicitly equal `currency`. It uses the existing resolver and captured
format context without new SQL/cache/ORM work. Base-currency/Company options and
child currency inheritance are NOT silently treated as invoice currency; their
own source resolution is still required. Other field types can use the existing
financial result's separately scoped resolver.

This resolves precision only. No Decimal-to-float money conversion, monetary
rounding, amount allocation, GL/VAT/QR/signing/XML generation or sending changes.
No complete preparation fingerprint or issuance/acceptance authority is granted.

## Missing persisted Check in an existing Singleton

The low-level reader's legacy default remains strict. Its new constructor-only
`allow_missing_check=True` supports an absent selected Check ONLY when a bounded
locking query witnesses a NONEMPTY `tabSingles` document. The query returns just
the exact DocType, never an unrelated field name/value. Both length/value passes
check this witness; the empty value query still supplies a native text descriptor.

In the inspected framework, nonempty Singleton storage skips new_doc; numeric
normalization sets an absent Check to zero even if its metadata default is 1.
Tests compare the actual installed v15 helper and the pinned v16 helper excerpt.
The latter is added to the existing MIT-attributed oracle with the same full-file
source hash, not a full v16 import or installed acceptance claim.

The raw absence is retained as `["absent"]`, not invented NULL/blank/`"0"`, with
an explicit nonempty witness in the separate
`currency-format-source-sql/absent-check-v1` payload profile. PRESENT records keep
their original v1 bytes/hash. An explicit zero insertion, removal of all storage
or membership change is detected at a subsequent check even when the effective
flag remains false. Row locks/RC limits remain as documented for the reader.

A wholly empty Singleton is STILL refused: its new_doc/default/bootstrap behavior
can depend on other context. This service never creates or saves that document,
fills a field or tells an operator to change a working setting to satisfy a test.

## Tests, messages and remaining work

Local tests cover Sales/POS, present/missing flags, normal related READ before all
dependencies, stale cache/metadata/source changes, locale/currency/revision drift,
interruptions, exact reconstruction, restricted precision scope, unchanged legacy
operations and ONE Arabic failure display. Internal codes remain English and the
existing financial messages/translations are reused, with nested messages muted
and the parent's state restored.

New guarded native SQL tests cover one-handle acquisition, unset precision using
the format context, owned callback rollback, pending parent work/borrow refusal,
late close-time denial, simultaneous financial/Singleton/default/metadata locks,
RC explicit-zero insertion after absent capture and wholly empty Singleton refusal.
All schemas/metadata/ACL documents are synthetic on new TCP-disabled test servers.

Next complete field-currency/Company/base/child resolution, whole-empty Singleton
hydration policy, other effective settings and native/ORM parity, and finish the
complete linked/permission/transaction source graph before preparation adoption.
Provider/namespace/cache provenance, actual installed v15/v16 behavior, accounting/
XML/SDK/authority acceptance and ordinary runtime authorization remain gates.
No working app/site/config/schema/customer/credential/worker/Bench or authority
operation occurs. Executed totals are in [STATUS.md](STATUS.md). See
[CURRENCY_FORMAT_SOURCE.md](CURRENCY_FORMAT_SOURCE.md), [CALCULATION_PRECISION.md](CALCULATION_PRECISION.md),
[DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) and [SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).
