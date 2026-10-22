# Permissioned, non-destructive Debug attachments

Increment 71 changes development source only. No working/production source,
assets, site, schema, permissions configuration, Bench/worker or authority action.

## Deliberate policy change

The old Sales/POS Debug code queried `DEBUG_INVOICE_%`, deleted matching File
rows with ignored permissions, then saved a replacement with ignored permissions.
The SQL LIKE underscores are wildcards, and a filename is not reliable evidence
of a file's purpose. A later save failure could also follow earlier deletions.

Both adapters now share `debug_artifact.py`. Each run uses a fresh opaque
`DEBUG_INVOICE_<random>.xml` name and normal `File.save()` permissions. There is
no old-file query/deletion, implicit replacement, permission override, helper
commit/rollback or retry. The actual framework filename is returned separately
from the canonical English result message. Invoice names are attachment
metadata, not filesystem path fragments.

This intentionally changes replace-on-run into history-preserving creation.
Existing diagnostic and signed/QR files are not selected for deletion. Repeated
runs can consume attachment limits/storage; standard File validation still
applies. Retention/cleanup needs a separately scoped, explicit operation, not
automatic prefix-based deletion. No existing files were deleted by this work.

## Access and rechecks

Before generation the adapter loads the exact saved invoice and linked saved
Company, requiring a signed-in non-Guest actor, normal invoice READ + WRITE,
Company READ, and File CREATE. The shared permission-signature helper supports
the inspected v15 `raise_exception` and v16 `print_logs` shapes without TypeError
fallback or Document.ignore_permissions shortcuts. A permission verdict must be
literal True. Missing rows, unknown engine signatures and malformed saved
identities/revisions fail closed with static English diagnostics.

These action permissions are checked even if the later invoice/settings checks
would skip generation. The endpoint is an attachment action, not a permissionless
invoice inspection. Roles previously relying on ignored permissions may now need
ordinary permissions; no role configuration is changed automatically.

The binding records exact invoice/Company identity, their observed modified
values and the actor. Fresh loads and ACL checks run before File construction
and again before File.save. A constructor cannot redirect the observed parent,
privacy, filename/content or existing URL before the save. Post-save observed
metadata must remain a saved private File for that parent with no attached
invoice field or permission override. No invoice/Company fields are written by
this helper. Public Debug signatures, type/phase/tax/signing/QR logic are kept.

## Failure, language and limits

Denied/review results remain English data, with Arabic display-only notices in
the common presenter. Unknown loader/permission/storage fault text is not sent
to the UI. Its exception cause remains available to the existing server error
logger, which retains its English app label and original technical traceback.
Raw authority/technical text is not translated or rewritten into stored XML.

There is no retry, deletion or guessed cleanup after File.save/hook faults. A
File or physical write may already exist; normal parent ownership/framework
rollback policy remains responsible. Interruptions propagate. These rechecks
are **not atomic locks**, transaction epochs, authenticated source provenance,
cross-site/raw-handle pinning, or protection against every File hook. Changes
after the last check and hook-side commits/writes still require real lifecycle
review. Do not treat local success as authority acceptance or immutable issued
artifact authentication.

Frappe's File implementation can rename or deduplicate content and reuse a
physical private-file URL. Fresh app names therefore do not guarantee separate
physical storage. This increment does not override storage hooks or dedup rules.
Real File/physical rollback, retention, UI reload, scoped log access, isolated
v15/v16 application rehearsal and cryptographic/SDK acceptance remain gates.

Increment 72 removes the planned full invoice reload instead of guarding it.
Creation now also rechecks source/Company/actor/ACL after File/comment hooks;
normal File READ gates a bounded private attachment projection for sidebar-only
display. Unsupported storage URLs do not trigger generation again. These remain
observed checks, not atomic File-hook or physical rollback guarantees. See
[DEBUG_UI_LIFECYCLE.md](DEBUG_UI_LIFECYCLE.md) for client state, failure policy
and remaining actual framework/browser/custom-hook gates.

## Offline verification

The fixed manifest adds `test_debug_artifact.py`: explicit v15/v16-signature and
Sales/POS synthetic runtimes cover literal ACLs, Guest refusal, saved identities,
history preservation, normal File saves, pre/post-construction drift, post-save
partial effects, cancellation, path-independent names and redacted UI faults.
Existing real Debug entry/body tests use mocked ERP/signing/File/HTTP, including
denied permissions before generation and source/Company/actor drift before save.
The same 168 POS routing cases and all earlier regressions remain selected.

Node VM tests cover 108 Company + 60 Debug cases, including translated deny/
review notices and unchanged English/raw payloads. No site/network guard is
relaxed and no user button or authority endpoint is actually invoked.

Final evidence: **11,153 local + 1,800 private SQL = 12,953 guarded Python
cases passed in 141.65 seconds**, with the same twelve owned-private SQL suites.
The 280 additions cover 256 explicit runtime/ACL/attachment cases and 24 real
Debug entry/body cases using mocked dependencies. Node VM checks passed **168
cases** (108 Company + 60 Debug). Tests model normal saved File completion and
saved revisions explicitly; the old fixed-name expectations now check the actual
new filename. No guard or permission policy was waived to preserve old tests.
