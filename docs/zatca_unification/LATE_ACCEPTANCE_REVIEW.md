# Explicit acceptance review of a superseded response

Workstream2 development,2026-11-21. This package is source-only and qualified
offline. No installed schema, tenant, actual invoice, service or authority API
was changed or invoked. Installed ERP15/16 and actual dummy-company rehearsals
retain their separate gates. This does not close workstream2.

## Operator workflow and admission

The readonly ZATCA Issuance form offers **Review Late Acceptance** for a current
DISPATCHING/OUTCOME_UNKNOWN original. A System Manager chooses an earlier saved
response from the Attempt link and confirms a local review. The fixed POST
receives only issuance ID, reviewed current attempt/revision and candidate ID.
The actor, source, Company, chain, credentials, body and desired outcome cannot
be supplied by the caller. Desk guards dirty/navigation/revision changes and
shows one result in English or Arabic. Diagnostics remain static English codes.

The owned service requires source READ+WRITE/Company READ before opening private
custody. Under chain/source/issuance locks it reruns the existing canonical current
fiscal projection and latest-version selection. It authenticates the named older
response and exact original with the same endpoint/environment/returned-XML matcher
used for ordinary native delivery. A generic200 is insufficient. The existing
Production clearance208 and Reporting409 rules apply without new normalization.

The newer attempt must satisfy the same shared explicit-retry eligibility:
expired unknown/unreceived reservation, or encrypted matching retained technical/
authentication failure. That gate is repeated during decision staging. Expiry
alone is not proof of nonreceipt. Another active chain reservation, unexpired
unknown, validation rejection, contradictory/unassessed current response, changed
source/version or denied ACL keeps review. The accepted candidate must be an
earlier attempt of the same original and operation. A Standard Reporting candidate
still needs its bound captured303 fallback. An older UUID/version cannot settle
the latest version; different operations do not override one another here.

## Protected decision, unchanged technical history

The late acceptance and the newer technical attempt remain separate facts. The
original active_attempt pointer stays on the newer attempt; no attempt number,
fence, encrypted response, original/header/AAD, UUID/hash/ICV/PIH or source amount
is overwritten. Two optional hidden readonly Long Text columns retain a separate
late-acceptance AEAD decision. The proof binds original/chain/artifact, selected
older receipt digest/fence, newer attempt/fence, prior state/revision, server actor/
UTC and canonical acceptance outcome. These are source declarations only, not
installed DDL or historical backfill. Older originals with both fields NULL retain
their existing current-receipt selection.

The older response assessment, decision and issuance accepted state commit
together. Only the matching newer chain reservation may be released; no other
source's reservation or generated chain head changes. Authenticated readback must
succeed before commit. A lost commit acknowledgement performs no compensation;
an explicit repeat using the original reviewed values freshly checks source/
custody/ACLs and returns the same decision. A repeat cannot choose another receipt.

The shared acceptance selector is adopted by the canonical retained reader and
source status projector. They authenticate the decision/attempt bindings and
rerun ordinary receipt/XML assessment. Missing, damaged, copied or contradictory
proof does not fall back to a different receipt. The retained view names the
selected acceptance attempt while the technical journal keeps its newer pointer.
A stopped Submission Intent can then reconcile through that same accepted view.
The existing cached accepted operation can project the exact selected raw response
without signing or sending, including after the signing key becomes unavailable.

An already-reserved worker may still start or finish transport after the local
decision; expiry and the local review cannot cancel a remote invocation. Its
response remains on its own attempt and cannot overwrite the reviewed accepted
state or proof. This review neither guarantees remote deduplication nor grants
an automatic retry, new corrected version or historical repair. Source status
projection remains the existing separately owned operation, not part of this
review transaction.

## Evidence and remaining work

Private SQL covers Sales/POS, Company/device/delegate owners, Standard clearance,
Reporting after303, Production208/409, received503 without lease rewriting,
unexpired/other-chain holds, contradictory newer400, stale review, roles/write/
fiscal/custody failures, late second response, stopped request reconciliation,
cached no-send projection, corrupted proof, truncated readback, parent writes and
lost commit acknowledgement. HTTP, ERP and signing inputs are synthetic; SQL is
fixture-owned private Unix MariaDB. Actual Desk source runs in English/Arabic VMs.
Counts/logs are in STATUS.md. No financial reference or original240 comparison
(91 identical/117 review/32 blocked) changed.

Remaining2 includes corrected-clock/rejection operator adoption, historical
inventory/drain and activation, frozen master/File/external print paths, wider
historical/contradictory response review and whole canonical mixed runtime
qualification. Installed, authentic SDK and actual pilot acceptance are separate.
