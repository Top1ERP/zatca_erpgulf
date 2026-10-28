# Read-only selected child currency and precision caches

Increment 125 — 2026-10-28. DEV only; not installed with the address hotfix.

`capture_child_cached_context` extends the SAME saved calculation service and
owned transaction as `capture_child_field_context`. It requires the same exact
saved row/field, normal table/row/field/related READ, site defaults and versioned
Company/format evidence. Existing capture methods retain their return types and
do not inspect extra caches. One shared result-builder composes all existing
protected source contracts; there is no second transaction/cleanup/UI pipeline.

## Exact sources, not cache population

`calculation_child_cache.observe_child_caches` reads ONLY:

1. Current request-local `field_currency` slots for `(child_doctype, row_name)`
   and `(child_doctype, parent_name)`, selecting the exact field name. A parent
   DocType key, other row or other field is not selected.
2. `_precision["main"][fieldname]` on the initial authorized direct saved child
   object and initial parent-child reference. This is the direct-row precision
   layout in the inspected installed15/pinned16 helpers; the parent's separate
   `precision(field, parentfield)` cache is not sampled here.

The saved table acquisition retains these two initial objects until disclosure.
Normal permission/source rechecks may load fresh documents but never substitute
their empty caches for the originals. The observer never calls precision(),
get_field_currency(), a loader, callback, refresh or cache-clear method. Built-in
dict operations select existing slots without invoking overridden mapping lookup
methods. No missing cache, main bucket or field is created.

Missing, NULL and blank field-currency slots remain distinct. Present NULL/blank
slots can block the framework's setdefault result even after lookup; the existing
pure child currency contract checks that behavior. Malformed cache containers are
refused rather than normalized. A missing global currency cache or global NULL
is observed without initializing it. Document precision maps/main buckets must
be dictionaries when present, matching the inspected precision method's shape.

Only effective currency-cache precedence is certified; an unused parent slot is
not made valid by a matching row slot. Existing numeric precision slots must
match both the fresh value AND type. Equal numeric precision does not establish
the correct currency, source Company or format. Missing numeric slots are valid
misses; existing stale/NULL/string/bool values are not silently repaired.

## Sampling and protected result

`SavedChildCacheRead` binds the protected selected field/source/default/Company/
format result, selected slot declarations and ephemeral document/container
identities. Its digest includes the site/namespace/actor/invoice/table/row/field/
version key and captured source digests. Repr is protected and pickle refused.

The service samples after initial native/default capture, again after the last
metadata/cache callbacks before final native checks, and after owned rollback/
close plus normal saved READ rechecks. All observations must agree. Even warming
a previously absent slot with a correct value or replacing a container with an
equivalent dict is drift, not proof of a stable read-only acquisition.

The initial document/container objects remain referenced during comparison.
Their Python identities are ephemeral comparison aids, not durable identifiers,
origin attestation or handles that can be reused after the operation. The result
records past observations; it does not continue monitoring live caches. It
cannot prove cache/ACL/SQL atomicity, historical or committed source provenance,
namespace/provider deployment identity, whole runtime correctness or issuance
authority. Trusted in-process code is not sandboxed by a frozen dataclass.

## Boundaries and next work

No ordinary runtime caller/provider is installed. Version15 still uses site
precision without format reads; version16 still uses its captured related format
context. No financial value, Decimal scale, quantization, FX, GL/VAT, XML, QR,
signature, counter, request route or authority behavior changes.

Next review unresolved-currency locale-only acquisition, remaining effective
settings, full native/ORM/accounting/XML parity and integration into one actual
pipeline. Measure/reduce repeated source/metadata reconstruction and query costs
at reviewed validation boundaries before claiming a lighter release. Complete
installed v15/v16 and SDK/performance/release evidence remains required before
separately approved isolated fictional-Company rehearsal and adoption decisions.

## Evidence and safety

Focused guarded tests passed **54 local cases in 89.68s** and **8 private native
SQL cases in 19.66s**. Coverage includes absent/populated caches, exact source
objects, stale/blocked values, malformed containers, late callback/cleanup
changes, equivalent container replacement, unrelated key isolation, READ before
cache inspection, no precision() calls and protected reconstruction. Full
regression evidence is recorded in [STATUS.md](STATUS.md).

All tests use synthetic data and NEW guard-owned TCP-disabled SQL fixtures.
No DEV cache code, schema, setting, credential or handler was applied to a live
site. The only authorized live exception is the independent one-file
[Phase-1 address hotfix](PHASE1_ADDRESS_HOTFIX.md). No authority request occurred.
