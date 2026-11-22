# Review-bound legacy XML page reads

Workstream2 development,2026-11-22. The existing internal owned
review_legacy_registration service now has a partial-page read mode. No live
source/site/schema/service, actual invoice, installation or authority API operation.
Installed15/16/dummy-company and authentic SDK acceptance remain separately gated.

## Saved review binding

Provide both history_review_id and history_page_after to the same internal review
service, with the same saved source/counter/File, expected anchor XML SHA256 and
reason. history_review_id must name its existing current inactive proposal; the
normal envelope authentication and exact anchor/current-head/owner/environment/
source/reason comparison must still match. Page mode cannot create or supersede a
proposal and cannot substitute another review ID. Noncanonical, missing or
out-of-range cursors are rejected; no float/leading-zero normalization occurs.

The parent still requires System Manager, ordinary Source/Company/counter/File
READ and selected credential-owner READ+WRITE, with the existing current issuer/
consumer/counter checks. Page mode does not authorize ordinary invoice writes.
Its result is reused=True, active=False, history=None and history_page containing
the partial read. There is no commit, new record, queue, counter/head update,
signing, transport or File/source write. Ordinary non-page review behavior and
the protected registration envelope are unchanged. No RPC/UI button is introduced.

## Cursor and evidence policy

after_icv='0' starts a read. Each page uses numeric DECIMAL(65,0) keyset queries,
shared NOWAIT locks and literal binary unit filtering across Sales/POS. Each table
returns at most65 metadata rows; the numeric merge selects at most64 sources.
It uses neither OFFSET nor floats. Returned cursors are exact decimal strings.

For a nonzero cursor, its actual saved source and private XML are read again before
the next page, under current READ permission. Callers cannot supply a previous
digest or key. A cursor inside an absent slot is rejected instead of silently
replaced by another predecessor. Adjacent PIH/digest comparisons reuse the common
history summarizer; gaps are not bridged. The verified anchor is reused only when
it is part of this read. Changed boundary declarations yield a broken link; an
unreadable/missing boundary yields boundary_unresolved and no fabricated link.

The page-specific16MiB budget covers successful older XML bytes including the
boundary, under the existing5MiB single-file/four-candidate limit. Parent anchor
and administrative consumer probes retain their earlier separate bounds. A budget
failure can leave a source unresolved; no unread source is marked inspected.
If boundary failure consumes the budget before advancing, next_after_icv is None
while remaining_sources stays positive. A caller must not auto-loop that position.

| Field | Meaning |
| --- | --- |
| review_id | Authenticated current proposal to which this read is bound |
| after_icv / through_icv | Requested exclusive start and last attempted page position |
| next_after_icv | Position for another partial read, or None when no advancement/remaining suffix is available |
| remaining_sources | Exact current count above through_icv, not completion of earlier pages |
| boundary_unresolved | The preceding position could not supply permitted unambiguous evidence |
| inventory | Frozen observations for this page plus its reread boundary only, with full known-position/gap counts |

A last-page remaining_sources=0 does not prove that earlier pages were requested,
unambiguous or unchanged. Inventory unprobed_sources is coverage outside this
particular read, not a cumulative counter. source_scan_complete can be true only
when a start-at-zero page covers the entire current known metadata set; it is
still not XML/signature/acceptance approval. The page/result is nonserializable
internal data; later operator adapters must preserve these distinctions.

## Limits and next development

This resumes read work from an explicit position without rereading all earlier
same-unit XML. A lost response can repeat the same page without a duplicate write.
The parent administrative/canonical/unique-tail and current aggregate checks still
run for each request; this is not O(1), installed performance or worker-drain proof.

The cursor is a partial-read selector, not a protected cumulative approval token.
Default page reads do not capture bytes. Explicit history_capture=True now adds
atomic immutable encrypted page/head retention:
[NATIVE_HISTORY_CAPTURE.md](NATIVE_HISTORY_CAPTURE.md).
Source/File changes between calls remain possible. Whole captured-ledger/coverage
qualification, rotated/unattributed archives, computed hash/signature/
SDK evidence, cutover/drain and activation remain open. No deployment, native
activation or remote acceptance is inferred from exhausting a suffix.

## Verification

11 new local cases cover numeric merge across types, exact cursors, gap/range and
boundary behavior, nonserializability and per-page coverage.17 new private cases
exercise actual unchanged saved review binding for Company/device/delegate owners,
cross-type continuation/repeat, wrong/missing/current review/role/reason/supersedes
admission, fresh changed/denied/budget-exhausted boundaries and the real64-source
limit over81 known positions. A page cannot bootstrap a proposal. No commit,
counter or authority call is performed by paging. Signed inputs are synthetic,
and altered declaration fixtures are not asserted cryptographically valid.

Final sets/logs are in STATUS.md. The mandatory offline guard admits fixture-owned
/tmp Unix MariaDB only, with --no-defaults/TCP disabled, and blocks site/network
access. Manifest254 local/88 private is not a full-run claim. No UI or financial
reference changed; original240 remains91 identical/117 review/32 blocked.
