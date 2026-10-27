# Selected metadata SQL acquisition and applied-definition matching

Increment 113 — 2026-10-27. Uninstalled dependency reader; caller-owned transaction.

## Responsibility

`metadata_source.py` reads selected DocType, DocField, Custom Field and Property
Setter rows on one explicit connection, then invokes the existing metadata
projector and customization matcher. The caller supplies an independently pinned
applied `SourceMetadata`. Actual framework base-field definitions and supported
field-type catalogs are used without constructing Meta or initializing a site.

The result binds raw identity/revision/membership/properties, baseline metadata
and the supplied applied declaration. It fills the raw-query boundary left open
by declaration-only matching, including rows whose effects equal baseline values.
No financial/profile format, fiscal precedence, hook, RPC or runtime caller is
changed. This is not the complete authorized preparation source reader.

## Scope and projections

Only the existing versioned `SOURCE_FIELDS` allowlist is queried for a known
source DocType. SQL table/column identifiers are internal constants; scope and
field predicates use bound parameters. Every row is checked for exact scope and
case after the database's normal collation. Binary record-name ordering matches
canonical ordering. Optional field absence remains explicit.

- DocType: name/revision and selected storage flags; virtual types are refused.
- DocField: exact DocType/fields parent identity, row index, virtual marker and
  selected field properties. Legacy NULL row revisions remain explicit.
- Custom Field: exact type/field identity, row index, virtual marker and selected
  properties. Its stored table establishes origin; a `custom_` name alone does
  not. Custom fields may not shadow standard or base definitions.
- Property Setter: relevant field properties plus storage/identity-changing
  DocType setters. Unsupported storage/scopes/casts and duplicate targets fail;
  UI-only/unselected properties are outside this projection. No setter is written
  or applied to framework objects.

Supported selected field types come from the installed framework's known catalog,
excluding Password. Selected virtual fields and unsupported type aliases fail.
Base fields remain supplied through actual `get_default_df`, not invented
DocField rows. Reconstruction uses the existing typed property/cast contracts;
NULL, blank, zero and string/numeric precision differences are preserved.

## Sensitive values and bounded reads

For each field/customization group a small preflight projection reads identities,
types and scope before any default/value projection. Existing Password fields or
unsupported setter types therefore fail before sensitive value columns are
returned. The subsequent SQL projections also use guarded CASE expressions:
unknown/Password field defaults and unsupported setter values return NULL.
Native READ COMMITTED tests insert both kinds AFTER preflight, prove the values
were masked in actual SQL results, then verify membership drift is refused.
Preflight/full identity/type/revision projections must agree exactly.

Selected field properties are bounded to 8,192 UTF-8 bytes; SQL returns at most
8,193 characters before rejecting overflow, without silent truncation. Record
names are similarly bounded. Standard rows are capped by selected field count,
Custom Fields by 128 and setters by 256, with a one-row overflow probe. The
shared canonical object limit is 2 MiB. These bound returned projections; they
are not a total transaction/scan/lock-wait budget or full-family memory proof.

## Transaction and result contract

`MariaDBMetadataSourceReader.load_for_update(applied)` requires autocommit off
and locks the current selected rows. It neither commits nor rolls back/closes,
changes session settings, discovers a connection, refreshes caches, evaluates a
default expression nor sends HTTP. Errors poison the reader, without retries;
interruptions propagate and cleanup remains the caller's responsibility.

`require_unchanged(observed)` independently validates the retained rows/derived
match, then re-reads membership and revisions in the same transaction. Current
locking reads bypass a stale MVCC snapshot, but can see their own uncommitted
writes. RC insertions can occur between boundaries; the native test detects a
new setter even when its applied value is unchanged. A complete source lock
strategy must still cover all dependencies, phantoms and actual physical indexes.

`SelectedMetadataRows` is an immutable private server observation. It binds the
framework version and both raw/applied data; a version change requires review.
Reconstruction repeats raw validation, baseline building and existing matching.
Repr is protected and pickle refused. Generic dataclass/raw-payload access is
not a disclosure sandbox or a permitted UI/log/queue/RPC representation.

The reader does not establish permission/provider/tenant/committed provenance,
physical column availability, authentic baseline origin, complete Meta validity
or fiscal correctness. Applied metadata equality can be satisfied by supplied
declarations; no verified/issuance grant is introduced. This digest is not the
complete preparation source fingerprint.

## Evidence and next composition

Tests exercise every selected source type, native SQL scopes/current reads,
standard/custom/setter revisions, same-effect inserted membership, held locks,
Password/unsupported preflight and phantom masking, collation, exact UTF-8 bounds,
nullable standard revisions and no implicit commit/cleanup/evaluation. The first
fixture assumed standard fields could not have custom_ names; correcting that
test assumption confirmed the reader uses stored table origin instead.

All native tables are synthetic on a NEW guard-owned TCP-disabled server; they
are not installed ERPNext metadata, a restored site or actual v16/SDK/authority
evidence. Totals are recorded in [STATUS.md](STATUS.md).

Next compose this reader with permissioned fresh acquisition and scoped defaults,
then complete the remaining source graph and effective precision/financial/XML
parity before runtime adoption. See [METADATA_RECONCILIATION.md](METADATA_RECONCILIATION.md),
[CALCULATION_DEFAULTS_ACCESS.md](CALCULATION_DEFAULTS_ACCESS.md),
[DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) and
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md). Working-environment changes
and all authority requests remain prohibited.
