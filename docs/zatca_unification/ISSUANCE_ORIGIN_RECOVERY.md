# Generation origin and automatic first-send recovery

Workstream2 development,2026-11-21. No installed schema/site, live source,
worker/service, invoice or authority API was changed or used. Installed ERP15/16
and dummy-company rehearsals retain their separate authorization gates.

## Captured authority, not inferred ownership

Canonical native generation now captures its execution-local delivery actor,
operation, action, method, Simplified/Standard decision and server UTC event time.
If generation runs under a durable request, its immutable header digest, record ID
and current claim fence are captured too. These values come from the checked
server contexts, not invoice owner/modified_by, a caller-supplied actor or a new
certificate. The time is audit metadata; it never changes the XML issue clock.

The optional issuance-origin AEAD capsule uses the existing site/namespace cipher
and exact artifact header as AAD. It is inserted atomically with the original,
chain advancement and source identity. Original artifact header/AAD, request/XML
bytes and financial observations remain unchanged. No parallel store was added.
Nullable readonly origin_actor/origin_action/origin_method index fields select
candidates; the capsule authenticates their exact values before admission.
origin_ciphertext is hidden/no-copy/print-hidden. These are source declarations,
not installed DDL, backfill, migration or rewriting of existing originals.

Normal retained publication does not require origin. Origin-sensitive reads
additionally verify the protected policy, original XML classification, and any
referenced durable request's actor/operation/header/fence and admissible state.
Trusted internal preparation without a delivery context retains NULL origin and
does not invent automatic authority. Missing or removed origin grants no automatic
send; direct explicit manual recovery remains available through its normal ACLs.

## Automatic first-send policy

| Protected origin / current state | Recovery actor and operation |
| --- | --- |
| DISPATCH and untouched PREPARED, same current method | Original enabled actor / recovery command |
| Original entry/submit Standard, including Batches/Background setting | Resume its original immediate-send policy |
| Original manual authorization, including Simplified Batches | Resume that manual operation under the original actor |
| Original scheduled DISPATCH | Original actor; repeat its current Background window |
| PREPARE for Background | Existing fresh scheduled operation under the scheduler's own ACL |
| PREPARE for Batches | Remain manual; no automatic send |
| Missing origin, disabled original sender, lost access or changed method | Hold; no actor substitution or inferred permission |
| Any active attempt, rejected/uncertain state or active expected-version command | No automatic retry/requeue |

The PREPARE/Background case is a separate existing Company schedule authorization,
not a resume of a stored user's DISPATCH command. It does not turn a deferred
original into a send that the original actor authorized. Immediate-send recovery
instead preserves the original principal and authenticates any original request
reference; it cannot silently substitute Administrator. An original user's later
permission/account change is checked before staging and again at worker claim.

The same collection header domain/store/fixed worker now accepts an internal
recovery operation only with an exact existing issuance ID. Plain v1 submit
headers cannot claim that operation. The worker opens origin, requires its own
actor to match DISPATCH, and uses the original operation for delivery policy under
the normal shared master locks. Changed method/classification or a return to
prepare-only does not send. An exact pre-transport scheduled window skip may WAIT;
unknown/rejected outcomes never become that harmless result. No new builder is
called, and authority attempts still use the existing independent artifact fence.

## Discovery and transaction boundaries

The existing recovery cron uses one shared prepared-discovery service for both
cases, with no invoice-age cutoff. It checks System Manager, current alias-aware
Company Phase2/enablement/method policy, normal source/Company ACLs, and candidate
origin. Disabled immediate senders and already active commands are excluded before
pagination. Up to100 commands are selected with100-row keyset pages, at most1000
rows examined,1024 Companies and16MiB decoded XML. Budget exhaustion is review,
not a claim of completed discovery. Candidate/byte limits do not rewrite dates or
assert tax reporting deadlines.

Only a clean owned discovery transaction is acquired; source/current original
locks end before command staging. Each candidate stages and commits one existing
after-commit command while its intended actor is active, then restores scheduler
session/permission caches. No borrowed callback crosses into the next actor.
Site, configured database/key and physical connection/socket stay pinned across
that transition. A failure before COMMIT can roll back only this acquired staging
transaction. Once commit is attempted, no compensating rollback is inferred.
READY survives queue failure and is handled by existing original-actor recovery.
No transport or signing runs in discovery, and no row lock spans HTTP.

## Intentional compatibility change and evidence

Earlier native Background discovery could schedule any untouched native original
from current Company policy alone. It now requires recorded origin too. Existing
NULL-origin rows and originals whose captured method differs from current policy
remain available for the explicit [manual action](PREPARED_ORIGINAL_RECOVERY.md),
without automatic backfill or guessed authorization. This change is development
source only; it was not applied to any live client.

Private SQL covers direct-entry and durable-request origin, Sales/POS and all
owner forms, immediate Standard and Simplified Live, deferred Background/Batches,
original manual recovery, current scheduled windows, disabled senders, lost write
access, changed settings, NULL/tampered origin, revoked request fences and queue
failure with actor restoration. Exact original bytes/UUID/ICV and one generation
are preserved, with HTTP/signing/accounting represented by fixtures/doubles.
Final qualification counts/logs are in STATUS.md. Financial baseline91/117/32 is
unchanged; this is not installed ERP, genuine authority or SDK acceptance.

Still open in2: unknown/late/unsealed handoff resolution and unchanged retry
operator adoption, corrected-clock/rejection workflows, historical inventory/drain
and actual activation, frozen print master/File consumers, whole canonical mixed
runtime qualification and installed lifecycle/GL/File acceptance. This closes the
implemented origin-backed first-send mechanism, not the entire workstream.
