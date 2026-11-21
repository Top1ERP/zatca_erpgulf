# Complete stopped requests from saved originals and responses

Workstream2 source development,2026-11-21. No live source, invoice, tenant/schema,
worker/service or authority API was changed or invoked. Installed ERP15/16 and
actual dummy-company rehearsals retain their separate approval gates.

## Explicit local operator action

The readonly Submission Intent form now offers **Reconcile Saved Result** for
RUNNING/REVIEW. Like unissued retirement, it requires System Manager plus current
source READ+WRITE/Company READ, including repeated calls. The fixed POST receives
only record ID and the state/fence shown before confirmation. Dirty/navigated
forms are not acted on, and one result is displayed in the user's language.
No caller supplies source/Company/actor, financial data, credentials or a builder.

The service never queues, generates, signs or transports. It verifies the stored
request, current saved business projection, exact chain/version/UUID/ICV and the
canonical original/receipt view. This can satisfy a stopped request from a matching
current original; it does not assert that the stopped process itself produced or
received that evidence. A reviewing manager does not impersonate the original
request actor, which remains unchanged in the immutable header.

| Verified current custody | Local action / acceptance result |
| --- | --- |
| Untouched PREPARED, no active attempt | COMPLETE / accepted=False; original remains ready and unsent |
| REPORTED/CLEARED with matched original and receipt | COMPLETE / accepted=True |
| Current captured response, assessment interrupted | Stage canonical assessment; complete only for matched acceptance |
| Rejected, unknown/in-flight, missing or contradictory evidence | Hold review; no completion or resend |
| Stale claim, changed fiscal data/chain/version or denied ACL | Hold review; no repair or replacement |

Local COMPLETE is not automatically reporting/clearance acceptance. The prepared
message explicitly says acceptance is unconfirmed. Current phase, rollout switch
and signing-key availability cannot invalidate a historical evidence read, but do
not grant any new delivery authorization. Source status/response fields are not
repaired by this action; the existing separately guarded projection remains its
own operation. No financial data, File, ICV or PIH is changed.

## Canonical readers and interrupted assessment

The retained-view implementation was extracted into read_retained_in_transaction;
the existing read_retained_invoice still acquires and closes its own transaction
and calls that same implementation. Source ACL/current fiscal publication rules,
latest saved version selection, original metadata/hash binding and accepted
receipt/returned-XML checks are unchanged. No parallel receipt parser was added.

Likewise, existing invocation assessment now delegates to the common
assess_retained_in_transaction helper. Explicit stopped-request review may stage
that same assessment for its **current** durably captured active attempt when the
issuance is REVIEW_REQUIRED. It verifies original request and receipt fence,
including the bound clearance303 evidence where required. The earlier durable
receipt remains unchanged. Assessment changes and request completion/proof commit
together; a failed proof readback rolls both back. Nonaccepted assessment does not
complete the request or authorize the303 follow-up transport here.

The existing endpoint/environment policy remains in native_response: matched
clearance200/208, Production duplicate restrictions, and Standard303 Reporting
reuse are tested without changing those rules. An official URL in a synthetic
fixture is only a policy label; HTTPAdapter and the offline guard prevent network.
This is metadata/receipt-contract evidence, not authentic CA/signature/SDK proof.

## Fences, proof and shared storage

Only a clean owned transaction is acquired. The request's current state/fence,
chain/source locks and another current request comparison precede completion.
Stored capsule is authenticated before COMMIT. Lost commit acknowledgement is
not compensated; a later authorized repeat reopens proof and freshly verifies
the same evidence. A stale worker cannot overwrite the completed request, and
its generation/reservation claim checks still fail after completion. No row lock
spans HTTP, because this action has no transport at all.

One shared nullable resolution_header/resolution_ciphertext pair now stores both
operator actions, replacing the earlier source-only retirement_* column names.
The retirement capsule's existing domain/body/header keys remain unchanged. A
separate intent-reconciliation AEAD domain binds original intent hash, prior state/
fence, reviewing actor/time, original XML digest, issuance ID/state, active attempt
and matched outcome. Ordinary worker COMPLETE without an operator capsule remains
compatible; proof on a nonterminal state is rejected. Reconciliation proof cannot
be read as retirement proof or grant deletion of an issued invoice.

This rename is a development schema declaration only. No DDL, migration, backfill
or persisted capsule rewrite was executed. An installed older development schema
requires a separately reviewed migration; these tests do not certify it. Invoice
request headers/AAD, original XML/receipt bytes and financial fixtures are unchanged.

## Verification and limits

Private SQL covers Sales/POS and all owner forms; v1/v2 RUNNING/REVIEW requests;
prepared, Reporting, Standard303 and direct/duplicate clearance; invalid signing
material with rollout disabled; missing/corrupt originals and receipts; stale
claims, permissions and disabled-original-actor review; capsule corruption;
interrupted assessment with atomic rollback; lost commit acknowledgement; and
retained byte/UUID/ICV/counter identity without another send. Synthetic Desk VM
tests cover English/Arabic and both local review actions. Final counts/logs are
recorded in STATUS.md. Financial/signing/ERP posting/HTTP remain explicit doubles.

Still open in2: current unknown/late/superseded response resolution and unchanged
retry operator adoption, corrected clock/rejection workflows, complete Standard/
non-Background prepared recovery, historical inventory/drain and activation,
frozen print master/File consumers, whole canonical mixed runtime and installed
GL/File/ERP15/16 acceptance. This is not full crash recovery or workstream2 closure.
