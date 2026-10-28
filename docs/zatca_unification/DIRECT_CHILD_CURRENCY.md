# Direct child-document currency and cache semantics

Increment 121 — 2026-10-28. Pure staged contract; no runtime activation.

## Purpose and callers

`child_field_currency.py` models the direct child-document currency lookup used
by `row.precision(field)`. It is deliberately separate from the parent-document
operation delivered in increment120: `invoice.precision(field, parentfield)`
passes the parent document to the framework's field-precision helper.

`ChildCurrencyInputs` holds explicit, immutable declarations for a Sales/POS
child and its parent. `ChildFieldCurrencyResolution` validates the selected child
Currency DocField, determines the fresh currency/cache owner, compares supplied
cache slots, and delegates numeric precision to the existing
`FieldPrecisionResolution`. It does not introduce another precision formula.

Increment122's caller-owned `child_currency_source.py` now constructs these inputs
and delegates currency resolution here. The intended authorized consumer is a
future adapter on the SAME owned financial service. This is not a second installed
capture service, public endpoint, button, provider or transaction owner. If that
adapter is not adopted, remove the staging contracts and their manifest/tests/docs
together; they have no legacy runtime callers. See
[CHILD_CURRENCY_SOURCE.md](CHILD_CURRENCY_SOURCE.md).

## Source-backed semantics

Comparison uses the actual installed Frappe15 helper and the existing pinned
Frappe16 MIT-attributed helper excerpt in
`tests/frappe16_precision_oracle.json`. Its full-file hash/commit are unchanged.
All dependencies are synthetic; no full v16 module, bench, site, Redis or linked
Company is accessed. The contract intentionally accepts only the two reviewed
Currency options below, not arbitrary customization expressions.

| Selected options and input | Fresh currency | Framework cache owner |
| --- | --- | --- |
| `currency`, nonempty own row currency | Own row currency | Child DocType / row name |
| `currency`, absent/NULL/blank own currency, parent declares currency | Parent database value | Child DocType / parent name |
| Same, empty database value, v16 nonempty `parent_doc.currency` | Supplied in-memory parent value | Child DocType / parent name |
| Same fallback under v15, or parent has no declared currency field | Unresolved | None |
| `Company:company:default_currency`, nonempty own row Company | Exact child Company's supplied lookup value | Child DocType / parent name |
| Same Company option without own Company | Unresolved | None |

The Company option does not fall through to the parent Company or parent currency.
The own Company may differ from the invoice Company; it must have its own exact
lookup declaration. Missing lookup evidence is refused rather than treated as a
known NULL response. A supplied NULL/blank lookup is explicitly unresolved.
The v16 `parent_doc` fallback requires that the parent metadata declares the field;
it is not a general alternative to the stored source.

## Cache presence matters

Inputs and cache slots retain three distinct states: `("absent",)`, `("null",)`
and `("str", value)` (including blank). No trimming or truthy-string conversion.
This is not a claim that a field/physical column is absent in a real document.

`require_cached_match(row_entry=..., parent_entry=...)` compares the effective
lookup result with the fresh declaration. Both cache keys use the CHILD DocType;
an invoice-DocType cache key is unrelated. A truthy row slot wins over a truthy
parent slot and prevents source lookup. An unused slot is not certified by a
matching effective slot. Equal row/parent names address one cache slot, so their
supplied states must agree.

An important finding from the first comparison run: existing NULL/blank slots
trigger source lookup but `setdefault` does not replace them. The helper can
therefore return NULL/blank after obtaining a valid currency. The initial model
treated them as absent; the oracle comparison exposed that mistake and the model
now preserves presence when evaluating the result. Tests cover blocking at both
row and parent owners. The contract never fills, clears or repairs either cache.

This check does not prove cache identity, caller provenance or simultaneous
stability. It checks exactly two supplied field slots, not an arbitrary mutable
cache container. Existing numeric document-precision caches still need the
separate `FieldPrecisionResolution.require_cached_match` comparison.

## Precision composition

`resolve_precision(defaults, currency_context=...)` uses the shared v15/v16 policy.
Configured field/default precision can succeed even when the declared fresh
currency is unresolved. Frappe15's configured-zero fallback and Frappe16's
preserved zero behavior remain unchanged.

When v16 consumes locale/currency formats, the format context's currency must
equal the direct-child currency. A child currency different from its parent's
cannot silently reuse the parent's format. Unresolved currency can use an
explicit locale-only context with currency formatting disabled; it cannot
authorize a guessed Currency record or `Currency(None)` query.

No amount conversion, Decimal-to-float cast, quantization, tax calculation,
GL/VAT/XML rule, QR, signature, request route or onboarding behavior is changed.
All existing financial/default/metadata payload formats remain unchanged. The
new digest identifies these supplied declarations only, not committed origin.
Protected repr/pickle refusal is not a sandbox against trusted in-process code.

## Integration gates

1. Extend the current owned service with exact row identity/table/index/revision
   binding to the locked invoice financial read. Normal saved parent/child READ
   must precede any source/provider acquisition and survive final disclosure.
   The inspected Frappe15 child-permission engine derives parent permission using
   parenttype/parentfield and valid Table metadata; a raw child name is insufficient.
2. Capture own currency/Company under a separate narrow versioned metadata/source
   profile. Most legacy financial v1 child profiles do not select these fields;
   advance-deduction currency is already selected and must agree in both profiles.
   Legacy metadata absence is not evidence about unselected fields. Frappe can load a leftover
   physical column even after its DocField is removed. Establish explicit bounded
   physical-column evidence or refuse disagreement; do not silently use the parent.
3. Capture/recheck selected parent currency, metadata and any supplied in-memory
   parent value. Define whether saved capture may use the v16 memory fallback;
   it must not silently override a conflicting stored parent.
4. Reuse existing Company and format readers for the exact own child Company/
   currency, with their normal READ, metadata, revision and native value checks
   on one owned handle. Do not add a new cleanup/display/transaction pipeline.
5. Bind actual cache slot presence to trusted scope/key/field providers and check
   through cleanup; compose numeric precision-cache checks separately. Do not use
   a matching number as proof of a matching currency or a frozen source graph.

Increment121 did not implement these gates. Increment122 now implements the native
child-link/physical-column reader and binds rows to locked financial evidence;
increment123 adds explicit saved graph/field READ composition in the shared
service. Related own-Company/format/cache composition remains open. Other
effective settings, complete accounting/XML/native-ORM parity, installed v15/v16
rehearsals and SDK acceptance also remain open.
See [CHILD_CALCULATION_ACCESS.md](CHILD_CALCULATION_ACCESS.md).

## Executed evidence and safety

The focused guarded suite passed **287 cases in 0.90 seconds**, including actual15/
pinned16 cache precedence, own/parent currencies, empty links, versioned parent_doc
fallback, Company option, equal cache keys, stale/blocked caches, precision
composition and malformed/cross-bound declarations. Full regression evidence is
recorded in [STATUS.md](STATUS.md).

No new private SQL schema or database reader is added here. Full regression uses
only the already reviewed NEW temporary TCP-disabled MariaDB fixtures with the
external-network/site-init guard active. No installed application, Company,
invoice, configuration, schema, credential, Bench or worker is changed. No
authority request, including Sandbox/Simulation, is permitted or performed.
See [FIELD_CURRENCY_ACCESS.md](FIELD_CURRENCY_ACCESS.md),
[DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) and
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).
