# CSID transport and local-outcome presentation

Increment 75, 2026-10-23. Isolated development only; no installed application,
asset build, site, credential data, schema, Bench/worker or authority action.

## One explicit execution boundary

The two public CSID signatures remain unchanged and guest access remains denied.
They now call one internal boundary and separate private Compliance/Final-CSID
workers. Only the public functions are whitelisted. The existing credential
writers, route/auth choices, timeout, certificate checks and field aliases remain;
the workers have no message ownership or retry/transaction authority.

Previously generic local catches concatenated `str(exception)` into public
errors; transport/other exception types could escape entirely. The hide-progress
call ran immediately after transport and was skipped on connection failure.
Its own failure could prevent parsing/storage of an already received reply.

`CSIDProgress` records only five internal booleans. `csid_local_failure` accepts
that progress and a literal purpose, never an exception, document, response,
credential or URL. It constructs static English ERROR metadata with a code and
message, not success or retry authorization:

| Last observed boundary | Local interpretation |
| --- | --- |
| Before transport invocation | Preparation failed; review saved source/settings |
| Transport entered, no return | Outcome unknown, including timeout/connection faults |
| Transport returned, save not entered | Processing not completed; returned value is not proof of a valid HTTP response |
| Save entered, did not return | Storage unconfirmed; earlier changes may already exist |
| Save returned | Local completion unconfirmed if cleanup/presentation fails; not proof of commit |

Only literal booleans and consistent stage order are accepted. An early private
worker return without normal save completion cannot produce a green result.
HTTP rejection metadata from increment 74 retains its existing classification.
Neither a timeout nor a local processing failure is converted to OTP rejection,
remote acceptance or permission to issue another credential.

## Messages, progress and partial effects

The boundary mutes child messages through the existing request-local context
manager. It restores the exact prior flag, leaves parent messages and language
owned by their caller, and emits one final localized result outside caught
exception contexts. It does not stringify, translate, log or export raw errors,
including exceptions whose `__str__` is unsafe. Public failures have no attached
raw exception context/cause in the synthetic checks. Arabic entries cover all
new stage messages and the progress-review notice. Normalized metadata remains
English; framework-wide log/snapshot language is not certified by this work.

Once showing progress is attempted, `finally` attempts to hide it, including
after transport, storage or cancellation faults. Cleanup messages are also muted.
Hiding is best effort, not a guaranteed browser result. Its failure preserves a
known primary HTTP/local diagnosis and adds one static review notice to that
same error. If storage returned normally, a later hide/presentation fault requires
local-completion review, not another request or a false storage-failed claim.

Moving hide into `finally` means UI cleanup no longer interrupts processing
between response reception and credential storage. A hide failure can now follow
completed legacy save effects; tests and messages explicitly retain that fact.
There is no guessed rollback, credential deletion, transaction commit, second
request or automatic retry. Hooks may already have written or committed. Their
effects are not undone. Interruptions such as KeyboardInterrupt/SystemExit/
GeneratorExit propagate; the boundary does not convert them into a normal result.
A cleanup hook's own BaseException is not swallowed either.

The final presenter is outside child muting. A custom presentation hook that
emits output and then raises can already have exposed a success notice; its
earlier output is not erased. The synthetic partial-presentation test expects
that prior notice plus the final local-review message, not an atomic one-dialog
guarantee across arbitrary hooks. In the ordinary modeled path there is one
final app-owned dialog; a parent mute setting is still respected.

## Compatibility and remaining gates

Success retains the purpose/status/message English JSON-string contract from
increment 73. Failures remain framework ValidationErrors, with coarse static
local diagnostics replacing raw exception text. A configuration failure now
uses the preparation message rather than re-exporting the original route error;
the route/no-request/auth/environment guards remain tested. An empty device CSR
also no longer references an undefined Company-only variable in its child error.
Commented credential/OTP popup examples in that worker have been removed.

This is not durable receipt custody, proof of transport delivery, cryptographic
acceptance, protected log access/retention, credential rotation, atomicity or
rollback. Existing ignored-permission writers and Company/device form save/reload
remain release gates. Framework snapshots, middleware, loader/permission hooks
and developer console/debug captures can inspect surrounding state; removing
an exception chain alone does not certify them secret-free. No old log or saved
credential has been inspected, cleaned up or migrated. Exact admin-only original
diagnostics need a separately scoped protected storage/access policy, not raw
public errors or a new implicit logger.

Installed v15/v16, real permissions/schema/hooks, browser/realtime cancellation,
physical/storage rollback and actual certificate/SDK/authority acceptance remain
separately approved gates. No claim about live readiness is made.

## Offline checks

The fixed manifest adds only the reviewed `test_csid_local_outcomes.py` suite.
Synthetic saved-document fixtures now model request-local flags explicitly.
Cases exercise the real public boundary and workers with mocked ERP/transport:
stage classifications, invalid progress, both owner types/purposes and real
English/Arabic catalog display, private loader/child errors, timeout/connection/
unprintable exceptions, malformed/missing response fields, save partial effects,
cleanup faults, cancellation, parent flag/message preservation, early return
and a presentation hook's already-emitted output. No transport/site/SQL ownership
guard is relaxed and no user button or real endpoint is invoked.

The independent Node VM selection remains 412 cases. Final guarded Python
evidence is recorded in [STATUS.md](STATUS.md).

Final guarded result: **11,656 local + 1,800 private SQL = 13,456 passed in
143.97 seconds**, using the same twelve owned-private SQL suites. The 189 new
local cases require only that explicit manifest addition; no runtime guard or
permission policy is relaxed. Standalone Node checks remain 412 cases. The prior
compatibility-only local run passed 11,467 cases in 73.41 seconds.

Increment 76 separately removes implicit save/reload from Company/device CSID
handlers and adds in-memory clean/pending/review guards and a display-only note.
CSR/configuration/other checks, manual saves, server access and full log/credential
lifecycle remain gates. See [CSID_FORM_LIFECYCLE.md](CSID_FORM_LIFECYCLE.md).
