# Native child currency and Company source

Increment 122 — 2026-10-28. Caller-owned staging reader, not runtime activation.

## Responsibility and API

`child_currency_source.py` composes existing native financial and selected
metadata readers. It acquires the own `currency` and `company` links of an exact
declared invoice child table, binding every returned row to the supplied locked
financial evidence. It does not create a new permission/cleanup/display service.

The explicit API is:

- `MariaDBChildCurrencyReader(connection).load_for_update(financial, parentfield,
  applied_metadata=...)`: capture one declared child table on the same supplied
  connection. The caller must already authorize that invoice/table and handle.
- `require_unchanged(observed)`: recheck financial data, selected metadata,
  physical membership and own child links on that same transaction.
- `LockedChildCurrencyRead.inputs_for(row_name, company_currency=...)`: produce
  the exact saved-child declarations for the existing pure currency contract.
  A selected own-Company proof is optional and must match the child's own link.
- `resolve_currency(row_name, fieldname, company_currency=...)`: delegate to
  `ChildFieldCurrencyResolution`; its precision operation delegates further to
  the existing shared `FieldPrecisionResolution`.

Only reviewed tests call the staging reader today. The planned production
consumer is the existing saved calculation service after its child READ/cache/
source guards are implemented. No whitelist, hook, button, provider registration,
migration or installed entry point changes. If the integration is abandoned,
remove this staging reader and its narrow profile/tests/docs together.

## Separate metadata profile

`source-child-currency-metadata/v1` selects only `currency` and `company` for the
six declared financial child DocTypes. It reuses `SourceMetadata`, the shared
DocType/DocField/Custom Field/Property Setter reader and existing customization
matching. Applied present fields must be `Link -> Currency` / `Link -> Company`;
unreviewed field types/options are refused rather than interpreted as equivalent.

The legacy source profile's field list, payloads and fingerprints are unchanged.
Most financial child profiles do not select these links. One important exception:
the advance-deduction profile ALREADY selects `currency`. For every overlapping
field, the side profile must match the financial profile's exact definition and
each captured value/presence. A second inconsistent currency proof is refused.

## Read and binding sequence

1. Reconstruct supplied native financial evidence and narrow applied metadata.
   Require exact root Table/options/child-type binding and overlap agreement.
2. Recheck the whole selected financial read on the caller's handle. This also
   verifies autocommit is off and acquires ordinary table/row/metadata locks.
3. Load selected child-link metadata using the shared bounded metadata reader.
4. Query only `currency`/`company` column names in `information_schema.COLUMNS`,
   constrained to the current database and exact allowlisted child table, with
   a fixed three-row bound. Require exact case/membership agreement with applied
   metadata. Never discover or return unrelated column names/values.
5. Reuse the financial reader's bounded child identity/length preflight and
   native CASE/value projection. Apply the existing aggregate byte bound before
   value projection. No ORM coercion, float conversion or copied SQL decoder.
6. Require preflight/full identities, revisions and lengths to agree, then
   recheck physical membership, selected metadata and native financial evidence.
7. Construct a protected result binding the full financial digest, exact table,
   narrow metadata digest, selected physical columns/native signatures and
   ordered row name/index/revision/own-link values. Match every row to the
   financial parent, including absent link fields and empty optional tables.
   Undeclared parent tables are refused.

Applied metadata absence alone does not prove physical column absence: a dropped
DocField may leave a column that ordinary ORM loading still sees. Such orphaned
columns are explicitly refused, even if their current value is NULL. A declared
but physically missing column is also refused. No implicit parent fallback or
schema repair hides either discrepancy. Unrelated columns are unselected.

Native tests demonstrate row/selected-metadata locks and table metadata locks
blocking changes until caller rollback on the synthetic InnoDB fixture. The
reader first obtains the normal table metadata lock before probing columns;
it does not claim that information_schema itself locks missing columns. Storage
engine/schema/provider identity and permissions remain acquisition gates.
READ COMMITTED can still admit new selected DocFields; completion rechecks
detect such insertions instead of claiming that row locks exclude all phantoms.

## Saved child semantics

Absent, SQL NULL and blank own links remain different tagged declarations.
No trimming, default injection, cache mutation or guessed Company. Saved capture
supplies no `parent_doc` fallback: the parent currency comes from the captured
financial header and its metadata. Future support for an in-memory parent needs
an explicit policy and separate binding, not an unobserved fallback.

An optional `LockedCompanyCurrencyRead` must match the exact nonempty own child
Company; its currency can differ from the source invoice Company's currency.
Tests demonstrate that binding without adopting the invoice Company. The proof's
typed reconstruction/name check does not establish its handle, ACL or provenance;
the future shared acquisition service must capture/recheck it on the owned handle.

`require_unchanged` detects own link changes even when neither the child's nor
parent's modified timestamp changes. It also rechecks child membership/order/
revision, source financial data and raw selected metadata membership. Failed
operations poison the reader; interruptions propagate and no retry, commit,
rollback or close occurs. Caller-owned dirty work remains pending.

## Remaining gates

- Compose normal saved parent/child READ with the existing actor/site/role,
  owned-connection, message aggregation and late disclosure checks. This reader
  accepts declarations and a handle; it is NOT standalone saved authorization.
- Bind actual authorized saved child values and provider metadata to this native
  evidence. Include child permlevel/parentfield behavior in v15/v16 rehearsals.
- Reuse the selected Company/Currency/Language/System readers for the exact own
  child currency/Company on the same handle, with trusted cache-key/presence
  providers and separate numeric precision-cache checks.
- Complete other effective settings, native/ORM/accounting/XML parity, full
  installed v15/v16 rehearsals and SDK evidence before release decisions.

No accepted/committed origin, complete preparation graph, signing authority,
monetary rounding, XML validity or authority acceptance is established here.
Protected repr/pickle refusal does not sandbox trusted in-process code. The
result remains an internal ephemeral object, not an RPC/log/queue export.

## Verification and safety

Focused guarded verification passed **74 local + 42 native SQL = 116 cases in
59.43 seconds**. It covers Sales/POS declared versions, all declared financial
table bindings, source presence, Company proof composition, advance overlap,
malformed/forged results, column discrepancies, native types, overlarge values,
RR/RC rechecks, optional empty tables, pending work and row/metadata/DDL locks.
Full regression totals are in [STATUS.md](STATUS.md).

Tests use synthetic sources and NEW owned TCP-disabled private MariaDB only.
No existing database, installed application, site/configuration/schema/data,
Company, credential, Bench or worker is changed. No authority request occurs,
including Sandbox/Simulation. No Decimal conversion, financial recalculation,
GL/VAT/XML/QR/signing or onboarding behavior is activated.

See [DIRECT_CHILD_CURRENCY.md](DIRECT_CHILD_CURRENCY.md),
[FIELD_CURRENCY_ACCESS.md](FIELD_CURRENCY_ACCESS.md),
[DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) and
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).
