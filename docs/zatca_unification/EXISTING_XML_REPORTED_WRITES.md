# Existing-XML reported-label write boundaries — increment 67

Development only, 2026-10-22. No installed application, site/config/schema/Bench/
worker/customer or authority action, including Sandbox/Simulation. REPORTED here
names an existing stored label, NOT verified remote acceptance or durable custody.

## Bounded shared write and callback guards

The four existing-XML Sales/POS Reporting adapters now reuse
`legacy_xml_persistence.persist_existing_xml_reported` for their eight repeated
200/202 and legacy-409 response-write blocks. The explicit server runtime and
fixed Sales/POS DocType are not browser parameters or a permission grant. Unknown
DocTypes fail before loading. The callback keeps this exact legacy order:

1. Load the fixed original invoice.
2. Read/assign the original unnormalized response text.
3. Assign the original submitted UUID and existing REPORTED status label.
4. Save with the existing ignored-permission flag, then perform the existing commit.

The caller still updates its request-pinned owner BEFORE this writer. Its actual
`record_submission_owner_success` now executes through the same received-step
guard, including owner lookup, optional notification, existing Phase-2/hash guards,
in-memory PIH assignment and owner save. No new owner selection, hash/counter
allocation, acceptance classification or source revision attestation is added.

Success logging also executes through the guard. The tiny transaction-free
`received_response_text_step` adapter performs the original lazy response-text
read INSIDE that callback boundary and forwards original arguments/result. It
does not normalize text, cache a response, inspect return-value truthiness or
reinterpret None/False as accepted/failed custody. Existing success-log routines
and their ignored-permission Document insert/hooks remain unchanged.

All four adapters' existing trailing error-log callback is guarded too. In the
legacy control flow this callback runs AFTER the 409 branch's success log; that
odd sequence is preserved, not endorsed or silently reclassified. All normal
branch labels/notifications/messages and actual callback order are unchanged.

## Failure semantics and preserved history

The guard translates ONLY the four formerly caught ValueError/TypeError/KeyError/
framework ValidationError families into the existing static English/Arabic local
review signal, outside raw handlers. The increment65 broad public XML wrappers
preserve that signal. Known local errors no longer cause another generic invoice
load/save/Error/Failed overwrite or failure commit after the fault. Deliberate
rejection throws remain outside the guard; increment66 rejection policy is unchanged.
Other previously unhandled types retain their old direct propagation; broader
callers for those types and arbitrary hook/driver errors are not globally rewritten.

This is **not atomicity**, protected receipt storage, an acceptance verdict or a
durable no-replay hold. Source objects and callbacks can already have effects:

| Failure point | Existing SQL effects that may remain |
| --- | --- |
| Before owner save | In-memory PIH may differ; no new owner row was necessarily saved. Unrelated parent work may already be pending. |
| After owner save, before invoice commit | PIH may be pending while the invoice response is still old; after invoice save, its response/UUID/status can also be pending. |
| After invoice commit or during later logging | PIH, response/UUID/status and unrelated parent work may already be committed. A subsequent rollback cannot undo that history. |

No rollback, close, reconnect, compensation, replacement response, retry or hold
release is added. The owner must retain originals, review the exact partial state
and reload/discard mutated objects before any later action. Traceback frames can
still hold protected context even though the static error has no raw attributes;
do not serialize/log those locals as a substitute for protected custody.

The original signed XML/base64 payload and QR links are preserved. No re-signing,
ICV generation, PIH policy/phase/unchanged-hash rule, credential/endpoint/settings
selection, advance lookup/eligibility/allocation/age, discount or GL/VAT arithmetic
is changed. The event logger still has its legacy commit/swallow/fallback/None
policy; its plaintext log read/export/retention scope is not repaired by this guard.

## Offline verification and remaining gates

New local cases execute the actual four APIs with real synthetic XML file reads,
mocked HTTP/ERP and actual pinned-owner/PIH helpers. They cover 136 adapter/status/
fault points across all four formerly caught families: owner lookup/save before/
after, invoice lookup/raw text/save before/after/final commit before/after, lazy
success-log payload reads, success logging and trailing 409 error logging. They
also cover public wrappers, Arabic, direct unhandled interruptions, unchanged
normal callback order and fixed source-only guard bindings. Shared-writer tests
require exact raw values/arguments and early unsupported-DocType refusal; the
text adapter must forward arguments and return values without classification.

The initial unchanged-writer local characterization produced **608 failures and
9,986 passes in 108.66 seconds**. Of those, 596 were local-review expectations;
twelve additional unhandled-log-error cases exposed an incorrect argument
signature in the new callback double. That double was corrected to accept the
original callback arguments before final verification. Its mismatch also caused
a local TypeError in affected log injections. No exception-class, source/custody
assertion or offline guard was relaxed to obtain a pass.

New native cases cover the same 136 points with BOTH explicit parent decisions.
They add only a synthetic owner-PIH table on the fixture-owned temporary InnoDB
server. The actual PIH helper's owner save and invoice save/commit are bridged to
that SAME owned transaction; independent readers and the owner read exact pending
versus committed PIH/response/UUID/status/business values at the failure point.
Snapshots must remain unchanged after propagation. No borrowed cleanup, generic
failure persistence, extra transport, artifact replacement or owner rewind occurs.
The test owner alone explicitly commits/rolls back pending work; prior commits survive.

This is not real Frappe Document/hook/worker execution, installed ERPNext16,
cryptographic/SDK or authority acceptance evidence. Remaining generated/reporting
writers, full worker error/commit/retry lifecycle, exact independent custody and
holds, scope/credential/transport provenance, Company/source-scoped log read/export/
retention and separately approved fictional-client v15/v16 rehearsal remain gates.

Final guarded combined evidence: **10,618 local + 1,800 private SQL = 12,418 passed
in 141.19 seconds**, across the same twelve private suites (668 local + 272 private
additions). The fixed manifest and offline guard remain unchanged: external network
and site initialization denied, fixture-owned Unix SQL only. No guard/ownership/
error-class assertion was relaxed, and no working environment was modified.
