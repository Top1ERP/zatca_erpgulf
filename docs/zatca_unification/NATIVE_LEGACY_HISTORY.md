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
| known_positions | Exact decimal string count of all saved positions in the literal unit, from current locking aggregates after canonical/unique-tail checks |
| source_scan_complete | All source metadata fits the older-document scan budget; never XML/archive completion |
| sources_seen / inspected_sources / unprobed_sources | Covered metadata positions, attempted evidence reads and all known positions without an attempt |
| missing_positions | Exact decimal string tail ICV minus known distinct positions from1, independently of the older-XML budget; None only for low-level partial arithmetic without a verified census |
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

Two current locking COUNT queries census the literal same-unit positions in both
tables before older metadata/XML reads. Counts are integer-only; malformed shapes,
count/metadata drift and impossible totals abort instead of implying zero. A plain
COUNT can reuse an old RR snapshot; these aggregates explicitly use shared NOWAIT
locks. The indexed equality filter is supplemented by a binary comparison so DB
collation cannot merge different unit strings. Counts are not a physical-unit
ownership assertion for aliases outside this exact scope.

The older-document scan limit remains1024 positions; each table query returns at
most1025 metadata rows. Above the limit, the report reuses just the verified anchor,
returns the full known count/exact missing-position difference, marks older metadata
coverage incomplete and counts all other positions as unprobed. It performs no
older-file scan. The existing File/InnoDB guard still runs. The COUNT result is a
full aggregate scan, not an O(1) or installed performance claim; administrative
review needs the existing index/maintenance qualification. Larger histories still
need paged/durable XML inventory before activation. Each older source allows
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

## Original qualification

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

## Exact census extension

17 additional local cases cover count/coverage separation, values above float
precision, invalid/inconsistent total/driver shapes, both fixed tables and a
physical-owner change between queries. Two additional private cases exercise
2,058 positions across Sales/POS, cancelled rows, unrelated/case-different units,
and a peer commit hidden from a prior ordinary repeatable-read snapshot. The large
case has tail3000, reports2058 known/942 missing/2057 unprobed, retains the anchor,
reads no older body/XML and leaves the counter/proposal inactive and unchanged.
The count does not fill missing XML or permit activation.

Final extension logs/counts are recorded in STATUS.md. The stored registration
format, source/financial data, UUID/ICV/PIH and public/UI contracts are unchanged.
The one new known_positions string exists only in the transient internal inventory.
