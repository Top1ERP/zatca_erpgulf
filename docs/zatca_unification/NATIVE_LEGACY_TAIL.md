# Negative saved-source tail checks

Workstream2, adopted by the internal `review_legacy_registration` service.
This strengthens the inactive continuity review; it does not activate a chain,
retire/freeze a legacy issuer or change an existing counter/invoice/PIH.

## Problem and resulting behavior

A counter can reference invoice27 even though an existing Sales or POS source
records a generated invoice28 in the same unit. The old review bound27 to the
counter, exact private XML and selected issuer material but could not exclude
that contradiction. A matching counter and anchor are now insufficient alone.

`native_legacy_tail.require_unambiguous_saved_tail` checks both source tables in
the review's owned transaction, after normal counter/anchor READ and locking:

- Only the already-authorized anchor may have ICV at or above the supplied tail.
  A duplicate or later source in either table holds; no maximum is adopted.
- A same-unit source with a missing/noncanonical ICV, draft/unknown document
  status, or another Company holds even when its apparent ICV is lower.
- Submitted and cancelled older sources in the same unit are compatible with
  this tail check. A cancelled generated tail still occupies its position.
- Saved REPORTED/CLEARED labels do not select the anchor or omit a newer rejected
  or unconfirmed source. Source kind/credit/debit classification is irrelevant
  to its generated position. Another unit's source does not change this tail.
- Missing POS history cannot become a Sales-only pass. Matching current SQL
  identity/UUID/ICV/source fields must still equal the saved authorized anchor.

## Exact comparison and locking

ICV remains a canonical positive ASCII integer, up to the existing64-digit codec
limit. The SQL comparison uses exact DECIMAL(65,0), never floating arithmetic or
lexicographic order. Invalid strings are contradictions, not values to repair.
The selected ICV projection is bounded to65 characters. No source value is
converted or written back, and no monetary/XML/hash/signature algorithm changed.

The actual source/counter column types must preserve exact values. Integer and
string types, or zero-scale DECIMAL, are admissible to the SQL check. Floating,
fractional, missing or unsupported columns hold. The existing anchor loader
retains its own strict saved Python integer/string validation. The private SQL
qualification demonstrates that DOUBLE loses the difference between
9007199254740993 and9007199254740992; scientific serialization is also rejected.
No schema/data repair is attempted. This codec test is not a claim that an
installed ERP BIGINT column can store all64-digit values.

Owner inventory and tail review share the session-isolation and physical-engine
checks. REPEATABLE-READ/SERIALIZABLE and InnoDB are required. Source predicates
run under shared NOWAIT range locks until review commit/rollback; the earlier
counter/anchor locks remain. Physical engine/type checks occur after the source
ranges open, while transaction metadata locks prevent a DDL race. No HTTP runs
inside this transaction.

LIMIT2 bounds returned rows, not physical rows examined or elapsed time. The
site's indexes and optimizer plan must be reviewed during separately authorized
installed acceptance; a unit index/approved maintenance window matters for a
large history. Private cases verify both unindexed and unit-indexed tables. This
bundle installs no index or schema on an ERP site. Ordinary invoice generation
does not run this administrative review query.

## Scope still open

This is a negative saved-tail check, not full history reconstruction. It does
not validate every older slot/UUID/PIH link, discover unitless/deleted sources,
attribute rotated legacy tokens, scan unattached XML, prove remote acceptance or
exclude old/external workers. Full identity/counter/source/File consumer coverage,
old-worker drain and authenticated atomic activation remain open. Existing review
envelopes/cipher domains were not changed, and no new persistent census proof is
claimed. Every explicit review/recovery reruns this check; future activation must
revalidate under its own fresh cutover locks rather than trust an older review.

## Offline evidence

New private tests use the actual review service and current SQL/cipher/file
implementation with explicit framework/metadata/signing fixtures, never an ERP
site or authority request. Coverage includes Sales/POS contradictions, invalid
and oversized ICVs, canonical boundaries, large exact values, cancellation,
recovery after a later generated source, engine/isolation failures, actual DOUBLE
loss and concurrent insert/update exclusion with and without a unit index.
Only fixture-owned temporary TCP-disabled MariaDB servers are used. The DOUBLE
case preserves/restores prior fixture strings; no financial reference changed.
Installed ERP15/16 and authentic SDK/authority acceptance remain separate gates.

Current test counts/logs are in STATUS.md. Original240 financial comparisons
remain91 identical /117 review /32 blocked.
