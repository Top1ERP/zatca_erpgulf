# Saved Final-auth preservation — increment 84 (development only)

Increment 85 starts a separate non-writing local key/CSR draft. No CSID writer/
selector uses it and pending-key custody is absent; see
[CSR_DRAFT_PREPARATION.md](CSR_DRAFT_PREPARATION.md). Limits below still apply.

## Bounded behavior change

Both `create_csid` and `production_csid` could overwrite a target's shared
certificate/authentication even when Final-CSID authentication was already saved.
The local CSR/key guard from increment 83 did not cover these writers.

Both writers now conservatively stop when their exact authorized saved target
has populated `custom_basic_auth_from_production` **or** `custom_final_auth_csid`.
Check both fields for Company and device targets, including the nonpreferred
legacy spelling. Whitespace, masked, invalid, historical and other-environment
text all count as present. Unknown types or unreadable state fail closed.

This deliberately prevents using either existing operation for re-issuance when
Final auth is observed. No force flag, role exception, environment override,
credential clearing, expiry inference or automatic existing-credential reuse is
introduced. A local block is not a new certificate, remote 401/403 or PASS. Do
not clear saved fields to bypass it; renewal needs a separately reviewed staged
workflow which preserves the active bundle.

## Presence is not credential validity or complete custody

`credential_presence.classify_saved_credential_presence` is the shared pure core
for both this guard and the increment 83 CSR/key policy. It accepts an exact
app-owned dictionary and a bounded unique ASCII field-name tuple, checks literal
types without stringifying/truth-testing private values, and returns only
`EMPTY`, `PRESENT` or `UNKNOWN`. Only None/exact empty text is absent. Unknown
state wins over another present value. No parsing/decryption, field selection,
transport, persistence or credential export occurs. CSR's six-field protection
semantics are retained and its existing suite is rerun, not weakened.

| Observed target state | Both CSID operations |
| --- | --- |
| Either Final-auth field contains text | `CSID_FINAL_AUTH_PRESERVATION_REQUIRED`; stop before transport if observed at preparation |
| Shape/type/read state is unverifiable | `CSID_FINAL_AUTH_STATE_UNCONFIRMED`; stop conservatively |
| Both fields are literal None/empty text | Continue existing preparation; **not** proof of no issued certificate, safe renewal or remote readiness |

Most importantly, certificate-only material with missing Final auth is **not**
protected by this new guard. A populated Compliance certificate/auth/request ID
can be needed for the initial Final transition, so this increment does not guess
certificate purpose from shared field names or block all such values. It does
not prove that the transition is safe merely because the two Final fields are
empty. Lost/stale/partially saved credentials and remote issuance remain review
and staged-custody gates. The CSR/key guard remains stricter for key replacement.

## Saved-source and response boundaries

Existing saved-target READ/WRITE and related Company READ/binding checks run
before this guard; permission denial does not disclose credential presence.
Only the actual write target is inspected. Client fields/force/ignored-permission
flags cannot clear the saved projection. A device's linked Company is not made
its write target, including when its signing policy uses Company credentials.
This preserves the existing separation, not correct ownership for every renewal.

The selected CSID worker checks the loaded target:

1. After source authorization, before CSR/OTP/auth/request/route preparation.
2. After the progress callback and immediately before entering transport.
3. After a successful response is parsed/processed, before any certificate/auth
   assignment for that response.

These are same-object observations, not fresh locked source/credential epochs.
They catch changes visible through callbacks, not every database race. Ordinary
save permissions/timestamps/hooks remain; no extra database reload, commit,
rollback, retry, credential restore or speculative cleanup is added. The guard
does not bind CSR/key/Compliance auth/request ID/environment across the attempt.
Existing non-200 response rejection still takes precedence and performs no
new successful-response credential write.

## One display owner, no secret diagnostics

The existing CSID operation runner presents static canonical English failure
metadata with display-only translation, including actual Arabic CSV entries.
Unknown read errors are not stringified and the final throw is outside child
exception context. Parent mute/message/language state and cancellation behavior
remain owned by the caller. No new logger is introduced.

Before transport, a preservation failure uses its static local code/message and
no HTTP status. After transport, retain the uncertain processing-stage result
and append a preservation notice in the same popup; do not call the request
unsent or authorize retry. If progress cleanup also fails, append its notice
without dropping the preservation notice. Hide-progress cleanup never repairs
credential fields or remote issuance. These are scoped app-owned messages, not
certification of full framework traces/hooks/logs/locals/read/export custody.

## Initial issuance and unresolved writer/storage behavior

The initial Compliance-to-Final transition, saved public signatures, success
JSON-string shape, route/OTP/header/timeout selection, response handling,
taxpayer check and ordinary save behavior remain. Final creation still uses
Compliance authentication, not Final auth. No real authority request was made
to demonstrate this; the evidence is synthetic transport assertions only.

That first Company transition still replaces the shared Compliance certificate
text; the device transition can still leave different values in the two legacy
certificate aliases. Existing lifecycle characterization explicitly preserves
these observations. This guard does **not** fix them or certify the resulting
credentials as usable. No protected receipt, coherent versioned activation,
source lock, lost/late-response recovery or installed storage is enabled.
Earlier encrypted bundle/archive primitives remain uninstalled/unactivated.
Review all other/direct/manual writers and build a source/epoch-bound staged
renewal/activation workflow before runtime adoption; do not weaken field conflict
checks or reconstruct an active certificate from an auth token to make it pass.

## Offline evidence and release gate

Only the two reviewed synthetic suites `test_csid_preservation.py` and
`test_credential_presence.py` are added to the fixed manifest. They exercise
actual public worker bodies with mocked saved records, explicit quiet v15/v16
ACL signatures, ephemeral test material and mocked HTTP/saves. Coverage includes
both auth fields/targets/purposes/languages, unknown reads/types, parent state,
cancellation, caller/env bypass attempts, changes during route/progress/response
callbacks, response-write prevention, combined cleanup failures, first Final
success then blocked repeated issuance, and device/Company separation.

Allowed routing/writer fixtures explicitly model pre-Final targets by clearing
**test objects only**. Negative source ACL fixtures retain their populated
credentials. Original route/OTP/Compliance-header/payload/save assertions remain;
the initial transition's known alias/purpose conflicts remain characterized.
No normal guard is bypassed. Actual installed Frappe/ERPNext 15/16 schemas,
field masking/roles/ORM/hooks/transactions, browser/Desk, SDK and authority
acceptance remain unverified. No live source/assets/config/schema/site/customer
credential/worker or authority operation is performed. Development completion,
then separately approved fictional-Company rehearsal, precedes adoption/pilots.

Final guarded combined verification: **13,122 local + 1,800 private SQL =
14,922 passed in 153.12 seconds**, across twelve owned-private SQL suites.
This adds **269 reviewed synthetic cases** (221 CSID-preservation and 48 shared
presence cases), retaining the prior CSR and initial-transition regressions.
All nine standalone Node VM scripts passed **1,444 cases**. No external-network,
site-init, SQL ownership, ordinary source permission or transport assertion was
waived. This is offline evidence, not real issuance or installed acceptance.
