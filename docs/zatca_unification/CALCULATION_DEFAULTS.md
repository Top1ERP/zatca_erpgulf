# Scoped calculation defaults: locked SQL rows and explicit cache comparison

Increment 111 — 2026-10-26. Development only, not installed or runtime-integrated.

## Delivered responsibility

`calculation_defaults.py` adds a fixed-query MariaDB reader for the three keys
used by the inspected field-precision path: `currency_precision`,
`float_precision` and `number_format`. The server caller supplies the exact
parent and connection. There is no ambient Frappe/site/defaults lookup, provider
discovery, cache refresh, fiscal calculation, SQL installation or transport.

This is one dependency of a future complete preparation read, not that complete
reader. It does not implement Custom Field/Property Setter acquisition,
Singleton/child capture, user overlays, permission filtering, effective precision
or a trusted source guard. Existing financial/settings/metadata profile formats
and runtime entry points are unchanged.

## SQL and transaction contract

`MariaDBCalculationDefaultsReader.load_for_update(parent)` requires autocommit
off, uses bound parameters and fixed selected columns, and returns every matching
selected row in creation/binary-name order. It preserves names, nullable creation/
modified timestamps, exact keys and raw text/NULL values. No revision is invented.
Normal database collation is used, followed by exact returned parent/key checks;
case variants are refused instead of silently normalized or adopted.

Ordinary buffered SQL results are bounded before decoding: at most 129 rows and
4,097 value characters are selected; validation accepts at most 128 rows and
4,096 UTF-8 bytes per value. Identity columns are similarly bounded. Invalid
driver values, oversized data and unsupported dates fail without truncation or
fallback. The immutable versioned payload uses the shared canonical 2 MiB bound.

This reader borrows one explicitly owned transaction and never commits, rolls
back, closes, reconnects or changes isolation/wait settings. Row locks survive
its return. The caller must guarantee authorization, exact provider/session/
tenant identity and cleanup on every exit. A failed read/check poisons the
reader; ordinary failures expose static English codes, and interruptions still
propagate. A new reader is not a substitute for cleaning a failed transaction.

Locking reads see current SQL data even if an earlier consistent read used an
old MVCC snapshot. They wait on another transaction's pending edit. However,
they CAN see their own transaction's uncommitted writes. Neither these rows nor
their fingerprint prove committed acquisition, origin, ACL, or source freshness
after return. Do not expose a `committed` or `verified` flag based on this object.

`require_unchanged(observed)` revalidates an independent observation and re-reads
membership, order, values and revisions on the same connection. Under READ
COMMITTED, a selected insertion can occur between checks: native tests exercise
and detect that phantom even when it leaves the folded value unchanged. Reviewed
REPEATABLE READ fixture indexes block selected insertions, including an empty
range; this is not a guarantee for arbitrary production schemas/plans. A final
source guard needs a reviewed complete locking/isolation/index strategy across
ALL dependencies. Per-lock waits also do not bound total transaction time.

## Cache consistency without implicit repair

`CalculationDefaultsRows.require_cache_match(parent, cached)` compares only the
three selected keys in an explicitly supplied `get_defaults_for` cache result.
It does not enumerate unrelated keys or fetch/refresh/write any cache. A cache
miss (`None`) differs from a cached empty dictionary. Text zero, blank, NULL,
missing values, list order and scalar/list shape remain distinct.

The selected-key folding rule is tested against the actual installed Frappe
cache-miss method with synthetic rows. It preserves first-seen distinct values,
including the framework's NULL behavior; it does not select a list's first item,
cast precision, merge user values or apply permissions. Equal creation stamps
with different values for one key are rejected because the framework's
creation-only ordering establishes no stable value precedence. A name tiebreak
orders raw membership only. Binary name ordering keeps canonical order consistent
despite SQL collation, including mixed-case names. Equal values at the same
timestamp remain separate raw rows in the fingerprint.

The caller must prove which API/parent/site produced the cache data; matching
supplied values cannot prove that fact or prevent a later cache change. The
retained raw-row format and folding contract are versioned; a framework behavior
change requires review, not silent reinterpretation. No cross-version installed
compatibility is inferred from the current native fixtures.

## Privacy and evidence

Values stay private to server composition. Repr is protected and pickle is
refused; generic dataclass/raw-payload access is not a disclosure sandbox or
permitted UI/RPC/log/queue export. There is no new frontend message or translation
path. Row fingerprints must not replace the complete preparation source hash.

Native tests create a NEW TCP-disabled fixture server and synthetic indexed
DefaultValue-shaped table. They cover parent/key isolation, current reads,
pending edits, retained locks, phantom rechecks, rollback ownership, collation,
bounds and lock timeouts. This is neither a restored Frappe schema nor installed
ERPNext 15/16, permission, SDK, signature or authority acceptance evidence.
Executed totals are recorded in [STATUS.md](STATUS.md).

Next compose authorized fresh committed acquisition and metadata/customization/
default scope checks with the remaining source graph. Establish actual effective
precision and amount/XML/GL/VAT parity before runtime adoption. See
[METADATA_RECONCILIATION.md](METADATA_RECONCILIATION.md),
[DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) and
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md). The user prohibition on working
environment changes and all authority requests remains unchanged.
