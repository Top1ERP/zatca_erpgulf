# Explicit party/address dependency observations

Increment 107 — 2026-10-25. Pure PARTIAL graph, not an address resolver or release.

## Scope

The component pins an independent issuing-settings/financial observation, then
captures the exact supplied source Company, Customer, optional invoice Cost
Center and Address records. The graph includes direct invoice customer/company
address refs, Customer primary address, Cost Center branch address and explicit
company/customer discovery candidates. A missing/extra/wrong record fails closed,
not permission to invent or silently replace a reference.

The source Company's overlapping fields AND modified value must agree with its
parent settings observation. Mixing source versions is rejected. Cost Center
Company must match the invoice Company under the local capture policy.
This does not authenticate site, tenant or historical ownership.

## Captured fields and relationships

- Company: names/Arabic aliases, Tax ID/country, cost-center control and source
  registration type/number.
- Customer: name/type/Tax ID/primary address and all registered Arabic-name, B2C,
  buyer ID/type and UNN aliases.
- Cost Center: Company, branch address and registration type/number.
- Address: lines/city/postal/state/country/PO box/building, title/type/creation,
  primary/shipping/disabled/company flags and registered Arabic-address aliases.
  Address line2 is retained exactly, including its existing short-address use.
- Dynamic Link: ordered identity/idx/parent binding plus link_doctype, link_name
  and optional link_title. Current link changes are data changes even when an
  Address or invoice modified timestamp remains fixed.

Field presence, NULL, blank, false, zero and raw country/name values remain
distinct. No Arabic/English name selection, country normalization, validation
level, display translation, financial recalculation or XML construction occurs.

The caller supplies discovery lists in observed query order. That order is
retained, not replaced with sorting or guessed primary/creation precedence.
Each declared discovery candidate must have a matching captured current Dynamic
Link to its declared source Company/Customer. This checks internal consistency,
NOT completeness/order/eligibility/authorization of the underlying query.

Direct invoice/primary references are captured independently of current
disabled/ownership flags. A historical submitted address may remain disabled or
currently unlinked; it is not automatically replaced. A draft invalid reference
is also only an observation, not a fiscal/ownership grant.

## Boundaries

Exact records are sorted by structured identity; shared address references are
deduplicated. Discovery lists are independently copied and reject duplicate
names within a role. Limits: 64 unique addresses, at most 67 graph records,
256 Dynamic Link rows TOTAL and 2 MiB for the new streamed canonical payload.
Parent settings and financial components have their own bounds; no complete
family/peak-memory bound is claimed.

Explicit Dynamic Link metadata is required even for empty links tables, and is
not accepted when no Address exists. Child Table presence/options, DocType,
parent/parenttype/parentfield, integer contiguous idx and globally unique SQL
child identity are checked using shared helpers. The shared capture helper now
also requires the declared table to exist before reading it. Old financial
fingerprint goldens continue to protect prior wire formats.

The protected result retains canonical bytes and independent parent objects,
redacts repr and refuses pickle. Raw fields contain personal/business data.
Generic dataclass serialization is not a security sandbox; do not send objects
to logs, UI/RPC responses or queues. No keys/certificates/auth/OTP/CSR/PIH/UUID/
ICV fields are requested.

## Existing policy differences remain open

The existing customer resolver prioritizes a submitted invoice's saved address,
even if now disabled or unlinked. Draft ownership and primary/discovery paths
have different checks. Sales XML may omit a B2C customer address; POS XML currently
requires a customer address. Supplier address/cost-center fallback behavior also
differs between the Sales/POS modules. This increment records those dependencies,
not silently unifies selection/eligibility or changes those runtime paths.

Complete authorized committed readers must later capture query membership/order
and rejected/missing candidates without pretending that a supplied candidate list
proves them. Address/Customer/Company policy settings, Country/POS-profile/time/
precision records, linked advance evidence, physical schema/type normalization
and actual arithmetic/XML/SDK/installed-version parity remain gates.

This PARTIAL digest is NOT PreparationContext.source_snapshot_sha256 and cannot
be the default recovery/custody evidence guard. No runtime hooks, provider, UI,
schema, site or authority transport is installed or changed.

## Tests

Synthetic Sales/POS and declared v15/v16 cases cover every selected field,
aliases/zero/absence, shared addresses, ordered candidate/link membership,
Company parent consistency, wrong/missing/extra records, child/metadata binding,
canonical payload tampering/bounds/privacy/no writes and independent pins.
A mocked actual-resolver case proves submitted disabled/unlinked address
preservation without fallback SQL/discovery; four pre-existing mocked resolver
regressions are also added to the guarded reviewed selection.

See [STATUS.md](STATUS.md), [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) and
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md). Passing these observations
does not prove installed ERPNext 15/16, complete source/ACL/financial validation,
signature or authority acceptance. No working environment or tax-authority
requests, including Sandbox/Simulation, are authorized.
