# Post-response error boundaries — increments 45, 57, 58 and 65

## Existing-XML presentation/logging boundary — increment 65 (2026-10-22)

The four existing-XML Reporting APIs now reuse the same received-step guard after
HTTP returns. This extends protection to existing signed XML, not a new sender,
receipt coordinator, CSID flow or signature/QR generator.

| Existing-XML entry point | Preserved presentation |
| --- | --- |
| `submit_xml_qr_notmultiple.reporting_api_xml_sales_invoice_simplified` | Existing Sales formatter |
| `sales_invoice_with_xmlqr.reporting_api_xml_sales_invoice` | Existing Sales formatter |
| `submit_poswithqr_notmultiple.reporting_api_xml_sales_invoice_simplified` | Original raw POS text |
| `pos_submit_with_xml_qr.reporting_api_machine` | Original raw POS text |

Each API binds `run_received_response_step` only AFTER its existing POST returns.
The existing hide notification, both event-log branches and every presentation
text read are guarded. Sales keeps its formatter through `received_response_message`;
the new tiny `received_response_text` adapter preserves raw POS text, without new
formatting, JSON extraction, response caching or status classification. Deferred
text-decoding errors therefore occur inside the selected presentation guard.

The four public XML wrappers previously caught all ordinary exceptions; the
simplified Sales wrapper also saved a new `Failed: ...` response and committed.
They now re-raise ONLY `LocalResponseProcessingError` unchanged before that broad
handler, so the static translated review reaches the caller without additional
generic error reads/writes/commits. Other exception handling is unchanged.
The wrapper itself does not acquire a sender, repair/reseal an artifact or retry.

Normal 200/202/409 branches, log labels, legacy duplicate behavior, intentional
remote rejection throws, UUID resets and existing save/db_set/commit order remain
unchanged. The two simplified adapters still have their existing UUID db_set with
commit=True on the characterized rejection branches; the two machine adapters
use ordinary assignments. These legacy effects are characterized, not endorsed.
Existing endpoint/auth/owner selection, file bytes/base64 payload, signing/ICV,
PIH updates on ordinary success and Company/device settings are not changed.

This is a **selected local-step boundary**, not blanket transaction isolation or
guarding of every response-field assignment, PIH/save/success-log/error-log failure.
Those remaining existing-XML operations and the other four generated/reporting
adapters require separate review. Pre-request show failures, HTTP/transport errors,
deliberate rejection handling and unrelated unhandled exceptions retain their
existing behavior. An event logger can still swallow a failure and return None,
or commit pending parent work before throwing. The guard cannot undo callback
effects or prior commits, ensure exact durable custody, block a later worker retry
or establish remote acceptance. Generic workers still have their own outer error
logging policy; this increment does not silently rewrite it.

New offline local cases cover all four formerly caught exception families for
eight status branches, hide/event/Sales-format failures, raw/formatted lazy text,
direct versus public-wrapper propagation, Arabic, unhandled interruptions,
pre-request distinction and ordinary rejection write-order goldens. The initial
unchanged-code run produced **379 failures and 9,065 passes in 74.93 seconds**:
376 reproduced the new local-review gap, while three golden assertions mistakenly
omitted the POS simplified UUID db_set. Those three assertions were corrected to
the actual unchanged code (one exact committed UUID db_set in BOTH simplified
adapters, none in the machine adapters), without changing rejection persistence.

New native cases use actual temporary InnoDB plus mocked HTTP/ERP and original
synthetic XML. They exercise direct/public-wrapper event failures for HTTP200/401,
both explicit owner decisions and an event callback that commits before failing.
Original receipt/status/UUID, signed XML/QR links, PIH and ICV stay unchanged by the
new failure path. Pending unrelated work remains the owner's decision; callback-
committed history survives a later owner rollback. No guard was relaxed and no
site, live source/config/schema/worker/customer or authority action occurred.
Installed v16/ORM/hooks, complete worker lifecycle, exact custody/provenance,
source/Company-scoped log access/retention and runtime adoption remain gates.

Final guarded combined evidence: **9,444 local + 1,308 private SQL = 10,752 passed
in 132.45 seconds**, across the same twelve private suites (416 local + 64 private
additions). The fixed manifest and offline guard remain unchanged: external
network/site initialization denied, fixture-owned Unix SQL only. This is not an
installed v16/ORM/worker/SDK or remote-acceptance result.

## Original bounded change — increment 45

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

## Received presentation/logging steps — increment 57

The [increment 56 audit](PRIMARY_WRITERS_AND_REVIEW.md) reproduced a gap outside
the original success/legacy-409 marker: a local formatter/event-log failure for
HTTP400/401/503 could enter a generic handler and commit local error fields.
Increment 57 closes that SPECIFIC local-step gap in the four primary Sales/POS
Reporting/Clearance APIs, without reclassifying deliberate HTTP rejections.

`run_received_response_step(step, ..., validation_error_type=...)` executes ONE
explicit local callback. ValueError, TypeError, KeyError and the caller's exact
framework ValidationError class become the existing static translated
`LocalResponseProcessingError` AFTER leaving the raw handler. RuntimeError and
BaseException interruptions retain their old propagation. Successful return
values/arguments are forwarded unchanged; False/None is not a new failure or
acceptance classification. The validation class is an explicit trusted code
dependency, never a request option or new operator endpoint.

`received_response_message(formatter, response)` reads the original text/status
and calls the original formatter THROUGH that guard, so lazy text decoding and
formatter failures share the boundary. No caching/JSON normalization or new
authority classification is introduced. Each API binds these helpers locally
only AFTER `requests.post` returned. Guarded steps are exactly:

- Both existing event-log calls (success-labelled or error-labelled branch).
- The existing `hide_gif` realtime callback.
- Every existing `format_zatca_response` call in the four APIs, including late
  formatting of rejection messages after some legacy writes already completed.

Transport, pre-request `show_gif`, explicit `frappe.throw` rejection calls,
response/status persistence, PIH/artifact work, and generic exception handlers
are NOT moved into that wrapper. It is not a blanket guard around all framework
operations, translations or arbitrary response-object behavior. Runtime status
fields remain the existing Requests response fields. The helper adds no explicit
database/file read/write/commit/rollback, logging fallback, transport/retry or raw
export; the existing translator and explicit callbacks retain their own behavior.

When a guarded local step fails, the RuntimeError-family signal bypasses legacy
narrow handlers even on a rejected/auth/server-error response. No subsequent
generic read/save/error-response overwrite/503 downgrade/failure commit is
allowed. It does NOT undo the callback's own effects or earlier commits, nor
guarantee the original response reached durable storage. Arguments/response may
remain in traceback frames: static exception attributes are not a secure receipt
store and frame locals must not be logged/serialized.

The actual `event_log.log_zatca_event` still inserts with ignored permissions,
commits internally, and catches ordinary failures before calling `frappe.log_error`.
If that fallback succeeds, the logger returns None and the API cannot distinguish
a swallowed insert failure from its normal None return. If insert/commit fails
AND fallback logging raises a formerly caught error, the new guard stops further
generic API effects; real logger-function tests exercise both paths. Its own
commit attempts/swallowed errors are NOT removed or made durable by wrapping it.
An explicit logger result/transaction contract is a separate integration gate.

Increment59 subsequently supplies an explicit [diagnostic staging contract](EVENT_LOG_TRANSACTION.md)
without switching invoice callers. Its exceptions may use this explicit step
guard; its INSERT_RETURNED result is not committed/durable receipt evidence.
The legacy logger behavior described above remains unchanged.

When callbacks work normally, the EXACT old rejection branches remain, including
their UUID placeholders, independent commits, generic deliberate-rejection
wrapping and sometimes misleading 503 labels. POS Reporting still links XML
before HTTP. Normal 200/202, Sales Clearance 303 and inconsistent legacy 409
semantics are unchanged. These limitations are explicit follow-up gates, NOT
endorsed behavior or silently fixed by this increment. The old increment56
logging-failure characterization now asserts exact no-extra-write regression
snapshots rather than preserving a known defect.

The same existing English/Arabic review catalog entry is reused. No new UI,
endpoint, provider, schema, credential/route, signature/QR/amount/advance or
scheduler/replay mechanism is added. This is development source ONLY: no working
application update or authority call, including Sandbox/Simulation, occurred.

## What these changes do NOT guarantee

Increment58 subsequently adds [selected rejection-persistence steps](REJECTION_PERSISTENCE.md)
to the same guard. Known local load/write/text/commit failures no longer trigger
additional generic error writes. Deliberate rejection throws and successful
legacy persistence ordering/commit policy remain unchanged. The exclusion of
persistence in the increment57 section above describes that historical increment,
not the subsequently extended boundary. Event logger ownership is NOT changed.

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

The original increment45 counts below are historical. Increment57 adds targeted
local/error-status/late-format/lazy-text/Arabic/transport/interruption/AST and
normal-rejection golden tests plus actual private SQL parent/commit observations;
its cumulative counts and timing are recorded in [STATUS.md](STATUS.md).

Increment57 adds **550 local + 88 private SQL cases**, reaching **8,049 local +
972 private SQL = 9,021 passing cases in 103.63 seconds**, across the same twelve
private suites. First combined passed 9,009 in 102.98 seconds before twelve real
event-logger-function/fallback/swallowed-failure cases. Local snapshots cover all four formerly caught error types at
format/log/hide for rejection branch families, late 400/401 formatting, lazy text,
Arabic, untouched ordinary return values, normal rejection goldens, RuntimeError/
interruptions, timeout/connection/pre-request failures and AST-limited wrapping.
The first local run's three failures were a golden-count omission of the EXISTING
pre-HTTP POS XML link; exact five-write sequences corrected the expectation.
No runtime branch or privacy/ownership assertion was weakened to make tests pass.

The 72 early private SQL cases preserve original fields and parent-controlled
pending work through explicit caller commit/rollback. Sixteen late 400/401 cases
retain already committed legacy rejection fields without an extra failure write,
while pending Sales Clearance response remains under the parent's commit/rollback
decision. These prove the bounded guard, NOT full receipt durability or atomic
whole-invoice behavior. Frappe/File/image/HTTP are synthetic; SQL is real only on
new owned temporary servers. No live/customer/authority/Bench action occurred.

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
