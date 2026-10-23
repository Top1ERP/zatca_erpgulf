# CSID forms without implicit save/reload

Increment 76, 2026-10-23. Development only. No installed source/assets, site,
schema, Company/credential data, Bench/worker or authority action.

## Observed issue and workflow change

Company Final-CSID and both device CSID handlers saved the client copy after
server credential writes. Company Compliance saved dirty input first and then
fully reloaded the form. The inspected Frappe 15 `check_if_latest` normally
refuses stale saves; this can cause a save conflict after successful issuance,
not proof that normal Frappe silently overwrites newer credentials. Full reload
removes the document from locals and can lose edits made while waiting.

All four buttons now use one runner requiring an active saved, explicitly clean
form and observed revision. **Users save OTP/environment/settings manually before
CSID creation.** No automatic pre/post-save, full reload, credential sync or source
assignment remains in these handlers. Frappe's timestamp protection is untouched.
The server's existing single success popup adds translated review/reload guidance.
The English status/purpose/message JSON-string contract is unchanged; no credential
or notice field is added to that result and the wizard still consumes it normally.

## Metadata, pending and review

Company uses captured abbreviation/environment. Device reads only `abbr` and
`custom_select` for its exact linked Company through ordinary permissioned
`frappe.client.get_value`, replacing the two full-Company reads in these handlers.
The inspected API checks permissions and uses its normal filtered list path.
No complete Company, OTP, certificate, key, auth value or complete device form
is requested/copied. Other application Company reads are not changed here.

After the device lookup, the runner rechecks the captured document object,
identity, modified value, link, abbreviation/environment, active route/form and
clean state. Changed/dirty/moved/unknown sources cancel before the CSID RPC.
Missing/throwing state helpers fail closed. This does not atomically pin the
linked Company's own concurrent revision or replace server source/epoch checks.

One pending promise per form coalesces clicks across both CSID buttons. Once
the credential RPC is entered, the original document object is marked for review
on success, rejection, framework exception, malformed reply or unknown delivery.
Another CSID click on it is refused. Review takes precedence over dirty-input
save guidance: a stale dirty copy is not instructed to save just to retry.
Metadata-only lookup failure does not mark a credential attempt and allows a
later explicit lookup. No automatic request retry is added.

These WeakMap/WeakSet guards are **in-memory UI policy only**. A new document
object, new tab/session, page reload or direct API call is not a durable hold.
Object replacement is not proof of fresh saved data or remote outcome review.
There is no cross-tab lock, authorization grant or credential activation decision.

The server owns the success notice; the client adds no duplicate success popup
or raw reply display/return. Malformed replies get static review text; framework
errors keep their owner. Navigation or edits while waiting cause no form write
or reload when the RPC returns. Raw XHR/errors are not stringified. Arbitrary
custom hooks/partial output are not an atomic one-dialog guarantee.

## Deliberate limits

Increment 76 covers the four Company/device CSID handlers. Increment 77 extends
their shared runner to both CSR handlers with key-replacement consent; see
[CSR_FORM_LIFECYCLE.md](CSR_FORM_LIFECYCLE.md). Increment 78 adds coordinated
Company configuration draft staging; see [CSR_CONFIGURATION_DRAFT.md](CSR_CONFIGURATION_DRAFT.md).
Device single-check and broader wizard/form save/read/log behavior remain gates.
The guard does not override manual/programmatic saves, disable a form, clear
messages or bypass timestamps. Fields may remain stale until deliberate reload;
users must preserve wanted edits first. A later manual reload is not protected
by an automatic merge or guaranteed edit recovery.

Ignored-permission server writers, saved-field access, credential epochs/rotation,
protected receipts and full framework log/debug/read/export/retention policy
remain gates. No persistent field/role/schema, auth/routing/timeout/acceptance or
credential storage policy changes. Installed v15/v16, browser/realtime behavior,
permissions/hooks and SDK/authority acceptance remain separately approved gates.

## Offline evidence

Eight added guarded Python cases verify real English/Arabic Company/device/
purpose success guidance within the same popup and unchanged English results.
Earlier mocked writer/route/auth/error assertions remain; no manifest changes.

The new Node VM script evaluates actual Company/device handlers in 312 cases:
dirty/new/inactive/unsupported forms, metadata-only lookup, observed source
changes/cancellation, cross-button click coalescing, edits/navigation while pending,
framework exceptions, malformed replies, unknown delivery, review precedence,
no save/reload/source mutation and explicit fresh-object behavior. Older Company
framework-error tests now require an RPC, avoiding guard-only false passes.

```sh
node zatca_erpgulf/zatca_erpgulf/tests/test_company_compliance_messages.js
node zatca_erpgulf/zatca_erpgulf/tests/test_debug_messages.js
node zatca_erpgulf/zatca_erpgulf/tests/test_debug_ui_lifecycle.js
node zatca_erpgulf/zatca_erpgulf/tests/test_csid_messages.js
node zatca_erpgulf/zatca_erpgulf/tests/test_csid_form_lifecycle.js
PYTHONDONTWRITEBYTECODE=1 ../../env/bin/python tools/run_unification_rehearsal.py --private-sql
```

Final guarded Python: **11,664 local + 1,800 private SQL = 13,464 passed in
161.29 seconds**, across the same twelve owned-private suites. Node: **724
synthetic cases** (108 Company, 60 Debug messages, 164 Debug lifecycle, 80 CSID
messages, 312 CSID forms). No guard, normal permission or acceptance policy is
waived and no real site/browser/authority request or v16 runtime is exercised.
