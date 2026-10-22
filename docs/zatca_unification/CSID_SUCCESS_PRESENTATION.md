# Auth-free CSID success presentation

Increment 73, 2026-10-23. Development worktree only. No installed source,
assets, site, Company/credential data, schema, worker or authority action.

## Observed issue and bounded change

The previous `create_csid` implementation displayed and returned the full HTTP
200 response body, including `binarySecurityToken`, `secret` and `requestID`.
It displayed that body before JSON validation and local save. Both wizard CSID
callbacks copied their returned strings into editable Long Text fields labelled
as authentication credentials. Production returned success/request-ID JSON,
not Basic auth, even before this increment.

Both existing success paths now call one private presenter only after their
existing save completes. Its input is just the literal purpose; it cannot accept
or inspect a response body, token, certificate or request ID. It displays one
static translated notice and returns an English JSON **string** containing only:

```json
{"status":"SUCCESS","purpose":"compliance","message":"Compliance CSID generated and saved successfully."}
```

The final-CSID variant uses `purpose: "production"` and the message
`Final CSID generated and saved successfully.`. Purpose does not mean the
selected environment is Production: routing/credential purpose remain separate.
No returned request ID, certificate, token, secret, OTP, CSR, auth header,
endpoint or raw response is added to this success projection. No logging writer
is introduced. Original saved credential/request-ID values remain unchanged.

The wizard consumes only the strict purpose/status/canonical-message contract.
It displays known translated result text, never a raw legacy response or an
arbitrary returned message. The two existing field names are retained for UI
compatibility, but their labels now identify results and they are read-only.
Unknown/malformed/old replies produce static review text without echoing data.
This does not validate or authorize the wizard's Next action.

## Compatibility and deliberate limits

The JSON-string return shape and public signatures remain. The secret-bearing
Compliance response content is deliberately removed; clients depending on raw
tokens or returned request IDs must change before adoption. The inspected
in-repository Company and Multiple Setting callbacks only check for errors;
the wizard's `.trim()` consumers have been replaced. This inventory is not a
guarantee about external integrations. No persistent DocType field is renamed.

This is **success-path redaction only**, not a complete CSID security redesign.
Failure bodies/exceptions, framework tracebacks, log read/export/retention,
credential-bearing saved form fields and general Company/Multiple Setting
access controls remain release gates. Existing CSID writers still use ignored
permissions and legacy shared certificate fields; no permission, key epoch,
rotation or storage migration is claimed. Existing Company/Multiple Setting
auto-save/reload and parent/request lifecycle still require review. Debug's
attachment-only client protection does not automatically cover CSID callers.

No response acceptance, certificate chain/VAT policy, timeout, save/commit,
endpoint selection, authentication selection, ICV/UUID/PIH or invoice submission
behavior is changed here. A save or presentation failure may follow earlier
effects. There is no added retry, cleanup, rollback or durable receipt custody.
Legacy HTTP 200 parsing/save behavior is characterized, not certified as remote
Compliance completion, cryptographic validity or safe credential activation.
Existing secret-bearing historical records were neither inspected nor deleted.

## Offline checks

The unchanged guarded manifest already selects `test_credential_lifecycle.py`.
Its real CSID entry-body tests use synthetic in-memory key/certificate material,
mocked saved documents and mocked HTTP. Additional cases cover Company/device,
both purposes, three environment projections and English/Arabic display,
unchanged saved values, no returned/displayed secret/request ID and no success
notice before parsing/save. Unknown pure-builder purposes fail without reflecting
input. This does not execute a browser, real issuance, File/site or installed
v16 runtime.

```sh
node zatca_erpgulf/zatca_erpgulf/tests/test_company_compliance_messages.js
node zatca_erpgulf/zatca_erpgulf/tests/test_debug_messages.js
node zatca_erpgulf/zatca_erpgulf/tests/test_debug_ui_lifecycle.js
node zatca_erpgulf/zatca_erpgulf/tests/test_csid_messages.js
PYTHONDONTWRITEBYTECODE=1 ../../env/bin/python tools/run_unification_rehearsal.py --private-sql
```

The new Node VM script adds 80 cases, including the actual two wizard callbacks,
English/Arabic rendering, raw/malformed/old response refusal and untouched input.
The full wizard source is syntax-compiled without starting its page. The total
standalone synthetic UI selection is now 412 cases (previous 332 + 80 CSID).
No network/site API is exposed inside the VM. Final Python evidence is recorded
in [STATUS.md](STATUS.md).

Final guarded Python evidence: **11,337 local + 1,800 private SQL = 13,137 passed
in 145.35 seconds**, across the same twelve owned-private SQL suites. The 44
new local cases require no manifest or runtime-guard changes. No tenant, real
HTTP, certificate issuance or installed v15/v16 lifecycle acceptance is inferred.
