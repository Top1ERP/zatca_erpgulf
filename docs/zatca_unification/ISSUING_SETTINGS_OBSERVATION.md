# Invoice issuing-settings observations

Increment 106 — 2026-10-25. Pure PARTIAL declarations, uninstalled.

Increment 107 adds an independently pinned party/address graph, requiring
matching overlapping Company fields/revision and preserving historical direct
address refs without choosing replacements. Both profiles remain PARTIAL; see
[PARTY_ADDRESS_OBSERVATION.md](PARTY_ADDRESS_OBSERVATION.md).

The invoice-owned financial profile now has a sibling observation for the exact
source Company, optional issuing device and its linked Company. At most three
explicit supplied records are permitted. Same-company links reuse one record;
missing/extra/wrong identities or metadata fail closed. No lookup/cache/SQL/ACL,
clock, credential resolution, HTTP, source write or commit occurs.

## Recorded scope and shared policies

Company fields include abbr/name/Tax ID/currency/country, all registered Arabic
name aliases, both phase spellings, enablement, all three environment URL fields,
submission/background/discount controls and both schedule windows. Device fields
are its linked Company and Use Company Certificate and Keys flag. Modified
values and optional schema presence are retained independently from content.

Zero, false, blank, NULL and absent remain distinct. Phase and name aliases are
OBSERVED, not resolved or overwritten. A Phase-1 Company with no environment/URL
does not become a Production submission. This is not a complete settings or
timezone/precision/address manifest.

The existing use_linked_company policy and a shared pure taxpayer declaration
check determine only the DECLARED owner binding. Foreign linked Companies
require equal nonempty stripped Tax IDs, including when the device uses its own
keys. Same-company behavior is unchanged. The legacy saved-owner resolver uses
the extracted check too, preserving its conditional reads and selection policy.
This comparison is NOT authenticated taxpayer/credential provenance.

All configured URL fields receive the existing pure API resolver's structural
validation, independently of selected environment, before retaining a result.
Absent/NULL/empty fields are observations. Query/userinfo/fragment, unsafe
schemes and standard-gateway environment mismatches fail with static errors.
This conservative capture rule does not change runtime routing or send any
request. Using the resolver's Compliance operation here is string validation,
NOT performing Compliance or choosing credentials.

No private key, certificate spelling, CSID authorization, OTP, CSR, PIH, UUID or
ICV is read. Other allowed fields can still contain sensitive business data;
protected payloads/URLs are not logs/UI/RPC/queue exports. Repr is redacted,
pickle refused, independent financial objects and canonical immutable bytes
are retained. The shared streamed payload limit is 2 MiB for this component;
the retained financial component has its own bound, not a family-wide budget.

## Cleanup without a second alias registry

Move the existing 13 alias groups, byte-for-byte in meaning/order, into
ksa_compliance/field_alias_registry.py, without Frappe/schema discovery.
field_compat.py re-exports the SAME public dictionary and keeps all lookup/
creation behavior. New pure profiles use that registry, not duplicate alias
selection logic. A read-only AST comparison against the previous committed
source and a fixed registry fingerprint verify unchanged contents.

Financial pin/reference helpers live in the financial observation module, not
the tax-template module; tax and settings depend on the same base. Canonical
scalar validation can return its decoded scalar for the shared flag/taxpayer
policies without changing serialized bytes. Existing financial fingerprint
goldens and tax/profile regression tests remain active.

Profile extensions/registry changes affecting its columns require explicit
version review; do not reinterpret retained version-1 observations silently.

## Limits and next gates

This is NOT the full preparation source hash or a default evidence guard.
Tenant/site/database origin, ordinary ACL, committed consistent acquisition,
physical v15/v16 schema/type normalization, addresses/parties/POS profiles,
time/precision settings, advances, credential epochs and accounting/XML parity
remain gates. The old runtime dispatchers are not replaced by this observation;
no schema/provider/UI binding or key store is installed. Synthetic version labels
do not prove installed ERPNext 15/16 or SDK/authority acceptance.

Tests cover source/device/linked/same-company/foreign-own combinations, shared
runtime-selection parity, each field and aliases, nullable/numeric flags,
cross-taxpayer denial, secret-field exclusion, all URL fields, exact records,
canonical reconstruction/bounds/privacy and independent pins.
See [STATUS.md](STATUS.md), [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) and
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md). No working environment or
authority requests are authorized by this work.
