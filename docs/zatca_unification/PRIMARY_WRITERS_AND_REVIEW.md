# Primary writers, missing/late responses and bounded review — increment 56

Source/offline/private-SQL audit dated 2026-10-16. No working environment,
customer data, authority request, runtime retry or deployed code was changed.
This is implementation evidence, NOT a regulatory endorsement or completed
durable-response/lost-response fix. The broader development remains unfinished.

## Three distinct storage families, not an installed unified ledger

| Family | Current writers/readers | Observed boundary |
| --- | --- | --- |
| Existing runtime | Four primary Sales/POS reporting/clearance APIs plus eight existing-XML/generation adapters | Mutable invoice response/status/UUID fields, owner PIH, File/log helpers and legacy commits; not the new encrypted pair ledger |
| Internal single-store primitives | `PrimaryReceiptPersistence` / `SavedPrimaryReceiptService`; custody repository / `SavedPrimaryReceiptCustodyService` | Independently store one exact journal response or one encrypted envelope; two separate commits may leave a partial pair |
| Staged paired workflow | Capture coordinator/access, pair reconciliation/access | Explicit exact request/hold/key/source binding; paired atomic response storage and review-only partial conflicts, with NO active runtime caller/provider registration |

The first family is characterized by `test_retry_identity_contract.py` and
`test_response_processing.py`. The new review suite scans the twelve actual
adapter function bodies for direct staged writer/reviewer references; it does
not claim whole-program proof against arbitrary dynamic/plugin code. The staged
single-store components are NOT the storage currently backing all invoices.
Consequently, an absent row in the new tables cannot explain a live customer's
history or authorize importing/reissuing their invoice. No live tables are
queried, backfilled or provisioned by this increment.

The four primary APIs still have independent response, owner/PIH, invoice, File
and log steps with legacy commits or `db_set(commit=True)`. POS reporting can
save request XML before HTTP. Existing-XML/generation adapters still have the
identity/reset differences recorded in [RETRY_IDENTITY.md](RETRY_IDENTITY.md).
The staged pair guards do not automatically govern those writes.

## Reproduced remaining runtime error gap

Increment 45 prevents previously caught local failures during primary
200/202/legacy-409 processing from running generic failure persistence. It does
NOT protect every rejection/error-status logging path. New mocked tests call
the four real primary APIs with HTTP 400/401/503 and a local event-log failure:
generic handlers can replace `custom_zatca_full_response` with local `Error: ...`
and commit mutable error fields; clearance can label the failure as 503. Exactly
one mocked post occurs. No real HTTP, actual customer response or secrets are
used. This is a characterized gap, NOT a repaired behavior in this increment.

The next bounded runtime-source change should isolate response formatting/logging
failures on ALL received statuses without converting intentional remote rejection
exceptions into local failures or changing acceptance/duplicate classification.
Use the existing static translated local-review signal, preserve known response
ownership and test all four adapters and their callers before expanding scope.
Do not simply remove every commit: a later exception can otherwise roll back the
only local evidence of a remote response. Independent durable custody and parent
transaction lifecycle must be designed before actual transport integration.

## Reproduced partial-store window and commit uncertainty

Private tests start with a real committed start/hold/request binding and an
original synthetic response whose pair commit did not finish. They invoke the
actual single-store journal helper or custody repository first. A second owned
connection observes JOURNAL_ONLY or CUSTODY_ONLY; explicit paired persistence
leaves it review-only and unchanged. A deliberately uncertain second independent
commit may leave that same partial pair OR a matched pair. Inspection distinguishes
local observations, but none proves remote non-delivery/acceptance or grants a
repair/retry. The original hold/request/envelope remain unchanged throughout.

This does not deprecate/delete single-store primitives: existing local callers
still need explicit compatibility policy. New unified runtime adoption must not
fall back to independent writers when paired persistence fails. Keep originals,
review the exact pair and preserve the no-replay hold instead of filling one half
speculatively or selecting newest/resealed data.

## Missing, unbound, unsealed and genuinely late are different

- Unknown observer outcome contains no complete response in the returned capture.
  It is NOT proof that the authority never received a request or that the observer
  retained nothing. Original observer/server custody and pre-first-durable-commit
  process-loss policy remain unresolved; this component cannot reconstruct bytes.
- A complete but unbound response remains a separate protected observation. Do
  not attach it to a preferred attempt/invoice, allocate a fresh identity or use
  payload success text as origin proof.
- A complete response without a usable original seal requires custody review,
  not an automatic seal/reseal/retry. No new key or nonce is obtained here.
- An original response already sealed against START/sequence 2 cannot be moved
  after a subsequently stored UNKNOWN event by changing its sequence/time/ID or
  predecessor. Tests prove both single-store and strict paired paths refuse that
  substitution; the pair remains conflict-review and the original seal is intact.
- The older explicit retained-receipt contract CAN represent an independently
  supplied late response against an already-UNKNOWN predecessor at sequence 3.
  Tests supply its OWN original ID/time/body, not a rewritten earlier response.
  Separate single-store SQL can retain that history/envelope, but START-only
  capture/pair reconciliation rejects its different predecessor BEFORE SQL.
  No real late-response receiver or permissioned paired late-adoption policy is
  implemented, and the older helper's capability is not approval to manufacture
  a late receipt or bypass the strict new boundary.

## Unified pure review, not authorization

`review_primary_outcome(captured, pair_observation=None)` validates exact typed
capture and optional paired results. A paired observation is admissible only if
the capture has an original seal and the full request/start/envelope is identical.
An independently reloaded identical seal is allowed; a reseal, different namespace,
changed request or fabricated metadata dictionary is not. No provider/key/SQL/
clock/file/cipher/observer callable is accepted or invoked.

The returned `PrimaryReviewObservation` holds ONLY closed state strings, not
protected input references. Its projection identifies the review focus:
start/preflight uncertainty, missing/unbound/unsealed response, local pair
uncertainty, missing/partial/conflicting pair or recorded/matched response without
acceptance proof. Status 200/202/409, binary/empty bodies or success-shaped JSON
do not change that scope. This does not deny success of a genuinely validated
authenticated response; this staged component does not possess that evidence.

An earlier completed-capture observation paired with a currently missing/partial/
conflicting observation sets `local_history_disagreement`. It is a difference
between supplied observations, not proof of deletion, corruption, chronology or
permission to repair. Unconfirmed inspection alone is not a proven disagreement.
The projection always keeps origin/epoch/transport/durable-custody/remote-acceptance
flags false and grants NO automatic follow-up, identity change, hold release,
raw export, dispatch or replay. An explicit separately authorized local operation
is not enabled or revoked by this diagnostic; existing source/ACL gates apply.

No UI labels or endpoint are installed. Review codes are internal; any future
operator UI must translate its labels and repeat final saved-source/ACL checks
before disclosure. This module cannot read a source or grant access to its status.

## Verification and next gates

Use the reviewed offline runner in the development worktree:

```sh
PYTHONDONTWRITEBYTECODE=1 ../../env/bin/python tools/run_unification_rehearsal.py --private-sql
```

Actual private SQL tests use only new temporary servers, synthetic keys/data/
responses and explicit caller transactions. No Bench/customer service is used.
The guarded combined run passed **7,499 local + 884 private SQL = 8,383 cases in
101.30 seconds**, across the same twelve private suites (107 local + 13 private
SQL additions). An initial test-only privacy assertion compared an absent seal's
`None` to the optional pair state's `None`; it was corrected to check non-None
protected identities and strengthened to require only the two closed state fields.
No storage/source/permission guard was waived. History is in [STATUS.md](STATUS.md).
Runtime-source error-log
characterization remains an explicit unresolved gate. Full installed v15/v16,
SDK/crypto/QR/advance GL/VAT, independent source/key/provider/epoch/transport
provenance, actual late receiver and pre-first-durable-response loss remain
unverified. Finish development before separately approved isolated fictional-
client rehearsal, adopt/cancel and gradual pilot decisions. Publication is not
deployment or authority-send permission; see [SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).
