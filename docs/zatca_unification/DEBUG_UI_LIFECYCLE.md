# Debug attachment presentation without invoice reload

Increment 72, 2026-10-23. Development worktree only. No installed application,
asset build, site, schema, worker, customer or authority action is authorized.

## Why this changes

The inspected Frappe 15 `form.js` reload implementation removes the document
from locals before loading it again. Checking that a form is clean before a
reload would not protect edits made while that reload is pending. Both Debug
menus therefore stop calling `frm.reload_doc()` entirely. This is not a change
to ordinary submission, financial calculations, XML signing or QR routing.

The menus use one shared `zatca_run_debug` wrapper. An unsaved/dirty or inactive
invoice form is refused before the request; the user chooses when to save.
There is no implicit invoice save. Concurrent clicks on the same form share
one pending promise; the pending entry is released when it settles. This is
only in-memory click coalescing, not durable request idempotency or permission
to resend after uncertain delivery. A later explicit click is a new operation.

## A single result, a bounded metadata update

After creating the File once, the backend freshly rechecks saved invoice and
Company revisions, actor and normal ACLs, then requires normal File READ before
returning attachment metadata. Only the File name, filename, a bounded local
private-file URL, privacy and parent identity are projected. No XML, credentials,
QR body or invoice financial payload is added. Observed metadata mutations in
the permission callback require review; a new source/ACL check follows it.
The earlier filename-only helper remains for internal compatibility.

Only `/private/files/<ASCII filename>` URLs and bounded ASCII alphanumeric/
underscore/hyphen File IDs are offered for automatic list updates. The inspected
stock attachment renderer embeds the ID in a link. Unsupported IDs/provider
URLs yield `attachment: null` with confirmed
creation, not an automatic second request. READ denial or observed post-save
source/actor/ACL drift yields review; already possible physical/File/comment
effects are neither retried nor cleaned up. These are observed checks, not
atomic locking, storage authenticity or rollback guarantees.

The client binds the result to the captured document object, identity, active
form and route. On the same form it validates parent/privacy/filename/local URL
and passes four whitelisted metadata fields to the existing
`frm.attachments.update_attachment` API. It never calls `attachment_uploaded`,
which can set an invoice field/reload docinfo. It never replaces all docinfo,
fetches another invoice, or performs a metadata RPC. The inspected Frappe 15
attachment API deduplicates by File name and refreshes the sidebar list only.

If the user edits while waiting, those fields stay untouched and the summary
explains that Debug used the saved invoice. If the active form changes, no
attachment update is attempted on that form; the summary names the original
invoice. If metadata is missing/unsafe or the list refresh fails, confirmed
creation stays success with an orange manual-review notice. The user must not
regenerate only to refresh the list. Transport uncertainty asks the user to
review existing attachments first. Framework-owned errors do not get a second
app-owned dialog. No automatic regeneration or lookup is attempted.

All notices appear in the same summary, translated only for display. Arabic
catalog entries cover guards, deferred edits, switched forms and refresh review.
Server status/message/notices remain English and original technical details
are not translated or rewritten. UI-only notices are added to a copy.

## File-hook review and remaining gates

Read-only inspection of local Frappe 15 File/Comment sources found normal
physical save/dedup and rollback callbacks, Attachment comments and after-commit
realtime notification. The ordinary Attachment comment path does not obviously
change invoice `modified` in those sources. This does not execute or certify
any installed hook. Custom hooks may still write/commit/change the source;
post-save rechecks refuse observed drift without promising to undo it.

Real File/physical rollback, dedup/storage providers, history/attachment limits,
custom hooks, realtime events and actual Desk navigation/language behavior need
separately approved isolated v15/v16 lifecycle rehearsal. No installed v16
runtime, browser, ZATCA SDK, remote compliance or authority acceptance has been
tested here. Crypto and production adoption remain separate gates.

## Offline checks

The unchanged fixed-manifest guarded Python selection covers both real Debug
entry bodies with mocked ERP/crypto/File/transport, plus explicit v15/v16-shaped
ACL engines and both invoice types. New cases cover metadata projection, literal
File READ, unsupported URLs, post-save hook drift and mutation during READ.
No guard, normal permission rule or private-SQL ownership check is relaxed.

Network-free Node VM checks evaluate the actual menus and common runner:

```sh
node zatca_erpgulf/zatca_erpgulf/tests/test_company_compliance_messages.js
node zatca_erpgulf/zatca_erpgulf/tests/test_debug_messages.js
node zatca_erpgulf/zatca_erpgulf/tests/test_debug_ui_lifecycle.js
PYTHONDONTWRITEBYTECODE=1 ../../env/bin/python tools/run_unification_rehearsal.py --private-sql
```

The standalone UI checks pass 332 synthetic cases: 108 Company, 60 Debug menu/
message and 164 Debug lifecycle cases, across English/Arabic and Sales/POS.
No browser or site API/network is exposed inside the VM. Full Python evidence
is recorded in [STATUS.md](STATUS.md).

Final guarded Python result: **11,293 local + 1,800 private SQL = 13,093 passed
in 141.30 seconds**, using the same twelve owned-private SQL suites. This adds
140 local cases, without changing the manifest or any safety guard.
