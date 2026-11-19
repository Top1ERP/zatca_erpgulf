# Workstream 2 — issuance, receipt and retry lifecycle

Active after workstream1 commit44fdd50. This workstream is not complete. Do not
announce workstream3 merely because a coordinator primitive or a larger test
selection passes. Development remains offline in the isolated worktree.

## Closure checklist

- [ ] No authority transport or issuance-side commit inside an ERP invoice submit
  transaction; Phase1 stays local. Preserve fiscal validation ordering and normal
  source permissions. Worker handoff must not serialize documents/credentials.
- [ ] Durable exact artifact + UUID/ICV/PIH/issuer/environment/version ownership,
  committed before transport. Missing/uncertain storage cannot regenerate or send.
- [ ] Stable EGS mapping across key renewal. Explicit NEW_EGS genesis and reviewed
  legacy continuity; never infer zero from missing XML, blank PIH or a new token.
- [ ] Atomic local chain advancement on document generation, independent of remote
  acceptance. Retain rejected originals; no counter/hash rewind or silent reuse.
- [ ] Serialize competing workers and preparation; durable attempt fencing and
  crash/unknown commit recovery; never hold DB row locks across HTTP.
- [ ] Exact captured receipt before derived invoice/QR/status updates. Distinguish
  validation rejection, technical/unknown failure, late response and local failure.
- [ ] Endpoint/environment-aware duplicate208/409 handling and clearance303
  fallback, bound to the original artifact/attempt. A generic status is not enough.
- [ ] Unknown outcome retries preserve exact bytes/UUID/hash/ICV; corrected verified
  rejection creates a new linked document version with the current local PIH.
- [ ] Saved-source cancellation/printing/recovery decisions use issued/accepted
  evidence, not UUID presence. No automatic historical invoice repair.
- [ ] Whole runtime Sales/POS/manual/worker/background/Debug/Compliance matrix,
  concurrent/restart/lost-response/private-SQL tests and readable operator messages.

## Primary guidance and deliberate policies

The [official detailed technical guideline](https://www.zatca.gov.sa/en/E-Invoicing/Introduction/Guidelines/Documents/E-invoicing-Detailed-Technical-Guideline.pdf)
distinguishes corrected rejection from an unchanged retry, retains generated
rejected-document chain positions, and bases the next PIH on the immediately
preceding generated document. A network timeout alone is not a verified rejection;
our unknown-outcome policy preserves the original artifact for review/retry.
The current local allocator/success-only PIH updater still needs replacement;
the already-tested pure issuing-chain model is not an adopted runtime service.

The [Fatoora Development Team announcement, 2025-08-07](https://zatca1.discourse.group/t/deployment-notification-duplication-check-response-codes-208-and-409/7954)
adds Production clearance duplicate208 with returned cleared XML and Reporting
409 for a previously reported hash. Do not treat every409 as accepted or use the
Reporting duplicate rule for clearance. An older guideline's unrestricted-repeat
wording predates this deployed duplicate check. Receipt/source/operation binding
and returned XML integrity still require their own verification.

Local Frappe15 `enqueue(...enqueue_after_commit=True)` supports handoff but obtains
Redis before adding its callback and has a migration-mode synchronous fallback.
A hook handoff must register its callback before any queue access, forbid inline
transport, and recheck saved source/settings/permissions in the worker. Queue
deduplication is not a durable invoice/chain lock or outbox. These are separate
closure items; an after-commit helper alone cannot close workstream2.

No live migration/worker operation, authority API request, credential activation,
installed acceptance or fictional Company on a working site is authorized.

Implementation sequence and current adoption limits: [WORKSTREAM_2_RUNTIME_DESIGN.md](WORKSTREAM_2_RUNTIME_DESIGN.md).

The first actual custody-backed Desk/transient-print adapter is documented in
[NATIVE_PUBLICATION.md](NATIVE_PUBLICATION.md). It does not close the publication
checklist: [generation-time collection evidence](PUBLICATION_COLLECTION_STATE.md)
now admits named payment/POS updates; legacy NULL evidence keeps its old full
comparison. Frozen master/print information, saved File consumers, external print
engines and pre-issuance native printing still require explicit adoption/acceptance.
