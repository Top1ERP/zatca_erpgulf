# Bounded CSID HTTP-failure presentation

Increment 74, 2026-10-23. Development only; no installed source/assets, site,
credentials, schema, Bench/worker or authority action.

## Scope and response handling

Both CSID functions previously copied unsuccessful response bodies into a
`frappe.throw`, then caught that ValidationError and threw a second prefixed
message. Compliance additionally labelled every HTTP 400 response Invalid OTP,
even when no such authority code was present. Response headers, reason phrases
and configured endpoints also reached the error text.

`csid_request_rejection` now constructs a bounded English diagnostic with only
`status`, `purpose`, `code`, `http_status` and a canonical app `message`. Its
status is always ERROR, never success. It does not store or export the original
body, reason, headers, URL, request ID, OTP, CSR, certificate or auth values.
This is allowlisted classification, not regex replacement of raw messages and
not an authenticated receipt or credential-activation decision.

| Response evidence | Canonical interpretation |
| --- | --- |
| 400 and exact `Invalid-OTP`, Compliance purpose only | OTP rejected; check OTP/environment |
| 400 and exact `Missing-ComplianceSteps`, Final-CSID purpose only | Required checks incomplete for the same Compliance CSID |
| 401 | Authentication failure; check purpose/environment/unit |
| 403 | Operation access denied |
| 429 | Rate-limit response; review outcome, no automatic retry |
| 500–599 | Remote error; review saved settings and outcome |
| Other/malformed/unknown evidence | CSID creation not confirmed; review before retry |

Only literal bounded integer HTTP statuses are included. Known 400 codes can
come from a JSON object's `code` or at most 16 object entries in `errors`.
The JSON text must be a literal string at most 65,536 characters. Unknown text,
codes, nested messages and fields are not copied. Malformed/deep JSON, unsupported
types and oversized bodies take the generic path. A known code for the other
purpose does not receive that purpose's specific interpretation. HTTP 200
processing/acceptance remains the existing path; this increment does not extend
the statuses that are considered successful.

## Single popup and compatibility

An internal exception carries just normalized metadata. Each existing CSID
function captures it without a popup and leaves that exception handler before
the final `frappe.throw`. The framework receives one localized app message, its
numeric HTTP status and a translated title; no second prefixed exception or raw
HTTP exception chain is attached. The public signatures, raised ValidationError
behavior and previous success JSON-string contract remain. Existing in-repository
clients still defer framework-owned errors. No retry, certificate save, extra
request, commit, cleanup or new diagnostic log writer is added on HTTP failure.

The normalized data stays English under an Arabic UI. Arabic display entries
cover every canonical message, title and status label. This does **not** certify
that every framework-owned Error Log, traceback, console/debug snapshot or local
variable capture is English or credential-free. The public error's exception
chain is checked, but framework snapshots/custom hooks need a separate lifecycle
audit before adoption. Original raw receipts are not silently rewritten into a
new storage format; no receipt archive is wired up by this presentation change.

This intentionally removes raw-body/request-ID/endpoint diagnostics from these
HTTP errors. External consumers parsing their old exception strings must migrate.
Route tests now assert the canonical failure plus the same mocked destination,
OTP/auth headers, no saved settings and unchanged environment guards, rather than
requiring the unsafe raw response substring to remain visible.

## Remaining boundaries

This is HTTP-response-failure presentation only. Connection/timeouts, invalid
local inputs or route configuration, HTTP 200 parse/save/presentation faults,
certificate/VAT checks and generic local exception wrappers remain unchanged
and require their own redaction/uncertain-outcome work. The existing progress
overlay cancellation/finally behavior, ignored-permission credential writers,
saved-field/endpoint access, form auto-save/reload, protected raw-receipt custody,
log read/export/retention and credential epochs/rotation remain release gates.
No general log-security or CSID workflow-completion claim is made.

Increment 75 separately introduces that local/transport-stage boundary and
best-effort progress cleanup; see [CSID_LOCAL_OUTCOMES.md](CSID_LOCAL_OUTCOMES.md).
The above limits describe increment 74, not a claim that the newer boundary
certifies storage, logs, client lifecycle or authority acceptance.

## Offline evidence

The unchanged guarded manifest already selects the credential lifecycle and
route tests. Added synthetic cases cover the pure response matrix, unsupported/
oversized/deep bodies, strict status types and both actual entry bodies across
Company/device, both purposes and real English/Arabic catalog display. Mocked
headers fail if read, translation input excludes secrets, failure raises only
once with no raw exception context/cause, save is not called and transport is
called exactly once. No real authority or customer material is used.

Existing standalone Node checks remain 412 synthetic cases. The final Python
result is recorded in [STATUS.md](STATUS.md). Installed v15/v16, real browser,
framework log/snapshot behavior, SDK and remote acceptance are still unverified.

Guarded combined evidence: **11,467 local + 1,800 private SQL = 13,267 passed in
142.51 seconds**, using the same twelve owned-private SQL suites. There are 130
new local cases with no manifest or guard changes. Standalone UI checks remain
412 synthetic cases; no transport or installed-framework acceptance is inferred.
The final stable-source local recheck passed all 11,467 cases in 73.09 seconds.
