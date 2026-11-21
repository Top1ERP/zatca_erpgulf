# Known legacy source/XML history observations

Workstream2 development,2026-11-22. Adopted by the actual owned inactive
review_legacy_registration service. No live migration/site/service/schema,
actual invoice, installation, authority API or cutover operation occurred.

## Why the tail alone is insufficient

An exact matching counter/anchor at27 cannot establish what happened to1..26.
The new helper observes known same-unit Sales/POS slots and their attached XML,
returning a transient history inventory alongside LegacyRegistrationReview.
It runs for new reviews and exact reused reviews before their result returns.
No original header/ciphertext format, registration digest or database field changes.
Partial/conflicting history can retain an **inactive** proposal; it cannot activate
it. Future activation needs fresh authenticated evidence and worker fencing/drain.

Both fixed source tables use current shared NOWAIT reads in the owned transaction,
under verified range isolation and InnoDB storage. The earlier exact-column,
positive canonical ICV, unique-slot and tail checks remain prerequisites.
Cancelled generated sources retain their position. Dates/statuses never select
a predecessor or imply acceptance. Source/File READ and fresh source identity
precede private bytes. Unexpected ORM/SQL/ownership failures abort review rather
than masquerade as a missing file. The already verified anchor is reused without
a second File read or credential lookup.

Each older XML must declare the saved name/UUID/ICV and seller VAT. Multiple
original/cleared copies can differ in bytes, but must declare the same invoice
digest, PIH and public key. Missing/unreadable/invalid/misowned/conflicting files
make the source unresolved; the first conflicting file is never silently chosen.
The existing bounded private/local/no-symlink reader and no-DTD/XXE XML/certificate
observers are reused. This does not compute invoice hashes or validate signatures.

| Inventory value | Meaning |
| --- | --- |
| source_scan_complete | No source-row overflow; not an external/archive census |
| sources_seen / inspected_sources / unprobed_sources | Covered bounded positions, attempted evidence reads and remaining positions without an attempt |
| missing_positions | Exact decimal string tail ICV minus known distinct positions from1, or None on incomplete source scan |
| unresolved_sources | Attempted sources lacking unambiguous permitted evidence |
| matched_links / broken_links | Equality/contradiction of declared PIH/digest at adjacent known ICVs with evidence |
| genesis_match | ICV1 declares the existing genesis PIH, or None without its evidence |
| tail_match | Observed tail matches the parent's already reviewed head, or None when not covered |
| rotated_key_sources | Older sources declaring a public key different from the anchor |
| xml_bytes | Additional successful older-file reads; the separately bounded anchor is not charged twice |

Missing positions are not invented, renumbered or treated as unused. A gap is not
silently bridged. All identity/count arithmetic is integer/string, including
values above float precision. Changed keys remain visible for ownership/epoch
review. There is no overall active/accepted/safe-to-activate boolean.

## Bounds and limits

The limit is1024 covered source positions; each table query reads at most1025
metadata rows. Overflow returns an incomplete report over at most1024 positions,
with no older-file probing or missing-position inference. Larger histories still
need reviewed paged/durable inventory before activation. Each older source allows
at most4 XML candidates, each within the existing5MiB reader limit, sharing a16MiB
additional-read budget. Bytes are charged before parsing. A size/budget failure
holds that source and conservatively ends further probing; unattempted positions
remain explicit. Invalid files never reset the shared budget.

The frozen nonserializable report exposes counts/booleans only, not names, XML,
certificates, keys or paths. It is a point-in-time declaration observation, not a
filesystem lease, computed-hash/signature/CA/SDK proof, remote acceptance, complete
archived/retired-alias history or drained-worker proof. Unattributed/rotated history,
large-history paging, durable cutover/fencing, renewal activation and installed15/16
remain open. The internal service gains no public RPC/UI button or user message.

## Qualification

13 new pure cases cover exact gaps, adjacent-only links, separate genesis/tail/
PIH/key/unresolved/unprobed limits, duplicate slots, nonserializability and large
integers.17 new private cases cover actual review/reuse, three owner selections,
Sales/POS links, missing/invalid/denied/conflicting files, key changes, per-file/
aggregate/source limits and changed old files on rereview. Deliberately altered
signed fixtures test declarations only, never assert valid cryptography.

Final:386 local cases across10 suites in1.87s;173 private cases across5 suites in
41.68s. Logs: `/tmp/zatca-axis2-history-local-final.log` and
`/tmp/zatca-axis2-history-private-second.log`. The first private run caught the
aggregate16MiB value being passed to the5MiB single-file reader; final code passes
min(remaining, single limit), with cumulative-budget/rereview regressions.
The mandatory offline guard denies external/site access and admits fixture-owned
/tmp Unix SQL only, with --no-defaults/TCP disabled. Manifest253 local/87 private
was not run in full. No UI/financial/golden reference changed; original240 stays
91/117/32. Workstream2 and installed/dummy-company/SDK acceptance remain open.
