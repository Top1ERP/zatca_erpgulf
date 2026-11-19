# Issued fiscal data versus later collection state

Workstream2 source development,2026-11-19. This replaces the initial blanket
post-payment print hold for newly captured native originals. It does not change
any monetary builder, request/XML byte, authority outcome, financial baseline,
site schema, live source or service. No authority request was made.

## Inspected ERP behavior

The local ERP15 `accounts.utils.update_voucher_outstanding` updates the saved
invoice outstanding balance and derived status. Its Payment Entry schedule
updater separately changes five collection columns. Official ERP16 source shows
the same separation: [voucher outstanding](https://github.com/frappe/erpnext/blob/version-16/erpnext/accounts/utils.py),
[Payment Entry schedule updates](https://github.com/frappe/erpnext/blob/version-16/erpnext/accounts/doctype/payment_entry/payment_entry.py).
Both versions' POS merge process updates `consolidated_invoice` and status on
the individual POS invoice: [ERP16 POS merge](https://github.com/frappe/erpnext/blob/version-16/erpnext/accounts/doctype/pos_invoice_merge_log/pos_invoice_merge_log.py).
These source inspections are not installed ERP posting/closing acceptance.

The generation-time `native-invoice-publication/v1` projection therefore omits:

| Exact location | Collection/bookkeeping fields |
| --- | --- |
| Sales/POS header | outstanding_amount, status |
| POS header only | consolidated_invoice |
| Sales Invoice payment_schedule, identified native Payment Schedule rows only | paid_amount, base_paid_amount, discounted_amount, outstanding, base_outstanding |

It preserves header paid/base-paid/change amounts, currency/conversion, totals,
discount basis/amount, taxes, customer/Company, issue clock, docstatus, return/
debit/advance data, unknown custom fields, native v16 tax children, all item/tax/
payment/advance rows, schedule amount/base amount/discount terms/dates/identity/
order. Similarly named fields in other rows/custom dictionaries are not omitted.
Native typed observations preserve Decimal scale, float identity and text. This
is a publication/exact-reuse rule, not a change to financial computation or an
assertion that every external accounting adjustment is tax compliant.

## Immutable capture and compatibility

`NativePreparation.handoff` computes the projection from the same already frozen
source observation used for the original full-source digest. It never rereads a
mutable invoice to invent historical evidence. Partial injected record adapters
cannot claim this native projection and continue without optional evidence.

`stage_issuance` stores optional `publication_ciphertext` in the same INSERT and
transaction as the exact original and chain advancement. Its separate
`publication-source` AEAD domain authenticates the entire existing artifact header;
its plaintext contains only profile/full-source/projection hashes. No source PII,
print document, credentials or raw receipt is duplicated. Source/version/record/
request/site/namespace changes and capsule-domain swaps fail verification.

The original v1 artifact header, AAD, encrypted request contract and request bytes
are unchanged. The optional hidden/read-only Long Text schema field is a source
definition only; no installation or migration occurred. Old NULL evidence keeps
the full original source comparison. No backfill/update method or silent new
profile interpretation exists. Empty/corrupt/unknown evidence stops publication,
not a fallback. Removing evidence cannot grant a collection exception. Diagnostic
original download remains independent of the optional projection.

## Reads, printing and exact dispatch

Current shared source/child reads verify the saved fiscal projection against the
captured evidence. Without evidence, the existing full original digest is used.
The same operation retains a current render-source digest in its nonserializable
view. Supplied print data must match that whole current saved observation, including
the current collection state, and the same custody UUID/ICV/chain. Thus legitimate
saved payment updates are allowed, while a stale/forged browser balance or paid
status is rejected. Metadata and issued-output exceptions remain unchanged.

Prepared/exact retry reservation uses the same protected projection when the full
source changed. It retains the original request bytes/UUID/ICV/hash/PIH and current
credential/permission/route/delivery/fencing checks. It cannot authorize a blind
unknown retry, replace a rejected original, regenerate XML or change acceptance.
Current full-source drift checks still pin each execution before its commit.

### Native dates versus JSON print input

The local Frappe15 print endpoint loads either a saved document or supplied JSON.
Its JSON handler represents date/datetime/time objects as text and timedelta via
`format_timedelta`. The official [Frappe16 response handler](https://github.com/frappe/frappe/blob/version-16/frappe/utils/response.py)
and [time formatter](https://github.com/frappe/frappe/blob/version-16/frappe/utils/data.py)
provide the corresponding wire representation. This is a concrete print-input
compatibility concern, not permission to replace the source's fiscal observation.

The request-local `native-invoice-render/v1` comparison treats only those temporal
representations as equivalent. It does not coerce Decimal/float/int/text money,
round values, translate dates, change a timezone, create a clock or rewrite XML.
Original generation/fiscal hashes stay typed and unchanged. Current balances and
all other print data still match the saved view. Tests invoke the actual local
framework JSON handler for dates, aware/naive datetimes, time and long/fractional
timedelta, exercise the actual hook, and prove numeric representation drift fails.
This remains source-level compatibility, not installed PDF/browser qualification.

## Verification and remaining work

372 local cases across10 suites pass in3.28s.165 cases across5 fixture-owned
private SQL suites pass in22.16s. Fixed81-suite issuer-binding regression passes
20,751 in120.13s. Sets overlap; the complete229 local/65 private manifest was not
run. Logs: `/tmp/zatca-axis2-collection-local-final.log`,
`/tmp/zatca-axis2-collection-private-final.log`,
`/tmp/zatca-axis2-collection-regression-final.log`.

Coverage includes immutable capture/rollback/lost-ack reads; absent legacy
evidence; damaged/copied/wrong-domain/profile/source-bound evidence; native-shaped
SQL source and schedule changes; paid/unpaid transitions and reversal; POS
consolidation reference; exact pending dispatch after collection without a second
generation/ICV; fiscal edits and supplied collection-value forgery. Existing
Simplified/Standard303, owner/device/linked and schema bootstrap suites remain.

Private registration is preseeded, framework loaders are explicit doubles, and
the metadata/signing builder uses synthetic UBL. There is no genuine Payment Entry,
POS closing, installed ERP15/16, print engine, CA or SDK acceptance. Original240
financial comparison remains91 identical/117 review differences/32 blocked.

Workstream2 remains open: actual initial/cutover activation and complete legacy
consumer inventory/drain; four existing-XML paths; unchanged retry/corrected-clock
operator adoption; draft handoff/durable discovery and source lifecycle; frozen
seller/buyer/address/print information and saved File/external print consumers;
whole canonical runtime qualification. Unknown new fields remain conservative
until their semantics and observation profile are explicitly reviewed. Current
master/print provenance and historical evidence migration are not solved merely
by omitting these verified collection fields.
