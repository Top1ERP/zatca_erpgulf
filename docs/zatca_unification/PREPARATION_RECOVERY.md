# Saved-WRITE exact-original local preparation recovery

Increment 101 — 2026-10-25. OFFLINE development only. This is an uninstalled
internal persistence boundary, NOT a live endpoint/button, authority client,
builder, credential activator, migration or queue. The existing READ-only
[preparation review](PREPARATION_REVIEW.md) remains separate and unchanged.

## Protected inputs, not a regeneration workflow

`RetainedPreparationOriginal` binds the server-provisioned site/namespace, the
original immutable hold/ticket and the exact already-generated candidate. It
rebuilds the existing strict ticket/context/candidate codecs and checks every
derived field, UUID/ICV/PIH, candidate context and any declared completed manifest.
Inputs are private server objects, not browser dictionaries or XML uploads.
No returned data contains raw XML/QR/certificate, UUID, ICV, PIH or hold ID.

The caller MUST retain independent protected custody even after denial,
interruption or an unconfirmed commit. The memory object is neither durable
encrypted custody nor proof of source/epoch/crypto provenance. This increment
does not install a vault, original exporter or automatic missing-original repair.
An original that was lost before durable custody STILL cannot be regenerated
through this service. The pending no-rebuild hold remains for separate review.

## Access and local mutation policy

`SavedPreparationRecoveryService(scope, source_evidence_guard, connection_factory)`
requires an explicit trusted server scope/factory and a MANDATORY evidence guard.
There is no default verifier, fallback to current settings or implicit latest
record selection. `persist(invoice_name, retained, doctype=...)` requires:

- Current correctly bound site and Administrator/System Manager identity.
- Normal saved source WRITE, independently of READ review permission, and saved
  Company/device/linked-Company READ. No ignore-permissions shortcut.
- A committed submitted source (`docstatus == 1`). Draft/cancelled documents
  remain READ-reviewable but are refused for this mutation. This is a conservative
  INTERNAL ADOPTION POLICY, not a claim that ZATCA requires submitted ERP status
  or that a historically generated cancelled document can be discarded. Their
  historical recovery needs a separately reviewed policy; do not clear the hold.
- Exact target/site/namespace, current seller/environment/owner/route binding,
  and normal saved revisions/projections consistent with the protected original.
- Literal True from `source_evidence_guard(scope, rows, retained, connection=...)`
  before acquisition, before/after local completion and after owned cleanup.

The evidence adapter MUST compare the committed accounting/issue-time/settings
snapshot and credential epoch with the original declared source digest, and
verify protected custody/source provenance. It must remain local, must not send
HTTP, and must not change connection ownership or write source data. No such
authentic ERP/custody adapter is installed here. A test callback's True is NOT
source attestation, crypto/SDK acceptance or a replacement for ordinary ACL.

The existing saved source/owner selection, permission-signature compatibility,
SQL source checks and owned-connection helper are reused. An independent validated
copy pins all nested/derived fields and exact immutable bytes; callback-boundary
comparisons do not repeatedly parse the XML. This is not a measured speed claim
or a Python sandbox against arbitrary trusted server code. Input substitution,
including coherent new bytes under the same UUID, is rejected before persistence.

## One owned transaction, no parent commit

After normal access and explicit evidence succeed, acquire only a NEW owned
non-autocommit connection. Recognizable ambient Frappe/raw parent handles are
refused without commit/rollback/close. Clear pending observations on the owned
handle only. Never supply borrowed parent work to this service.

Within the owned transaction, lock/recheck the exact current source projections
BEFORE the registered chain/hold. Recheck projections on BOTH sides of the
evidence callback, then call the existing exact hold `complete()` operation.
Original bytes, next chain head and hold completion share one atomic transaction.
Confirm returned ticket/manifest/registration/position and repeat guards before
commit. The repository itself still owns no commit/rollback/connection lifecycle.

The existing repository supports only the retained pending ticket plus unchanged
predecessor, or an exactly already-recorded original. Exact redelivery after later
issuance does not increase the counter again or rewind the head. Different bytes,
missing hold, partial records, corrupt tickets or unexpected predecessors never
create/reset/release/adopt anything. Completing an exact original clears its
active-chain marker through the existing atomic protocol, NOT through a manual
release API; the permanent saved-source hold remains.

Owned commit AND close must both return to report
`PREPARATION_ORIGINAL_STORED_LOCAL_NO_REPLAY`. This includes matching an already
stored original, not necessarily a fresh insert. A local acquire/SQL/commit/close
exception yields `PREPARATION_RECOVERY_UNCONFIRMED_NO_REBUILD` after final access/
evidence checks. That does NOT prove rollback or absence: commit may have succeeded.
No automatic retry or second connection is opened by the recovery method.

Late source/ACL/evidence denial refuses even metadata and may occur AFTER a
successful owned commit. The error therefore does not claim no data changed,
and must not cause clearing the original, resetting a counter or cleaning the
ambient parent. Interruptions propagate after best-effort owned cleanup. Keep
the exact retained input for explicitly authorized LOCAL reconciliation only.

## Output and remaining gates

Return only fixed English state, local transaction completion observation and
false-only provider/history/epoch/signature/custody/remote/dispatch/rebuild/replay/
release grants. A local completion flag is not authenticated provider origin or
authority acceptance. `present_preparation_recovery(report, translate)` validates
the exact schema and produces ONE localized app-owned title/message/indicator.
Arabic entries cover both outcomes and denial/failure messages; English metadata
is unchanged. No event logger, raw export or translated authority payload exists.

This service does not modify invoice/accounting/QR fields, create a hold or
invoice, allocate UUID/ICV, build/sign XML, request a certificate, release/reset
pending history, send HTTP or confer permission to do those things. READ review
does not gain a persist method. No provider registration, live UI/hook or schema
installation occurs. Keep factory/tenant/source/epoch/custody authentication,
whole-worker lock/transaction lifecycle, legacy continuity and installed ERPNext
15/16/SDK acceptance as deployment gates. Permission tables themselves are not
atomically locked by current-source row checks.

Tests use synthetic unsigned originals/declared credentials and signature mocks
for v15/v16 permissions, not installed version acceptance. Private native tests
cover actual source/original locks, repeat and concurrent recovery, same UUID
with changed bytes, missing holds, uncertain commit/close, revocation before and
after commit, stale ORM data, borrowed parent preservation and callback-side
projected SQL drift rollback. The native source tables/server are fixture-owned,
never a Frappe site or a real Company. Follow [SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md):
finish development, separately approve isolated fictional-company rehearsal,
then decide adoption/cancellation and any gradual pilot. Authority I/O remains
prohibited regardless of a later rehearsal/deployment approval.

Final guarded verification: **14,888 local + 2,168 private SQL = 17,056 passed
in 181.93 seconds**, across fourteen private SQL suites. This increment adds
**165 cases**: 121 local retained/WRITE/evidence/display cases and 44 native
recovery cases. Targeted READ/recovery suites passed **336 cases in 2.91 seconds**;
the expanded native chain suite passed **146 cases in 5.98 seconds** before the
final independent-pinning refinement, which the combined run verifies too.
All nine Node VM scripts passed **1,444 cases**. No assertion, ACL, timeout,
offline/site/network or crypto guard was waived. Installed v15/v16, an authentic
source/custody verifier, encrypted original custody and remote acceptance are
not claimed.
