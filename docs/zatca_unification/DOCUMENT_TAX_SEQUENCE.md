# Shared document discount/tax composition — increment200

Increment201 additionally shares the actual regular-line implementation behind
ordinary Sales item builders with/without templates. Caller item/advance
selection and direct-reference behavior remain. See
[SALES_ITEM_CONSOLIDATION.md](SALES_ITEM_CONSOLIDATION.md).

Development only. `document_tax_xml.py` now composes existing allowance and tax
builders at ten generator contexts. POS Debug keeps two explicit template
branches, so eleven physical spans use the shared sequence. No live installation
or authority request is authorized by this extraction.

## Preparation flow

```mermaid
flowchart LR
    A[Caller identity and type] --> B[Shared reference and party sequence]
    B --> C[Shared allowance then tax composition]
    C --> D[Caller item / advance-line selection]
    D --> E[Shared signing and QR sequence]
    E --> F[Existing artifact / dispatch owner]
```

`DocumentTaxTools` binds the adapter's existing ordinary/template discount and tax
functions, plus its nominal variants where supported. It stores only function
references and retains no namespace, source document or credential material.
Bindings are fresh per invocation; existing imported override points remain.
The module imports only dataclass/type utilities and performs no framework or
master-record read, numeric conversion, persistence, signing or sending.

`populate_document_tax` calls allowance first and tax second, passing each
returned XML root onward and propagating original errors. It does not reinterpret
amounts, Decimal/float policy, rates, tax categories, exemptions, totals, rounding,
discount distribution, FX, prepayments or accounting rules. The actual builder
implementations and their per-adapter differences remain unchanged.

## Nominal and template policy

| Existing caller policy | Shared handoff | Preserved behavior |
| --- | --- | --- |
| Sales ordinary and invoice Compliance | Required-field reader `source.custom_zatca_nominal_invoice == 1` | Read immediately before allowance, then again before tax; a builder-induced change or second-read failure remains observable |
| Sales Debug | Capture optional `getattr(..., 0) == 1` once, then read that captured boolean | Missing field remains allowed; both steps use the original outer-branch decision |
| POS ordinary, Compliance and Debug | No nominal reader or nominal binding | Do not acquire Sales-only nominal functions or inspect that source field |

Template selection retains the existing flag's Python truthiness, including
legacy string flags. This is compatibility, not a new flag-normalization policy.
POS Debug keeps its original outer branch and item calls; its two shared calls
pass literal False/True. Other callers pass their existing template selector.
Template discovery, mixed-template validation and whether a caller trusts or
recomputes that selector remain owned by the original adapters.

The three Sales ordinary paths, Sales invoice Compliance and Sales Debug use
their existing nominal-aware builders. Main POS, foreground/background without-
XML POS, invoice POS Compliance and POS Debug use their existing POS builders.
See [PARTY_XML_SEQUENCE.md](PARTY_XML_SEQUENCE.md) and
[SIGNING_PIPELINE.md](SIGNING_PIPELINE.md) for surrounding caller maps.

## Boundaries retained

- Item, direct-advance and legacy-copy selection stays at each original call
  site, including existing template-item return handling. No advance search,
  allocation, eligibility, remaining-amount or GL behavior is changed.
- Public signatures/decorators and all imported builder paths remain available.
  No runtime file or supported entry point was removed.
- An obsolete commented PDF invocation beside ordinary Sales signing was
  removed. Its malformed example was not executable code or a registered caller.
- Existing source/issuer choice, type classification, ordinary/sample diversion,
  Company-only automatic onboarding, UUID/ICV/PIH behavior, headers, formatting,
  artifacts, scheduling, API routing and response handling are unchanged.
- Existing error/display/logging owners remain. The pure layer's programmer-
  error codes are English and static; it adds no popup, log or translation key.
- Phase-1 QR does not acquire an XML/tax-source or Phase-2 dependency from this
  shared composition step.

## Offline verification

`test_document_tax_xml.py` adds **332 cases**, including **288 real builder parity
cases** across ordinary Sales, nominal Sales and POS, template/no-template,
SAR/USD, no/document/distributed discount, positive/negative values, synthetic
v15 JSON/v16 child tax-detail shapes and inclusive/exclusive settings. Prior
direct selection is implemented independently of the new binding factory.
XML bytes and master-read order match, and supplied numeric inputs stay intact.
Master reads use mocked records; the real tax builders run with no allocated
advances and a deliberately unavailable optional advance schema. This does not
establish advance accounting or installed ERPNext lifecycle behavior.

The other cases verify nominal changes between steps, exact source-read counts,
first/second reader failure, original builder exceptions, returned-root
replacement, legacy flag truthiness, minimal POS dependencies, optional Debug
versus required Sales fields, invalid configuration and frozen bindings without
namespace/source retention.

Final guarded selection: **5,500 distinct local cases passed across 35 reviewed
suites**, including those 332 new cases. It also covers earlier real party and
signing/QR parity, six samples, issuer modes, Debug/Compliance isolation, routing,
settings, scheduling, messages and Phase-1/Phase-2/advance artifact preservation.
Initial overlapping 5,168/322-case runs are not added to this count. Final log:
`/tmp/zatca-document-tax-regression-final-200.log`. The manifest is now 170 local
and 57 private suites; this was neither a whole-manifest nor native SQL run.

AST review against `c1befcc2ece768d43e32b5c3c723eb14dfd5c684` normalized only the
eleven replaced spans and added imports. Every other node in the eight adapter
modules matched, including item/advance selection and outer template branches.
Review separately checked root/source arguments, template/nominal binding and
the exact nominal predicate or Debug capture. Tool:
`/tmp/zatca_tax_structure_200.py`; report:
`/tmp/zatca-document-tax-structure-200.json`. Actual allowance/tax/item builder
modules are unchanged. No performance or source-size gain is claimed.

## Remaining work

This unifies orchestration, not the underlying Sales/POS arithmetic. Inherited
differences and fiscal correctness still require GL/VAT/XML/QR reconciliation.
Complete monetary/runtime adoption, advance accounting, effective settings and
aliases, first-chain/retry/credential guarantees, SDK acceptance, installed
ERPNext/Frappe 15/16 and separately approved fictional-client rehearsal remain
release gates. A passing parity check does not certify the inherited output.

No live source, configuration, schema, customer data, Bench or worker changed;
no authority request occurred. The unrelated existing live tooltip edit remains.
