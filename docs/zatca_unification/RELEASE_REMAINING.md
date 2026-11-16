# Remaining release work — 2026-11-16, increment229

This is the current closure list. Earlier increment reports describe historical
steps; a helper's isolated tests do not mean that it has been adopted by every
runtime path. Development is still isolated. The installed working baseline is
not replaced, and no authority API request is authorized.

The current code has shared financial/type/party/signing/QR composition, selected
source gates, centralized request ownership and route selection, Compliance
outcome checks, translated review contracts and extensive local comparisons.
It is not yet a release accepted on installed ERPNext15/16. A test count cannot
supply a defensible project completion percentage or evidence of remote acceptance.

## Seven closure groups, in dependency order

| Priority | Remaining engineering work | Evidence needed to close |
| --- | --- | --- |
| 1. Source, settings and credentials | Finish binding the saved invoice revision, phase, Company/issuing unit, environment and credential purpose/version through preparation, signer and request. Extend source consistency beyond the four existing-XML adapters where justified. Integrate or explicitly defer internal snapshot/staging components; do not activate them implicitly. | Every adopted route has an owner/settings/source contract and a conflict test; no mixed environment, wrong taxpayer, stale key or unexpected cross-company fallback. |
| 2. Issuance, response and retry lifecycle | Complete transaction ownership and remove unsafe hook commits through services. Serialize ICV/PIH changes per issuing unit/environment, including first issuance, duplicate workers, rejected/unknown results, partial commits and cancellation eligibility. Resolve legacy 409 interpretation through receipt evidence. | Concurrent/restart/lost-response tests; unchanged identity on uncertain retries; no inferred acceptance from UUID or generic HTTP status; accepted artifacts preserved and recovery explicit. |
| 3. Financial compatibility and advances | Review the 117 observed differences and 32 ambiguous cases in the original 240-case simulation. Finish native ERP reconciliation for item/invoice tax sources, multiple VAT accounts, genuine zero/exempt categories, inclusive prices, Net/Grand Total discounts, FX and rounding. Complete type386/partial/multiple/legacy advances, deductions, returns and cancellation. | Document each approved amount/XML difference and rejection rule; match native row sums, group VAT, GL, VAT reporting and outstanding amounts. Case counts are simulated comparisons, not customer invoice counts or production failures. |
| 4. Runtime cleanup and user contracts | Complete the entry-point/dependency map and remove remaining duplicated extractors, legacy branches and obsolete helpers only after tracing consumers and customization compatibility. Keep active diagnostics/test references separate from runtime. Finish consistent Arabic display/English logging across remaining generic catches. | A reviewed runtime file/entry-point inventory, explicit compatibility/deprecation decisions and whole-flow tests for manual/POS/background/Debug/single/all/automatic Compliance; no unreferenced production module. |
| 5. Installed ERPNext15/16 acceptance | Pin separate isolated Frappe/ERPNext benches, runtime/dependencies and dependent apps. Verify fresh installation, upgrade, DocType/alias defaults, permissions, hooks, tax JSON/child tables, Sales `is_pos` and POS accounting. | Actual installed application evidence for both versions; source/shape mocks are insufficient. No upgrade or test Company on a working customer site. |
| 6. XML, signing and QR acceptance | Exercise complete signed outputs through a pinned official local SDK and scanner/decoder checks, covering ordinary/credit/debit, standard/simplified, advance/final, Phase1/2, both currencies and supported settings. Complete Debug/no-send consistency and negative crypto/XML fixtures. | Recorded SDK/runtime/spec revisions, signed XML/QR identities and correct monetary tags. Local checks are not authority acceptance. No authority API is used while the ban remains. |
| 7. Rehearsal, recovery and adoption | After engineering closure, prepare a separately approved isolated fictional-company rehearsal with egress controls, recoverable data/files/encryption configuration and restore/rollback evidence. User decides adoption or rejection after results. | Named tested release commit, clean repository, isolated restore/application acceptance and explicit decision. A subsequent active-client pilot/rollout needs separate approval; authority sending needs its own explicit change to the ban. |

## Practical next sequence

1. Complete source/settings/credential binding and the issuance/response lifecycle
   together; they define which immutable data an attempt may use and how its
   uncertain result is retained. Keep new metadata guards separate from authentic
   cryptographic/receipt evidence.
2. Close the financial and advance matrix against native accounting, documenting
   each accepted change before treating compatibility as complete. No account
   selection or historical invoice repair should be inferred from a passing mock.
3. Freeze the intended runtime scope, remove the remaining duplication, and run
   the complete purpose/phase/settings matrix. Keep compatibility wrappers only
   where an actual consumer contract warrants them.
4. Perform installed15/16 and local SDK acceptance, then prepare the approved
   fictional-company rehearsal. Do not substitute another development-only
   micro-refactor or a larger test count for these application acceptance gates.

For the current metadata-consistency increment and its limited guarantees, see
[EXISTING_XML_BINDING.md](EXISTING_XML_BINDING.md). The full original plan and
historical execution evidence remain in [PLAN.md](PLAN.md) and [STATUS.md](STATUS.md).
