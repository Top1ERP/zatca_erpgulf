# Authenticated initial requests and explicit stopped-stage retirement

Workstream2 source development,2026-11-21. All verification is offline in the
isolated worktree. No installed schema, site, Company, invoice, worker or authority
operation was performed. Installed ERP15/16 and actual dummy-company rehearsals
retain their separate authorization gates.

## Initial custody is not permission to execute

A before-commit callback can fail and be incorrectly caught by its enclosing
caller. A later commit may then leave a STAGED request. Previously neither draft
nor collection requests retained authenticated headers at this point. Ordinary
workers correctly refused them, but the explicit unissued-retirement action could
not verify their source binding either.

New draft requests now seal a small submit-stage-v1 header at insertion. It binds
record/source key, saved doctype/name, original actor, operation and creation stamp
in the separate submission-stage AEAD domain. It contains no Company, chain,
fiscal digest or acceptance claim. The normal before-commit callback authenticates
that initial capsule before replacing it with the existing complete v1 header and
submission-intent ciphertext. Later ERP writes are still included in that final
fiscal observation. Final v1 keys, AAD/body and worker behavior are unchanged.

New collection/recovery/retry requests already have their complete header at
insertion. They now retain that encrypted header immediately, in their existing
respective domain, while remaining STAGED. Finalization authenticates it before
changing the command to READY. The active-slot/index and expected-version bindings
are checked too. Finalization cannot overwrite damaged initial custody or promote
a previously retired stage. No new queue, store, columns or migration is added.

## One existing operator action

The readonly request form now also offers **Retire Unissued Request** for STAGED.
The same English/Arabic confirmation, fixed POST, expected claim, owned clean
transaction, System Manager/source READ+WRITE/Company READ and source/history
locks apply. Inspection opts into STAGED only at the internal finalization and
retirement boundaries. Normal reads, worker claim and automatic discovery still
reject an unfinished stage. A partial submit-stage-v1 header cannot be promoted
by relabeling its state READY/RUNNING/COMPLETE/REVIEW/WAITING; it lacks executable
fiscal/chain authority and the reader refuses that combination.

Retirement requires a current unclaimed stage, no saved egs marker and no issuance
for that source across chains. A collection that observed an expected original
cannot use missing custody as evidence of nonissuance. It retains the exact initial
header/ciphertext and adds the existing independent retirement proof, with
prior_state=STAGED and no prior fence. The nullable active slot is released, never
the record/source history. A resumed finalizer cannot overwrite RETIRED. Normal
source lifecycle checks admit only all-authenticated retired history and still
apply their ordinary permissions, accounting and link checks.

Old NULL/unsealed STAGED rows remain held. No header is manufactured from mutable
indexes, source repaired, historical record backfilled or operator exception
granted. Legacy reconciliation for such historical corruption remains a separate
review task. Closing a local unissued request neither proves authority acceptance
nor changes an invoice, XML, UUID, ICV, PIH, posting clock or financial amount.

## Verification

The new private-SQL cases cover actual failed-callback/later-commit paths, draft
and collection stages, Sales/POS and owner variants, role/write denial, copied or
corrupt binding, old NULL envelopes, claimed-stage refusal, original custody even
after marker erasure, missing expected custody, parent writes, lost commit
acknowledgement and resumed old finalizers. Local tests cover exact header/domain,
non-executability and proof binding. The actual Desk JavaScript runs in synthetic
English/Arabic VMs. Broader affected suites verify prior handoff, explicit retry,
publication and native dispatch behavior. Counts/logs are recorded in STATUS.md;
these doubles and fixture-owned Unix SQL do not prove installed GL/File/SDK or
authority acceptance. The original financial comparison91/117/32 is unchanged.
