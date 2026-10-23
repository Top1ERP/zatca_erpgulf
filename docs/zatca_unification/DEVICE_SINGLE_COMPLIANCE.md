# Saved-device single Compliance — increment 79 (development only)

## Replaced form behavior

`ZATCA Multiple Setting.custom_check_compliance` previously fetched a complete
Company, sent the entire device form to `zatca_call_compliance`, and saved the
open form after return. The handler now delegates to a shared UI runner and one
saved-device summary API. No Company lookup, complete device/credential payload,
automatic save/reload/model assignment or automatic retry remains in this handler.
Company single/batch/synthetic check handlers and the legacy direct API are not
changed by this increment.

The new facade is `device_compliance.run_device_compliance_summary(device_name,
expected_modified)`. It accepts only a device identity and comparison revision,
not Company abbreviation, invoice identity, validation selector, credential or
full source document from the client. Validate identity/revision and session actor
before loading records. Load the exact saved device, its linked Company and its
saved sample **Sales Invoice**. Check exact returned identities and ordinary
saved-row READ permissions through the existing quiet v15/v16-signature adapter.
Require the observed device revision to match and the sample to belong to the
linked Company. Missing/denied/mismatched sources stop before delegation; no
alternate Company/VAT/abbreviation lookup or permission fallback is added.

The saved Company validation label still wins with the historical numeric `1`
fallback to Simplified Invoice. The device's own label is not substituted. Call
the existing legacy Compliance generator **once**, with saved abbreviation,
Company/invoice identity, explicit label and device **identity-only** JSON. Existing
saved credential-owner resolution continues to reload the selected device/owner.
Return the same one-row English `results` / `single_check: true` contract used by
the Company single presenter. HTTP 200 alone/unknown responses cannot create a
PASS; warnings and validated previous-completion markers retain existing policy.

## Shared source and UI policy

Extract the small pure name/revision validators into `saved_form_source.py`.
CSR configuration reuses the revision validator through its existing static-error
mapping, without changing its API/result semantics. Modified values are observed
naive DATETIME comparison markers, not epoch/issuance timestamps or row locks.

Extract saved-form active/clean/name/snapshot policy into one UI helper reused by
credential/configuration and device Compliance runners. A device check requires
an active saved clean form with Company/sample/revision metadata. It shares the
per-form pending promise with CSR/CSID/configuration: clicks while another action
waits do not start or queue another action. A document previously marked for
credential review cannot use the check button to bypass that review; this takes
precedence over dirty-form save guidance.

After the RPC returns, changed/dirty/replaced/navigated forms receive one static
notice that the request **may have completed**, not a false cancellation/no-send
claim or a summary associated with a different active form. No form values are
changed. Normal responses use the existing localized single-summary renderer;
original technical details remain escaped and unmodified. Framework errors retain
their owner; unknown client failure has one localized outcome-review message.
CSR/CSID creation after a normally completed check is not marked as a credential
mutation. A later explicit click can retry: these are UI guards, **not** durable
idempotency, a remote outcome journal or cross-tab locks.

The facade mutes child preparation/collection popups request-locally and restores
the exact parent flag. Unknown preparation exceptions are not stringified or
implicitly chained into its final static failure. A failure escaping collection
is conservatively unconfirmed, not a claim that no remote request happened.
Interrupts propagate with flag restoration. No new logger or translated stored
result is introduced; known app labels translate only at display.

## Deliberate limits / remaining adoption gates

This is one selected device Compliance check, **not** all six onboarding steps,
invoice reporting/clearance, credential issuance, activation or permission to
send. The user prohibition on authority requests, including Sandbox/Simulation,
remains in force; all verification uses mocks. No actual API/button is invoked.

The delegated generator, temporary XML, HTTP/auth routing, cryptography and
credential-owner policy are unchanged. Its existing collection technical-details
semantics preserve original legacy exception text; this is **not** a full secret
redaction, traceback/locals or log/read/export/retention guarantee. Complete
framework/custom-hook output and legacy direct API ACL remain separate gates.
No new persistent field/schema, invoice/Company/device save, transaction/commit,
key generation, key rotation or activation is added by this facade/runner.

Only the device's observed revision is compared. Company/invoice/credential
revisions are not pinned across generation/HTTP, nor are ACLs transactionally
locked. Concurrent source/owner changes, remote lost/late response policy,
protected original receipt custody and durable duplicate prevention remain gates.
POS Invoice onboarding expansion is not implied by a Sales Invoice-only button.
Full installed v15/v16 Desk/request-decorator/ORM/hooks and SDK/authority acceptance
remain unverified and need separately approved later isolated rehearsal.

## Offline verification

The new fixed-manifest Python suite covers all six saved Company labels plus
legacy fallbacks, warnings/previous completion/unknown/exception outcomes,
v15/v16 ACL signatures, exact source/permissions/revisions, cross-Company refusal,
parent state, cancellation and no facade writes. Only Frappe's HTTP type decorator
is unwrapped for the request-free harness; the actual endpoint body runs.
Submission is fully mocked: no keys, tenant data, files or real HTTP are used.

The Node script evaluates the actual device handler in **128 cases**, both UI
languages: entry guards, one limited request, cross-action coalescing/review,
changed forms, malformed/ambiguous replies, one escaped/localized summary,
framework/unknown failures, no form writes/retry, and later explicit actions.
All seven previous UI scripts are rerun, including the shared-policy consumers.

```sh
node zatca_erpgulf/zatca_erpgulf/tests/test_device_compliance_form.js
PYTHONDONTWRITEBYTECODE=1 ../../env/bin/python tools/run_unification_rehearsal.py --private-sql
```

Only the reviewed synthetic device suite is added to the fixed manifest. No
network/site/private-SQL guard or ordinary permission/acceptance rule is relaxed.
The installed/live source/assets/config/schema/sites/workers remain untouched.
Final guarded Python: **11,909 local + 1,800 private SQL = 13,709 passed in
146.69 seconds**, with **143 added synthetic device cases** across the same
twelve owned-private SQL suites. All eight standalone Node scripts passed
**1,152 cases** (128 new device form cases). Neither result is actual installed
ERPNext/Desk, SDK, signing-material or authority acceptance evidence.
