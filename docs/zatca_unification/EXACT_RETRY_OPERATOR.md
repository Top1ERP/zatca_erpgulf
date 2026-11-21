# Explicit retry of the exact saved original

Workstream2 source development,2026-11-21. No authority request, installed site/
schema, live source, service or actual invoice action was performed. Installed
ERP15/16, authentic SDK and dummy-company rehearsals keep their separate gates.

## Deliberate review, separate from automatic first-send recovery

The readonly ZATCA Dispatch Attempt form now offers **Request Exact Retry** for
STARTED/OUTCOME_UNKNOWN or retained AUTHORIZATION_FAILED/TECHNICAL_FAILURE.
Confirmation explicitly says the previous attempt may already have been received.
The fixed POST receives only issuance ID, prior attempt ID and its recorded fence.
System Manager, native rollout and ordinary source READ+WRITE/Company READ are
required. The reviewer is the new command actor, not an impersonation of the
original sender. No document, actor override, credential, date or financial data
is supplied by the client.

The server authenticates the current original and fiscal projection, requires the
exact current attempt, and applies the shared reservation gate. Unknown/unreceived
attempts need expiry of their server-clock reservation. Expiry is **not** proof of
failure or nonreceipt; retry is deliberate and can produce a duplicate remote
invocation with the same invoice identity. A retained technical/authentication
failure is rederived from exact encrypted original/receipt custody before using
the existing no-wait received-failure rule. Mutable outcome labels alone cannot
shorten the gate. Genuine validation rejection does not authorize unchanged retry.

| Current state/evidence | Action |
| --- | --- |
| Current unreceived attempt, expired reservation | Explicit exact retry may register |
| Current retained matching technical/authentication failure | Explicit exact retry may register under existing failure policy |
| Reservation still active | Hold; no new command/transport |
| Rejection, unassessed/contradictory receipt or wrong attempt/fence | Hold for review/reconciliation/correction |
| Changed fiscal data/version, denied ACL or disabled Company Phase2 | Hold; never regenerate or override settings |
| Matching acceptance arrives after registration | Complete from stored receipt without another send |

Automatic origin/PREPARED discovery remains limited to untouched originals and
does not manufacture retry authorization. A saved response awaiting assessment
should use the existing reconciliation operation, not this retry endpoint.

## One shared durable command and worker lifecycle

The existing Submission Intent store, active-slot uniqueness, callback arming,
before-commit finalization, rollback cancellation, after-commit queue and fixed
worker are reused. A separate retry-v1 header and retry-intent AEAD domain bind
the existing version, prior attempt and prior fence in the immutable actor/source
header and active slot. Two nullable readonly index fields retry_attempt_id and
retry_fence_token must match it. Plain submit/ordinary collection headers cannot
claim retry authority; old header shapes/AAD/bodies remain unchanged with NULL
retry indexes. New fields are source declarations only, not installed migration.

Preflight owns only a clean read transaction, then a RetryIntent borrows the parent
transaction. It repeats current evidence during staging and before commit. A
pending approval returns DEFERRED / accepted=False and a translated blue notice;
there is no transport in the request handler. Parent rollback cancels the command;
queue failure after actual commit preserves READY for existing actor recovery.
An explicit repeat coalesces on the exact prior attempt/fence. A failed local
command can be replaced only after another explicit reviewed request and fresh
eligibility; stored old command headers are never rewritten or auto-rearmed.

The worker repeats phase/policy/ACL/issuer/route checks and the exact current
version/attempt. Attempt reservation rechecks the prior fence, server lease and
canonical received-failure evidence under the owned source/chain/issuance locks.
Only then is a new technical attempt/fence committed before HTTP. No lock spans
HTTP. XML/request bytes, business UUID/hash/ICV/PIH and version are retained; no
builder is called and no source correction, counter rewind or signing occurs.

The existing bounded clearance303 fallback stays bound to its recorded response.
Retry after a Reporting timeout in that flow retains the Reporting endpoint and
the same original body. Existing endpoint/environment-specific duplicate rules
remain unchanged; arbitrary200/208/409 is not an acceptance grant. Late attempts
retain their own responses and cannot overwrite a newer active outcome. This
bundle does not adopt an arbitrary late/superseded acceptance as current truth.

A subsequent separate [late acceptance review](LATE_ACCEPTANCE_REVIEW.md) operator
now admits an explicitly reviewed earlier same-original/operation acceptance under
the shared current-attempt eligibility gate. Retry itself still does not choose
or adopt a superseded response, and contradictory newer rejections stay held.

## Evidence and remaining work

Private SQL covers Sales/POS, owner variants, unchanged bytes/UUID/hash/ICV with a
new attempt, unexpired lease refusal, received401/500/503 without lease rewrite,
corrupt custody, stale fences at staging/finalization/worker reservation, rollback,
coalescing, index tampering, phase/rollout/role/fiscal failures, preserved parent
writes, late-current acceptance avoiding another send and Reporting after303.
Synthetic Desk VM covers English/Arabic, confirmation, state/outcome/role/dirty/
navigation gates and one local result. Final counts/logs are in STATUS.md. These
are fixture-owned SQL and mocked ERP/financial/signing/HTTP inputs, not installed
or genuine authority acceptance. The original financial comparison91/117/32 stays.

Still open in2: remaining late/superseded/unsealed handoff resolution, corrected
clock/rejection operator adoption, historical inventory/drain and actual chain
activation, frozen print master/File consumers, whole canonical mixed runtime
qualification and installed lifecycle/GL/File acceptance. This is explicit
unchanged retry adoption, not complete workstream2 or automatic unknown replay.
