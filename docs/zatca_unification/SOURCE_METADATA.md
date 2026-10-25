# Applied source metadata and explicit base-field adapter

Increment 109 — 2026-10-25. Read-only compatibility foundation, uninstalled.

Increment 110 adds explicit baseline/raw/applied declaration matching with the
installed non-temporal Frappe cast subset, plus actual defaults API behavior
tests. It does not establish committed provenance or resolve defaults. See
[METADATA_RECONCILIATION.md](METADATA_RECONCILIATION.md).

## Finding from local framework source

Frappe Meta.has_field/get_field use the applied DocField map. Default/base fields
such as docstatus and creation are not normal entries there. The source financial
profile requires docstatus; Address observations include creation. Passing raw
Meta directly can therefore reject a legitimate financial source or misrepresent
base-field presence. Prior synthetic metadata included those names explicitly;
that was not installed-framework integration evidence.

This increment adds an explicit adapter rather than assuming physical columns or
inventing definitions. Callers must supply the EXACT selected base definitions
separately, for example using the existing framework get_default_df. Raw Meta and
base declarations may not shadow one another. Tests use the actual installed
helper without creating Meta, initializing a site or reading a customer.

## Contracts

SourceMetadata captures the selected allowlist across the existing source/
settings/tax/party/POS profiles. It records each applied field's type, options,
precision, default, required/read-only/hidden/nonnegative/allow-on-submit/custom
markers, optional field absence and explicit Singleton/child-table storage kind.

SourceFieldDefinition provides immutable get, fieldtype and options lookups.
It is not a full Frappe DocField API or proof of Custom Field/Property Setter
origin. Values are canonical typed scalars: zero, false, blank and NULL remain
distinct, and default expressions are retained as text, NEVER evaluated.
Password field types are refused BEFORE capture asks for a default.

SourceDocumentView exposes only bound DocType/name, independent metadata and a
narrow allowlisted get interface. It has no save/db_set/permission bypass.
Original document and Meta objects are not modified. Identity drift is rejected.
VALUES are still delegated reads and may change: this view is NOT an immutable
snapshot, saved ACL, database lock or replacement for a Frappe Document.

The adapter makes explicit base docstatus/creation available to the existing
pure profiles. It does not alter financial/tax/settings wire formats or any
runtime controller. A test first reproduces missing-docstatus rejection with a
raw-Meta-shaped double, then shows the adapted capture has IDENTICAL original
financial bytes/fingerprint. Other tests demonstrate that a precision-only
metadata change can leave the old amount snapshot unchanged; complete source
binding must include metadata too.

No Frappe/SQL/files/clock/defaults/cache/Property Setter lookup, schema discovery,
data modification or transport exists in the adapter. The caller supplies
already-authorized applied metadata and explicit base declarations.

## Safety, bounds and limits

The versioned metadata profile uses a fixed source-column allowlist and the
existing streamed 2 MiB canonical bound per Meta/field-definition object. Raw
fields/defaults can contain sensitive business data. Repr is redacted and pickle
refused; generic dataclass serialization is not a privacy sandbox or UI/RPC/
queue/log export. No complete-family memory bound is claimed.

Declarations do NOT prove physical columns, actual metadata freshness, site/
tenant/ACL, raw Custom Field/Setter provenance, effective defaults, fiscal
precision or installed-version compatibility. A metadata hash is not
PreparationContext.source_snapshot_sha256 and does not replace the required
custody/recovery source guard. No provider/hook/UI/schema/runtime is installed.

Profile allowlists currently derive from the explicitly versioned source
contracts. Changes to those contracts/registries affecting field layout require
metadata-profile version review; do not silently reinterpret retained v1 bytes.

## Property Setter/defaults work still required

Read-only local source inspection shows applied Meta adds Custom Fields and
applies Property Setters with property-type casting. Capturing the resulting
properties does NOT prove that cached Meta agrees with the current stored rows.
Raw relevant Custom Field/Setter identity/value/membership/revision and ordering/
casting evidence still need committed capture. Increment 110 matches supplied
declarations; acquisition/completeness and cache freshness remain unverified.

Defaults are API/scope dependent. The inspected db.get_default path defaults
to __default; get_defaults merges its base with user defaults, and other getters
also apply list/permission behavior. __global is not interchangeable with
__default. A universal guessed global/site/user order would be wrong.
Record requested API/key/site/user/scope, exact rows/membership/order and cache
observations before introducing any effective-default resolver.

Next build those provenance/default-scope contracts and the authorized committed
reader, including Singles/child/metadata locking and physical v15/v16 scalar/
schema normalization. Then bind complete source/metadata/settings consistently,
test actual amounts/XML/GL/VAT/QR/signature parity and finish runtime integration.
No installed ERPNext 16 or SDK/authority acceptance is implied by synthetic labels.

See [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md), [STATUS.md](STATUS.md) and
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md). No working environment changes
or authority requests, including Sandbox/Simulation, are authorized.
