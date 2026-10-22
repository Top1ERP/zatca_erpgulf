# Operation summaries and display-only translation

Increment 68 implements the user's message policy in the development worktree.
It is not an installed asset change or a deployment authorization.

## Adopted boundaries

- Company `custom_run_all_compliance` and
  `custom_run_zatca_onboarding_checks` use one server-side result collector and
  one client-side summary presenter. Each requested document type keeps its own
  outcome; one failure does not erase the other five results.
- The collector temporarily mutes only nested Frappe messages in this request.
  Frappe exceptions still raise and are recorded as failed rows. The previous
  mute flag is restored exactly, including absent flags, nested calls and
  interruptions. Parent-owned queued messages are never cleared. Cancellation
  propagates rather than being converted into an ordinary failed check.
- The presenter displays one dialog with counts, translated document types,
  statuses and messages, and expandable technical details. Identical technical
  details are grouped once and labelled with the affected document types.
  Arbitrary diagnostics are HTML-escaped, never interpreted as markup.
- Warnings stay visible, including their original codes/text. They retain the
  existing compliance acceptance rule; an otherwise complete warning result is
  orange, not silently downgraded to failure or reported as unqualified success.
- The existing CSID creation catch also stops adding a second dialog when
  Frappe already presents an HTTP/validation/session/permission error. The
  framework remains responsible for these infrastructure errors. Local client
  errors use a static translated message, never `[object Object]` or raw XHR.
- Run All Compliance no longer performs an unnecessary restore/save/reload of
  `custom_validation_type`: the server already passes each type explicitly and
  does not mutate this Company setting. This does not save dirty form changes
  or discard dirty form values, or change the server's saved-settings selection.

## English storage, localized presentation

`collect_compliance_results` returns stable English `message`, `type`, `status`
and `compliance_status` fields. Failure `technical_details` retains the original
exception string. Successful `validation_details` retains the already parsed
`validationResults` object, including warning information. Its pretty JSON in
the dialog is explicitly a *view of parsed fields*, not the original HTTP body.
Neither field is used to overwrite invoice responses or diagnostic response
logs. No new database log write or commit is added by the collector.

The presenter translates only known app-owned keys through Frappe `__`, using
the current user's UI language. Arabic entries are in `translations/ar.csv`.
Unknown/raw authority text, codes and request IDs are not translated. Neither
server language nor User/Company preferences are changed for the operation.

The explicit retained-response diagnostic writer now stores its app-owned
title/status labels in canonical English, irrespective of the request language.
This supersedes increment 61's translated stored-label behavior. Custody,
original response text, ACL checks and transaction ownership are unchanged.
No historical log rows are rewritten. Raw authority payloads may themselves
contain another language and must remain original; "English logs" never means
translating signed content or reserializing an original response.

## Acceptance and remaining scope

HTTP 200 alone still cannot pass a check. The existing shared outcome classifier
alone determines PASS/ALREADY_COMPLETED; unconfirmed results remain FAIL.
The UI requires six distinct known PASS types before presenting a completed
batch, and the automatic route also requires the existing `all_passed` flag.
Empty/malformed results never enable the final-CSID instruction.

This is initial adoption, not application-wide notification consolidation.
Single-check, invoice/POS submit/debug, background/retry, CSR/CSID server wrappers
and all other diagnostic writers still require explicit migration. In
particular, an existing certificate-generation success popup containing a raw
certificate response is not changed or certified safe by this increment; a
separate redacted onboarding-result contract is still required. Legacy localized
exception strings are retained as original technical details, not automatically
reverse-translated. Other legacy logging calls are not claimed to be English.
Do not globally intercept `frappe.msgprint`, force English for a whole request,
clear unrelated notifications, or reuse translated display HTML as log content.

No new endpoint, transport call, credential selection, retry, certificate
issuance, signed XML/QR/PIH/ICV, accounting/advance, schema or live change is made.
Tests stub every submission; the agent does not invoke either real button.

## Verification

The fixed-manifest Python runner includes synthetic collector, both real button
boundaries, flag restoration, interruption, unchanged raw diagnostics, warning
visibility, English labels under Arabic, and existing acceptance regressions.
The independent Node VM test exposes only mocked Frappe calls, not a network or
site API inside the VM:

```sh
node zatca_erpgulf/zatca_erpgulf/tests/test_company_compliance_messages.js
PYTHONDONTWRITEBYTECODE=1 ../../env/bin/python tools/run_unification_rehearsal.py --private-sql
```

This verifies synthetic behavior, not actual browser rendering, an installed
v16 runtime, real authority acceptance or deployment readiness. Actual isolated
v15/v16 browser/language rehearsal remains a separately approved gate.

Final evidence: **12,443 guarded Python cases passed in 140.86 seconds**
(10,643 local + 1,800 private SQL in the existing twelve owned-private suites),
plus **84 standalone synthetic Node VM cases**. Network/site initialization
remained denied by the unchanged rehearsal guard. An initial UI assertion
incorrectly expected a PASS label in an all-failed table and another used a
different Arabic word than the catalog; both assertions were corrected without
weakening the message, outcome, raw-data or no-network contracts.
