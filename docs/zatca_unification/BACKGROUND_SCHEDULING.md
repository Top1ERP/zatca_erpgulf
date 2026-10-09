# Company-scoped Sales/POS scheduling — increment 8

Development only: no worker execution against a tenant, live invoice mutation,
configuration write, deployment, restart, or ZATCA request was performed.

## Corrected selection

Previously, any Company's open Background window enabled processing of pending
invoices across all Companies. Only Phase-1 was skipped inside the invoice loop.
POS also ignored its second window whenever the first pair was configured.

`background_worker.py` now provides one worker selection loop for Sales and POS.
Only the saved invoice's own enabled Phase-2 Company, with Background selected
and an open Company window, permits processing. One Company cannot authorize
another Company's send or draft submission. Unknown/blank phase and other
submission modes do not authorize the automatic worker. Explicit manual/batch
submission entry points are not changed.

Both Company window pairs use the pure `scheduling.py` rules:

- Start/end are inclusive; a start later than end crosses midnight.
- Either valid window can authorize the run, including POS's second window.
- Two empty values disable that pair. No configured windows means no permission.
- One missing boundary or an invalid value blocks that Company's run and logs
  the configuration failure. Both windows are validated before granting access;
  a valid first window does not hide an invalid second one.
- Time objects, SQL/Frappe timedeltas within a day, HH:MM:SS strings including
  single-digit hours, and fractional seconds are supported. Midnight is valid
  even as `timedelta(0)`. Negative/day-long durations and timezone-bearing clock
  objects are rejected instead of silently wrapping.

The worker takes one site-local clock and one settings snapshot per Company per
run. Invalid Company configuration is logged once and skipped; subsequent
Companies still run. The public cron and Sales/POS function paths remain stable,
as do the public time-helper imports. Duplicate preliminary discovery queries
were removed.

## Identity, draft, and foreground boundaries

The discovery horizon remains 24 hours by creation time, with docstatus 0/1 and
`Not Submitted` / `503 Service Unavailable`. Each saved invoice is reread, and
its status/docstatus checked before Company/customer loading or mutation. A stale
query cannot authorize a cancelled, accepted, or otherwise nonpending invoice.

Draft auto-submission still requires its own Company's `custom_submit_or_not`
and the existing customer B2C alias resolver. Frappe checkbox integer/string
representations are normalized; canonical false values are not overridden by
alternative fields. After `submit()`, `reload()` reads changes made by on_submit
through another Document instance. Already accepted invoices are not sent again.

The callback retains `bypass_background_check=True`, but only after Company
eligibility has passed. The actual parent adapters use this flag to select live
generation/existing XML rather than the foreground Background preparation path.
Those preparation adapters deliberately continue deferring HTTP; removing their
Background deferral would send during ordinary ERPNext submission.

Sales retains its per-processed-invoice commit; POS retains the scheduler job's
outer commit boundary. Error logging uses named arguments. One invoice failure
does not abort later invoices in either worker. No rollback/savepoint redesign
was introduced: failures may leave earlier hook writes in the transaction, and
some legacy callbacks themselves commit. These remain transaction-level release
gates, not guarantees provided by this selector.

## Verification and remaining limits

168 new site-free tests exercise both public workers, the actual Sales/POS
on_submit branches with stubbed builders, and the bridge from the worker into
those branches. Cases cover Company isolation, disabled/unknown/mismatched
settings, both windows, boundaries/midnight, malformed/missing configuration,
stale accepted/cancelled rows, draft policy/aliases, saved phase precedence,
on_submit acceptance via reload, callback failures, discovery failure, existing
XML reuse, and cron dispatch. No real SQL/HTTP/hook accounting was exercised.

Status rechecks do not provide a distributed lock, reserve an immutable signed
payload, or close the race between concurrent workers. Stable retry UUID/hash/
ICV, atomic counter/PIH coordination, transaction isolation, queue ownership,
creation-horizon policy, and unique-ID/gPOS foreground branch parity still need
separate audited changes and integration tests. This change does not establish
ZATCA acceptance or ERPNext 16 runtime compatibility.
