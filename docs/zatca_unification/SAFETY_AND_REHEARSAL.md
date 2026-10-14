# Offline development mandate and release sequence — increment 27

## Current user restriction, effective 2026-10-10

The user forbids applying development results to ANY working/production
environment and forbids agent-initiated requests to the tax authority. Development
continues in the isolated Git worktree only. Earlier requests to submit invoices,
restart Bench/workers or test CSIDs do NOT authorize those actions now.

No installed app update, merge into deployed source, migration, site configuration
write, Company creation on a running site, worker/scheduler action or Bench restart
is permitted. Do not modify host firewall/services to enforce the test policy:
existing customer services must remain unaffected. A development GitHub branch
push is not deployment or activation.

The authority-request ban includes Sandbox, Simulation and Production, OTP/CSID
issuance, Compliance invoices, final CSID, reporting and clearance. A dummy Company,
Sandbox label, synthetic invoice or successful HTTP-shaped mock does not waive it.
Only a later explicit user instruction changing this restriction can authorize
such requests; even future pilot/deployment approval is not API-send approval.

## Delivered rehearsal boundary

`tools/run_unification_rehearsal.py` invokes only an explicit reviewed manifest in
the linked development worktree. It does not use Bench or discover a site, tenant,
URL, OTP, CSID, storage namespace, SQL host/socket or an operational command.
Private SQL is OFF by default and cannot be enabled just by inheriting an
environment flag. The child uses the worktree PYTHONPATH, no bytecode/cache writes,
no inherited pytest options/plugins and no automatic third-party pytest plugins.

An explicitly loaded pytest guard starts before selected test collection. It:

- rejects ordinary Python TCP/IPv6 socket construction, including loopback and
  inherited descriptor adoption, DNS lookup, UDP/server operations and unknown
  Unix connections; reads/writes require a previously admitted private Unix peer;
- rejects normal Requests Session request/send paths before ordinary session
  authentication discovery, and Frappe init/connect, including starting
  with an already initialized site context;
- permits native subprocesses only for exact reviewed MariaDB installation/server
  command lists, with --no-defaults, fixed owned paths and --skip-networking;
  shell/env/cwd/executable/command overrides and Bench/curl are not accepted;
- creates owned 0700 scratch directories below /tmp, admits only their registered
  SQL sockets, rejects symlink retargeting, tracks its exact Popen objects and
  cleans up only those owned processes/directories after the tests;
- rejects broad/unreviewed pytest collection and non-worktree invocation.

The private SQL fixture now REQUIRES this active guard BEFORE binary discovery,
directory creation or subprocess acquisition. A manual opt-in environment flag
without the guard fails closed; there is no live database fallback. Existing
per-fixture checks still verify the private server socket/datadir/TCP-disabled
configuration. Synthetic HTTP pools still exercise preparation/adapter behavior
without releasing bytes to an actual HTTP socket.

This is an accidental-I/O regression guard, NOT a hostile-code/OS/network sandbox
or proof against cached aliases, monkeypatching, native extensions, raw syscalls
or native child-process behavior. Only the reviewed ordinary Python paths and
fixed native fixtures are exercised. Full future application rehearsal requires
separate approved infrastructure/egress isolation; this test guard must not be
installed into a running Frappe process or used to disable customer operations.

## Reproduction from the development worktree

Local-only tests:

```sh
PYTHONDONTWRITEBYTECODE=1 ../../env/bin/python tools/run_unification_rehearsal.py
```

Local tests plus all six owned-private SQL suites:

```sh
PYTHONDONTWRITEBYTECODE=1 ../../env/bin/python tools/run_unification_rehearsal.py --private-sql
```

The second command may require narrowly reviewed permission for its private Unix
socket/native server subprocess. It accepts no site, URL, socket, OTP, deployment
or generic pytest target/option. Do not point it at the installed application.
The SQL subprocesses have no customer data and are not a restored Frappe site.
No dependency upgrade, runtime installation, credentials or external request is
needed by this increment.

## Verification

80 added local cases prove known denial paths are stopped before native I/O,
using stubs/mocks rather than actually reaching denied targets. They cover
TCP/IPv6/loopback, inherited/unknown peers, DNS, Requests/site operations,
exact process arguments, symlink changes, owned cleanup, no unguarded private
SQL startup, fixed test selection, option rejection and sanitized runner setup.

At increment 27 the protected runner passed **3,919 local + 118 private SQL = 4,037 cases**.
All six existing SQL suites, including contention and owned-process crash recovery,
were rerun under the new guard. No tax-authority send, tenant DB read/write,
working-site Company, Bench action, full ERPNext 16 boot, browser, SDK or real
TLS handshake is demonstrated by these results.

Increment 28 adds [explicit local receipt persistence recovery](COMPLIANCE_RECEIPT_RECOVERY.md),
reaching **3,986 local + 131 private SQL = 4,117 cases** across seven guarded SQL
suites. This remains synthetic offline storage evidence, not remote acceptance
or authorization to operate on a working environment.

Increment 29 adds [permissioned local recovery/shared saved-source access](COMPLIANCE_RECEIPT_RECOVERY_ACCESS.md),
reaching **4,173 local + 143 private SQL = 4,316 cases** across eight guarded SQL
suites. Source/permission/provenance limitations and the mandatory acceptance
order below remain unchanged; no installed provider or authority call exists.

Increment 30 adds [shared issue-time parsing and adapter checks](ISSUE_TIMESTAMP.md).
The offline guard also denies the normal `frappe.logger` entry point before
log discovery; translation fixtures stay mocked. This does not add a global
filesystem/hostile-code sandbox or permit any working-environment operation.
The final guarded selection reaches **4,386 local + 143 private SQL = 4,529 cases**.

Increment 31 adds [original advance reference observations](ADVANCE_REFERENCE.md)
and 101 synthetic/legacy-characterization cases. It is not adopted by runtime
assembly and cannot establish authentic issuance/acceptance or repair customer
references. Current-source metadata must not rewrite historical XML clock fields.
The user mandate and separate development/dummy/pilot gates remain unchanged.
The guarded runs passed **4,487 local + 143 private SQL = 4,630 cases**.

Increment 32 adds [exact archived-attempt advance source choice](ADVANCE_SOURCE_SELECTION.md).
The selector has no current-site/file/status lookup or runtime integration. A
consistent response and exact bytes do not prove authorized origin or durable
commit; the new ninth private SQL suite explicitly rehearses uncommitted rollback.
Site/namespace/committed-record provenance and saved-row permission checks remain
gates before any source disclosure or settlement adoption. No working-source
change, authority call or fictional Company on a customer bench is authorized.
The final guarded run passed **4,565 local + 153 private SQL = 4,718 cases**.

## Mandatory order for subsequent work

The user reiterated the whole-change decision on 2026-10-11: after finished
development and isolated fictional-client rehearsal, they choose adoption of
ALL changes or cancellation. That decision is still pending and does not imply
deployment or revoke the sending ban. See [DUMMY_REHEARSAL_DECISION.md](DUMMY_REHEARSAL_DECISION.md).

Increment 33 adds [permissioned metadata-only advance source inspection](ADVANCE_SOURCE_ACCESS.md).
Saved source/owner ACL, owned local locks and cleanup are rehearsed without
runtime adoption, source XML export, tenant acquisition or authority sending.
Provider provenance and authentic acceptance remain gates; no authority flag is
set true just because a local permission/metadata check succeeds.
The final guarded selection passed **4,642 local + 176 private SQL = 4,818 cases**.

Increment 34 adds [five-tag QR/missing-source review](ADVANCE_SOURCE_GAP.md).
It cannot produce missing original identities/XML, change accounting eligibility,
scan images/files, repair a tenant, make authority requests or activate a bridge.
All new cases use fabricated payloads or mocked builders. The unchanged legacy
ordinary QR commit is characterized with a mock, never a working transaction.
The final guarded selection passed **4,718 local + 176 private SQL = 4,894 cases**.

Increment 35 changes [Phase-1 QR metadata transaction ownership](PHASE1_QR_TRANSACTION.md)
in DEVELOPMENT only: no ordinary helper recursive invoice save/commit/schema DDL.
Tests use mocked File/image operations and an eleventh owned-private SQL suite;
they do not create QR files or update an installed tenant. Attachment deletion,
caller commits and actual filesystem/installed v15/v16 integration remain gates.
The final guarded selection passed **4,744 local + 188 private SQL = 4,932 cases**.

Increment 36 adds [ordinary QR preservation/review](QR_ATTACHMENT_PRESERVATION.md).
PRESERVE/REVIEW never delete, relink, clear a saved reference or create an image.
Only supplied synthetic metadata and owned private SQL projections are exercised;
no files, tenant/production state or authority API is touched. Other QR writers
and actual filesystem/concurrency/installed-app behavior remain open gates.
The final guarded selection passed **4,822 local + 196 private SQL = 5,018 cases**.

Increment 37 extends [preservation to the advance print hook](ADVANCE_QR_PRESERVATION.md).
No forced replacement or implicit final-invoice attachment cleanup remains in
that hook. Existing amount/discount/FX/status gates and advance lookup/allocation/
eligibility stay unchanged. Explicit regeneration, concurrency and installed
lifecycle remain unfinished. Only synthetic mock/owned-private SQL data was used;
no working source/schema/Company/worker or authority request changed.
The guarded combined selection passed **4,884 local + 200 private SQL = 5,084 cases**
in **44.50 seconds** across the same eleven private SQL suites.

Increment 38 adds [saved-row QR recovery access](QR_REGENERATION_ACCESS.md):
read/write ACL boundaries, exact File ownership, bounded observations, static
Arabic denial and POST-only mutation registration. Unit tests unwrap the request
typing decorator and use mocked ERP/File methods and memory-only XML content;
they do not establish installed v16/HTTP/File lifecycle acceptance. Legacy
selection/re-link/commit behavior remains explicitly unapproved and unfinished.
The guarded run passed **5,063 local + 200 private SQL = 5,263 cases** in
**47.83 seconds**, with the same eleven private SQL suites. No working site,
worker, schema, customer data or authority request was touched.

1. **Complete development offline.** Finish the shared settings/source/credential
   contracts, amounts/advance handling, immutable XML/signature/QR pipeline,
   debug/single/all/synthetic Compliance adapters, identity/retry coordination and
   dependency/version acceptance evidence. Tests use generated keys and synthetic
   documents only. Counts/HTTP-shaped responses are not remote verification.
2. **Then obtain separate dummy-company rehearsal approval.** Choose a NEW isolated
   v15/v16 test bench and purely fictional Company/data, not an extra Company in
   a working customer bench. Disable/contain outgoing HTTP, email, webhooks and
   automatic jobs in that isolated infrastructure before full-app testing. No
   live configuration or existing customer worker is altered to prepare it.
3. **Rehearse the completed build on that fictional Company first.** Cover fresh
   install/migration behavior, English/Arabic controls, all document/phase modes,
   POS, advances, GL/VAT reconciliation, debug and local simulated onboarding.
   Local fake CSIDs/results remain visibly simulated; they cannot generate a
   genuine final CSID or complete an actual authority Compliance step. The current
   authority-request ban remains in force throughout this stage.
4. **Only after documented dummy acceptance, obtain a named active-client pilot
   decision.** Review backup/restore and rollback/immutable-artifact/counter
   preservation, specify exact source/config/schema changes, explain impact and
   secure explicit approval BEFORE any working-environment write. Pilot approval
   must separately address the still-active authority-send prohibition; do not
   activate hooks that would cause a prohibited send indirectly.
5. **Expand gradually after pilot acceptance and another rollout decision.** Never
   infer fleet deployment, invoice replay, credential rotation or an API send from
   a generic "continue". Monitor only the approved scope and preserve customer data.

These stages are future gates, not actions executed or approved by this increment.
Full development and real v15/v16/application/crypto/advance acceptance remain
unfinished. Remote authority acceptance is a separate unverified gate and cannot
be inferred or marked complete while actual requests remain prohibited.
