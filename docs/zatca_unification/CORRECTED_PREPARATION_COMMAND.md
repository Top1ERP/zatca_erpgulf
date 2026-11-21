# Durable corrected XML preparation, separate from delivery

Workstream2 source development,2026-11-21. All implementation/qualification is
offline in the isolated worktree. No live site/source/schema/service, installed
Company or actual invoice was changed and no authority API was invoked. Installed
ERP15/16 and actual dummy-company rehearsals retain their separate gates.

## Deliberate local operator workflow

The readonly ZATCA Dispatch Attempt form offers **Prepare Corrected XML** for a
retained validation rejection. It is a separate choice from **Request Exact Retry**:
unknown/technical attempts do not acquire correction authority. Server eligibility
remains authoritative; a displayed mutable label alone is not a rejection proof.
The confirmation explains new UUID/counter, retained original, unchanged posting
fields and no sending. Only issuance/attempt/fence identifiers enter a fixed POST.
Dirty, navigated or rebound forms do not submit stale decisions. One blue pending
message and View Request action are translated at display time into English/Arabic.

Registration requires System Manager, current native rollout/enabled Phase2,
source READ+WRITE/Company READ and a clean owned preflight. It verifies the latest
rejected version, saved source output binding, exact400/canonical assessment,
approved attempt fence and bounded coherent earlier history. The existing
[history/clock rules](CORRECTION_HISTORY_AND_CLOCK.md) remain mandatory. Source
fiscal data may have been explicitly corrected since the rejected XML; registration
approves its **current saved** projection, not an old original or client document.
No customer or ERP Sales/POS Invoice is created or financially edited.

The new command uses the existing Submission Intent store, nullable unique active
slot, callback arming and fixed worker. The correction-v1 header and separate
correction-intent AEAD body bind actor/source/Company/chain/fiscal projection,
expected rejected version and rejected attempt/fence. Two nullable readonly indexed
Data fields must match those new header values. Old original/collection/recovery/
retry headers, bodies, AAD and active-slot hashes remain unchanged with NULL new
indexes; no old authority shape can claim correction intent. These are source
declarations only, not installed schema migration or history backfill.

## Parent and worker ownership

After clean preflight ends, staging borrows the parent's current connection and
never commits or rolls it back. Current source/Company permissions, phase/rollout/
role, fiscal projection, original/attempt/fence and prior history are rechecked
before commit. Parent rollback cancels only the local request. Queue access occurs
after the real parent commit; a lost queue registration leaves READY for existing
original-actor recovery. Explicit repeated approval coalesces on the exact slot.
An old REVIEW request can release its slot only after a fresh explicit request and
fresh eligible rejection; its header/ciphertext/state are retained.

The fixed worker claims the authenticated command with its normal fence and enabled
actor. The correction branch uses the existing owned preparation backend rather
than the ordinary delivery provider. It repeats current source/claim/permissions
and requires the approved rejected fence again under the actual generation locks.
The server selects the current correction clock at generation time; no client
date/time is queued. The actual Sales/POS builders consume the immutable ticket.

The result is one linked PREPARED original: new UUID/hash/next local ICV/current
generated PIH, old original/receipts retained, no ERP posting/financial change and
no transport. It deliberately has no automatic generation-origin delivery grant.
The request can finish COMPLETE with result_code=prepared and accepted=False;
COMPLETE is local preparation, not authority acceptance. Sending still requires
the separately authorized existing explicit saved-original/manual workflow.

## Crash, stale work and saved-result recovery

Generation rechecks the immutable request's RUNNING fence under the source lock;
a stale command cannot silently issue from another projection/version. Competing
commands serialize through the existing chain/source custody. A changed version
between preflight and creation holds review, never creates an extra version.

A worker stopping after original custody commits may find its linked new version
on resume. Only canonical current-source custody plus the exact replaces_issuance
link, consecutive source version, same source/Company/chain and authenticated
approved rejected receipt/fence/history can satisfy that request. Untouched
PREPARED completes locally; acceptance requires the ordinary canonical receipt
view. Unknown/in-flight/rejected or contradictory newer custody remains review.
No source-output proxy is constructed to impersonate the old rejected version.

The existing **Reconcile Saved Result** operator now admits this same verified link
when the request's expected version is the rejected predecessor. It retains the
immutable original command and writes its normal independent resolution proof.
Lost creation-commit acknowledgement preserves custody/head and permits explicit
reconciliation; no compensating deletion, counter/hash rewind or blind generation
is attempted. Already COMPLETE/REVIEW/RUNNING requests are not automatically rearmed.

## Evidence and remaining work

Local/private/Desk VM counts and log paths are in STATUS.md. Private tests cover
Sales/POS and owner variants, corrected source projection, parent rollback,
coalescing, before-commit/worker/actual-generation drift, role/phase/rollout/write/
receipt/fence/index denial, one linked version with no extra HTTP, queue loss and
actor recovery, stopped RUNNING/REVIEW reconciliation, resumed no-build reuse,
lost creation acknowledgement and explicit replacement of a failed unissued
command. They use fixture-owned Unix SQL and synthetic financial/signing/HTTP
inputs. The actual English/Arabic Desk asset is executed in an offline VM.

This adopts the durable correction operator; it does not close workstream2. Full
canonical mixed-runtime/currency/tax/advance/Debug/Compliance qualification,
historical inventory/drain/activation, frozen print/master/File consumers and
wider contradictory/history transitions remain. Installed GL/File, authentic SDK
and actual fictional-company/pilot acceptance retain their separate gates. No
financial reference or original240 comparison (91/117/32) was changed.
