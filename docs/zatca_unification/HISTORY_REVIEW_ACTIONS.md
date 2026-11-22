# Operator capture and audit actions

Workstream2, development only,2026-11-22. The existing inactive legacy review now
has fixed local Desk actions using the actual capture/audit services. No installed
site/schema/asset, invoice, counter, service or authority API was changed.

## Workflow

Open an existing current inactive LEGACY_REVIEWED Issuing Chain as System Manager.
The form offers:

1. **Capture Next History Page**: the server derives the next cursor from its
   authenticated head, saves at most one bounded page and reports cumulative
   captured/unresolved counts. An exhausted capture returns a distinct notice,
   never an empty appended page or an approval result.
2. **Audit Captured History**: starts or resumes one bounded backward segment.
   A completed checkpoint returns its saved report with its original UTC time.
3. **Restart Captured History Audit**: confirms replacement of derived audit
   progress, then requests a fresh check from the current authenticated head.
   Captured pages/review/originals remain retained.

The result is one aggregated message. Audit summaries include checked/remaining
pages, missing positions, unresolved sources, broken declared PIH links, rotated
keys and initial PIH match. They explicitly distinguish saved evidence from
activation/ZATCA acceptance. Display uses the current user's translation catalog;
the app supplies Arabic strings. Diagnostics retain static English codes only.

Refresh never starts work. There are no timers, automatic continuation loops,
worker jobs, authority requests or invoice/customer creation. Each page/segment
needs another deliberate action. The browser blocks duplicate in-flight clicks,
dirty forms and stale form/result callbacks. This is synthetic Desk qualification,
not an installed/browser or performance claim.

## Server boundary

The POST action accepts only review ID and one fixed operation. It does not
accept invoice fields, XML, File path, counter seed, reason, cursor or approval.
A clean owned read scope requires System Manager and current chain/source/
Company/counter/File READ plus selected owner READ+WRITE. Public header metadata
only locates saved rows until the root review is authenticated; permissions
precede root XML decryption. The namespace key-check probe still runs normally.

Source identity, anchor File/checksum, retained review reason and continuation
cursor come from authenticated saved custody. After the read scope releases its
locks, the actual owned review service rechecks its current issuer/counter/tail/
source/attachment/proposal binding. A preflight observation never grants a lease
across that boundary. An intervening permission/configuration/review change holds.
Only that actual service may commit a new page/checkpoint. Preflight cannot commit
or roll back foreign writes/callbacks; dirty parents are refused intact.

Public failures suppress child messages and produce one translated static error.
Unknown commit acknowledgment remains uncertain, with retained metadata available
to the next explicit invocation. No raw XML/review reason/key/token/SQL/parser
exception enters output or logs. The endpoint is not an archive XML export.

## Prerequisites and remaining gates

Initial review creation is still the internal reviewed-registration service; these
buttons do not manufacture a proposal or authorize migration from old settings.
The source-only native metadata/storage must already be installed and initialized
in a separately approved isolated acceptance environment. These actions perform
no bootstrap/install and expose no bypass for missing storage, active/superseded
reviews or unsupported owners.

The capture/audit limits and saved-report semantics remain those documented in
[NATIVE_HISTORY_CAPTURE.md](NATIVE_HISTORY_CAPTURE.md) and
[NATIVE_HISTORY_AUDIT.md](NATIVE_HISTORY_AUDIT.md). This operator adoption does not
prove complete archived/physical history, calculated hashes/signatures/SDK, drained
workers, correct initial/new-CSID epoch, safe activation or real ERP15/16 behavior.
The renewal plan is separately corrected in
[CSID_COUNTER_EPOCHS.md](CSID_COUNTER_EPOCHS.md). Workstream2 remains open.

## Qualification

Local tests exercise the fixed command contract, invalid operations, metadata-only
results, exhausted captures, translated aggregate messages, English diagnostics,
unknown commit preservation and Arabic catalog. Private SQL tests exercise actual
capture/audit/replay/restart for Company/device/delegated owners, access before
root XML decryption, active-review refusal, access changes after preflight and
preservation of foreign writes/callbacks. Synthetic JavaScript VM checks cover
both display languages, explicit POST, duplicate clicks, restart confirmation,
stale/dirty/new/active/role/slot/version conditions and recovery after RPC failure.

Exact final counts/logs are recorded in STATUS. HTTP/ERP data remain doubles;
private SQL uses only fixture-owned `/tmp` Unix sockets with TCP disabled. No
financial/golden reference was changed and original240 remains91/117/32.
