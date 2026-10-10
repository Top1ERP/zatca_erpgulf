# Single-attempt dispatch observations — increment 14

Follow-up: increment 15 adds [response assessment](RESPONSE_ASSESSMENT.md) over
this unchanged receipt journal. It classifies local operation/validation/XML
consistency, not verified network provenance, persistence or acceptance authority.

Development branch only. No runtime adapter uses this journal, and no tenant,
invoice, UUID/ICV, counter, PIH, credential, schema or stored artifact changed.
No HTTP, deployment, bench/worker restart or live-source edit was executed.
The user explicitly requires notice before any change to the live application;
rollout scope/window and release gates remain separate decisions.

## Implemented boundary

`dispatch_journal.py` is a pure, frozen, **single-attempt** event contract over
one `PreparedIssuanceCandidate`. It is not a dispatcher, durable ledger/outbox,
SQL lease, cross-attempt coordinator, retry policy or acceptance validator.
Creating an empty journal is never dispatch authority. No UI/whitelisted method
or hook was added; static internal codes will need translation in future adapters.

Events declare canonical nonnil event/attempt UUIDs, contiguous sequence, supplied
explicit UTC timestamps and the exact candidate's scope/content fingerprints.
The model reads no clock or current invoice/settings/credentials. It never signs,
normalizes XML, allocates counters, attaches files, sends HTTP or commits SQL.

| Event | Required observation | Derived local state |
| --- | --- | --- |
| No event | Existing prepared candidate only | `PREPARED_CANDIDATE` |
| `ATTEMPT_STARTED` | One declared attempt bound to the unchanged candidate | `IN_FLIGHT_OBSERVED` |
| `TRANSPORT_UNKNOWN` | Static TIMEOUT/CONNECTION_ERROR/WORKER_INTERRUPTION cause; no raw exception or HTTP fields | `OUTCOME_UNKNOWN` |
| `HTTP_RESPONSE` with 401/403 | Bounded exact response bytes and terminal HTTP status | `AUTHORIZATION_FAILURE_OBSERVED` |
| Other `HTTP_RESPONSE` | The same receipt contract, regardless of body or status | `HTTP_RESPONSE_OBSERVED` |

None of these is verified acceptance. In particular, 200/202, generic 409,
REPORTED/CLEARED text, empty/malformed/HTML bodies and saved status do not advance
PIH or grant replay. This increment intentionally does **not** parse/classify the
body into validation rejection versus confirmed reporting/clearance acceptance.
A separate strict endpoint/receipt/identity contract is still required.

## Exact evidence and sequence

Receipt bodies must be immutable bytes up to the existing 8 MiB response bound.
They are not decoded, pretty-printed, truncated, interpreted as JSON or normalized.
The receipt records their SHA-256 and length; empty bytes remain an actual empty
receipt, not a fabricated successful response. HTTP status must be an integer
200–599, not a boolean/float/string or an informational 1xx status.
Optional request IDs use the current contract's canonical UUID form; arbitrary
header/exception text is not accepted. A future capture adapter must handle
unsupported metadata without discarding protected raw receipt evidence.

`append_dispatch_event` returns a new validated tuple history. Repeated event-ID
delivery with identical facts returns the existing journal, including after a
late response. Reusing an ID with changed status/body/reference is a conflict,
not overwrite. Direct construction also rejects duplicate IDs, sequence gaps,
foreign candidate/attempt references and backwards event times. Equal UTC times
are ordered by sequence. IDs and operational timestamps are not invoice issue
date/time or evidence of actual remote wire timing.

At most three events are admitted: start, optional unknown outcome, optional
response. A late receipt for the same attempt can follow OUTCOME_UNKNOWN; the
earlier timeout/interruption remains in the history. A known receipt cannot be
overwritten/downgraded, and another unknown event is not resolution. A second
start is refused both while in flight and after an observed terminal outcome.

`active_attempt_id=None` after an unknown/receipt means only this model has no
locally active observed attempt. It does not prove remote processing stopped,
release a SQL lease or permit a second request. A caller can construct another
memory object; only future persisted, authorized cross-attempt coordination can
actually prevent duplicate concurrent submissions.

Candidate bytes/UUID/ICV/PIH/epoch remain unchanged through every transition.
Changing candidate XML under an existing history fails the manifest binding.
The versioned journal fingerprint covers candidate references and ordered event
projections/body hashes. It is bookkeeping, not a trusted timestamp, HMAC,
tamper-proof storage or proof that caller-supplied receipts came from ZATCA.

## Privacy and authority

Bodies, XML and raw route URL are omitted from repr/diagnostics. No keys/auth are
accepted. Generic dataclass serialization can still expose bodies and must not be
used in logs/UI. Receipt storage needs actual access control, encryption/recovery
policy and immutable-persistence enforcement outside this model.

`persistence_verified`, `lease_verified`, `remote_acceptance_verified`,
`dispatch_authorized` and `replay_authorized` remain false in every state.
The journal does not consume historical display observations as live acceptance
proof and does not manufacture success, failure-based identity resets or retries.

## Verification and next gate

161 new local cases cover Sales/POS reporting/clearance parity, unknown causes,
late receipts, HTTP status/body preservation, UUID/hash/time/type bounds,
sequence/attempt/candidate mismatch, idempotent redelivery versus conflicts,
second-start refusal, protected candidate identity, derived-field immutability,
safe projections and no database/filesystem/HTTP/clock access. Synthetic receipts
and deliberately invalid signature fixtures are not remote acceptance evidence.
The combined selected suite passes 2,048 cases in v15/Python 3.10 locally.

No actual site, SQL transaction/locking, ERPNext 16, browser, SDK or HTTP result
was exercised. Next: strict live response/endpoint and returned-XML identity
classification; then verified source/credential/chain provenance, durable
repository/outbox/leases and restored-site interruption/concurrency rehearsal.
Do not connect these local states to live status/PIH or automatic dispatch.
