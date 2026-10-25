# Declared field customization matching and defaults API contracts

Increment 110 — 2026-10-25. Development only; no runtime caller or installation.

## Purpose and boundary

`metadata_reconciliation.py` compares three supplied declarations for one selected
DocType: baseline metadata before Custom Fields/Property Setters, relevant raw
customization rows, and applied metadata after their effects. It reuses
`SourceMetadata` and independently validates both parents rather than trusting
cached derived fields. The document read view now shares that same pin helper.
Existing source-profile payloads and financial calculations are unchanged.

This is an explicit framework adapter, not a framework-free observation module.
Its sole framework computation is the installed `frappe.utils.data.cast` over a
restricted non-temporal subset. It never instantiates Meta, loads a record,
queries SQL/Redis/defaults, modifies a definition, evaluates an expression,
refreshes a cache, initializes a site or sends HTTP.

## Matching rules

- Baseline/applied DocType and Singleton/child storage declarations must agree.
  Selected base fields cannot be customized by this matcher. Baseline custom
  markers must not conceal an already-applied Custom Field.
- Custom Fields must add an absent allowlisted field for that DocType. Record
  names and field names must be unique. Their declared attributes and Frappe's
  integer custom marker must match the applied declaration exactly.
- Property Setters may affect only allowlisted DocField properties. Unknown
  scopes, absent fields, base fields and duplicate field/property targets fail;
  the matcher does not guess the result of ambiguous query ordering.
- Casts use the setter's property type, not the target field type. For example,
  `Int` plus `"2"` yields an integer, whereas `Data` preserves a string. Supported
  types are Data/Text/Small Text/Long Text/Text Editor/Select/Link/Dynamic Link,
  Int/Check and Float/Currency/Percent. Date/Datetime/Time/Password/unknown paths
  are refused before casting. No clock-based fallback or precision lookup runs.
- Type tags preserve NULL, false, zero, blank and exact raw row values/revisions.
  Default expressions remain text. Missing or stale effects fail comparison.

The versioned `FieldCustomizationMatch` binds both metadata fingerprints, the
installed framework version and exact projected raw rows. Rows are canonical by
record name; properties have a fixed layout. Direct reconstruction repeats
validation/casting/equality checks. A different framework version requires an
explicit review instead of silent historical reinterpretation.

Bounds are 128 Custom Fields, 256 setters and the shared streamed 2 MiB canonical
payload ceiling per object. Failures use static English codes without embedding
raw defaults or framework errors. Repr is protected and pickle is refused;
generic dataclass/raw-payload access remains private and is not a disclosure
sandbox or a permitted UI/log/queue/RPC representation.

## What equality does not prove

The caller still supplies all three inputs. Equality cannot prove their source,
query completeness, tenant/ACL, committed revision, physical schema, baseline
authenticity or cache freshness. In particular, an omitted setter whose effect
equals the baseline is not discoverable from final value equality. A modified
timestamp or fingerprint alone does not prove a committed read.

No provenance flag, issuance authorization, complete preparation-source digest,
effective precision resolver or default trusted provider is introduced. Runtime
controllers, schema, UI and existing preparation/recovery guards are not wired
to this adapter. Authorized fixed-column committed acquisition and membership/
revision evidence remain required before integration.

## Defaults behavior pinned before designing a reader

Synthetic tests invoke actual installed Frappe methods with explicit in-memory
sources. They do not read any customer's defaults or test another installed
framework version. The observed APIs have different contracts:

| API | Observed behavior relevant to acquisition |
| --- | --- |
| `Database.get_default` | Reads one parent, implicitly `__default`; list handling differs from tuple handling and preserves a list when its first value is false |
| `Database.get_global` | Delegates to `get_default` with implicit `__global`, or an explicit supplied parent |
| `Database.get_defaults` | Reads only the selected parent; an exact key takes precedence over its scrubbed form |
| `frappe.defaults.get_defaults` | Copies `__default`, then overlays the selected user's keys, including present blank/zero/false/NULL values |
| `frappe.defaults.get_global_default` | Despite its name, uses merged user defaults and a user-permission filter, plus list/tuple selection |
| `frappe.defaults.get_defaults_for` | A cache hit returns the cached object without reading committed SQL rows |

There is no universal global/site/user precedence to infer from these names.
These characterization tests deliberately preserve the installed behavior;
they do not make that behavior the application's new fiscal policy or implement
a defaults resolver. The future reader must declare API/key/user/parent scope,
distinguish cache from committed records, and capture exact membership/order and
permission inputs. Missing or false values must not be silently conflated.

Local source inspection also connects this boundary to the current financial
path: `tax_error._tax_amount_precision` asks the tax row or invoice for precision.
Installed `BaseDocument.precision` caches results on that document and delegates
to `get_field_precision`. That helper first uses a truthy field precision; for
Currency it then reads `db.get_default("currency_precision")` with a number-format
fallback, and for other numeric fields uses float precision with a fallback of
three. These are source-inspection findings, not a newly executed calculation
resolver. The future capture must account for both document precision caches and
the selected defaults API; supplying Currency records alone does not establish
the effective precision of this path.

## Verification and remaining work

The metadata suite checks all supported casts against the actual framework,
typed-value differences, stale/missing/conflicting declarations, independent
parents, bounds, direct payload corruption and the actual Meta setter method
with a synthetic database double. Defaults tests exercise actual API methods
with no SQL/Redis/site boot. Full guarded regression and Node results are
recorded in [STATUS.md](STATUS.md).

Next implement authorized committed metadata/default acquisition, including
query completeness, scoped cache comparisons, Singleton/child locks and physical
v15/v16 differences. Then establish effective precision and financial/XML/GL/VAT
parity and integrate the pipeline. Synthetic v15/v16 labels do not establish
installed ERPNext 16, SDK, signing or authority acceptance.

See [SOURCE_METADATA.md](SOURCE_METADATA.md),
[DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) and
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).
