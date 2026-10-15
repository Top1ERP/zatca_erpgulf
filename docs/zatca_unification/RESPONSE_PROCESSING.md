# Primary post-response error boundary — increment 45

## Bounded change in development

The four primary Sales/POS Reporting/Clearance functions now distinguish the
legacy response-processing branch from generic pre-response/rejection failure
handling. Immediately after mock/real `requests.post` returns, they mark the
existing branch set before formatting, realtime hiding, logging, PIH work or
artifact/metadata handling. This is an error-write guard, NOT response validation:

- Sales Reporting/Clearance and POS Reporting: existing 200/202/409 paths.
- POS Clearance: existing 200/202 paths; its legacy 409 rejection is unchanged.

If a previously caught ValueError, TypeError, KeyError or Frappe ValidationError
occurs while processing that response, generic error handling no longer fetches/
saves the invoice, overwrites its response with `Error: ...`, writes status 503,
or commits a failure classification. Reporting's inner wrapper rethrows to that
outer boundary instead of interpolating local exception contents.

After leaving the exception handler, the function raises the shared
`LocalResponseProcessingError` with a static Arabic/English review message. The
original exception is not chained into that signal. It retains no response body,
invoice identity, credentials, path, original exception or acceptance flag in its
instance attributes. It is deliberately a RuntimeError, not a legacy
ValueError/ValidationError: existing narrow generator handlers must not swallow
it or reclassify it as an authority rejection. It is not a success-shaped return.
No retry, response/QR repair, notification modal, new endpoint or transaction
operation is performed by this error signal.

Unchanged normal success and explicit HTTP rejection handling remains covered
by the existing route/owner/identity suites, including their inconsistent 409
behavior. Transport timeouts still propagate without this response marker. Other
previously unhandled exception types, including RuntimeError, retain their old
propagation behavior; this increment does not promise redaction of every possible
framework/database exception.

## What this does NOT guarantee

[Increment 46](PRIMARY_RECEIPT_PERSISTENCE.md) subsequently adds an internal local
exact-retained-receipt persistence/redelivery primitive. It is not wired to these
APIs or a scheduler; runtime durable receipt/retry limitations below remain.

HTTP status alone is NOT acceptance evidence, a validated invoice or authentic
receipt. No new success verdict is introduced. Existing business branches still
need adoption of the endpoint-bound response assessment and exact identity/epoch/
XML/crypto checks. Their current 200/202/409/PIH behavior is not certified here.

This guard prevents generic failure writes AFTER a local error; it cannot undo
previous independent commits or guarantee a receipt was stored before the error.
Sales Reporting still attaches XML/QR before its final invoice response save.
An early formatting/logging/PIH error can happen before the response is persisted.
Clearance still independently commits response, UUID and status before returned
XML/image processing; those legacy commits can also commit unrelated parent work.
This increment adds no commit/rollback and does not manufacture a replacement
receipt when SQL fails. Pending document objects must still be discarded/reloaded
by their transaction owner. It is not an atomic whole-invoice transaction fix.

The review text explicitly says acceptance and durable receipt storage are NOT
confirmed and requests review before further submission. No in-call retry occurs.
There is not yet a durable review hold preventing a later scheduler/queue/manual
retry. Lost-response/timeout recovery, exact-attempt durable receipts/outbox,
replay coordination and full parent failure integration remain blocking gates.
Nor does this protect all other existing-XML/generated/batch adapters, physical
File lifecycle, source/permission races, or historic artifact recovery.

No advance search/allocation/remaining/age/settlement, discount/GL/VAT arithmetic,
Compliance/Debug controls, credential/endpoint configuration or schema changes.

## Offline evidence

143 new local cases execute the actual four adapters with mocked HTTP/ERP/File:
all four formerly caught error types at log/PIH/final-log stages, image/File/XML/
JSON/invoice-save/realtime failures, 200/202 and the three legacy 409 branch sets,
static/unchained Arabic review and unchanged uncaught RuntimeError propagation.
At each injected fault, snapshots record the current values and counts of all
invoice/DB/error-handler calls: no extra generic failure read/write/commit is
allowed after the fault. Each case confirms exactly one mocked HTTP call, not
authority acceptance. No credentials/response/local exception appear in the
review text or its attributes. Traceback frame/local lifetime is not a protected
receipt store or a general-purpose secret container.

The first local run exposed an unmocked translation lookup; the offline guard
blocked Frappe cache/logger access. A fixture-only follow-up incorrectly tried
to patch a nonexistent `frappe` attribute on the minimal signal module. The
fixture now patches only its `_` translator; the guard and runtime code were not
weakened and no site was initialized to make tests pass.

24 new cases in the existing private SQL suite use owned temporary InnoDB tables,
actual separate-reader transactions and mocked HTTP/ERP/File. Sixteen early-error
cases show existing receipt/status/UUID are untouched and pending parent work
stays parent-controlled under commit/rollback. Eight late-clearance JSON/QR-error
cases deliberately reproduce the three legacy commits, then prove no fourth
failure commit/receipt overwrite/503 downgrade occurs. The latter demonstrate
the remaining premature-parent-commit defect, not a claim it has been fixed.

The final guarded selection passed **5,801 local + 375 private SQL = 6,176 cases
in 51.87 seconds**, across the same twelve private SQL suites. See
[STATUS.md](STATUS.md) for the cumulative evidence. No installed
source/config/schema/assets/workers/customer data or authority request changed.
Complete offline development before separately approved NEW isolated fictional-
client v15/v16 benches, followed by the whole-change adoption/cancellation choice.
