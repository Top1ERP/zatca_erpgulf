# Resumable captured-ledger audit

Workstream2 development, 2026-11-22. This internal service verifies the previously
retained capture ledger. No installed site, authority API, worker, active chain,
ERP invoice or accounting data was changed. It grants no activation or compliance
approval. Installed15/16 and dummy-company acceptance retain their separate gates.

## Entry and transaction ownership

The existing `review_legacy_registration` service accepts `history_audit=True`
with its current inactive `history_review_id` and `history_page_after='0'`.
Capture and audit cannot run in the same operation. The saved review, reason,
anchor checksum, current issuer/tail and normal System Manager/Source/Company/
counter/File admission must still match. The core review is internal. Existing
inactive reviews can now use the fixed local operator actions described in
[HISTORY_REVIEW_ACTIONS.md](HISTORY_REVIEW_ACTIONS.md); those actions derive saved
arguments server-side rather than exposing the internal command's parameters.

The audit starts at the authenticated capture head and follows its predecessors;
the caller supplies neither a backward cursor nor a previous digest. A bounded
segment stages an authenticated checkpoint in the same owned transaction. The
parent confirms transaction ownership and commits. Compare failure or access/
integrity failure aborts without publishing progress. A lost COMMIT acknowledgment
remains uncertain; repeating the command resumes the saved checkpoint, or reuses
the completed report, without generating another invoice or moving an ICV.

## Checks and bounds

Each segment checks at most eight pages and reserves a full16MiB payload allowance
before opening another page. Actual decrypted payload bytes consume a32MiB
segment budget. Page contents are processed one at a time. These are application
input bounds, not a wall-clock deadline or an operating-system memory guarantee.

Checks include:

- Current locking page-catalog count equals the protected head's page number;
  missing prefix pages and unreferenced extra rows cannot be skipped.
- Exact previous-header digest, descending page number, numeric cursor, stable
  census and cumulative captured/unresolved counts match at every step.
- The separately authenticated access manifest passes current saved Source/File
  READ and identity/attachment checks before large XML decryption.
- The prior page's last fresh source agrees with the newer page's reread boundary,
  including observed/unresolved state and an exact shared XML copy where observed.
  A generated cancellation may change docstatus without erasing the chain slot.
- Captured inventories agree with independent recomputation of adjacent declared
  PIH links, missing positions, genesis/tail declarations, rotated keys and source
  coverage. A repeated boundary is excluded from cumulative fresh-source counts.
- The first page terminates at the original zero cursor with zero prior counts.
  Strictly decreasing page numbers prevent cycles and repeated-page accounting.

XML/hash/certificate fields here are declarations inspected from captured bytes.
This does not compute/qualify the invoice digest, XML signature, certificate trust
chain or authentic SDK result. A whole traversal can retain broken links,
unresolved inputs, rotated keys and gaps; these remain explicit report values.

## Checkpoint and report meaning

Two new nullable hidden/no-copy/print-hidden Long Text fields on the existing
Issuing Chain retain the checkpoint header and ciphertext. The new
`legacy-history-audit` cipher domain binds the namespace, review identity, exact
header and constant payload. Existing domains/AAD are unchanged. Physical column
types and bounded SQL reads are checked before use. The CAS update also pins the
unchanged inactive review, capture header/ciphertext and prior checkpoint pair.
These are source declarations only; no schema installation was performed.

The header pins the capture-head digest, remaining predecessor, cumulative counts,
boundary fingerprint, checking actor and UTC time. It contains no raw XML, private
key, token or filesystem path. The result exposes metadata only:

- `traversal_complete`: every page under this captured head was checked.
- `capture_exhausted`: the capture reaches the reviewed tail and contains all
  currently known literal-unit positions. Missing numerical slots are separate.
- `missing_positions`, `unresolved_sources`, `broken_links`, `rotated_sources`
  and `genesis_match`: retained observations, never an overall approval flag.
- `checked_at_utc`: time of the last successful segment; `reused=True` means a
  saved completed report was returned without a fresh whole-ledger traversal.

A saved report is point-in-time evidence, not a perpetual byte-integrity or
permissions lease. For example, later corruption of a nonlatest page body is
detected by a new traversal, not by merely displaying the earlier report.
`history_audit_restart=True` explicitly starts that fresh traversal. It first
authenticates the checkpoint being replaced, and permits rebinding an extended
capture head. Normal resume refuses head changes. Restart replaces derived audit
progress/report only; immutable captured pages and the review stay retained.
This checkpoint is not an append-only history of past audit runs.

## Evidence and remaining work

The focused and broader offline suites cover complete/segmented traversal,
payload reservation, exact counts, three owner policies, nonlatest corruption,
missing/orphan/index rows, changed-head explicit restart, checkpoint tampering,
Source READ denial between segments, compare failure, lost COMMIT acknowledgment,
report replay and explicit fresh recheck. Issue fixtures deliberately alter XML
declarations and are not claimed to be cryptographically valid.

Audit bundle qualification:526 local cases across17 suites and316 private SQL
cases across10 suites. See STATUS for exact logs/timings. The reviewed manifest
had256 local/90 private suites at that bundle and was not run in full. Sets overlap with prior
bundles and are not release totals. The offline guard denies site initialization
and external network; SQL fixtures use only a private `/tmp` Unix socket with
`--no-defaults` and TCP disabled. Financial references remain91 identical/117
review/32 blocked for the original240; none was rebaselined.

Full physical/archived/unattributed/rotated-owner census, stable credential renewal,
legacy worker drain, safe activation and whole canonical runtime qualification
remain workstream2 tasks. This service does not close that workstream or qualify
installation, actual QR/signing/SDK, real ERP15/16 or live/dummy-company rollout.
