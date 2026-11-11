# Engineering quality as part of completion

The user explicitly requires supporting improvements alongside functional
development. They are part of the release scope, not optional work deferred
until after the fictional-client rehearsal. Apply the same development-only
and no-authority-request restrictions as [PLAN.md](PLAN.md).

## Required work and evidence

| Area | Work included | Evidence required before completion |
| --- | --- | --- |
| Performance | Reduce repeated snapshot reconstruction and validation; avoid unused dependency reads and unnecessary database queries; keep expensive work off save and polling paths | Before/after profiles on identical fixtures, query counts, and measured time/CPU/memory where relevant; preserve numeric, byte and access invariants |
| Shared implementation | Consolidate calculations, settings resolution, XML, signing and QR behind explicit adapters | Caller/dependency map, parity checks, and documented compatibility wrappers; no duplicated business rule hidden in an alternate path |
| Unused code and files | Retire superseded implementations and obsolete imports/helpers after runtime adoption | Check Python callers, dotted RPC paths, hooks, patches, fixtures, DocTypes, JavaScript, templates and supported integrations; a text search alone cannot prove a file unused |
| Readability and maintenance | Clear names and ownership; English docstrings/comments explaining invariants and non-obvious decisions; a current entry-point map | A reviewer can follow each supported flow from entry point to output without reconstructing the conversation |
| Messages and translation | One comprehensive user-facing result per operation; Arabic display for Arabic users and English display for English users; English structured internal diagnostics | Success, warning and failure checks in both UI languages; stable machine codes and original authority payloads remain intact; no nested popup cascade |
| Settings and aliases | One explicit precedence policy for Company, device/POS and linked-company sources; distinguish absent, NULL, zero and false; detect conflicts | A field/alias and settings matrix covering Phase 1/2 and each purpose; no implicit credential or company substitution |
| Background work and retries | Clear operation state, useful progress, bounded polling and deterministic retry identity; prevent duplicate scheduling | Offline duplicate/concurrency and recovery cases; measure polling/query load instead of choosing an arbitrary delay |
| Compatibility | Preserve supported public entry points and data while consolidating internals; support the reviewed ERPNext/Frappe 15/16 matrices | Pinned-source comparisons plus fresh-install, upgrade and installed-runtime evidence on separately approved isolated benches |
| Diagnostics and recovery | Actionable aggregated messages, useful English logs and explicit ownership of artifacts/transactions | No key/token leakage, unchanged accepted artifacts, tested cleanup/recovery, and a documented rollback procedure |
| Documentation and delivery | Keep architecture, settings, test scope and remaining limitations aligned with the implementation | Reviewable DEV commits, accurate test counts, current acceptance checklist and no unsupported readiness or performance claim |

Do not remove a live/public entry point merely because its replacement passes
isolated tests. Use a small compatibility wrapper where callers must be
preserved, and retire it only after its supported dependencies are accounted for.
Keep reference fixtures and test evidence distinct from dead runtime code.

## How each development bundle closes

1. Identify the affected functional paths and applicable quality rows above.
2. Implement the feature/fix and its supporting cleanup together, using shared
   logic rather than adding another parallel implementation.
3. Run meaningful affected regressions. Profile changes that claim better
   performance under comparable conditions; documentation-only changes do not
   require an unrelated application test run.
4. Record what improved, what was actually verified, and what remains open.
   A bundle may be complete while a release gate remains open; state both.
5. Before the fictional-client rehearsal, review every row and the functional
   acceptance matrix in [PLAN.md](PLAN.md). Essential quality work must not be
   silently excluded from the release decision.

## Current runtime consolidation

Increment201 shares the actual ordinary Sales item-line body in its existing
module, retaining exact source/read/price/XML/error semantics and direct-advance
handoff. A frozen old implementation and exact specialized-AST comparison
support the change; 6,145 selected cases passed, including 544 new cases. Runtime
source is 48 lines shorter, not a performance claim. Distinct legacy advance/POS
builders and redundant legacy tax-detail work remain review tasks. See
[SALES_ITEM_CONSOLIDATION.md](SALES_ITEM_CONSOLIDATION.md).

Increment200 composes existing allowance/tax builders at ten generator contexts
with explicit nominal read timing and unchanged item/advance dispatch. The
reviewed selection passed 5,500 distinct cases, including 332 new cases and 288
real builder byte/read-order parity combinations. See
[DOCUMENT_TAX_SEQUENCE.md](DOCUMENT_TAX_SEQUENCE.md). Arithmetic consolidation,
fiscal reconciliation and full runtime/installed acceptance remain required;
orchestration cleanup is not proof of those gates or a performance gain.

Increment199 shares the five-step reference/party/payment sequence at ten
existing generator sites. Explicit purpose/adapter bindings preserve builder
order and content, exact issuer/source/number arguments and the late return flag.
The reviewed selection passed 5,168 distinct local cases, including 164 new
real-builder, missing-PIH and failure-boundary cases. See
[PARTY_XML_SEQUENCE.md](PARTY_XML_SEQUENCE.md). This organizes runtime preparation
without altering monetary policy or claiming performance, fiscal or installed
15/16 acceptance.

Increment198 shares five-tag serialization across ordinary Phase-1 Sales/POS and
the eligible initial-advance hook. It fixes UTF-8 byte lengths, adds bounded
English-code/localized-display failures and avoids encoding obviously oversized
input. Monetary/name/eligibility policies and artifacts remain separate; the
Phase-2 encoder moves unchanged with an import alias. The reviewed selection
passed 4,867 distinct cases, including 145 new local/private SQL cases. See
[QR_SERIALIZATION.md](QR_SERIALIZATION.md). Fiscal amount reconciliation and
complete alias/settings consistency are not inferred from serialization parity.

Increment197 replaces ten repeated signing/QR sequences with one shared
implementation, preserving existing adapter compatibility points and policies.
It removes adjacent obsolete commented file bridges and reduces affected runtime
source by 222 lines including the shared module. This is maintainability/source
evidence, not a performance claim. The reviewed selection passed 4,384 distinct
cases, including 59 new real-XML/crypto and failure-boundary cases. See
[SIGNING_PIPELINE.md](SIGNING_PIPELINE.md). Full runtime, fiscal, SDK and installed
15/16 acceptance remain required before rehearsal or deployment.

## Current performance work

Increment196 removes repeated whole-invoice reconstruction during checked
field-precision resolution while preserving the same rule and independently
validating public APIs. It also preserves bounded installer diagnostics for
failed NEW test-database setup. See
[PRECISION_SOURCE_COST.md](PRECISION_SOURCE_COST.md). This remains isolated work,
not installation or a waiver of performance/accounting acceptance gates.
Controlled stage/field CPU measurements improved 48.2–49.9%, scoped Python peak
allocations improved 23.9–27.6%, and one connected synthetic selection decreased
from 124.98s to 73.33s. These are separate workloads, not production guarantees.

Increment195 continues with shared source reconstruction for sibling rounding
fields and one field-validation kernel. A controlled two-field stage benchmark
used 48.5–49.2% less CPU and 44.8–46.0% lower scoped peak allocations. Each stage
pin still reconstructs independently; this does not close the runtime adoption
or production performance gates. See
[ROUNDING_STAGE_COST.md](ROUNDING_STAGE_COST.md).

Increment194 delivers the first supporting improvement against this priority:
shared captured-row composition removes redundant metadata reconstruction and
one private document facade. A controlled component benchmark uses 27.7% less
CPU; one selected connected synthetic test is 28.6% shorter. This does not close
the invoice-save performance gate. See
[METADATA_CAPTURE_COST.md](METADATA_CAPTURE_COST.md) for parity, scope and limits.

Increment193 established 464 distinct passing cases in its reviewed validation
set, including 11 new cases. Later reports record their own reviewed selections;
repeated cases must not be summed into a release-wide coverage claim. Its repeated evidence
reconstruction is still expensive. Those test-group durations are not invoice
latency measurements. The earlier bounded metadata improvement does not close
the performance gate for the combined pipeline.

The next implementation priority is to profile and reduce this reconstruction
cost while preserving source ownership, exact numeric types/rounding, metadata
bytes and late permission/source checks. Do this before putting the inspection
on an actual invoice-save or polling path. Avoid a global cache or an unchecked
validation bypass as a shortcut.

Alongside that work, maintain the shared caller map and identify which legacy
paths can become compatibility wrappers when runtime consolidation is ready.
Then check aggregated bilingual output and the effective settings/alias matrix
at each adopted boundary. File removal follows verified caller migration; no
unused-file count or complete de-duplication is claimed yet.

Full GL/VAT/XML reconciliation, installed 15/16 runtime acceptance and the other
functional gates remain open. No live installation, worker restart, migration,
working-site data change or authority request is authorized by this plan update.
