# One permissioned defaults and source-metadata read

Increment 114 — 2026-10-27. Uninstalled server composition, not a fiscal resolver.

## Delivered behavior

`SavedCalculationDefaultsService.capture_context` adds an explicit combined
operation to the existing service. It uses the same saved READ/site/actor policy,
owned connection acquisition, rollback/close and one translated failure wrapper.
There is one transaction pipeline, not a second copy of those policies.
The existing `capture` operation retains its defaults-only result and performs
no metadata provider or metadata SQL work, even when that provider is configured.

The combined operation binds exactly the saved invoice and Company metadata to
the three-key defaults read. Sales/POS, configured parent kind and saved status
policies are unchanged. No certificate, route, accepted ZATCA label or previous
invoice is required. No hook, RPC, frontend, provider or runtime caller is installed.

## Server dependencies and bounded selection

The optional constructor-only `applied_metadata_reader(scope, types)` is required
for `capture_context`. The service derives types from its two authorized saved
source rows: Company and the exact Sales Invoice/POS Invoice type. The callback
must return a plain dictionary containing exactly those two independently valid
`SourceMetadata` declarations; missing/extra/wrong types fail before SQL acquisition.
Every minimal saved-row column must be present, including explicit base docstatus.

The callback runs after saved ACL checks, before the connection factory, and
again before final SQL rechecks. Returned declarations are independently pinned;
a changed second declaration is rejected. Nothing accepts arbitrary metadata
types or framework Meta objects from an HTTP request. These remain trusted server
read dependencies whose site/cache/API origin must be audited.

## Transaction sequence

1. Authorize saved invoice/Company READ and pin the exact metadata declarations.
2. Acquire one new owned connection and discard its pre-existing pending work,
   without cleaning recognizable ambient handles or the user's parent transaction.
3. Lock minimal saved-source projections, then load/match Company and invoice
   metadata in a fixed order using the existing selected metadata SQL reader.
4. Load selected defaults, compare the supplied defaults cache, and repeat normal
   saved-source/default checks. Check the cache and applied declarations again.
5. After those callbacks, recheck source rows, defaults and BOTH metadata sets
   using the SAME connection. Reject raw revision/membership changes even when
   final applied values happen to be equal.
6. Build a private independent result, attempt both owned rollback and close,
   then recheck source/actor/ACL before disclosure. Never commit or retry.

Native tests mutate metadata/default/source rows in either defaults callback and
the final metadata callback; the combined capture denies and rolls back those
owned edits. Another test inserts a same-effect setter under READ COMMITTED and
confirms the changed membership is rejected. Competing native writers prove
metadata/default locks coexist until combined cleanup. Pending parent work is
preserved, including rejection of a borrowed raw connection.

## Result and presentation

`SavedCalculationContextRead.settings` is an independent
`SavedCalculationDefaultsRead`; `.metadata` is the exact ordered pair of private
`SelectedMetadataRows`. Reconstruction pins all parents, checks type/column
coverage and refuses corrupt, missing, reordered or unrelated metadata. Repr is
protected and pickle refused. No public dictionary, queue/log/RPC representation,
issuance flag or complete preparation fingerprint is introduced. Generic raw
access remains a trusted-code boundary, not a disclosure sandbox.

The common display wrapper still restores parent mute flags/messages and
translates ONE final app-owned failure. New nested metadata producer messages
are suppressed too. Existing English internal codes and the two existing Arabic
translations are reused; no duplicate presentation or translation catalog is added.

## Practical limits and next work

This operation remains a PARTIAL read of defaults and TWO source metadata types. It does not
read the financial invoice rows, child membership, tax templates, addresses,
currencies or calculation Singletons. Minimal source projections cover ownership/
revision/status, not the complete accounting state. Audited provider registration,
physical schema, actual installed v15/v16 behavior and complete graph locking
remain integration gates.

SQL and caches/ACL are not frozen atomically. Callbacks must be audited read
dependencies; arbitrary trusted Python is not sandboxed. Fixed boundary checks
do not prove a simultaneous cache snapshot or prevent later changes. After owned
cleanup the observations can become stale; they cannot authorize a later build,
replay or send. Native tests use real private SQL with synthetic ACL/applied Meta,
not an installed Frappe site or actual v16/SDK/authority acceptance.

Increment 116 adds a separate explicit financial composition in this SAME service;
see [CALCULATION_FINANCIAL_ACCESS.md](CALCULATION_FINANCIAL_ACCESS.md). This
metadata-only method does not acquire financial rows implicitly.

Next complete linked dependency acquisition and native/ORM parity, compose their
metadata and effective precision consistently, and establish amount/XML/GL/VAT
parity before pipeline adoption. Executed evidence is in [STATUS.md](STATUS.md).
See [CALCULATION_DEFAULTS_ACCESS.md](CALCULATION_DEFAULTS_ACCESS.md),
[METADATA_SOURCE.md](METADATA_SOURCE.md), [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md)
and [SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md). No working-environment
change or authority request is authorized by this increment.
