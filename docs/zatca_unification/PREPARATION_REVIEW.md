# Permissioned local preparation review

Increment 100 — 2026-10-25. OFFLINE development only. This is an uninstalled
internal metadata service plus display formatter, NOT a Company/invoice button,
whitelisted endpoint, provider registration, live hook, worker or migration.
No live source/schema/configuration was changed and no authority was contacted.

## Scope and source selection

[Durable preparation](DURABLE_PREPARATION.md) deliberately leaves a no-rebuild
hold after uncertainty. Earlier exact inspection required the complete original
ticket in memory. `MariaDBPreparationHoldRepository.load_for_source` now supports
protected inspection from the saved doctype/Company/invoice identity alone.

It uses the SAME permanent logical-source hash as reservation, validates input
before SQL, and makes one bounded unique-index source lookup in the explicit
namespace. The initial ticket read is nonlocking to preserve chain-before-hold
lock order. It then invokes the EXISTING strict exact loader: lock the registered
chain, reconstruct/compare the canonical ticket and indexed binding, verify the
current predecessor if pending, and compare the original/manifest if completed.
No latest/search/file scan, blank-field genesis or speculative repair is used.

A pending ticket can therefore be observed after loss of the original process
without invoking a builder. Absence is only a point-in-time local observation;
it proves neither that no original exists elsewhere nor that nothing was sent.
Concurrent reservations may occur after an absent read. None of these results
is a lease, a build opportunity, release permission or authority acceptance.

## Saved-source access boundary

`SavedPreparationReviewService(scope, connection_factory).inspect(...)` requires
the correctly bound current site and Administrator/System Manager AND normal
saved source READ plus Company/device/linked-Company READ. `ignore_permissions`
flags do not bypass the explicit ordinary permission check. WRITE is deliberately
not required for this read-only metadata inspection; it grants no mutation.

The existing archive engine now exposes its saved-row selection separately from
accepted archive/UUID/ICV binding. Existing QR/advance/receipt/pair clients retain
their identity/status rules unchanged. The review service reuses that selection,
owner resolution, v15/v16 permission-signature compatibility, exact source SQL
checks and existing owned-connection acquisition/cleanup rather than inventing
another permission system or switching legacy clients to a relaxed policy.

Review permits saved draft, submitted or cancelled Sales/POS documents and does
not require a saved UUID, ICV or accepted status: these may not yet have been
written when the pre-build hold was committed. Its current source projection
pins Company, docstatus, device selection and revision, with Company/related-owner
projections. It is NOT an accounting/source-tax snapshot and does not authenticate
the declared historical source digest or credential epoch.

Saved permissions/revisions are checked before acquisition; exact current source
SQL projections are locked and compared before and after hold access. When a
hold exists, it must match saved source identity, seller VAT, environment, credential owner and
route. Changed ownership/routing requires a separately reviewed historical-access
policy, not automatic fallback. Source/actor/ACL are rechecked after rollback and
close before any metadata is returned. Permission tables themselves are not
atomically locked or historically attested by these checks.

Only a NEW owned connection is accepted. Recognizable ambient Frappe/raw parent
handles are refused WITHOUT rollback/close. An owned handle's pending observations
are cleared first, then inspection always rolls back/closes; this service never
commits or cleans the ambient parent. Factory/tenant/namespace provenance is still
an external audit gate. Future generation/reconciliation adapters must coordinate
the same source-before-chain lock order; the supplied generic guard is not such
an installed ERP adapter.

## Minimal metadata and one display message

The report contains a fixed English `state`, nullable local original/active-hold
observations, and false-only verification/authorization flags. No XML, QR,
certificate, auth, ticket, UUID, ICV, PIH, hold ID, source name or protected hashes
are exported. Three states are intentionally non-authorizing:

- `PENDING_ORIGINAL_UNCONFIRMED_REVIEW`: a hold exists without a completed original
  recorded by this store. The builder MAY already have run; do not regenerate.
- `ORIGINAL_RECORDED_LOCAL_NO_REPLAY`: exact original/manifest were observed
  locally, not cryptographic validation, remote acceptance or resend permission.
- `NO_LOCAL_HOLD_OBSERVED_REVIEW`: no matching hold was observed in this namespace,
  NOT proof of no generation, no request or eligibility for a new original.

`present_preparation_review(report, translate)` validates that exact metadata
schema and false-only grants, then returns ONE app-owned title/message/indicator.
Arabic entries cover all three messages, title and both failure/denial messages.
Callers use the current user's translator for display ONLY; the report remains
English and unchanged. This increment writes no diagnostic/event record. A future
logger must store the English metadata, never the localized display projection.
There is no new live UI or button, and no XML/authority payload translation.

## Limits and rehearsal

This service does NOT call reserve/complete, regenerate/sign XML/QR, release a
hold, write a source, activate a certificate, authorize replay or send HTTP.
Late denial refuses even metadata; parser/SQL/provider errors become one translated
redacted error with no underlying exception context. Interruptions propagate
after best-effort owned cleanup. Raw original export and any exact-original
persistence need a separate saved WRITE/custody/provenance boundary.

Unit tests use synthetic documents and v15/v16 permission SIGNATURE mocks, not
installed version tests. They cover pending/recorded/absent, Sales/POS, all source
statuses, Company/device/linked ownership, saved IDs missing, route environments,
ordinary ACL refusal, site/role/actor checks, boundary drift, private failures,
borrowed-handle refusal, cleanup interruptions, protected lookup validation and
English metadata/Arabic single-message presentation. Native tests use ONLY the
fixture-owned SQL database and synthetic source tables for fresh-process lookup,
crash/restart, pending/completed/absent observations, current-source locks and
stale ORM values, related-owner access and rollback of an owned uncommitted
observation. No Frappe site or actual credential/enrollment is used.

Remain gated on authenticated source/tenant/connection/epoch provenance, durable
encrypted custody and reviewed recovery of a missing original, legacy writer/
counter mapping, whole-worker integration, installed ERPNext 15/16 and SDK/remote
acceptance. Preserve the user's completion-first isolated fictional-company then
adoption/cancellation and gradual-pilot order in [SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).
Authority requests remain prohibited regardless of future rehearsal approval.

Final guarded verification: **14,767 local + 2,124 private SQL = 16,891 passed
in 187.54 seconds**, across fourteen private SQL suites. This increment adds
**241 cases**: 215 local access/lookup/display cases and 26 native source-review
cases. Targeted shared QR/advance/review tests passed **484 cases in 3.43 seconds**;
the extended native chain suite passed **102 cases in 4.06 seconds**. All nine
Node VM scripts passed **1,444 cases**. Four initial native checks failed because
their new test helper lacked its Mock import; the import was corrected without
changing any assertion, permission, timeout or offline/network restriction.
No installed v15/v16, authentic enrollment/signature or authority acceptance is claimed.
