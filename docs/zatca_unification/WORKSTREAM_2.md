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

The four existing-XML wrapper/API pairs now have actual native admission for
exact private attached originals, version fences and frozen retained type policy:
[NATIVE_EXISTING_XML.md](NATIVE_EXISTING_XML.md). This is not legacy-history import
or completion of activation/drain, explicit retry/correction and whole-runtime gates.

Initial native CSR preparation now uses a bounded, permission-checked saved-owner
identity inventory under verified InnoDB range-lock semantics. It rejects another
material/history-backed declaration of the same unit before generating a key.
This covers owner/key/serial discovery only; full legacy counter/source/File
history and drained dispatchers remain open. See
[NATIVE_IDENTITY_INVENTORY.md](NATIVE_IDENTITY_INVENTORY.md).

Inactive legacy review now also rejects saved Sales/POS contradictions to the
counter tail, with exact ICV comparison and verified source/counter storage
semantics. This is neither a full older-slot/PIH inventory nor activation/drain:
[NATIVE_LEGACY_TAIL.md](NATIVE_LEGACY_TAIL.md).

The same review now checks canonical older saved UUIDs and duplicate ICV/UUID
slots within and between Sales/POS, using current locking aggregates/joins so an
older ORM snapshot cannot hide a newly committed duplicate. Gaps are not a zero
seed or a reason to renumber. Full XML/PIH/rotated-consumer history remains open.

Known owner/delegate/declared-unit consumer closure and a permission-checked,
current locked counter catalog are now adopted in that inactive review. Another
known Production counter holds without maximum/zero inference. Captured issuer
records are also compared with current locking reads before material admission.
This is not full unattributed history, drain or activation:
[NATIVE_LEGACY_CONSUMERS.md](NATIVE_LEGACY_CONSUMERS.md).

Otherwise unattributed counter references now have a bounded attached-XML probe.
Saved source/File permissions and current identity binding precede public-key/
declared-unit comparisons. Potential overlap holds; missing/over-budget evidence
is unresolved, and infrastructure failures abort review. No complete history,
cryptographic trust, drain or activation is inferred:
[NATIVE_LEGACY_ARTIFACT_PROBE.md](NATIVE_LEGACY_ARTIFACT_PROBE.md).

Selected native submit hooks now stage a separate authenticated submission intent
in the parent ERP transaction and seal its final source/actor/chain binding before
commit. Identifier-only after-commit enqueue and bounded READY recovery use a
fixed worker; RUNNING/REVIEW never authorize automatic retry. Unmarked legacy
handoff is unchanged. This is not complete started/crash/draft/PREPARED discovery
or installed lifecycle acceptance: [NATIVE_SUBMISSION_INTENT.md](NATIVE_SUBMISSION_INTENT.md).
