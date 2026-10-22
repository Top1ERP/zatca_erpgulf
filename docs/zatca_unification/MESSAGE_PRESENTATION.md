# Operation summaries and display-only translation

Increments 68/69 implement the user's message policy in the development worktree.
It is not an installed asset change or a deployment authorization.

## Adopted boundaries

- Company `custom_run_all_compliance` and
  `custom_run_zatca_onboarding_checks` use one server-side result collector and
  one client-side summary presenter. Each requested document type keeps its own
  outcome; one failure does not erase the other five results.
- Increment 69 adds Company `custom_check_compliance` through
  `run_single_compliance_summary`. It checks normal Company/Sales Invoice READ
  permissions before sample preparation, reads the saved Company selection,
  preserves the existing numeric `1` fallback, and executes exactly one check.
  The Company identity, not the entire unsaved form/credential fields, is
  supplied to the existing generator. No type setting is written. The legacy
  Sales/POS compliance entry points and their current callers remain available.
- Increment 69 adds the existing Sales/POS `Create XML for Debug` menus. Public
  signatures are preserved; request-local muting encloses the original local
  generation/logging behavior. App-owned notices become canonical English
  fields instead of separate server popups. Both menus now render skipped and
  failed results too, instead of silently ignoring returned error dictionaries.
  Existing success attachment reload remains; framework-owned infrastructure
  errors are not globally intercepted or suppressed.
- Shared display functions now live in `public/js/operation_messages.js`,
  declared once in development `app_include_js`. The request-local context is
  shared by compliance and Debug in Python `operation_messages.py`. This is
  source-only; no installed assets/cache/build/Bench change was performed.
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

Debug returns `status` (success/skipped/error), English `message`, English
`notices`, a separate `file_name` on success, and original `technical_details`
on failure. In particular, disabled POS Debug now returns a structured skipped
result instead of None plus a misleading submission popup: it still does not
generate XML. Disabled Sales Debug still generates locally with a notice. This
does not align or change the two existing settings policies. Same-taxpayer
intra-company transfers still skip generation. An existing issued XML/QR notice
does not silently skip the current separate Debug generation/replacement path.

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
Ordinary invoice/POS submission, direct legacy single-check calls,
background/retry, CSR/CSID server wrappers and other diagnostic writers still
require explicit migration. In
particular, an existing certificate-generation success popup containing a raw
certificate response is not changed or certified safe by this increment; a
separate redacted onboarding-result contract is still required. Legacy localized
exception strings are retained as original technical details, not automatically
reverse-translated. Other legacy logging calls are not claimed to be English.
Do not globally intercept `frappe.msgprint`, force English for a whole request,
clear unrelated notifications, or reuse translated display HTML as log content.

Increment 69 adds one authenticated presentation endpoint around the existing
single-check operation, not a new transport path. No new transport call,
credential-selection policy, retry, certificate issuance, signed XML/QR/PIH/ICV,
accounting/advance, schema or live change is made. Tests stub every submission;
the agent does not invoke any real button or authority endpoint.

Message consolidation did not certify Debug attachment safety. Increment 71
replaces ignored-permission deletion/save with normal ACLs and non-destructive
uniquely named private attachments; physical File/hooks/rollback, retention and
reload remain adoption gates. See [DEBUG_ATTACHMENT_ACCESS.md](DEBUG_ATTACHMENT_ACCESS.md).
Source inspection also found the old POS Phase-2
Background branch referred to undefined `bypass_background_check`. Increment 69
made this existing returned error visible but did not repair it. Increment 70
removes the unused POS selector and its undefined read, preserving the actual
type/preflight rules; Sales Debug type selection is unchanged. Real File/reload
and installed framework lifecycle still need review before adoption.
See [POS_DEBUG_LOCAL_ROUTING.md](POS_DEBUG_LOCAL_ROUTING.md).

## Verification

The fixed-manifest Python runner includes the collector, both batch buttons,
the real single-summary boundary and generator integration, READ-denial and
cross-Company refusal, both real Debug bodies with mocked ERP/signing/I/O,
flag restoration/interruption, unchanged raw diagnostics, warnings, English
labels under Arabic, settings policies and existing acceptance regressions.
The independent Node VM test exposes only mocked Frappe calls, not a network or
site API inside the VM:

```sh
node zatca_erpgulf/zatca_erpgulf/tests/test_company_compliance_messages.js
node zatca_erpgulf/zatca_erpgulf/tests/test_debug_messages.js
node zatca_erpgulf/zatca_erpgulf/tests/test_debug_ui_lifecycle.js
node zatca_erpgulf/zatca_erpgulf/tests/test_csid_messages.js
PYTHONDONTWRITEBYTECODE=1 ../../env/bin/python tools/run_unification_rehearsal.py --private-sql
```

This verifies synthetic behavior, not actual browser rendering, an installed
v16 runtime, real authority acceptance or deployment readiness. Actual isolated
v15/v16 browser/language rehearsal remains a separately approved gate.

Increment 68 evidence: **12,443 guarded Python cases passed in 140.86 seconds**
(10,643 local + 1,800 private SQL in the existing twelve owned-private suites),
plus **84 standalone synthetic Node VM cases**. Network/site initialization
remained denied by the unchanged rehearsal guard. An initial UI assertion
incorrectly expected a PASS label in an all-failed table and another used a
different Arabic word than the catalog; both assertions were corrected without
weakening the message, outcome, raw-data or no-network contracts.

Increment 69's UI evidence is **108 Company cases + 52 Sales/POS Debug cases =
160 synthetic VM cases**. The actual menu callbacks are evaluated with a mocked
framework, while full invoice script sources are syntax-compiled without
executing unrelated callbacks. Both languages, one app-owned summary, literal
original diagnostics, HTML escaping, warnings/skips/failures and unchanged
payloads are covered. This is not browser/Desk/framework lifecycle proof.
An initial disabled-POS test incorrectly called Mock assertions on a real
function; a fail-if-called mock now checks that generation is actually avoided.
No application safety assertion or offline guard was weakened.

Final increment 69 combined evidence: **10,682 local + 1,800 private SQL =
12,482 Python cases passed in 142.98 seconds**, with the same twelve owned-private
SQL suites and the fixed offline guard. There are 39 additional local cases.
An intermediate complete run passed 12,479 before three final integration/
characterization cases. The added integration first failed because its nested
Frappe HTTP type wrapper required request-local framework flags; the fixture
now unwraps only that decorator, just as the outer site-free boundary tests do.
The real generator body, source-company refusal and all acceptance/ACL checks
remain exercised. No site was initialized or guard bypassed to make it pass.

Increment 71 adds canonical English deny/review notices with Arabic display
entries and normal saved-source/Company/File ACLs. It deliberately replaces old
Debug-file deletion with uniquely named private attachments preserving history;
the message contract otherwise remains. Evidence: **12,953 guarded Python
cases in 141.65 seconds** and **168 synthetic UI cases**. Actual File hooks,
physical rollback, retention, UI reload and installed v15/v16 remain separate
gates; see [DEBUG_ATTACHMENT_ACCESS.md](DEBUG_ATTACHMENT_ACCESS.md).

Increment 72 removes both Debug invoice reloads and adds localized guards and
UI-only notices to the same summary for dirty/inactive forms, edits during the
request, moved forms and failed attachment-list refresh. Creation is not repeated
to refresh metadata; generic uncertain transport asks for attachment review
first. Raw server data is unchanged. Synthetic UI evidence grows to 332 cases
(108 Company, 60 Debug menu/message, 164 lifecycle). See
[DEBUG_UI_LIFECYCLE.md](DEBUG_UI_LIFECYCLE.md); this is not installed Desk proof.

Increment 73 removes raw CSID success material from popup/return. One private
purpose-only presenter emits English JSON-string metadata and one translated
notice after save. Wizard result fields display known translated text read-only;
old/raw replies are not copied. The 80 new VM cases bring standalone UI coverage
to 412. Failures/logs/traces, credential storage/access/rotation and CSID caller
save/reload remain separate gates. See
[CSID_SUCCESS_PRESENTATION.md](CSID_SUCCESS_PRESENTATION.md).
