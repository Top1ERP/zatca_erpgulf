# Saved-source access to local primary receipt persistence — increment 47

Increment 48 adds an optional [explicit Unix connection provider](PRIMARY_RECEIPT_PROVIDER.md)
and synthetic composition tests. It is not installed and does not establish
historical source/receipt provenance or durable retained-input custody.

## Internal service, NOT installed or activated

`SavedPrimaryReceiptService` is a protected server-to-server boundary around the
increment 46 local persistence primitive. It has no whitelist, button, hook,
queue integration, active provider registration, transport or clock dependency.
No primary request adapter/scheduler calls it. Raw retained objects are NOT
browser JSON, an export format, or input to be rebuilt from operator fields.

The existing archive inspection engine now exposes its saved-row/binding/recheck
policy internally. Advance and QR inspection retain their read-only invoice
permission and accepted-status rules. The receipt service uses a private policy
adapter requiring invoice WRITE and related-row READ, without copying the owner/
route/revision logic or granting mutation to the inspection APIs. Source/row
contracts and quiet v15/v16 permission-signature compatibility are shared.

## Access and exact declaration binding

1. Require the configured site and a current non-Guest System Manager or
   Administrator before parsing protected input, source reads or provider use.
2. Rebuild/validate the retained receipt and namespace; reject a supplied target
   that differs from its exact saved invoice identity before ORM filtering.
3. Reload the submitted Sales/POS invoice, Company, own device/linked Company
   through direct quiet permission checks. Invoice WRITE is a permission gate
   for local journal persistence, NOT an invoice write or accounting operation.
   `ignore_permissions` flags and document permission shortcuts do not bypass it.
4. Require the existing Company/Tax-ID/owner/route/environment/UUID/ICV/issuing-unit
   binding and exact non-secret source revisions. No private key/certificate/auth
   field is projected or loaded. The device certificate-owner selection flag is
   non-secret and remains part of that owner policy.
5. A fixed server lookup supplies `PrimaryReceiptBinding`: context/epoch declaration,
   UUID/ICV, exact predecessor journal hash, attempt ID and response-event metadata
   SHA-256. The event metadata includes ID, sequence, time, HTTP status, request ID
   and raw-response hash/length. This binds the retained response as well as its
   attempt; the lookup is not passed that receipt to simply echo its declarations.
6. Recheck ACL/source before acquisition, before/after owned SQL locks and after
   close. The same owned transaction locks exact bounded saved-row projections
   before journal load/append and again before commit. No source/ACL lock spans
   an authority request because no request exists in this component.

Unlike QR/advance archive inspection, receipt storage does NOT require the current
invoice label to be REPORTED/CLEARED: storing a reply may precede that label or
record a rejection/unknown local outcome. Status is still captured/rechecked in
the source projection, never promoted to acceptance proof. Invoice identity and
submitted-state requirements remain. No legacy advance age/lookup/allocation/
remaining/settlement, totals, discounts or GL/VAT rule is changed.

## Resource ownership and outcomes

The connection factory is an explicit server dependency. Recognizable ambient
Frappe/raw handles are rejected without commit/rollback/close. A newly declared
OWNED handle is validated and initially rolled back to discard pending provider
observations; acquisition failures clean only that owned handle, preserving
interruption priority. The increment 46 primitive then owns commit/cleanup.
Ambient Frappe transactions are never committed, rolled back or saved here.

Storage/source-guard uncertainty retains the exact original input with the
unconfirmed/no-replay result. Final permission/source checks can refuse result
disclosure even AFTER an owned commit; that commit cannot be undone. Therefore
the caller must retain its original protected receipt on error, revocation or
interruption. Static Arabic/English denied/failed messages do not chain raw
SQL/provider/source exceptions. No diagnostic result grants dispatch or replay.

## Explicit limits before adoption

Current role/ACL/source locks and a server lookup declaration do not authenticate
the historical source snapshot, epoch, response, site/database/namespace origin
or protected receipt custody. Provider provenance/owned-handle origin still
require an audit; recognizable-handle rejection is not universal wrapper detection.
Ambient permission checks are repeated, not atomically locked permission tables.
Current routing/owner drift fails closed; separate historical access policy is
needed instead of fallback to today's credentials or another attempt.

This is an internal operator-context access boundary, not automatic background
dispatch authorization or a durable retry hold. No scheduler/manual retry hold,
start reservation, transport capture/spool, authentic receipt validation or raw
export is enabled. Runtime legacy partial commits and missing early durable
receipts remain until reviewed exact-attempt integration. Physical File behavior,
actual installed v15/v16 lifecycle/browser/SDK/authority acceptance remain gates.

## Offline evidence

The extraction-only run passed all **5,883 existing local cases in 27.43 seconds**.
The first access matrix passed **6,049 local cases in 30.04 seconds**. Existing
advance/QR source-selection/access assertions were not relaxed or replaced.

188 new local cases cover v15/v16-shaped quiet ACL engines, Sales/POS, standard/
simplified/late observations, owner variants, environments, WRITE versus related
READ denial, actor/site/revision/lookup/event/epoch drift, before-provider target
validation, non-accepted status observations, borrowed handles, storage uncertainty,
post-close revocation, interrupts, Arabic messages and protected input/output.
A first combined run failed two newly added secret-read tests because their
substring rule classified the legitimate certificate-owner selection flag as
secret. Only that non-secret field was exempted; credential reads remain forbidden.

54 cases are added to the EXISTING QR source private SQL suite: exact source and
journal locks with one owned append, stale ambient versus actual SQL source
changes, WRITE/related-READ denial before acquisition, revocation after append
versus after close, and borrowed-parent pending-work preservation. Mocked ACL/ERP
and generated certificates/sources are synthetic; SQL is owned temporary InnoDB
only. No tenant/site/customer or physical File/authority request is exercised.

The final guarded run passed **6,071 local + 470 private SQL = 6,541 cases in
54.22 seconds**, across the same twelve private SQL suites. See
[STATUS.md](STATUS.md) for cumulative evidence. Complete development before
separately approved NEW isolated fictional-client v15/v16 rehearsals and the
whole-change adoption/cancellation decision. No working application/config/schema/
assets/workers/customer data or authority request changed.
