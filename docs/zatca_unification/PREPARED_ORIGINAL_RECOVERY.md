# Explicit queueing of an untouched saved original

Workstream2 source development,2026-11-21. No live source, tenant/schema,
invoice, worker/service or authority API was changed or invoked. Actual installed
ERP15/16 and dummy-company rehearsals still need their specific authorization.

## Operator behavior

The readonly ZATCA Issuance form now offers **Queue Saved Original** for PREPARED
records without an active attempt. This supports a Standard original whose
process stopped before dispatch, a Simplified Live original in the same condition,
and a deliberate manual send for Batches/Background. Existing automatic Background
discovery remains unchanged. This is an explicit new manual authorization by the
current operator, not implicit recovery under another user's identity.

Normal DocType JS loading supplies the button; there is no global asset hook or
new schema. Nothing happens on refresh. A System Manager confirms one specific
immutable issuance ID, with dirty/navigated forms excluded. The POST receives only
that ID. The result is one translated blue notice with an action to open the new
Submission Intent. It says DEFERRED / accepted=False, never authority acceptance.
The request is queued only after parent commit, not by generic ledger form save.

## Canonical admission and shared execution

The server verifies native rollout, System Manager, source READ+WRITE and Company
READ. A clean owned read scope rejects foreign parent writes/callbacks; index
metadata locates a source but cannot grant send authority. Canonical retained
reading then authenticates current source/child fiscal projection, chain/version,
UUID/ICV and exact original. The selected record must still be the latest native
original, PREPARED with no active attempt. No age cutoff, Customer-based
reclassification, credential export or source edit is introduced.

After releasing only that owned read scope, the service uses the existing borrowed
manual collection registrar on the parent transaction. It pins expected_issuance_id
to the selected original and uses the same immutable actor/source header, nullable
active slot, before-commit finalizer, after-commit enqueue and fixed worker. No
parallel queue, allocator, builder or transport was added. Source/Company policy
and current signing/route/issuer requirements are checked again by the worker.
Current phase/enablement or rollout changes are not overridden.

The worker must reuse that exact original. Missing/replaced custody or fiscal
drift cannot fall back to new generation; rejected/unknown/in-flight custody does
not authorize retry. If another worker completes the same original between
preflight and staging, the command resolves the matching saved receipt without
another send. Repeated requests coalesce on the existing active manual slot.
Rollback removes the staged command and makes retained queue callbacks inert;
after-commit queue loss remains recoverable by the existing READY rediscovery.

| Current evidence / policy | Effect |
| --- | --- |
| Untouched PREPARED, normal ACL and enabled Phase2 | Register manual version-pinned request |
| Simplified Background outside its window | Explicit manual operation may dispatch, matching existing manual behavior |
| Accepted before this action | No new recovery request is needed; view its saved result |
| Rejected, unknown, reserved/in-flight or fallback state | Review, no blind retry |
| Missing/damaged original, source mismatch or denied access | Review, no regeneration |
| Company Phase1/disabled or native rollout off | No override / no new send |

This does not turn all prepared records into automatic delivery. Batches remains
manual, and automatic non-Background first-send discovery with authenticated
origin/actor policy remains open. The new action deliberately does not select a
new actor for an old stored request; it records a fresh explicit manual command.

## Verification and remaining gates

Private SQL covers Sales/POS, all three owner forms, Live/Background/Batches and
Simplified/Standard; exact sent request hashes and retained UUID/ICV/XML/counter;
no builder call on recovery; Standard303's bound two calls with identical bytes;
parent rollback/coalescing; accepted-original races; missing custody; reserved/
unknown/rejected states; role/source/Company permissions; rollout/phase changes;
fiscal/ciphertext corruption; and preserved foreign parent writes. Synthetic Desk
VM covers English/Arabic, explicit confirmation, role/state/dirty/navigation gates,
one result and fixed request navigation. Final evidence is in STATUS.md.

Fixtures own only temporary Unix-socket SQL with TCP disabled. ERP/accounting,
financial metadata/signing and HTTP remain doubles. No financial reference changed;
the original240 comparison remains91 identical/117 review/32 blocked.

Still open in2: automatic first-send recovery outside Background with origin/actor
binding for old originals without evidence, unknown/late/unsealed handoff resolution and exact retry operator paths,
corrected-clock/rejection adoption, historical inventory/drain and actual chain
activation, frozen print master/File consumers, whole canonical mixed runtime,
and installed lifecycle/GL/File qualification. Workstream2 is not complete.

The subsequent [origin-backed discovery](ISSUANCE_ORIGIN_RECOVERY.md) now supplies
automatic first-send recovery for newly captured DISPATCH origins under their
original enabled actor. It also requires origin for deferred Background discovery;
old NULL-origin rows retain this explicit manual action. No authority, installed
schema or live policy was changed by either development bundle.
