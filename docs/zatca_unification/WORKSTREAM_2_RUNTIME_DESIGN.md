# Native dispatch integration design — workstream2, active

Known-unit inactive review/reuse now returns a bounded source/XML history report,
with exact missing-position arithmetic, adjacent declared PIH links, genesis/tail
observations, changed public keys and explicit unresolved/unprobed limits. It
changes no stored registration envelope or active flag and cannot replace fresh
crypto/history/drain evidence: [NATIVE_LEGACY_HISTORY.md](NATIVE_LEGACY_HISTORY.md).

This document records implementation decisions, not completed runtime adoption.
The old uninstalled nested staging models remain deferred; adding another isolated
model is not sufficient. Finish the worker/provider integration below before
closing workstream2 or proposing installation.

## Current implemented portion

The existing submit-hook validators still run in their original order. A scoped
hook marker intercepts all six production generators and four existing-XML
wrappers before identity allocation/file extraction, registering callbacks in the
ERP transaction and queuing only after commit. Selected native owners now also
stage/finalize a durable intent as described below. The final13 native HTTP fences reject a
bypassing extension inside the hook. The callback queues identifiers only, checks
site/actor and avoids the framework's migration-mode inline fallback. Rollback,
partial registration and retained contexts cannot release a job. Queue invocation
failure is explicitly unknown, because a worker might already be running.

The worker reloads permissions/phase/status. Registered native owners now enter
the owned facade before legacy status-only skipping; unmarked owners retain
legacy processing. Native scheduled/manual submitted collections share that
policy, as described in [NATIVE_PROVIDER.md](NATIVE_PROVIDER.md). The later native
intent provides durable READY discovery, with started/uncertain delivery recovery
still open. The background draft worker
skips its old second immediate send when the hook registered a deferred submission.
Two intra-company hook paths update output fields within the enclosing transaction,
without save hooks or an early accounting commit.

Six source-only DocTypes declare protected metadata views: Dispatch Control,
Issuing Chain, Issuance, Dispatch Attempt, Onboarding Attempt and Submission Intent. Their shared
controller denies generic write/delete/rename; roles have read only. Invoice
payloads contain no credentials; issued CSID secrets occur only in their distinct
encrypted onboarding-response custody. No site has these schemas installed by the agent. The
flat AES-GCM envelope binds site, namespace, record, payload kind and exact header.
It is separate from the deferred credential-version activation design.

The fixed-table DispatchStore stages encrypted request + next local chain head in
one caller-owned transaction, reads exact originals, reserves fenced attempts,
retains immutable receipts and records current/stale assessments with compare
checks. The owned services described below call it in explicit transactions.
The six generators and submitted worker/manual/scheduled paths now adopt those
services conditionally for native registrations. Existing-XML admission,
publication, activation and whole canonical runtime qualification are still open;
these private tests are not an installed native dispatcher.

The explicit storage initializer, worker key-check probe and unique declared EGS
reservation are now described in [NATIVE_STORAGE.md](NATIVE_STORAGE.md). They do
not install a schema, activate a chain or change a site's encryption key. Missing
or partial/orphan custody cannot be reset by a normal worker or the setup service.

## Integration sequence and closure requirements

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
   immutable InvoicePayload/route before native HTTP. All six Reporting adapters
   and two primary Clearance adapters now hand off before legacy File/realtime/
   batch side effects when an owned preparation ticket is active. An internal BaseException
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
the owned assessor handles the next ledger step. Derived source writes remain
separate.

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
Neither changes the original bytes or counter. Accepted source status now uses
the separate owned projector below; File publication remains unactivated.

`dispatch_saved_invoice` now joins those services. It prepares once, commits an
attempt, invokes once, retains the response and assesses from committed custody.
A current verified303 may perform one Reporting fallback. It decrypts the original
303 evidence and reuses the exact request bytes/UUID/hash/ICV/PIH; a later retry
stays on Reporting. A stale response cannot launch a fallback. Unexpected or
unconfirmed responses cannot create an automatic replacement. Failure results
distinguish invocation uncertainty, custody uncertainty and processing failure
after retained receipt. No legacy source-identity reset writer runs here.

`read_retained_invoice` now reads one exact source/Company/chain/UUID/ICV reference
with saved-source read ACL. It opens/decrypts the original and checks its metadata;
an accepted ledger state additionally needs the matching retained response contract
(and303 evidence when applicable). It does not parse a current private key, select
a current gateway, require a current Company phase or re-sign. The owned read
scope rolls back only its clean read transaction; it does not repair ERP fields.
Generic rename/rebind remains a separately reviewed transition.

The dispatcher consults that retained view first. An accepted original returns its
stored result with `reused_accepted=True`, with no builder/reservation/HTTP. An
existing unaccepted original skips the builder and goes through the ordinary
permission/material/reservation policy; reading history does not authorize a
retry. In this version unchanged retries still require the existing full signing
material check in reservation, although no re-sign occurs. A keyless transport-only
authorization adapter is not yet implemented. Unknown legacy status/response
markers require review even when earlier code erased UUID/counter output fields;
their absence alone must not be treated as a new issuance.

A server-loaded source already marked `egs:<chain UUID>` cannot silently reenter
legacy UUID/ICV/production HTTP paths. Active native preparation bypasses that
guard only through its owned ticket. Debug and Compliance metadata stay local to
their own purpose; the standalone Compliance API fence explicitly declares its
purpose and cannot relabel a production scope. This is an adoption safeguard, not
a hostile-Python sandbox or permission substitute.

The private owned-pipeline suite runs real worker ownership, actual SQL commits,
local signing/temporary formatting, encrypted custody and native response assessment
together for Sales and POS through Company/device/linked owners. It also exercises
303 fallback without re-signing and proves a separate connection can acquire the
chain NOWAIT during the mocked HTTP call. Its source loaders and callback shape
are explicit framework doubles and its input XML uses the synthetic onboarding
builder. It does not run installed ERP document/accounting hooks, the six full
financial builders, SDK validation or any authority exchange.

These services are not yet activated by the native worker. Registration/bootstrap,
File/print/UI publication, corrected-clock builder adoption, existing XML admission
and the public/manual/background adoption matrix are still open. Source-name
index installation/performance and native framework ownership need installed5
acceptance. Do not install these source DocTypes or treat this as a completed
dispatcher. Known absent legacy markers are not complete historical provenance;
registration/cutover admission must explicitly cover legacy sources before adoption.

Focused evidence (overlapping, not additive release totals):

- 42 private InnoDB cases:36 repository cases plus6 combined owner/pipeline/fallback
 cases; staging/rollback/concurrent/shared locks, exact retry custody, immutable
 receipts, stale/current assessments and metadata tamper.
- 609 local coordinator/transaction/transport/assessment cases: native signing
 and capture, source/route/output changes, quiet ACL, unknown commit, bounded
 mocked HTTP and all invoice/credit/debit/advance response metadata contracts.
- 20,750 existing fixed issuer-binding regression cases,81 suites.

Logs: `/tmp/zatca-axis2-central-private-final.log`,
`/tmp/zatca-axis2-purpose-and-fallback-final.log`,
`/tmp/zatca-axis2-purpose-regression-final.log`.

The source-only bigint customization currently covers Sales Invoice; the private
pipeline intentionally uses string ICV support columns. Internal64-digit parsing
does not prove installed Sales/POS field capacity or browser JSON integer fidelity.
The owned preparation/reservation now reads actual current-DB column definitions
and stops before signing/staging/dispatch if UUID/unit columns are missing/short
or the next/retained counter does not fit its integer/string storage. It rejects
FLOAT/DECIMAL counter columns and never alters a schema or passes ICV through
float. Private SQL verifies real INT/BIGINT/FLOAT definitions. Installed5 must
still verify ORM/UI metadata parity, source schemas and data preservation.

Commit return alone is no longer sufficient to release an invocation: physical
connection/socket/site/actor/key bindings and empty callbacks are rechecked after
commit. A returning but rebound commit is COMMIT_UNKNOWN with no speculative
rollback. Original/receipt opens use shared NOWAIT current reads; an earlier
repeatable-read view cannot hide newly committed custody and invite regeneration.
Two private SQL cases explicitly keep an old ordinary read snapshot while the
repository reads the later committed original/response.

Authenticated historical identities are Data, not mutable ERP Link/Dynamic Link
fields. Local Frappe15 `rename_doc.update_link_field_values` and
`rename_dynamic_links` rewrite references directly without invoking the referencing
record's controller. Those rewrites would otherwise invalidate ciphertext AAD.
The immutable labels/UUID references now survive generic renames; internal data
references retain search indexes. This does **not** authorize source/owner renames:
the lifecycle/alias review guard remains required before public adoption so a
rename cannot strand source lookup or reset an EGS registration.

Focused follow-up logs: `/tmp/zatca-axis2-custody-schema-final.log`629 local cases
and `/tmp/zatca-axis2-custody-schema-private-final.log`45 private SQL cases. The financial builders
and reference fixtures remain unchanged; the changed legacy bodies are only
UUID/POS metadata/ICV guards, the final HTTP fence and its Compliance caller.

## Next integration batch

1. Finish File/print/UI publication from committed current custody and the
   operation-specific publication rule. A prepared Simplified original may supply
   its local QR/XML before Reporting, without being marked remotely accepted.
   Standard publication needs matched clearance or the explicit303 fallback rule.
   A response writer must never rewind the owner's generation-time PIH to an
   older accepted invoice. The retained reader/cached accepted no-send path is
   implemented, including invalid current signing keys and read-only source ACL
   in the private pipeline. Match the current source issuance identity before
   projecting a historical receipt; do not introduce Frappe File callbacks into
   the strict read-only preparation transaction.
2. Corrected-clock and durable operator source adoption is implemented in
   [CORRECTED_PREPARATION_COMMAND.md](CORRECTED_PREPARATION_COMMAND.md). It requires
   matched400/coherent history, current source approval and a fenced owned worker;
   it links an unsent new version and retains the old one/current generated tail.
   Complete the whole canonical mixed-runtime matrix and later installed/SDK
   gates; narrower fixture success does not close them. Unknown/auth/technical/
   duplicate review alone never grants replacement or counter rewind. ERP posting
   date/time is not automatically changed.
3. Complete server-owned registration/bootstrap and cutover admission. A validated
   initial Final-CSID outcome must bind a genuinely new server-owned onboarding
   intent; missing history/token/PIH is insufficient. Existing installations need
   explicit reviewed continuity using the last **generated** document. Renewal
   preserves the opaque chain; automatic credential staging remains deferred1.
   The owned legacy-review staging service below now retains exact reviewed
   positive-counter anchors, including explicit rereview without destroying the
   older evidence. It creates inactive candidates only. The initial owned CSR
   and fenced CSID response services below now retain their bound evidence, with
   FINAL_READY still inactive. Complete unit-identity inventory, namespace/bootstrap,
   legacy-worker draining and activation are still open.
   No Company/source/schema operation is to be executed on a working site here.
4. Complete adoption across all existing-XML/draft/publication paths and qualify
   the whole runtime together. Six production generators and submitted manual/
   worker/scheduled paths now use the facade described in NATIVE_PROVIDER.md.
   Do not activate one path and
   leave another allocating through the legacy counter. External XML needs its
   own source/file/chain admission and cannot consume a freshly proposed random
   native UUID. Unverified extensions must stop before transport. Batch/hold
   generation now reaches the request handoff in the eight native API adapters
   without the legacy queue/File/save branch. The provider now selects prepare-only
   versus dispatch according to Company scheduling. Local
   Simplified publication must not wait for Reporting success.
5. Complete cancellation/printing/recovery/rename decisions and aggregated translated
   operator outcomes. Then freeze the workstream2 qualification. Installed5,
   authentic crypto/SDK6, financial3 and the separately approved pilot7 retain
   their own gates; service-only/private-SQL success does not close those gates.

Retained-access follow-up:638 local cases in
`/tmp/zatca-axis2-retained-access-final.log`,45 private SQL cases in
`/tmp/zatca-axis2-retained-access-private-final.log`. The six combined private
pipeline cases now also invalidate the current signing key, reduce source access
to read only, retrieve the exact accepted original and repeat the dispatch command
without another transport call or counter increment. These are overlapping local
evidence, not new installed/financial/authority acceptance.

## Accepted source status, native artifact reads and explicit corrected versions

`native_projection.project_accepted_status` is now called by the coordinator after
current accepted receipt assessment, including208/409 contracts. It independently
checks source/Company ACL, locks opaque chain/current source/issuance in order,
decrypts the original and current receipt, reassesses acceptance, rejects older
source versions, and writes only `custom_zatca_status` and exact UTF-8
`custom_zatca_full_response`. Physical character/octet capacities must fit; no
schema alteration or response truncation. No source save/File/accounting hooks,
financial changes, ICV allocation or PIH rewind. An identical projection is a
read-only no-op. A cached read-only viewer may explicitly skip projection, but
never gains write permission. A post-receipt projection failure remains a retained
acceptance with a distinct local-review result. A later authorized call repairs
the fields without reading a current signing key, rebuilding or sending again.

`native_artifact.read_native_artifact` obtains exact current custody through the
existing read-ACL service. Simplified documents expose the generated original
XML/QR before Reporting without an accepted flag. Standard documents need the
matching cleared XML/QR, or accepted Reporting after the retained303 chain;303
alone is insufficient. A returned Standard issue-clock change is not normalized
or hidden by substituting the original QR. Missing/malformed native custody never
falls back to an old attachment. The immutable data view carries ledger state;
rejected originals are diagnostic data, not a valid-invoice/printing authorization.
It performs no File/image write and has not been wired into print/UI hooks.
This is a point-in-time read, not a reusable File-publication capability; a future
writer must independently recheck the current source/version under its own lock.
`qr_xml_contract` shares the bounded lexical parser with the legacy QR reader;
its error/reader aliases and bounded override preserve existing tests. Canonical
Base64 and metadata agreement remain distinct from TLV/crypto/SDK validation6.

`DispatchStore.find_source_issuance` now reads the latest version before comparing
the saved Company/UUID/ICV. Resetting source outputs to an older valid UUID cannot
select that older version for current recovery/printing. Historical ciphertext
remains readable by explicit record custody. The public rename/rebind guard is
still required before adoption.

`prepare_corrected_rejection` is an explicit no-HTTP operation, separate from
ordinary prepare/retry. It requires the named current rejected issuance and
attempt, source write ACL, no competing chain attempt, exact saved outputs,
decrypted matched HTTP400 validation rejection and current issuer binding. A new
version gets a new UUID/hash, next local ICV/current generated PIH and a durable
`replaces_issuance` reference. Identity/custody/head and compatibility status reset
commit together; the old original/receipt stays intact. The produced issue instant
must differ, classification/endpoint must match, and Reporting retains the
original XML transaction date. An unchanged-clock canonical builder fails locally
without any counter advance or automatic ERP time edit. Actual builder/operator
clock selection, fiscal-source edits and installed document lifecycle still need
their explicit adoption/financial acceptance; this is not a new public reissue RPC.

The official [technical guideline](https://www.zatca.gov.sa/en/E-Invoicing/Introduction/Guidelines/Documents/E-invoicing-Detailed-Technical-Guideline.pdf)
FAQ distinguishes new identifiers/timestamp after validation rejection from
retrying an uncertain exchange, preserves the Reporting transaction date, and
bases PIH on the immediately preceding generated document. This implementation
does not infer rejection from401, technical failures or unknown/duplicate review.

Final focused evidence for this bundle (overlapping earlier evidence):

- 1,108 local cases across16 reviewed suites in4.40s, including the shared legacy
  QR read/access/regeneration contracts and native coordination/transaction tests.
- 49 private InnoDB cases in4.80s. Nine combined Sales/POS cases cover Company,
  device and linked owners across Simplified, Standard303 and matched400 rejection/
  explicit replacement. Source projection failure is recovered with an invalid
  current key, without another HTTP invocation. Prepared Simplified reads work
  before the mocked response; Standard reads remain held until its bound outcome.
  Resetting a source to an older version cannot select that version as current.
- Logs: `/tmp/zatca-axis2-projection-rejection-final.log` and
  `/tmp/zatca-axis2-projection-rejection-private-final.log`.

No source financial amount/date/time is changed by these services. The test
builder explicitly supplies a later replacement clock; it remains the synthetic
onboarding/signing helper, not installed ERP financial-builder/SDK acceptance.
The original240 financial comparison and expected reference files are unchanged.

## Native API handoff before legacy side effects

The six Reporting APIs previously reached their final native fence only in an
immediate-send branch. Five also attempted a File/source attachment write before
that fence. An owned read-only preparation could therefore fail or enter a legacy
batch path instead of returning its original. All six Reporting APIs and both
primary Clearance APIs now call `capture_before_legacy_side_effects` immediately
after their one payload capture. It reuses the existing source/material/payload
fence and internal handoff. Outside an owned native preparation it is inert; the
legacy Company send setting and request/response/file behavior remain unchanged.
The primary attachment preflight recognizes the same owned source ticket and
avoids querying/writing File metadata for a temporary native artifact; a foreign
source still fails. Current-custody publication remains a separate operation.

The nine private pipeline cases now use those actual API adapters rather than a
direct test-only final-fence call. They cover all six Reporting adapters and both
Clearance adapters across Company/device/linked owners, Batches/Background send
settings,303 and rejection/replacement. Files and realtime/legacy HTTP must not
execute before the handoff. The coordinator's explicit internal dispatch is
mocked; this does not claim that public batch discovery/scheduling is adopted or
that native dispatch automatically honors send settings. A future provider must
choose prepare-only/scheduled/explicit send before entering that operation.

Follow-up evidence:20,750 fixed issuer-binding regression cases in117.32s,
1,108 focused native/QR cases in4.57s and49 private SQL cases in4.92s. These
selections overlap earlier evidence; they are not additive release totals. Logs:
`/tmp/zatca-axis2-native-api-regression.log`,
`/tmp/zatca-axis2-native-api-local-final.log`,
`/tmp/zatca-axis2-native-api-private-final.log`. Financial builders/reference
expectations are unchanged. The synthetic builder still does not exercise full
installed financial generation, ERP accounting, authentic SDK or authority APIs.

## Owned legacy-continuity reviews

`native_registration.review_legacy_registration` now loads saved source, routing
Company, actual credential owner, legacy counter and private attached XML under
an owned transaction. It requires System Manager, READ on source/Company/counter/
File and READ+WRITE on the selected credential owner before parsing its signing
key. It never writes/relinks the invoice, so source WRITE is not required for
this review operation. Corrected issuance and attachment writers retain their
separate source-WRITE requirements.

The counter's exact Company/unit/purpose/key and last invoice/type must match.
Canonical positive integer/string ICV must agree with source and XML; float,
zero, missing history and ambiguous shared-unit counters are rejected. The old
counter field `environment=Production` denotes credential purpose, not historical
gateway provenance. Current gateway/environment is retained as the reviewed
configuration; this is not proof of where an old invoice was submitted.
The original's invoice ID/UUID/ICV/taxpayer, declared invoice digest and embedded
certificate must match the saved source, current owner's PIH and selected public
material. A success-only PIH pointing behind the generated counter cannot seed a
new chain. No automatic counter, PIH, invoice or credential repair is attempted.
Historical cancelled source state does not erase a matched generated position.

The reviewer supplies the SHA256 of the exact local private XML they selected.
The shared attachment reader now accepts the owning runtime explicitly while
preserving its former default ABI. It still rejects foreign/public/remote/debug-prefixed/
unsafe attachments and bounds raw file reads without following a leaf symlink.
No File.get_content URL fetch or directory/newest-file discovery occurs.

`DispatchStore.stage_reviewed_registration` persists one flat header and exact
reason/XML payload in the existing Issuing Chain table, using a distinct
`chain-registration` AES-GCM domain. No credential/private key/OTP is stored.
The encrypted review binds site/namespace/record/public owner/environment and
the exact bytes. Hidden read-only header/ciphertext fields preserve the source
controller's generic edit/delete/rename protection. No financial amount is
recalculated. This is local consistency/custody review, not computed-hash/XML
signature/CA/SDK validation or remote acceptance proof; those retain3/6 gates.

The result is an **inactive candidate** with a positive retained ICV/PIH,
`active_owner_key=NULL` and no local issuance/attempt. New chain metadata now
defaults inactive. A nullable unique `registration_review_key` permits one
current inactive review per owner/environment while leaving old evidence intact.
The owner lookup also has a declared search index. Missing current slots with
existing history are an explicit review condition, never permission to reset.

Ordinary repeat calls reuse exact matching committed review custody. A changed
head/reason/source/file requires explicit `supersedes_review_id` identifying the
current candidate. Closing the older review slot and inserting the new encrypted
candidate are one transaction. The old header/ciphertext/anchor remain unchanged;
the new header links the older review. Partial failures restore the old slot and
remove the new record. Unknown commit acknowledgments remain uncertain; repeating
the same command recovers the existing current record without another version.
Candidate IDs identify review proposals, not an already activated EGS. Activation
must establish the stable native chain identity; ordinary rereview cannot replace
an active chain or infer a new EGS from a changed certificate/token.

This service has no public RPC, UI button, worker hook, installation, native
activation or legacy retirement. An inactive reviewed row cannot obtain a native
dispatch slot. Historical counters/files and incomplete old gateway provenance
do not prove that all linked Companies/devices share one complete EGS history.
Before actual cutover the provider must inventory all consumers, authenticate the
initial/legacy origin, reconcile the financial/crypto evidence, drain and fence
legacy generation/transport and freshly compare the current head. A DB counter
row lock alone cannot prove an older worker has not already entered HTTP. Do not
add a caller `drained=True` or `approved=True` flag as a substitute. Initial new
EGS onboarding and reviewed live activation remain required workstream2 work.

Final focused evidence for this increment:

- 450 local cases across13 suites in2.35s: registration envelope/domain/bounds,
  native schema and dispatch/retry/read contracts, plus unchanged legacy attached/
  generated/history/certificate inventory behavior.
- 95 private InnoDB cases in6.95s:46 review-service cases and49 existing dispatch/
  repository cases. The review matrix covers Sales/POS, Simplified/Standard
  originals and Company/device/linked owners. It verifies role/ACL denial,
  counter/file/PIH mismatch, a counter above the safe float-integer range,
  cancelled-source continuity, ambiguity, tamper, rollback, lost acknowledgments,
  explicit supersession and a genuinely later synthetic generated invoice.
- Logs: `/tmp/zatca-axis2-legacy-registration-local-final.log` and
  `/tmp/zatca-axis2-legacy-registration-private-final.log`.

The fixed manifest now declares218 local/60 private suites; this increment did
not run the whole manifest. Earlier counts overlap and are not additive release
totals. Its source loaders/permissions/credential material are explicit framework
doubles, with real private SQL locks/commits, local signing and private file reads.
No installed Frappe/ERP15/16, complete financial/XSD/SDK, history completeness,
legacy-worker drain or authority acceptance is established. No working-site
schema/configuration/invoice/service operation was performed. Financial builders
and the original240 comparison/reference expectations remain unchanged.

## Initial CSR custody — 2026-11-19

`native_onboarding.prepare_new_unit` requires the explicit site rollout setting,
System Manager, saved target READ+WRITE and routing Company READ. It resolves the
actual credential owner and rejects a device choosing its Company's key rather
than creating another unit. Initial material/history must be empty; an existing
intent, key, credential, noninitial PIH or legacy counter cannot be silently
adopted or replaced. Namespace, encryption key and storage metadata must already
exist; this service performs no installation/bootstrap.

A fresh secp256k1 key, the existing environment-specific CSR template, saved-owner
marker and encrypted public CSR intent commit in one owned transaction. Physical
column capacity is checked before writing. Configuration/route/taxpayer/owner
observations are rechecked after cryptography. Partial writes roll back together;
lost commit acknowledgments are uncertain and a repeat recovers the exact saved
key/CSR. The private key remains in the existing owner field; the intent stores
only public CSR bytes/fingerprints, not OTP/private-key/auth material. This is
initial custody, not the deferred versioned secret renewal mechanism.

The row is inactive NEW_EGS/CSR_READY with no active owner slot. Its zero/initial
hash is a reservation, never genesis authorization. There is no Final-CSID proof,
CA trust/revocation proof, native activation, public worker adoption or legacy
cutover in this increment. Compliance and Final-CSID calls for a native owner
currently stop before the legacy writer; their fenced replacement is pending.
The feature is disabled by default. Ordinary unmarked legacy paths keep their
existing behavior; the marker prevents fallback even if the flag is later off.

Company/device ORM validation blocks invented/cleared markers, stale protected
credential/route/identity/PIH/counter updates and rename/delete. Unrelated business
fields and OTP entry remain editable. Its shared field vocabulary is kept in the
pure credential policy module so ordinary Company saves do not import invoice
generation/crypto services. This is not protection against privileged raw SQL;
cross-owner copying of native keys/credentials still needs a registry fence
before Final-CSID activation/public adoption.

Evidence:58 focused local cases (`/tmp/zatca-axis2-onboarding-local.log`),32 private
InnoDB cases (`/tmp/zatca-axis2-onboarding-private.log`) and the81-suite fixed
issuer-binding profile20,750 cases (`/tmp/zatca-axis2-onboarding-regression.log`).
Private coverage includes Company/device, existing CSR button compatibility,
permission/role denial before key generation, shared Company-key rejection,
actual SQL rollback/commit loss and changed config/key/CSR/schema/capacity.
Framework permissions/metadata are explicit doubles, not installed15/16 proof.
The manifest now declares220 local/61 private suites; it was not run in full.
No live-site/schema/configuration/service change or authority request occurred.

## Fenced initial CSID requests and receipt recovery — 2026-11-19

`native_enrollment.request_initial_csid` continues the same saved CSR intent for
`compliance` and then `production/csids`. It requires System Manager, saved owner
READ+WRITE, Company READ, the native rollout flag and exact current owner/route/
taxpayer/key/CSR/configuration binding. This is initial enrollment only. It does
not renew, replace or import unrecorded credentials. A Final request uses the
admitted encrypted Compliance receipt's exact requestID and auth, with matching
saved owner fields. The existing environment is retained; Production onboarding
does not silently switch to Sandbox or invoice reporting/clearance.

The new source-only `ZATCA Onboarding Attempt` controller denies generic edits,
rename and deletion. Its public flat header contains identities/fingerprints and
an opaque request fence. Its exact request body contains only CSR or Compliance
requestID; OTP and HTTP Basic headers are transient and never queued/persisted.
The raw response can contain the issued secret, so it has a separate AES-GCM
`onboarding-response` domain with hidden/no-copy/no-print custody. No response or
secret reaches messages/logs. The existing site encryption key/namespace is used;
neither is created or rotated. This is retained response custody, not the deferred
general versioned credential renewal/activation mechanism.

There are three separate owned commits:

1. Reserve the exact request and set a pending pointer before one HTTP invocation.
2. Retain the exact response before parsing or projecting credentials.
3. Atomically project validated owner material and the admitted attempt pointer.

An interrupted request or lost reservation acknowledgment is held as pending;
no lease expiry or automatic new key/request guesses its remote outcome. A lost
response/admission acknowledgment, projection error or restored original route
can recover the retained result without sending again. Current head must remain
inactive, zero/initial hash and free of any issuance/attempt; absence of invoice
history by itself never activates a unit. The mutable owner and routing source
are reloaded after crypto/metadata work before SQL projection/reservation.

`onboarding_response` requires an exact bounded JSON response, HTTP200, ISSUED,
no errors, a canonical requestID, a nonempty printable secret and a recognized
certificate token encoding. The certificate must be current, secp256k1, match the
saved CSR public key/taxpayer and the app's DirectoryName surname EGS-serial
profile. Unknown profiles, duplicate JSON keys, changed unit/VAT/key and malformed
responses require review. Returned requestID identifies that issuance response;
Final's ID is not assumed to equal the earlier Compliance ID sent in its body.
Native projection stores the certificate as canonical Base64 DER; existing
legacy owners and financial/hash algorithms are unchanged. Device Compliance
and Final retain the existing purpose-specific field policy.

Only a subsequent explicit service/button call may reserve a new request after
an authenticated retained HTTP400 with exactly Invalid-OTP (Compliance) or
Missing-ComplianceSteps (Final). The prior header/ciphertext/response remain
immutable and the new attempt links its predecessor. Unknown/malformed bodies,
401,5xx and incomplete responses never authorize this release. The receiving
invocation does not retry. These are supported endpoint error contracts, not
claims that local tests completed any authority Compliance steps.

`onboarding_transport` shares only the existing bounded TLS entity exchange.
Its typed invocation permits onboarding endpoints and their respective OTP or
Compliance auth only. Invoice `NativeInvocation` keeps its original two endpoint
restriction. Neither adapter uses ambient Session/netrc/proxy/redirect/retry
behavior. The shared90s elapsed checks still do not interrupt native DNS/read
calls or provide a hard wall-clock guarantee. All exchanges in this development
run were mocked under the offline guard; no authority request was performed.

The existing CSR/CSID buttons now distinguish durable native outcomes from legacy
in-memory progress flags. Atomic CSR commit loss and retained recovery no longer
create invalid partial-save progress combinations. Native completion retains the
legacy success return shape and emits one translated notice that the unit is
inactive. Native failures have one translated review message; structured success
metadata stays English and contains no requestID, token or secret. The rollout
setting is disabled by default. No active installation was changed/enabled here.

`native_owner_registry` closes the ordinary unmarked-copy gap noted in the CSR
increment. It derives public fingerprints from the supplied saved/application
key/CSR/certificate/auth projections, then checks the indexed native registry.
Forms cannot import registered native material into another unmarked owner;
legacy credential writers, UUID/ICV generation and final Production-purpose
request selection/transport also hold copied native keys/auth. The marker cannot
be bypassed by clearing the rollout flag. Default legacy material with no native
registration keeps its path. Metadata without the marker is inert; after marker
installation, a registry read failure is review. Invalid legacy aliases do not
hide another valid copied material field. No privileged raw-SQL sandbox or CA
trust assertion is made. Unchanged ordinary forms avoid crypto/registry work.

FINAL_READY is deliberately **inactive**. Initial intent plus locally consistent
returned material is not complete public adoption, authenticated history
inventory, a new counter genesis authorization, CA path/revocation/SDK acceptance
or permission to deploy. Serial/identity inventory across owners and legacy
consumers, reviewed activation/worker fencing, namespace/bootstrap, corrected
clocks, publication and remaining public paths still belong to workstream2.

The certificate/CSR profile was checked against the official
[Security Features Implementation Standards v1.2](https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/20230519_ZATCA_Electronic_Invoice_Security_Features_Implementation_Standards_vF.pdf)
and response shape against the official
[Developer Portal User Manual](https://zatca.gov.sa/en/E-Invoicing/SystemsDevelopers/ComplianceEnablementToolbox/Documents/Developer%20Portal%20User%20Manual.pdf).
Those describe the intended profile/process; synthetic certificates and fixed
fixtures do not establish CA trust or real-world acceptance of every profile.

Focused evidence:153 local cases across8 suites in0.92s and157 private InnoDB
cases across5 suites in11.43s. Logs: `/tmp/zatca-axis2-enrollment-local.log` and
`/tmp/zatca-axis2-enrollment-private.log`. Coverage includes Company/device CSR,
both buttons, actual SQL reservation visibility, concurrent button exclusion,
unknown commits at all three stages, local projection/metadata/route failures,
exact cached recovery, known400 predecessor retention, wrong certificates,
registry copies and the existing dispatch/cutover pipelines. Manifest224 local/
62 private suites; the whole manifest was not run. Installed ERP15/16, financial
parity and authentic complete XML/SDK acceptance retain their separate gates.
The fixed81-suite issuer-binding regression also passes20,750 in120.68s, logged
in `/tmp/zatca-axis2-enrollment-regression.log`. These sets overlap; they are not
additive release totals. Read-only live-source checks retain HEAD ba51f258 and
the previously recorded tooltip/customer-address hashes and dirty-file state.
Financial builders and the original240 reference comparison91/117/32 are unchanged.

## Custody-backed Desk views and transient print adoption — 2026-11-19

`native_publication` now connects the retained XML/QR readers to three authenticated
GET-only view/download endpoints and actual Sales/POS before-print hooks. Both
Desk types use a shared read-only asset with translated QR/status messages,
issued/original XML downloads, explicit refresh and stale/dirty-form guards.
The print document's identity is compared to the same selected custody view,
including fields omitted from its business observation; an earlier source read
cannot authorize a changed version. Current source/child/Company reads are shared
NOWAIT. Exact returned XML encoding/BOM is preserved; responses are no-store.

No File/source persistence, counter/PIH change, canonical builder, signing or
transport runs during publication. Print QR and verified status changes are
in-memory only. Rejected/review originals remain separately diagnostic; Standard
print requires matched clearance or bound accepted303. A prepared/uncertain
Simplified original can supply its QR without claiming remote acceptance.

This is not publication closure. The current source digest is deliberately strict:
even outstanding-balance/payment bookkeeping changes can block printing. A reviewed
versioned fiscal projection, frozen master/print information, saved File/external
consumers, pre-issuance print policy and installed/browser/PDF/SDK qualification
remain open. Do not silently reinterpret existing originals or relax observations
to make tests pass. Details and operation matrix are in
[NATIVE_PUBLICATION.md](NATIVE_PUBLICATION.md).

Final qualification:196 local cases across5 suites in1.61s;75 fixture-owned private
SQL cases across3 suites in15.82s;100 synthetic UI cases; fixed81-suite regression
20,751 in122.40s. Logs use `/tmp/zatca-axis2-publication-*-final.log`. Sets overlap;
the whole228 local/65 private manifest was not run. Private active registration
and synthetic metadata/UBL builder remain explicit fixture inputs, not installed
ERP or authority acceptance. Source-only live checks retain ba51f258 and recorded
dirty tooltip/customer-address hashes. No financial expectation/reference change,
live/schema/service operation, native activation or authority request occurred.

## Generation-time collection-state evidence — 2026-11-19

The blanket post-payment hold above is resolved for newly captured native
originals by `native-invoice-publication/v1`. It retains all typed source fields
except identified header collection state, five owned Sales Payment Schedule
collection columns and the POS consolidation link. Actual ERP15 source and public
ERP16 code were inspected. The full generation observation remains unchanged.

One optional `publication_ciphertext` is inserted atomically with the original
and local chain advance. A separate AEAD domain authenticates the exact existing
artifact header, profile and source/projection digests. Original v1 request
ciphertext/AAD/header contracts and bytes are unchanged. Missing historical
evidence keeps the prior full-source comparison; no backfill method exists.
Corrupt/foreign/unknown evidence fails closed without hiding diagnostic originals.

Current saved fiscal state must match this captured projection. Render JSON then
matches the whole current saved observation, so it cannot fabricate paid status,
outstanding balance or child metrics. Exact retained preparation/reservation also
permits these collection updates, without another build/UUID/ICV/PIH or blind
unknown retry. Pending/accepted and legacy outcomes keep their separate rules.

The current render comparison also accepts Frappe's verified native-date/time
versus JSON text representation, without numeric coercion or any change to the
stored typed generation/fiscal observation. Actual framework JSON and hook tests
cover this separate print-input boundary; PDF/browser acceptance remains gated.

372 local cases across10 suites pass in3.28s;165 private SQL cases across5 suites
pass in22.16s; fixed81-suite issuer-binding regression20,751 in120.13s. Logs use
`/tmp/zatca-axis2-collection-*-final.log`. Sets overlap;229 local/65 private manifest
was not run in full. Native-shaped SQL source/child doubles exercise payment
transitions/reversal, pending exact dispatch and POS consolidation references;
they do not perform genuine ERP posting/closing or prove installed15/16/SDK.
Financial builders/reference91/117/32 remain unchanged. Full rule and remaining
publication boundaries: [PUBLICATION_COLLECTION_STATE.md](PUBLICATION_COLLECTION_STATE.md).

## Existing native XML adapter and retained classification — 2026-11-19

The four existing-XML wrapper/API pairs now select native admission before legacy
extractors and response writers. A submitted saved Source/Company and exact one
private local File require their normal permissions. Bounded bytes and raw UUID/
hash arguments must match the authenticated current original exactly. No remote,
traversal, public/Debug, symlink, ambiguous, changed or unowned file can create a
new issuance or grant a retry. Caller data cannot select a different source/issuer.

The matching issuance ID is checked through facade, reservation and status
projection, including read-only cached projection. Owned preparation captures
all four APIs before legacy progress; no old HTTP/writer runs for a native result.
The same entry/manual/scheduled policy remains in use. Retained PREPARED XML now
supplies its original classification through the shared-lock policy recheck;
changing the current Customer B2C flag cannot reclassify it or alter deferral.
Its supplying version is fenced for ordinary retained dispatch too.

Matched cached acceptance needs no new send/current signing key. Rejected,
unknown or in-flight outcomes stay held even with an exact matching upload.
Legacy/unowned history remains outside this adapter and needs continuity review/
drain rather than an inferred zero counter or imported acceptance. Details and
the eight callsites are in [NATIVE_EXISTING_XML.md](NATIVE_EXISTING_XML.md).

Qualification:691 local cases across6 suites in4.72s;138 fixture-owned private SQL
cases across4 suites in21.63s; fixed81-suite issuer-binding regression20,751
in114.45s. Logs use `/tmp/zatca-axis2-existing-xml-*-final.log`. Sets overlap;
whole230 local/66 private manifest was not run. No financial reference, live/
schema/service, native activation or authority request changed. Private active
registration/framework and synthetic metadata/UBL builders remain explicit
fixtures, not installed ERP/CA/SDK/genuine authority acceptance. Workstream2 is
still open for initial/cutover activation/inventory/drain, operator retry/correction,
draft/durable handoff, source lifecycle, frozen print/master and File/external
publication, and whole canonical runtime qualification.

## Saved-owner identity inventory before initial native key generation

The next activation prerequisite is now adopted at the initial CSR writer:
[NATIVE_IDENTITY_INVENTORY.md](NATIVE_IDENTITY_INVENTORY.md). It discovers saved
Company/device material and declared identities, preserves delegation provenance,
requires full ordinary READ coverage and verifies InnoDB/session isolation before
exhausting both owner PRIMARY ranges under shared NOWAIT locks. Matching legacy
material/history-backed unit claims stop a fresh initial key. Unused config
templates are reported; unique native unit reservation remains authoritative for
their eventual first use. Cached owned CSR recovery and invoice runtime are
unchanged. No complete-history, old-worker drain or activation claim follows.

## Saved Sales/POS contradictions to a reviewed legacy tail

The actual inactive legacy review now checks both saved source tables before
retaining/reusing its exact anchor. Another same-unit source at/above the counter
tail, noncanonical/partial source or another Company holds; no latest/max seed
or Source status acceptance is inferred. Exact SQL comparison, physical column/
engine checks and shared range locks cover this negative proof. Owner inventory
reuses the same isolation/engine helpers. Tests include actual DOUBLE loss,
unindexed/indexed concurrent inserts and updates, cancellation and recovery after
a newer source appears. This remains administrative review, not an invoice-path
scan, complete history reconstruction, worker drain or activation. See
[NATIVE_LEGACY_TAIL.md](NATIVE_LEGACY_TAIL.md).

The subsequent saved-slot extension rejects noncanonical older UUIDs and repeated
ICV/UUID positions within Sales/POS and across their join, even below a valid
current tail. All aggregate/join probes are current locking reads. Actual private
review tests commit duplicates after its initial ORM read view and require their
detection; no plain consistent snapshot is used as a census. Noncontiguous legacy
positions retain the exact reviewed counter. No all-history cryptographic proof,
new persistent census/activation envelope, renumbering or authority call follows.

## Known consumer closure and current issuer/counter observations

Inactive legacy review now traverses saved public-key/declared-unit relations and
explicit Company-key delegates, then reads the full bounded saved counter catalog
with ordinary READ ACL and current shared PRIMARY range locks. Current legacy
logical aliases and saved pointers expose known fragments; another Production
counter holds even when inactive/zero. Compliance/Debug purposes remain separate;
unattributed history is not a no-history proof. Owner inventory's nonpersisted
digest is now v2; artifact/registration/onboarding cipher envelopes are unchanged.

The review compares captured credential/routing projections, including delegate
flags and schema presence, with current locking ORM reads before material
admission. This closes a demonstrated older-read-view window where a token,
environment or flag could change underneath a captured issuer. Source flags,
ordinary generation, money/XML/signature logic and chain activation are unchanged.
The actual review/private fixture matrix now uses independent fresh test keys and
persisted mutation rows; it must not hide real cross-case copied-key conflicts.
See [NATIVE_LEGACY_CONSUMERS.md](NATIVE_LEGACY_CONSUMERS.md) for coverage and the
still-open full historical/installed/drain/activation gates.

## Historical attached declarations behind unattributed counters

The current inactive review now probes otherwise unattributed saved counter
references through current permission-checked Source/Company/File reads and
bounded private attached XML. Overlapping embedded public keys or declared full
unit identities hold review without a counter merge or certified ancestry claim.
Missing/denied/invalid evidence stays unresolved. The probe caps counters/files/
successful XML bytes, charges bytes before parsing and records unprobed states;
the shared file reader preserves its old default while supporting a lower cap.

SQL/ORM/engine/owner failures propagate so a possible database rollback cannot
discard locks and then continue to commit as a mere optional-file miss. Tests
exercise actual review, deliberately untrusted fixture signatures, a changed
archived File URL after its earlier ORM view and byte-budget edge cases. Existing
certificate fingerprint semantics/envelopes and financial/signing algorithms are
unchanged. No full cryptographic history, installed or cutover/drain closure:
[NATIVE_LEGACY_ARTIFACT_PROBE.md](NATIVE_LEGACY_ARTIFACT_PROBE.md).

## Durable committed native ERP handoff

Selected native submit-hook entries now borrow their ERP transaction to stage an
intent, finalize an authenticated fiscal source/actor/chain binding before commit,
and enqueue only its ID after commit. The separate read-only service DocType and
cipher kind cannot be installed or activated by an ordinary worker. Legacy
unmarked hooks retain their existing callback. No new signing or financial rule
is introduced.

The fixed owned worker claims READY with an enabled original actor and persistent
RUNNING fence. Generation and reservation recheck the bound fiscal source/chain
under their actual locks. Bounded System Manager discovery has no invoice-age
horizon, enqueues under authenticated original actors and restores session state.
RUNNING/REVIEW are held, not reclaimed, because durable handoff alone cannot
establish an unknown native transport outcome. Draft-operation propagation and
later PREPARED dispatch remain separate work. Detailed behavior and acceptance
limits: [NATIVE_SUBMISSION_INTENT.md](NATIVE_SUBMISSION_INTENT.md).

## Fixed draft operation propagation and scheduled waiting

The manual Sales/POS and shared scheduled draft callers now share a narrow
site/actor/source operation scope around ordinary ERP submit. Selected native
handoff copies manual/scheduled into its authenticated header; ordinary submit
and unmarked legacy queue policy remain unchanged. A retained or cross-context
scope cannot authorize another source. The native Sales external-ID Background
parent return now enters that same deferral after its existing validation.

A scheduled closed-window result is explicitly distinguished before preparation/
reservation/transport. Only that exact enabled Background result may persist as
WAITING. Future claims use new fences and repeat source/actor/policy checks;
rejected/uncertain originals are inspected before window policy, not hidden as a
wait. Discovery orders READY/WAITING by modification, authenticates the full
bounded batch before state changes and moves disabled original accounts to a
review hold without mutating source or immutable original actor/header.

Local tests exercise the actual parent branch with a storage double; private SQL
exercises the actual bridge/storage/provider with ERP-submit and signing-input
doubles. Their composition does not certify installed ERP accounting or full
canonical runtime. The old collector catches per-invoice errors and retains its
Sales/POS commit distinction: batch rollback and callback cleanup ownership still
need dedicated qualification, particularly with uncommitted POS parent writes.
Do not claim these gates from identifier/context tests or add a speculative
rollback that discards another operation's writes. See
[NATIVE_DRAFT_SUBMISSION.md](NATIVE_DRAFT_SUBMISSION.md).

## Borrowed ERP draft rollback and callback ownership

Selected Phase2 native draft submit now has a pinned borrowed savepoint boundary.
Current source/children observation, InnoDB catalog admission, callback prefix
identity, session transaction counters and a first commit fence precede submit.
Only an armed uncancelled native registration permits normal completion. A normal
failure cancels retained request closures and confirms local rollback plus
operation-only rollback callbacks before restoring parent callback prefixes/write
counter. No whole-parent commit/rollback is performed by this helper.

Lost ownership/epoch/savepoint or callback/cleanup provenance stops both collector
catch layers. Native/legacy transport and owned-worker entry are also denied
through this wider scope after the hook itself closes. Static English diagnostics
and fresh translated boundary errors avoid returning private child context.
Private SQL covers the actual Sales/POS collector with a failing middle source and
prior diagnostic writes. These are synthetic ERP/ledger/signing doubles; whole
installed GL/File, mixed submitted/legacy batches and runtime remain open. Details:
[NATIVE_DRAFT_ISOLATION.md](NATIVE_DRAFT_ISOLATION.md).

## Submitted native collection commands and existing prepared originals

Manual Sales/POS and shared scheduled submitted collections now register a
protected after-commit command instead of entering an owned dispatcher against
pending draft ERP writes/callbacks. The existing intent DocType/worker is reused;
original v1 submit headers are unchanged. A separate collection cipher/header
kind authenticates actor, expected original and a nullable unique active slot.
No-op duplicate INSERT arbitrates the slot using the current engine view rather
than a missing-key gap read or an older RR snapshot. Unknown/rejected native
custody blocks normal registration; explicit safe manual recovery creates a new
record without rewriting an earlier review.

The worker rechecks the expected version and releases only a completed collection
slot. A Background-only PREPARED discovery uses current alias-aware Company policy,
normal ACLs, authenticated originals, record/byte/company bounds and exclusion of
active scheduled commands, without an age cutoff. It owns only its separately
acquired clean scheduler transaction; no generation or transport runs in discovery.
Complete Standard/non-Background crash recovery remains open.

Actual local Frappe source inspection exposed LocalProxy-versus-target identity
comparisons hidden by direct test doubles. A shared current_database helper now
resolves the actual local DB object in parent/savepoint/queue guards. Private SQL
uses the real proxy class and independent RR connections; installed ERP15/16
acceptance remains a separate gate. Details and source-only schema changes:
[NATIVE_COLLECTION_REQUESTS.md](NATIVE_COLLECTION_REQUESTS.md).

## Destructive source lifecycle retention

The Sales/POS destructive document hooks now borrow the current transaction and
lock the saved source before reading native issuance/request history. Any retained
history or saved egs marker holds cancellation/deletion/rename; merge also checks
the destination. Normal unissued sources with UUID only retain ERP behavior.
This is negative retention evidence, never a claim of authenticated acceptance.
Phase/rollout changes and cleared output fields do not erase immutable identities.
No commit/rollback, request retirement, counter rewind or history deletion occurs.
Full physical source_name indexes and InnoDB are checked without migration; the
Submission Intent source declaration adds its search index. Installed lifecycle
qualification remains open. See
[NATIVE_INVOICE_LIFECYCLE.md](NATIVE_INVOICE_LIFECYCLE.md).

## Explicit unissued request retirement

A fixed System-Manager/source-permission Desk action now retires authenticated
READY/WAITING/RUNNING/REVIEW requests only when source locking and current native
history prove no generated or expected original. An independent authenticated
retirement capsule binds original header hash, prior fence/state, reviewing actor
and server time. Atomic state/proof storage is read back before commit; unknown
commit acknowledgement is never compensated. Original request history remains.

Worker execution now rechecks its committed RUNNING fence/header under generation
and reservation source locks, retaining a shared request lock through commit.
Paused old workers cannot generate/reserve after retirement, and stale completion
cannot overwrite it. A source without issuance/egs marker can pass the ordinary
retention guard only when all bounded request history verifies as RETIRED. This
borrows the parent transaction without taking over ERP commit/rollback. No queued
resend, ICV/PIH rewind or accepted outcome is implied. Custody-backed started-work
reconciliation and installed acceptance remain open. Details:
[NATIVE_UNISSUED_RETIREMENT.md](NATIVE_UNISSUED_RETIREMENT.md).

## Stopped requests with committed originals or captured responses

The fixed permissioned reconciliation action now reads the same retained-view
implementation as normal invoice publication and stages the same canonical
assessment as invocation processing. A current durable response whose assessment
was interrupted can be classified locally and committed atomically with request
completion/proof. No source projection, financial change, new artifact, transport
or queue registration occurs. Prepared completion remains accepted=False;
accepted completion requires matching retained receipt evidence. Current unknown,
rejected, late/superseded or contradictory outcomes remain held.

The two operator actions share nullable resolution_header/resolution_ciphertext,
generalizing the prior source-only retirement column names without rewriting any
capsule domain/body/header. Canonical owned-reader and assessment wrappers retain
their original transaction behavior; only their implementations are reused inside
the explicitly owned operator scope. Proof readback precedes commit and unknown
commit acknowledgement is never compensated. Separate installed schema/ERP and
genuine receipt/signature acceptance gates remain. Details:
[NATIVE_INTENT_RECONCILIATION.md](NATIVE_INTENT_RECONCILIATION.md).

## Explicit recovery from a prepared Issuance record

The readonly Issuance form now offers a deliberate manual queue action for an
untouched PREPARED original. Canonical ACL/current-source/custody admission occurs
in a clean owned read scope; the subsequent parent transaction borrows the shared
collection registrar with that exact expected version. The existing fixed worker
reuses saved bytes and repeats policy, actor, credential/route and outcome checks.
No builder, new artifact or transport runs in registration. Rollback prevents
queue handoff, and a race to existing acceptance resolves without another send.
This supports Standard and non-Background manual recovery without silently
changing automatic origin/actor policy, which remains open. Details:
[PREPARED_ORIGINAL_RECOVERY.md](PREPARED_ORIGINAL_RECOVERY.md).

## Origin-backed automatic first-send recovery

Canonical generation now inserts an optional protected origin capsule and three
authenticated selector indexes with the original and chain advancement. Delivery
actor/action/operation/method/classification and an optional original request
header/fence reference come from server contexts. The existing artifact header/
AAD, XML/request bytes and financial snapshot remain unchanged.

The shared prepared-discovery service now selects authenticated untouched origins,
checks enabled original senders/current ACL and method, and stages the same fixed
collection worker. Internal recovery commands require an existing exact version;
the worker verifies origin and repeats the original operation under current master
locks. Immediate sends retain the original actor; deferred Background is a distinct
current scheduler operation. Batches PREPARE never becomes automatic. Per-candidate
staging commits under that actor before restoring scheduler state, while site/key/
DB/physical connection remain pinned. No commit-unknown compensation or authority
transport occurs in discovery. Missing origin now holds old native records for
explicit manual action; no origin is backfilled from ERP owner fields. Details:
[ISSUANCE_ORIGIN_RECOVERY.md](ISSUANCE_ORIGIN_RECOVERY.md).

## Explicit unchanged retry operator

The Attempt form now registers a deliberate exact retry through the same durable
command/callback/worker lifecycle. retry-v1 has its own cipher domain and immutable
prior attempt/fence plus exact version, with matching nullable physical indexes.
Ordinary submit/collection/recovery shapes cannot claim that authority. Staging,
before-commit finalization and actual reservation repeat the current gate.

Lease/chain eligibility was factored from existing reservation into one shared
repository method. The owned retry evidence boundary additionally opens encrypted
original/receipt custody and reruns the canonical assessor for received technical/
authentication failures; mutable labels cannot bypass a reservation. Explicit
expired-unknown retry retains exact invoice bytes/identity and may still duplicate
a prior remote invocation. No new generation or automatic unknown replay occurs.
Current matched acceptance racing the command resolves without another send;
303 Reporting continuity uses its existing saved fallback evidence. Details:
[EXACT_RETRY_OPERATOR.md](EXACT_RETRY_OPERATOR.md).

Initial requests now retain authenticated STAGED custody before finalization.
Draft stage headers deliberately omit fiscal/Company/chain authority and use a
separate submission-stage domain. Collection/retry stages retain their complete
header in the existing domain. Both finalizers authenticate the initial envelope
before promotion; ordinary workers still reject STAGED. Explicit unissued
retirement now admits verified unclaimed stages, retaining the initial envelope
and recording its prior state. Old NULL envelopes remain held. No source/financial
repair, migration or installed action is performed:
[AUTHENTICATED_STAGED_REQUESTS.md](AUTHENTICATED_STAGED_REQUESTS.md).

The explicit Issuance-form late acceptance operator now authenticates an older
same-original/operation receipt and shared current-attempt eligibility under owned
locks. It records a separate protected decision and accepted state atomically,
keeping the newer technical-attempt pointer and all response/original bytes.
Canonical retained reads and projection authenticate that selection and rerun the
existing matcher; stopped intent reconciliation reuses the accepted view. No send,
chain-head rewind or automatic adoption occurs. Contradictory newer rejection,
unexpired or unrelated reservations and older versions remain held:
[LATE_ACCEPTANCE_REVIEW.md](LATE_ACCEPTANCE_REVIEW.md).

The correction backend now locks/rederives bounded attempt history and refuses
replacement when a prior invocation is unknown, accepted, technical/unconfirmed
or missing. A prior safe response need not have an already-written outcome label.
An explicit use_current_issue_time mode requires current native/Phase2/System-
Manager admission and supplies a server-selected immutable XML clock through the
preparation ticket to both Sales/POS metadata. Final custody verifies that exact
clock before committing the linked PREPARED version. Posting fields and normal/
Debug/Compliance paths remain unchanged. Desk/durable correction adoption remains
open: [CORRECTION_HISTORY_AND_CLOCK.md](CORRECTION_HISTORY_AND_CLOCK.md).

That operator is now adopted as correction-v1 in the existing store/callback/
worker lifecycle, with its own AEAD body and exact rejected attempt/fence indexes.
Current fiscal approval and actual generation claim/policy/rejection checks remain
separate. It prepares linked unsent custody only, without automatic origin/send
authority. Worker resume and the existing explicit request reconciliation verify
the exact current linked version and old rejection before local completion:
[CORRECTED_PREPARATION_COMMAND.md](CORRECTED_PREPARATION_COMMAND.md).

Native print-only artifact selection now extracts immutable saved seller/buyer
legal/name/ID/VAT/postal projections and compares selected cleared parties to the
original. The actual before_print hook applies them to supported transient fields
and party titles after fresh current-source/render verification. A typed local
stamp/observation adapter supports reprint without excluding arbitrary fiscal
fields or changing stored profiles. No live master fallback fills absent XML buyer
values. Header/template/direct-read/File/external gates remain open:
[ISSUED_PRINT_PARTIES.md](ISSUED_PRINT_PARTIES.md).

Named saved native sources without an issuance marker now receive a saved-policy/
selected-owner print hold before they can fall back to a legacy QR. It uses the
shared owner selector in READ mode; processing retains WRITE. Phase1/disabled/
legacy paths and historical custody selection remain unchanged. No preparation,
request finalization, enqueue or transport occurs in print. Installed/external
print remains open:
[NATIVE_PRINT_ADMISSION.md](NATIVE_PRINT_ADMISSION.md).

The existing Desk preview now classifies saved ownership before attempting custody:
LEGACY restores the normal QR field; UNISSUED supplies one waiting message without
an Error Log or issuance/QR/acceptance claim. A newly issued original found behind
an unmarked form requires an invoice refresh, with no model mutation or old/new
field mixing. Company/device token guards and strict contradictory-status handling
protect late reads. No polling/worker/transport is introduced:
[NATIVE_PREVIEW_ADMISSION.md](NATIVE_PREVIEW_ADMISSION.md).
