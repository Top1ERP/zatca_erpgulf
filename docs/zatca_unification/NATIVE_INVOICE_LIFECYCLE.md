# Retaining native invoice identities during destructive ERP actions

Workstream2 development,2026-11-21. Development source only: no live source,
site/schema, invoice, service or authority endpoint was changed or used.

## Behavior change

The existing cancellation hook checks the invoice's display status for REPORTED
or CLEARED. That alone cannot retain native source identity after local generation,
queue registration, lost/unknown delivery, or erasure of those output fields.
Native issuance and request records deliberately use immutable Data references;
generic framework Link checking cannot protect these references automatically.

Sales/POS now run a shared retention guard before cancellation, deletion and
rename. Merge also checks its destination, preventing an unissued source from
modifying an already protected target. The former cancellation and advance-payment
validators remain in order after this guard. No generic permission bypass is added.

| Saved evidence | Additional native guard behavior |
| --- | --- |
| No issuance/request/egs marker; UUID only | Continue normal ERP validators |
| Any issuance, including PREPARED, rejected or unknown | Hold destructive action for reviewed transition |
| Any queued/historical submission request, including STAGED/REVIEW | Hold unless all bounded requests have authenticated unissued retirement proofs |
| Persisted egs marker with missing/corrupt custody | Hold for review |
| Missing/unverifiable transactional storage or owner binding | Hold for review |
| Installation without native owner schema and no native source hint | Preserve older hooks |

This is intentionally more conservative than the previous status-only native
cancellation check. Queued but unissued invoices need explicit request retirement;
the subsequent [retirement service](NATIVE_UNISSUED_RETIREMENT.md) supplies that
transition with authenticated proofs and old-worker fencing. A hold never claims
that ZATCA accepted the invoice. UUID presence,
an edited display status and an unverified state/index row cannot certify receipt.
Legacy status and framework links/accounting restrictions are not removed.

## Transaction and race boundary

The guard borrows the current site connection and never commits, rolls back,
closes it, resets callbacks, stages an intent, signs or sends. It pins the actual
LocalProxy target, connection/socket, site, actor, database and autocommit state.
Current source row locks serialize against native preparation's same row lock;
NOWAIT contention holds rather than assuming no issuance. Current shared history
lookups see a committed row behind an older repeatable-read snapshot.

Both immutable stores are queried by source type/name across chains and versions,
independent of current Company phase, rollout switch, certificate or signing key.
The database rows supply markers; a supplied browser document cannot invent or
remove retention evidence. Since any stored history denies a destructive action,
the guard does not decrypt it and cannot use that denial as authenticated positive
acceptance evidence. Verified receipt publication remains a different service.

Table metadata locks precede InnoDB checks. Full leading source_name indexes are
required before current history reads to avoid intentionally scanning and locking
unrelated history. The existing Submission Intent source_name field gains a
search_index source declaration. Physical installation/migration is separately
gated; hooks perform no DDL or repair. The private fixture creates only its own
temporary indexes to represent that schema.

The local Frappe15 source calls before_cancel before cancellation, on_trash before
deletion, and before_rename before source/link mutation. These source inspections
and AST hook-wiring checks are not an installed ERP15/16 lifecycle qualification.
Privileged raw SQL, explicit ignore_on_trash/rename validation bypasses, custom
side effects before an app hook and external applications remain outside this
ordinary document-hook boundary.

## Messages and qualification

One fresh exception displays a real Arabic catalog translation when selected;
the diagnostic records only a fixed English code. SQL driver text and child
exception context are not exported, and a diagnostic writer failure cannot
permit the destructive action.

Final qualification evidence is recorded in STATUS.md. Private SQL covers
Sales/POS, Company/device/linked owners, unissued UUID-only sources in both phases,
generated histories with cleared output fields and changed rollout/phase, pending
request rollback, older RR views, merge targets, row contention, missing indexes,
and actual Werkzeug LocalProxy replacement. HTTP/signing/accounting remain explicit
doubles. This is neither an actual invoice cancellation nor a site migration.

Workstream2 remains open: issued-source transitions and custody-backed reconciliation,
whole-runtime and installed lifecycle/GL/File acceptance, started/uncertain intent
resolution, unchanged retry/corrected-clock operator adoption, full historical
inventory/drain and activation, Standard/non-Background recovery and frozen print
master/File compatibility. No financial or signing/reference baseline changed.
