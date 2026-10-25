# Shared invoice XML and first-invoice boundaries

Increment 96 is an OFFLINE development batch, not a runtime installation or
permission to contact any authority environment. Public Sales/POS function names
remain available; no fixture, Company, site, counter or stored PIH is migrated.

## Consolidation delivered

- `invoice_xml_core.py` owns metadata order, PIH/QR/signature reference fragments
  and sample type emission. It has no Frappe dependency, HTTP, persistence,
  counter allocation or UUID generation. Legacy QR placeholder replacement is
  still the responsibility of the signing pipeline, not proof of a valid QR.
- `compliance_types.py` owns all six existing sample type specifications. Both
  ordinary sample adapters and automatic onboarding use them, including the
  pre-existing simplified debit-note flags. No regulatory flag rule is changed.
  Explicit valid string/integer selectors are normalized; malformed selectors
  and ordinary selector zero cannot silently create an incomplete sample.
- Credential selection and XML PIH selection share one saved-owner record
  resolver. Company, own-device and linked-Company policy use saved source links,
  normalized checkbox values and existing taxpayer checks. Caller-supplied links
  do not override the saved source. PIH does not project credential fields.
- `invoice_identity.py` owns the duplicated legacy UUID placeholder filter used
  by Sales generation and submission checks. Compatibility aliases remain. This
  is intentionally a presence filter, not strict UUID syntax validation: a
  previously issued non-placeholder value must not be replaced speculatively.
- Remove the obsolete commented-out POS supplier builder, including two orphaned
  statements that were unreachable after an old exception-handler return. Keep
  the actual active supplier builder unchanged.

## First invoice: what is and is not fixed

Increment 97 adds the separate [declared new-EGS ledger](ISSUING_CHAIN.md), not
automatic genesis in these legacy adapters. Its shared published seed also
replaces the random-ID-derived automatic-sample fallback when Company PIH is
empty. The ordinary guard and old counter/UUID policies below remain unchanged.

A selected missing, blank or non-text PIH now fails with a static translated
message before the shared reference fragment is appended. It never falls back
to another owner's PIH, generates a seed, looks up a previous local invoice,
changes a configured hash or resets a counter. Nonempty configured text remains
exactly unchanged: this increment does not validate hash encoding/provenance.

This protects against silently emitting an empty PIH; it does **not** complete
first-invoice initialization. A confirmed new issuing unit and an existing chain
with missing local history must remain distinct. A reviewed initial-hash policy,
verified chain identity/epoch and historical recovery are still required.

The guard is at `additional_reference`, not before the entire generator. Earlier
legacy UUID/ICV persistence can already have occurred. The batch does not make
that generator atomic or authorize automatic retry after any error. The Sales
UUID persistence/commit policy, POS fresh UUID generation, credential-derived
counter keys, rejection UUID writes and PIH advancement policy stay unchanged.
See [RETRY_IDENTITY.md](RETRY_IDENTITY.md) and
[LEGACY_XML_AND_ICV.md](LEGACY_XML_AND_ICV.md).

Debug/Compliance retain their existing disposable identity/counter policies;
ordinary sample generation now refuses missing saved PIH too. Automatic
onboarding still has its separately documented synthetic PIH/ICV construction;
sharing type specifications is not adoption of that fallback for real invoices.
Phase-1 ordinary QR does not use this new XML fragment or acquire a Phase-2
chain requirement. No discount, tax, advance-settlement, signature-digest or
accounting calculation is changed here.

## Verification and remaining integration

The new fixed-manifest suite exercises both real Sales/POS adapter functions with
synthetic Frappe records, pure byte/order/escaping expectations, Company/device/
linked ownership, numeric/string flags, caller spoofing, empty selected/unselected
hashes, translated display, all six sample types and automatic sample generation,
legacy UUID placeholders, and first-counter Production/Compliance/Debug behavior.
All I/O boundaries are mocked; this is not a tenant or installed version test.

The new suite passed **171 cases**. The full guarded selection passed **14,252
local + 2,022 owned-private SQL = 16,274 cases in 172.76 seconds**; all nine Node
VM scripts passed **1,444 cases**. Native SQL required the approved execution
boundary after a restricted-environment startup failure, with the same offline
guard and exact private-server configuration retained. No assertion was waived.

Saved-row rereads are observational and can race. Bind XML, signature, request,
PIH and immutable UUID/ICV to one verified issuance snapshot/transaction before
claiming retry, first-two-invoices concurrency or credential-rotation safety.
No installed ERPNext 15/16, SDK/crypto acceptance, actual browser or performance
improvement is established by reducing duplicated source. Measure query/CPU/
memory/latency differences in a separately approved isolated rehearsal.
