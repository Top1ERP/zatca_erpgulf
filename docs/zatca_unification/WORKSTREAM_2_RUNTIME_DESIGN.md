# Native dispatch integration design — workstream2, active

This document records implementation decisions, not completed runtime adoption.
The old uninstalled nested staging models remain deferred; adding another isolated
model is not sufficient. Finish the worker/provider integration below before
closing workstream2 or proposing installation.

## Current implemented portion

The existing submit-hook validators still run in their original order. A scoped
hook marker intercepts all six production generators and four existing-XML
wrappers before identity allocation/file extraction, registering a callback only
after the ERP transaction commits. The final13 native HTTP fences reject a
bypassing extension inside the hook. The callback queues identifiers only, checks
site/actor and avoids the framework's migration-mode inline fallback. Rollback,
partial registration and retained contexts cannot release a job. Queue invocation
failure is explicitly unknown, because a worker might already be running.

The worker reloads permissions/phase/status and then still calls legacy processing.
This is not a durable outbox or distributed lock. The background draft worker
skips its old second immediate send when the hook registered a deferred submission.
Two intra-company hook paths update output fields within the enclosing transaction,
without save hooks or an early accounting commit.

Four source-only DocTypes declare protected metadata views: Dispatch Control,
Issuing Chain, Issuance, Dispatch Attempt. Their shared controller denies generic
write/delete/rename; roles have read only. XML/request/receipt payloads are encrypted,
never credential stores. No site has these schemas installed by the agent. The
flat AES-GCM envelope binds site, namespace, record, payload kind and exact header.
It is separate from the deferred credential-version activation design.

The fixed-table DispatchStore stages encrypted request + next local chain head in
one caller-owned transaction, reads exact originals, reserves fenced attempts,
retains immutable receipts and records current/stale assessments with compare
checks. The owned services described below call it in explicit transactions.
The public worker has not yet adopted those services; source-only schemas and
private repository tests are not an installed native dispatcher.

## Remaining integration sequence

1. Acquire a clean **worker-owned** Frappe DB transaction/site/actor/namespace/key
   without connecting to another configured site, discarding parent writes or
   creating a missing encryption key. Refuse dirty/pending callback ownership.
   Pin the actual connection and owner; restore its local proxy on every exit.
   Installed15/16 acceptance must validate the framework signatures/callbacks.
2. Introduce an internal preparation ticket (never queued/RPC/serialized) carrying
   one registration/predecessor/UUID/ICV and source. Native UUID/ICV/PIH readers use
   it without their old commits. Ordinary/native metadata and read adapters must
   load locked fresh saved records, not a stale repeatable-read snapshot.
3. Run canonical builders under a request-local read-only DB guard. Known Frappe
   reads are allowed; hidden commit/rollback/DDL/DML and connection switching fail
   before transport. No global module monkeypatch. Frappe's query builder executes
   through `frappe.db.sql`, so a local DB proxy can guard native paths. This is not
   a sandbox for arbitrary privileged Python or cached raw connections.
4. Intercept QR persistence before File/image writes and capture the actual
   immutable InvoicePayload/route before native HTTP. An internal BaseException
   handoff may unwind legacy generic writers; it is not a successful mock response.
   Use private temporary artifacts during preparation. Avoid fixed-filename
   overwrites of an already issued/accepted artifact.
5. Validate the produced metadata/material/source and atomically store encrypted
   exact request, next local chain head and invoice issuance outputs. Commit only
   at the coordinator boundary. If acknowledgment is unknown, fresh-read the same
   record/manifest; do not regenerate or send until committed custody is confirmed.
6. Create an attempt/fence and commit it before HTTP. Release all row locks. Send
   the exact stored body once through a common native transport, retaining no
   auth/private key in records. A new request scope must match the stored public
   certificate/owner/environment/source binding; do not re-sign an uncertain retry.
7. Seal the exact response before derived source/QR/status updates. Preserve late
   responses on their original attempt; stale workers cannot overwrite a newer
   attempt. Distinguish HTTP200/202 accepted contracts, clearance208 with matched
   returned XML, Reporting409 duplicate evidence,303 fallback, verified rejection,
   authorization/technical/unknown failure and local post-response failure.
8. Route manual/batch/scheduled paths through the same coordinator and add explicit
   unchanged retry/corrected-rejection decisions. Automatic background discovery
   must not automatically replace an unknown artifact. A corrected verified
   rejection gets a new linked issuance version; ordinary retries reuse bytes.
9. Persist a server-owned registration from a validated initial Final-CSID outcome,
   or an explicit reviewed legacy continuity operation. Missing history/blank PIH/
   changed auth token is not NEW_EGS proof. Shared linked-owner credentials need
   one EGS chain across source Companies with the same declared taxpayer. Renewal
   keeps the stable EGS identity; credential staging is still explicitly deferred.
10. Complete concurrent/restart/lost/late/partial SQL and whole-runtime tests, then
    installed acceptance/local SDK in their later workstreams. No authority call.

## Important contract details

- Chain IDs are opaque registrations, independent of auth-token hashes and human
  invoice numbers. Counter values remain canonical digit strings internally;
  never convert a legacy large ICV through float. The published genesis seed
  applies only to a verified explicit NEW_EGS registration.
- The active-owner slot is nullable/unique; historical registrations keep their
  immutable owner key without occupying the new active slot. No default creation
  or legacy counter migration occurs on a normal invoice request.
- Artifact ciphertext contains the exact request body; original normalized XML
  can be decoded from it. Do not duplicate large XML/Base64 copies in a second
  memory/archive graph. Public headers contain fixed flat identity/fingerprint
  fields, not credentials, arbitrary raw response text or URLs with secrets.
- Source `modified` is provenance, not a trusted epoch. Preserve legitimate payment/
  account-status updates when defining the durable fiscal-source comparison;
  an exact original retry must not silently rebuild against changed templates.
  Fiscal-source differences and accounting reconciliation also belong to3.
- Queue deduplication is only an optimization. Durable source/chain/attempt locking
  is mandatory. NOWAIT reduces contention delay, but is not acceptance evidence.
  Do not infer a source cancellation right from UUID absence/presence alone.
- The controller guards ordinary framework writes; privileged raw SQL/Python and
  third-party hooks are not a hostile-code sandbox. Do not claim DB epoch/root CA/
  revocation/network provenance from local fingerprints or a supplied callback.

## Verification context

The earlier205-suite run in the changing development checkout was not a final
frozen qualification:38,938 passed/38 failed in1791.60s. Twenty identified source/
fixture failures were resolved by the final81-suite workstream1 profile;16 older
retry cases used XML whose UUID did not match their intended request, and2 source
inspection failures occurred while that file changed during the run. The retry
fixture now matches the request without changing expected HTTP/UUID/ICV policy.

A separate clean qualification worktree pins runtime44fdd50 plus only that fixture
correction (detached commit b78fd24). Its full local run finished:39,003 passed in
3017.23s,205 suites (`/tmp/zatca-axis1-frozen-qualification.log`). The checkout was
not edited during the run. This is local runtime qualification, not installed
ERP15/16 or SDK acceptance. Workstream2 changes remain in DEV, not deployed.

## Owned native preparation and dispatch custody now implemented

`worker_transaction.py` rejects parent writes/callbacks before and after lazy
connection discovery, pins site/actor/connection/socket/config, loads an existing
namespace/key without creating either, and owns only its own commit/rollback.
It obtains UTC lease observations from that database. A lost commit acknowledgment
never releases a transport invocation or triggers a speculative rollback.

`native_preparation.py` supplies ticket-owned UUID/ICV/PIH to native readers,
captures the actual signed producer request at its final HTTP fence, and uses a
private0600 temporary XML file. `native_dispatch.prepare_saved_invoice` binds the
saved source/ACL/registration, runs preparation under the local read guard, stages
the encrypted exact body and chain head, and updates issuance outputs in the same
owned transaction. Existing originals are decrypted and checked, never regenerated.
Observed business drift currently requires review, including any nonfiscal fields
in that observation; the later fiscal comparison must explicitly justify permitted
payment/status changes rather than silently accepting a changed source.

`reserve_saved_issuance` commits a new fenced attempt before returning a transient
secret-bearing invocation. The initial attempt requires PREPARED. An unchanged
uncertain retry requires an explicit matching prior attempt and expired lease;
expiry is not rejection or permission to issue a replacement. `native_transport`
sends the exact body once through a direct HTTPAdapter with TLS verification,
no redirects/environment/netrc/proxy or automatic retry. It bounds identity-encoded
entity reads, checks framing and sanitizes failures. Timed checks are not a hard
wall deadline for DNS/native I/O. All exchanges in development tests are mocked.

`retain_dispatch_observation` commits the encrypted original response before any
derived source update. Receipt retention does not depend on mutable source ACL or
a still-valid certificate after a response was received. It can lock the original
historical chain. Stale responses remain on their own attempt and cannot clear a
newer fence. A retained current response enters REVIEW_REQUIRED, not acceptance;
the operation-specific classifier/derived writer is still to be integrated.

`response_contract.py` shares validation/message and bounded returned-XML readers
with the earlier assessment model. The old module's XML-bound override remains a
small compatibility wrapper; no expected assessment or financial fixture changed.
`native_response.py` checks one flat original/header/receipt contract.200/202 need
consistent operation and validation status; clearance requires returned metadata/
type parity. Production208 additionally requires the fixed standard gateway and
cleared XML. Reporting409 requires that standard Production route, exact artifact
binding, the explicit English duplicate diagnostic and no contradictory errors.
Generic/custom-gateway/Sandbox409 stays review-only.401/403 and technical responses
never authorize a newly generated replacement.303 is a clearance fallback
observation, not acceptance. Returned metadata matching does not verify computed
invoice hashes, XML signatures, CA trust or financial parity; those remain6/3.

`assess_retained_dispatch` opens encrypted committed original and response in a
fresh owned transaction, runs that assessor and records the result. A late older
attempt/version can retain its assessment without changing the latest issuance.
Idempotent recovery reports an already applied current decision correctly. An
explicit unchanged retry after a complete classified authentication/technical
failure may start immediately; an interrupted attempt needs its expired lease.
Neither changes the original bytes or counter. Derived source/QR/File updates
are still separate and have not been wired.

These services are not yet activated by the native worker. Registration/bootstrap,
derived writes, corrected rejection,303 fallback execution, existing XML admission
and the public/manual/background adoption matrix are still open. Source-name
index installation/performance and native framework ownership need installed5
acceptance. Do not install these source DocTypes or treat this as a completed
dispatcher. Known absent legacy markers are not complete historical provenance;
registration/cutover admission must explicitly cover legacy sources before adoption.

Focused evidence (overlapping, not additive release totals):

- 33 private InnoDB cases: staging/rollback/concurrent/shared locks, exact retry
 custody, immutable receipts, stale/current assessments and metadata tamper.
- 585 local coordinator/transaction/transport/assessment cases: native signing
 and capture, source/route/output changes, quiet ACL, unknown commit, bounded
 mocked HTTP and all invoice/credit/debit/advance response metadata contracts.
- 20,750 existing fixed issuer-binding regression cases,81 suites.

Logs: `/tmp/zatca-axis2-assessment-sql-final.log`,
`/tmp/zatca-axis2-runtime-and-response-final.log`,
`/tmp/zatca-axis2-issuer-regression.log`.
