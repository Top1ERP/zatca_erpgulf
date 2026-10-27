# Permissioned invoice-owned financial and calculation context

Increment 116 — 2026-10-27. Uninstalled server composition, not XML generation.

## Purpose and callers

`SavedCalculationDefaultsService.capture_financial_context` composes the native
invoice reader with the existing permissioned defaults/metadata acquisition.
It reuses the saved READ/site/actor policy, fresh owned connection, cleanup and
single-message display boundary. This is an explicit internal staging operation;
there is no hook, RPC, frontend, installed provider or issuance caller.
The existing defaults-only `capture` and two-type `capture_context` retain their
results and do not acquire financial rows or extended child metadata.

Saved Sales Invoice and POS Invoice are supported. Status 0/1/2 is recorded,
not interpreted as issuance eligibility. No certificate, phase selector, remote
acceptance label or previous invoice is required to READ this source context.
The explicit `erp_major` must be integer 15 or 16; it declares the observation
profile rather than proving which ERP runtime/schema is installed.

## Shared transaction sequence

1. Check ordinary saved invoice/Company READ and the shared administrative role,
   actor and site boundaries before metadata, cache or SQL acquisition.
2. Ask the trusted applied-metadata callback for Company and the exact invoice
   type. Derive only present child types from that pinned root declaration.
   Ask for the extended exact family and require its original pair unchanged.
   Require the shared financial profile's table options and selected columns.
3. Acquire one fresh owned connection, discard its pre-existing pending work,
   and lock/reconcile the minimal saved source rows. Recognizable ambient handles
   are refused without taking ownership of the parent's pending transaction.
4. Load Company metadata through the existing metadata reader. Load the invoice
   and present children through `MariaDBInvoiceFinancialReader`, including their
   own metadata. Reuse the resulting invoice metadata in the context instead of
   duplicating its initial SQL read.
5. Read the selected defaults and check the explicit cache projection. Recheck
   saved source/defaults, repeat the cache and two-stage metadata callback, then
   recheck all selected source/default/Company metadata and native financial data
   on the SAME handle. Raw child membership/value/revision changes are checked
   even if the invoice's `modified` remains unchanged.
6. Independently pin the protected combined result, attempt owned rollback/close,
   and recheck visible saved source/actor/ACL before returning it. Never commit,
   retry, save an invoice, refresh a cache or change a schema.

Applied-metadata/cache/factory callbacks remain trusted server dependencies.
Their site/namespace/read-mode origin is an adoption gate, not established by a
successful callback or a hash. No request supplies arbitrary metadata types.
Normal permission checks do not use caller ignore-permission flags.

## Protected result and numeric meaning

`SavedCalculationFinancialRead.context` retains the existing PARTIAL defaults
and exact Company/invoice metadata context. `.financial` retains the native SQL
observation, invoice/child metadata, physical projection signatures and child
revisions. Construction revalidates both parents and requires the overlapping
invoice metadata, DocType/name, revision, Company and typed docstatus to match.
Unrelated or corrupt independently supplied parents fail with a static English
internal code. Repr is protected and pickle refused; raw dataclass/property access
is still a trusted-code boundary, not an RPC/log/queue disclosure sandbox.

Native DECIMAL scale remains intact (`8.700000000`, including zero/subcent
values). No Decimal-to-float conversion, quantization, amount allocation or fiscal
policy is introduced. The existing `0E-9` snapshot codec is NOT an XML serializer.
SQL FLOAT/DOUBLE values remain supported by the underlying native reader; this
mode is not a global prohibition on float or a finding that legacy XML is invalid.

The [official XML implementation standard, sections 7.3 and 10](https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/20220624_ZATCA_Electronic_Invoice_XML_Implementation_Standard_vF.pdf)
defines decimal semantic values and rounding, not a Python float requirement.
Amount and unit-price precision differ. Preserve source evidence separately from
future field-specific calculation/formatting; do not apply two-decimal rounding
to every captured scalar or silently redefine existing fingerprints.

## Messages and tests

The shared display wrapper chooses one financial-context permission/failure
summary, suppresses nested producer/cleanup messages and restores parent message
state. English internal codes remain unchanged; the two new summaries have Arabic
catalog entries for display only. No raw driver/source/financial payload is shown
or newly logged. Ordinary defaults and metadata-only operations retain their
existing messages and translations.

Local tests exercise exact dynamic metadata scope, Sales/POS and declared ERP
profiles, all saved statuses/default scopes, late source/ACL drift, callback and
interruption failures, exact cross-parent reconstruction and Arabic presentation.
The new private SQL suite uses a NEW guarded TCP-disabled fixture, synthetic
metadata and ACL documents. It checks actual native amounts/child revisions,
callback changes and RC inserts without parent revision changes, retained locks,
rollback of owned pending edits, unchanged pending parent work, borrowed-handle
refusal, late cleanup failures and old advance references/zero allocations.
It never looks up or settles those historical references.

## Remaining integration gates

This combines selected financial rows and calculation DEFAULTS, not the complete
linked settings graph, effective precision resolver or authoritative preparation
snapshot. Parties/addresses, Company/device/POS policy, Currency/Singleton/tax
templates and authenticated original advance evidence remain separate work.
Caches/permissions are not atomic SQL state; RC can admit a phantom after the
last check, and results can become stale after cleanup. Arbitrary trusted callback
Python is not sandboxed. The combined hashes authorize no later build or send.

Next implement the explicit native/ORM bridge and effective settings acquisition,
then prove amount/XML/GL/VAT parity before preparation/runtime adoption. Installed
ERPNext 15/16, browser, SDK and authority acceptance remain unverified. No working
environment, credential, Bench/worker or authority endpoint changes occur.
See [FINANCIAL_SOURCE_SQL.md](FINANCIAL_SOURCE_SQL.md),
[CALCULATION_CONTEXT.md](CALCULATION_CONTEXT.md), [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md)
and [SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md). Executed totals are in
[STATUS.md](STATUS.md).

Increment 117 adds `resolve_precision` on this protected result. It selects only
captured invoice/child metadata and exact site defaults, with no new SQL/cache
read. See [CALCULATION_PRECISION.md](CALCULATION_PRECISION.md) for pinned v15/v16
differences, explicit v16 locale/currency declarations and remaining acquisition
gates. It does not round amounts, refresh document caches or change old snapshots.
