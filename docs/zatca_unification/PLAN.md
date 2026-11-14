# ZATCA path unification: ERPNext 15 and 16

Implementation plan opened 2026-10-09. Status and executed tests are recorded in
[STATUS.md](STATUS.md). This is incremental application development, not approval
to deploy across tenants, upgrade ERPNext, submit production invoices, or delete
legacy accounting records. The older `docs/zatca_advance_redesign/` records remain
historical evidence; their deployment claims do not apply to this new branch.

The current user restriction (2026-10-10) forbids applying results to ANY working
or production environment and forbids agent-initiated tax-authority requests,
including Sandbox/Simulation Compliance. Continue offline development only.
No installed-source/configuration/schema write, Company creation on a working
site, migration or Bench/worker restart is authorized by "continue" or prior notice.
The mandatory order is completed development, then separately approved isolated
fictional-Company rehearsal, then explicitly approved gradual active-client
pilot/rollout. API sending needs separate explicit authority changing the ban.
See [SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md); it supersedes any older
operational request or less restrictive deployment wording in historical records.

## Declared POS VAT-account adoption — increment218

Extend the financial adapter to several VAT accounts only when single-row item
templates declare one account per item and native account-specific rates plus
recorded after-discount account amounts corroborate scope. Bind v16 references
to actual tax-child names; do not sum generic rates or infer VAT from Tax account
eligibility. Keep the original single-account outputs and rejection codes frozen.
Preserve native independent foreign-header conversion and reject cross-account
rounding inconsistencies without silently modifying invoice or XML amounts.

This covers separate declared VAT accounts across items. Multi-row item
templates, invoice-level multi-account roles, non-VAT charge/deduction tax bases
and omitted/not-applicable v16 pairs still need explicit policy. Continue broader
Sales/advance reconciliation and trusted source/settings/transaction integration
before installed lifecycle, SDK and fictional-client rehearsal. No working-site
or authority API action is authorized. See
[POS_VAT_ACCOUNTS.md](POS_VAT_ACCOUNTS.md).

## POS final-net adoption scope — increment217

Ordinary POS Invoice financial builders now delegate coherently to final ERP
nets, shared line/tax/money emitters and a recorded-total reconciliation guard.
Keep the old public entry points as compatibility wrappers. Preserve the native
rounding source, including Global Defaults when the invoice field is absent;
keep discount display financially neutral and group by actual category/rate.
The original matrix explicitly records48 emitted POS changes and32 blocked POS
examples. Review these deltas before adoption; a successful expected-rejection
test does not make an unsupported scenario production-ready.

Next resolve explicit VAT/non-VAT ledger roles and multiple tax/charge rows,
then nominal/cash POS and wider Sales/advance reconciliation. Integrate trusted
source/settings/credential and transaction provenance before installed v15/v16
lifecycle, SDK and separately approved fictional-client rehearsal. Preserve
accepted/supplied artifacts and verify ICV/rollback and concurrency in that
rehearsal. No authority API request or deployment is authorized here. See
[POS_FINAL_NET_XML.md](POS_FINAL_NET_XML.md).

## Original-output compatibility priority — 2026-11-14

The user requires stable results for existing inputs, including multiple taxes
per item and invoice-template sources, and wants differences reported because
some are acceptable and others are not. The user preferred simulation. Maintain
an oracle from the original pre-development source2e97708 with its own native
financial dependencies, not only a comparison with a recent DEV parent.

Increment213 adds240 exact financial-fragment comparisons:176 identical and64
characterized differences from earlier changes. Record unchanged totals separately
from XML-subtotal changes and distinguish generic tax rows from proven VAT roles.
A passing test that expects a difference is not equivalence, user approval or
permission to deploy. Keep these differences visible for review before adopting
or further changing the affected financial policy. No automatic rollback,
legacy-behavior toggle or VAT-account filter is introduced in this increment.
See [BASELINE_TAX_COMPATIBILITY.md](BASELINE_TAX_COMPATIBILITY.md).

## Target design

Increment216 verifies real15/16 discount allocation methods and final net-field
consumption without reproducing allocation inside the app. A stronger native
marker/net predicate permits ordinary mixed-category Sales discounts only after
allocation, preserving other restrictions. Complete POS line/price/allowance/tax/
monetary migration is required; replacing one field would leave its old header
allowance. Close that and accounting reconciliation before rehearsal. Review
cash/non-trade, native marker differences and manual overrides separately. See
[DISTRIBUTED_INVOICE_DISCOUNT.md](DISTRIBUTED_INVOICE_DISCOUNT.md).

Increment215 fixes final group rounding in four Sales ordinary/nominal calculators
using shared pure Decimal arithmetic. Keep rate/category/source and per-line math
unchanged; expose tiny DOC/SAR changes with complete original-output evidence.
The explicit row-rounded ERP0.00/XML0.01 negative case is still not blocked by a
universal runtime guard. Close source/accounting reconciliation before any pilot,
then unify POS groups/rounding and verify its net/inclusive/discount settings.
Foreign/nominal currency policy and full SDK/runtime gates remain. See
[GROUP_VAT_ROUNDING.md](GROUP_VAT_ROUNDING.md).

Increment214 adds a bounded independent standards audit alongside original-output
parity. Officially linked XML v1.2 grouping/final-rounding criteria expose inherited
Sales/POS gaps; the36 new comparisons do not change numerical policies. Correct
category/rate groups and final rounding only after reviewing each intended delta
and reconciling ERPNext invoice/ledger and row-wise-tax settings. Then run both
parity/rule matrices and complete full XML/SDK/runtime gates. Unchanged POS or
matched totals alone are not evidence of compliance. See
[TAX_STANDARD_AUDIT.md](TAX_STANDARD_AUDIT.md).

Increment212 shares non-template native-read/rounding/fallback mechanics behind
ordinary/nominal compatibility wrappers, preserving their exact results, reads,
errors and separate empty-zero behavior. Correct the stale template-first source
contract and map current category/rate/account/settings ownership without claiming
all routes are unified. Establish explicit VAT-row ownership and reconcile known
plain item/summary/nominal/POS source differences next; full fiscal/runtime gates
remain. See [NON_TEMPLATE_TAX_RATE.md](NON_TEMPLATE_TAX_RATE.md).

Increment211 extracts the active reconciliation account classifier behind its
existing adapter and fixes caller-default contamination in unresolved-account
caches. Preserve query, known-account and direct-template policies. Characterize
native v15/v16 mixed-charge rates without using generic Tax/Liability eligibility
as VAT identity. Establish declared VAT-source ownership before changing the
native XML selector. See [TAX_ACCOUNT_POLICY.md](TAX_ACCOUNT_POLICY.md).

Increment210 centralizes the five canonical save/submit tax-metadata checks and
skips them only for explicitly resolved Phase-1. Preserve general enablement,
item values, Phase-2/unknown behavior, field-schema alias priority and the entire
remaining submit body. Clarify the two existing setting descriptions with Arabic
translations in development definitions only. Resolve VAT/non-VAT row ownership
before expanding effective-item rate checks; complete the remaining phase and
installed/fiscal acceptance audit separately. See
[TAX_PHASE_POLICY.md](TAX_PHASE_POLICY.md).

Increment209 aligns preflight invoice-level rate/reason priority with the reviewed
XML source scenarios, preserving zero, genuinely absent fallback and category
ownership. Reuse bilingual mixed-source labels and retain existing rules/gates.
Make the five synthetic source-priority tests site-independent and remove only
the proven overwritten category assignment. Per-item/Phase1/2/source/category/
code policy and full fiscal/runtime acceptance still need separate review. See
[TAX_SOURCE_CONSISTENCY.md](TAX_SOURCE_CONSISTENCY.md).

Increment208 preserves selected zero in ordinary/nominal consumers using an
optional native missing-source default. Keep legacy two-argument/full-detail
behavior and v16 authority. Group non-template subtotals per quantized rate,
share empty accumulators and retain line rounding, net acquisition, category/
reason and nominal SAR/OOS ownership. Verify exact pre-fix deltas, literal
mixed-rate totals and unchanged homogeneous/empty XML. Category/rate/exemption,
malformed/source-completeness and full GL/SDK checks remain required. See
[ZERO_RATE_SELECTION.md](ZERO_RATE_SELECTION.md).

Increment207 shares full-detail/rate-only selection and adopts rate-only at
seven existing Sales/POS consumers, preserving payload conversion, non-finite
handling, the full API and caller math. Verify exact full-mode AST, seven caller
bindings, native values/reads and actual finite/non-finite consumer outputs.
Next resolve the characterized zero-to-invoice-rate fallback in nominal/Sales
helpers with explicit source-presence and fiscal rules, rather than assuming
selector zero authority means whole-system correctness. See
[ITEM_TAX_RATE_ONLY.md](ITEM_TAX_RATE_ONLY.md).

Increment206 narrows v15 JSON folding to the exact requested key, preserving
complete direct-dict/custom-subclass/default folds and all existing rate/amount
and v16 rules. Verify exact parent outputs/reads, selected normalization counts,
key collisions, retired off-target errors and real Sales/POS/nominal consumers.
Measure the native adapter change independently; retain installed/fiscal gates.
See [V15_TAX_KEY_LOOKUP.md](V15_TAX_KEY_LOOKUP.md).

Increment205 removes the unused first tax acquisition/JSON serialization from
plain Sales/advance item loops, keeping the public JSON compatibility helper.
Verify exact parent bytes/errors and explicit removed-read deltas, one fresh
native result per row, remaining read-order parity and the entire unchanged
numeric/source/handler AST. Measure the real item-builder component separately
from production latency or installed runtime. See
[ITEM_TAX_READ_COST.md](ITEM_TAX_READ_COST.md).

Increment204 repairs finite native Decimal/float pairs at the two legacy
reference tax-amount expressions, using the float's decimal text without
projecting Decimal through float. Retain all already-compatible results, context,
source/read/error boundaries and the frozen old fixture; explicitly assert the
intentional old-failure/new-XML delta. Do not treat synthetic type repair as an
installed legacy-field contract or fiscal rounding/rate certification. See
[LEGACY_ADVANCE_NUMERIC.md](LEGACY_ADVANCE_NUMERIC.md).

Increment203 shares legacy advance tax-subtotal and category/item/zero-price
emission while retaining the exact tax-amount statement between the shared
steps in each caller. Preserve discovery, direct priority, identity/time and
last-row semantics; verify full bytes/reads/partial failures and exact specialized
module AST. The inherited Decimal/float failure and legacy monetary/time/source
policy still need separate resolution. See
[LEGACY_ADVANCE_XML.md](LEGACY_ADVANCE_XML.md).

Increment202 shares regular-line XML emission across all four Sales item
builders, including the advance-named wrappers. Preserve explicit legacy unit/
attribute/RHS timing, rate/template acquisition and last-loop/reference tails.
Verify full bytes, source/master/app-read order and partial errors against frozen
old wrappers; retain actual monetary and allocation rules. See
[ADVANCE_ITEM_EMISSION.md](ADVANCE_ITEM_EMISSION.md).

Increment201 consolidates the actual regular-line body of ordinary Sales item
builders with/without templates in their existing module. Retain source/read/
error/XML/price semantics and direct-advance handoff; verify both specialized
bodies against a frozen old implementation. Keep distinct legacy advance and POS
implementations until their differences are separately reviewed. See
[SALES_ITEM_CONSOLIDATION.md](SALES_ITEM_CONSOLIDATION.md).

Increment200 composes allowance then tax at ten generator contexts using the
existing per-adapter functions. Preserve required twice-read Sales nominal
policy, optional once-captured Debug policy and no POS nominal consumption.
Keep template semantics, item/advance dispatch and arithmetic unchanged; verify
real XML/master-read parity and surrounding ASTs independently of the binding
factory. See [DOCUMENT_TAX_SEQUENCE.md](DOCUMENT_TAX_SEQUENCE.md).

Increment199 composes the five existing reference/party/payment functions at ten
generator call sites with explicit ordinary/Debug/Compliance modes. Preserve
builder order, returned roots, exact source/number/issuer arguments, late return
reads and existing Sales/POS content differences. Keep classification, monetary/
advance selection, automatic Company-only onboarding, signing and dispatch in
their current owners. Verify real per-adapter XML/read parity and unchanged
surrounding ASTs. See [PARTY_XML_SEQUENCE.md](PARTY_XML_SEQUENCE.md).

Increment198 shares pure five-tag Phase-1 serialization across ordinary Sales/
POS and eligible initial advances, preserving their own monetary/name/gate
policies. Count UTF-8 bytes, fail before image/File writes with one localized
message, and reject obviously oversized text before encoding. Move the existing
Phase-2 wire helper unchanged behind its compatibility import; keep binary and
long-tag policies separate. Verify byte/amount parity and parent transaction
ownership before considering fiscal/runtime adoption. See
[QR_SERIALIZATION.md](QR_SERIALIZATION.md).

Increment197 adopts a shared in-memory signing/QR sequence at ten existing
generator call sites. Preserve the actual cryptographic rules, adapter import
compatibility, issuer arguments, formatting and all preparation/dispatch policies.
Automatic onboarding shares QR encoding but retains its hash-stabilization gate.
Remove only superseded blocks/comments and verify real XML/QR parity plus
unchanged surrounding adapter ASTs. This improves runtime organization without
installing the branch or adopting expensive inspectors on save. See
[SIGNING_PIPELINE.md](SIGNING_PIPELINE.md).

Increment196 resolves field precision directly from the already reconstructed
numeric/format sources using the same validating precision constructor. Keep
independent public API revalidation, field/currency scope and cache checks;
share the cache scalar check instead of re-entering whole-source APIs inside
the checked kernel. Add bounded owned-installer failure diagnostics to offline
test infrastructure. See [PRECISION_SOURCE_COST.md](PRECISION_SOURCE_COST.md).

Increment195 shares one reconstructed numeric/method source across sibling
rounding fields and one numerical field kernel across standalone/grouped reads.
Compare every supplied sibling against the freshly checked sources and its
recomputed result; retain owner, format/cache, type and signed-zero checks.
No global cache, caller bypass or installed-source adoption is introduced. See
[ROUNDING_STAGE_COST.md](ROUNDING_STAGE_COST.md).

Increment194 reduces repeated metadata reconstruction by sharing one checked
match factory between ordinary document capture and direct captured SQL tags.
Retain source-only column checks, the full match constructor, pre-getter guards
and exact wire/digest behavior. Remove only the unused private document facade;
measure the component and connected inspection separately. See
[METADATA_CAPTURE_COST.md](METADATA_CAPTURE_COST.md).

Supporting engineering improvements are required alongside functional work:
performance, shared implementations and safe cleanup, readable English source
documentation, aggregated bilingual messages, effective settings/aliases,
background/retry behavior, compatibility and maintainability. Track their
evidence and release criteria in [ENGINEERING_QUALITY.md](ENGINEERING_QUALITY.md).
They are included before fictional-client acceptance, not an optional phase
after functional development. The immediate priority is reducing the connected
inspection's reconstruction cost before invoice-save integration.

Increment193 connects saved advance aggregation, the old-write-off ceiling,
conditional reset, outstanding and bounded write-off re-entry on one owned
source. Reuse the row-precision lifecycle and existing arithmetic kernels;
the new internal inspection operation neither allocates/relinks advances nor
replaces an installed controller. See the ten-step bundle and release limits in
[ADVANCE_SETTLEMENT_CHAIN.md](ADVANCE_SETTLEMENT_CHAIN.md).

Combined batch189–192 profiles evidence reconstruction and accelerates only
private field subtrees inside an already bounded/canonical parent, retaining
streaming bounds, all field validation and wire bytes. Add a pure same-source
saved-advance comparison against consumed settlement totals with MATCH/MISMATCH/
NOT_CONSUMED outcomes, never repair, relink or authority acceptance. Preserve
all existing capture methods and explicit precision/provenance gates. See
[ENCODING_AND_ADVANCE_COMPARISON.md](ENCODING_AND_ADVANCE_COMPARISON.md).

Combined batch185–188 adds a separate saved-numeric two-call inspection with
automatic lazy POS dependencies on the existing owned capture. Share the pending
balance primitive with redistribution, authorize each related dependency before
its provider/SQL, retain early/unused-source exits and complete deferred default
consumption in the second call. All final source/permission/cleanup checks remain.
No public financial override or actual append identity is accepted/generated.
Existing capture methods and runtime registration remain unchanged. See
[SETTLEMENT_PLAN.md](SETTLEMENT_PLAN.md).

Combined batch182–184 binds one write-off/outstanding re-entry to the preceding
in-memory prefix, automatic flag and payment effects. Reuse the original paid
kernel for processed/replaced rows, preserve ordinary table-clear effects, and
reject arbitrary rows, retired names, changed headers and third ancestry. The
same sequence validates the second call without forcing its balance to zero.
An uncaptured newly needed POS default source remains a mandatory review gate;
complete two-pass same-owner acquisition before whole service adoption. See
[WRITE_OFF_REENTRY.md](WRITE_OFF_REENTRY.md).

Combined batch180–181 extends the same union with advance precision and binds
the outstanding round/source-before-FX prefix to the exact payable inputs and
paid conversion rate. Reuse existing write-off side proofs and numeric kernels;
replace the synthetic sequence's prefix stubs with actual15/pinned16 method
bodies. Retain separate method/precision traces and NULL/empty-setting behavior.
The second outstanding pass after write-off, changed flags/derived return rows,
accounting eligibility and whole runtime adoption remain open. See
[SETTLEMENT_SEQUENCE.md](SETTLEMENT_SEQUENCE.md).

Combined batch177–179 joins guarded paid, party/receivable/write-off, rounding
controls and optional POS lookup on one original graph/field union/method/pool
and owned handle. Project strict substages and check exact paid/change/payable/
outstanding/POS handoffs, party currency, lookup consumption and write-off
followup. Preserve paid-before-guard, integer-zero skip, no invented post-return
outstanding recalculation and one explicit later write-off recalculation. Prefix
execution, the second outstanding pass, accounting eligibility and whole runtime
adoption remain open. See [SETTLEMENT_SEQUENCE.md](SETTLEMENT_SEQUENCE.md).

Combined batch175–176 adds saved invoice/profile/table/row/field READ before
metadata/SQL callbacks and one-owned POS source acquisition through the existing
financial/default pipeline. Reuse the table/Link helpers, keep lazy limit-only
dependencies and native consumed values, and recheck initial plus fresh access
through close before protected disclosure. This remains an uninstalled explicit
inspection; branch choice, account eligibility and whole-controller composition
are not activated. See [POS_PROFILE_ACCESS.md](POS_PROFILE_ACCESS.md).

Combined batch173–174 adds separate native consumed POS Profile limit and
default-payment scopes, retaining original invoice/Company/metadata/native-type
binding on one borrowed transaction. Refuse missing masters, cross-company,
multiple defaults and orphan candidates; preserve absent-default versus found
blank/NULL mode and do not filter allow-in-returns. Completion rechecks remain
mandatory, especially for later orphan inserts under READ COMMITTED. Saved ACL/
owned acquisition and full controller composition remain open. See
[POS_PROFILE_SOURCE.md](POS_PROFILE_SOURCE.md).

Combined batch170–172 compares the post-balance POS write-off/return conditions,
lazy default-payment query and exact party-currency row replacement. Extract the
existing paid kernel once and reuse it for the derived return rows, preserving
loyalty, FX/precision order and the earlier outstanding amount. Profile/default
query answers remain supplied observations; native custody, account/sign rules
and full controller assembly remain open. See
[POS_BALANCE_ADJUSTMENTS.md](POS_BALANCE_ADJUSTMENTS.md).

Combined batch167–169 adds a separate native Check/Link guard profile, saved
return/internal entry inspection and exact short-circuit comparison, then binds
the real paid stage and guards on one owned source. Preserve paid BEFORE reset,
integer zero, self-link target differences for Sales/POS, absent POS controls and
same-company internal-transfer logic. The downstream balance/rounding, POS
Profile/redistribution and complete accounting assembly remain open. See
[OUTSTANDING_ENTRY_GUARDS.md](OUTSTANDING_ENTRY_GUARDS.md).

Combined batch164–166 extracts shared saved write-off/party acquisition and
side-field precision from the advance ceiling, reuses it in one owned receivable
context, and compares the payable/outstanding suffix plus ordered automatic
write-off updates and one downstream call. Preserve party-currency selection,
advance units, independent total fallbacks, NULL lookup/precision differences and
legacy negative ties. Full eligibility/POS/recursion/settlement assembly remains
open. See [RECEIVABLE_CALCULATIONS.md](RECEIVABLE_CALCULATIONS.md).

Combined batch161–163 adds a native payment-controls side profile and one-owned
Sales Invoice paid/change context, exact base-controller payment/loyalty
aggregation, and cash-change comparisons bound to that paid result. Preserve
precision-free row conversion, company-currency loyalty, return retention,
ordinary-sale clearing, exact Cash categories and independent total fallbacks.
Standalone POS Invoice validation and full outstanding/write-off recursion
remain separate integration gates. See [PAYMENT_CALCULATIONS.md](PAYMENT_CALCULATIONS.md).

Combined batch158–160 adds a distinct native write-off profile through the
shared root-controls reader, one-owned advance/party/write-off ceiling context,
and exact current-value/precision/setting comparison through the limit decision.
Keep15/16 foreign-total precision differences, separate converted write-off
rounding, strict positive-ceiling comparison and reset AFTER the check. Existing
profiles/advance APIs remain compatible; no controller/writer activation. Full
paid/outstanding/write-off recursion and fiscal/settlement parity remain. See
[ADVANCE_LIMIT.md](ADVANCE_LIMIT.md).

Combined batch155–157 closes the standard saved unset16 advance-party source
gap: a separate optional-child profile and shared reader, conditional normal/
native parent-party acquisition, exact original cache/format binding and the
existing per-row aggregate interface. Own row party currency wins; parent fallback
uses party-account currency rather than transaction currency. Old profiles remain
byte-compatible. Blank/missing parent or unproved parent_doc remains outside the
saved domain; full limits/FX/settlement/fiscal/runtime gates stay open. See
[ADVANCE_PARTY_CURRENCY.md](ADVANCE_PARTY_CURRENCY.md).

Combined batch151–154 adds one-owned root/direct-advance precision acquisition,
original row/reference cache observations, lazy native child/own-Company formats
and per-row aggregate precision binding. Share one graph/handle, initial formats
by distinct currency, and configured precision across rows. Check all related
access before child/format providers. Primary standard `party_account_currency`
is explicitly tested: configured15/16 precision works; unset16 requires its own
native row/parent party-currency source and remains refused. Do not substitute
invoice currency. See [ADVANCE_ROUNDING_CONTEXT.md](ADVANCE_ROUNDING_CONTEXT.md).

Combined batch148–150 adds complete explicit current-row observations, ordered
net-total calculation comparison and a separate direct-row advance aggregation
prefix. Reuse the saved owned context, shared trace validator and versioned
rounding kernel; preserve saved/current separation, integer sum semantics and
conditional dependencies for empty advances. Compare actual15/pinned16 method
bodies on synthetic objects only. Later tax/discount/FX/settlement/XML and active
controller provenance remain gates. See [CALCULATED_TOTALS.md](CALCULATED_TOTALS.md).

Combined batch145–147 adds one-owned explicit multi-field stage acquisition,
ordered native/fixed before/after and precision/setting trace comparison, and
actual15/pinned16 synthetic round_floats_in probes. Share one financial/method
read and format sources by parent scope; preserve skip semantics and conditional
raw-method fallback lookups. Default field order/outside-manifest fields and
active controller/calculation/provenance remain gates; no execution/writer
activation. See [ROUNDING_STAGE.md](ROUNDING_STAGE.md).

Combined batch142–144 delivers three connected tasks before one checkpoint:
reproducible pinned15/16 Currency metadata coverage, same-owned supplemental
party_account_currency (including parent-owned advances), and conditional exact
Company API-cache projection. Share one parent-scope registry and the existing
bounded link reader; preserve old financial/Company bytes and all15 capture APIs.
No runtime activation. See [OWNER_CURRENCY_AND_CACHE.md](OWNER_CURRENCY_AND_CACHE.md).

Increment141 completes lazy v16 format acquisition for the two standard owner-
field Currency option branches on the SAME field-rounding pipeline, after native
site defaults. Reuse precision selection, normal field READ, format/Company SQL
and cache/cleanup logic; pin the parent's field_currency cache key without
population and keep locale fallback. No new capture API or runtime activation.
Active controller/API-cache provenance, unsupported option/currency patterns,
batching/performance and full fiscal parity remain. See [FIELD_ROUNDING.md](FIELD_ROUNDING.md).

Increment140 composes a selected saved field's numeric/native graph, site
defaults, System method and original owner's existing precision cache on ONE
owned pipeline. Calculate only the selected comparison result, with exact type/
bit checks and no normalization or controller invocation. Reuse shared source/
ACL/metadata/cache/cleanup paths; reject changed or stale caches and unsupported
v16 format fallback. Owner-field formats and active controller-stage provenance
remain gates before fiscal integration. See [FIELD_ROUNDING.md](FIELD_ROUNDING.md).

Increment139 adds a pure explicit versioned field-rounding primitive, sharing
the unchanged legacy kernel and retaining verified15/16 Banker's/Commercial
differences. Compare real numeric helpers and Document.round_floats_in for NULL,
owner precision, default/explicit field order, upfront setting lookup and16 skip
semantics. No runtime registration or source-profile change. Bind actual caller
stage/effective precision-cache/source provenance before adopting it for amounts,
tax, advances or XML. See [FIELD_ROUNDING.md](FIELD_ROUNDING.md).

Increment138 adds complete selected real-number getter views bound to native
financial evidence. SAVED preserves raw type/scale/sign/NULL; explicit fixed
observations compare only the framework's precision-free representation. Compose
saved header/direct-child/reference equality on the SAME owned financial service,
reusing graph READ, metadata, native SQL and cleanup with no extra native query/provider.
Preserve all native/profile bytes; no document fix or fiscal math is introduced.
Actual controller-stage provenance, effective settings and accounting/XML gates
remain. See [FINANCIAL_NUMERIC_VIEWS.md](FINANCIAL_NUMERIC_VIEWS.md).

Increment137 distinguishes ordinary saved Check getters from explicit numeric-
fix projections in actual15/pinned16 scalar loading. Bind observed None only to
proved native NULL/absence, retain exact saved values and the old strict fixed
API, and reject false-equivalent getter/native drift. No coercion, default/global
fallback, amount conversion or native-profile change is introduced. Complete
controller/child/lazy/amount/precision/cache and runtime gates remain. See
[INVOICE_CHECK_LOADING.md](INVOICE_CHECK_LOADING.md).

Increment136 composes the consumed rounded-total sources on the SAME owned
financial/defaults service. Share declared guard/version helpers; preserve
consolidated/field-presence/invoice-over-global priority and authorize each
conditional related source before its acquisition. Reuse one financial graph,
read fraction only when enabled and method when consumed, including disabled
v16 base conversion, and recheck every selected source through cleanup. The
retained adjustment getter is only a
zero/nonzero guard witness, not an amount-equality or normalization claim.
Complete money/provider/runtime/adoption gates remain. See
[ROUNDED_TOTAL_ACCESS.md](ROUNDED_TOTAL_ACCESS.md).

Increment135 adds optional permissioned invoice-Currency fraction inspection on
the SAME owned financial/defaults service. Reuse full financial graph and related
record/field READ before all callbacks; bind original/fresh invoice currency,
definitions/levels and Currency revision, then compare native configuration to
the exact consumed post-flt API value through cleanup. No document default or
ORM value replaces that API projection. Old operations acquire no new dependency.
Consumed guarded composition, provider/role review and release gates remain.
See [CURRENCY_FRACTION_ACCESS.md](CURRENCY_FRACTION_ACCESS.md).

Increment134 adds bounded native invoice-Currency fraction evidence, including
exact Link/currency identity, required metadata and separate raw/precision-free
flt configuration projection. Reuse financial SQL and the declared fraction
classifier, preserve money/old profiles and compare supplied effective floats
without cache lookup. Increment135 composes normal related READ and exact API
comparison; concrete provider provenance and consumed guarded composition remain.
See [CURRENCY_FRACTION_SOURCE.md](CURRENCY_FRACTION_SOURCE.md).

Increment133 composes invoice-control inspection on the SAME saved financial/
defaults service. Reuse extracted financial graph READ, including empty-table
and field checks; bind initial and fresh invoice definitions/levels/owner and
canonical Check getters through cleanup. Acquire no unused child-link/global/
format/method source, change no raw amounts and preserve existing child entry
contracts. Active policy, fraction/method/ERP amount provenance and release gates
remain. See [INVOICE_ROUNDING_ACCESS.md](INVOICE_ROUNDING_ACCESS.md).

Increment132 adds native optional invoice rounding controls bound to the existing
financial graph. Prove metadata and physical column membership, exact overlapping
definitions/values/descriptors and original revision; retain raw Check/amount
tags and separate normalized Check getters. Reuse financial bounded SQL without
changing old profile bytes, calculating amounts or installing a provider. Normal
selected-field READ/getters and consumed global/fraction/method composition stay
in the existing owned-service plan. See [INVOICE_ROUNDING_SOURCE.md](INVOICE_ROUNDING_SOURCE.md).

Increment131 composes native global Check inspection into the SAME saved service
with ordinary invoice/Company/Global record and selected-field READ, pinned field
definitions/levels and cache/source checks through cleanup. Share Singleton-setting
acquisition with the existing method path. Never substitute a normal document
default for get_single_value's effective int projection. This optional inspection
does not choose the active invoice branch; native invoice/consolidation/fraction
sources and consumed-dependency selection remain next. No runtime provider or
rollout is installed. See [GLOBAL_ROUNDING_SOURCE.md](GLOBAL_ROUNDING_SOURCE.md).

Increment130 adds bounded native Global Defaults rounded-total Check evidence
and an exact comparison to the consumed pure control plan. Preserve missing/NULL/
blank/zero identities, but match get_single_value's normalized int API result:
even an empty Singleton needs no document-default witness for this API. Reuse
the existing SQL transport and metadata reader; no independent acquisition engine
or runtime provider is installed. Compose normal READ/cache/source provenance,
invoice/consolidation/fraction controls and final rechecks into the existing
owned service before adoption. See [GLOBAL_ROUNDING_SOURCE.md](GLOBAL_ROUNDING_SOURCE.md).

Increment129 pins ERPNext16 controller evidence and adds a pure rounded-total
control plan. Preserve consolidated/metadata guards, invoice field presence over
global/POS settings, actual invoice currency, fraction-plus-final-method dependency
and different disabled base effects in15/16. No amount conversion, old profile
change or runtime adoption. Native/effective controls, frontend/merge/amount/GL/
VAT/XML parity and release gates remain. See [ROUNDED_TOTAL_CONTROL.md](ROUNDED_TOTAL_CONTROL.md).

Increment128 acquires the selected saved/native rounding setting on the SAME
context/defaults service. Reuse bounded format text/witness SQL, shared metadata/
normal READ and cleanup. Compare exact consumed caches across close, distinguish
missing/stored NULL, skip unused System dependencies under explicit overrides,
and finish trusted callbacks before final cross-source checks. No amounts/runtime
activation; provider provenance, remaining rounding controls, complete monetary
parity and installed/release gates remain. See [CALCULATION_ROUNDING.md](CALCULATION_ROUNDING.md).

Increment127 adds pure settings/version-bound rounding-method selection without
amount conversion or old observation/default profile changes. Characterize
override/System/legacy precedence, exact consumed cache projection and actual
versioned helper behavior with pinned sources. Native System Settings capture,
currency-fraction/POS/rounded-total/row-wise-tax controls and complete monetary
parity remain before runtime adoption. See [CALCULATION_ROUNDING.md](CALCULATION_ROUNDING.md).

Increment126 admits proved missing own child Company links on the SAME selected
field/cache operations. Reuse version15 site precision; under version16 authorize
only Language/System Settings with the currency-format flag disabled. Do not
substitute parent Company/currency or query Currency(None). Preserve normal/native
graph checks, cache-presence semantics and rechecks through owned cleanup.
Remaining effective settings, complete source/accounting/XML parity, runtime
adoption and installed15/16/performance/release gates remain. See
[CHILD_FIELD_FORMAT_ACCESS.md](CHILD_FIELD_FORMAT_ACCESS.md).

Increment125 adds exact selected request-local field-currency and numeric
precision cache observations on the SAME service, retaining initial authorized
objects and rejecting drift through cleanup without cache population/repair.
The Phase-1 address guard is corrected in DEV and, by separate explicit approval,
as an independent one-file current-version hotfix for all shared Bench sites.
This is not a DEV rollout. See [CHILD_CACHE_OBSERVATION.md](CHILD_CACHE_OBSERVATION.md)
and [PHASE1_ADDRESS_HOTFIX.md](PHASE1_ADDRESS_HOTFIX.md).

Increment 124 adds exact saved child-field selection and own-Company/native
currency proof to the SAME pipeline. Reuse format acquisition for version16's
selected Currency/Language/System context and cache; preserve version15's site
precision without unused format reads. Check related field READ before every
provider/SQL boundary and keep metadata/native/locale/ACL rechecks through cleanup.
At that increment, actual field/precision cache sampling and unresolved-currency
locale-only policy remained open; increments125/126 address these scoped cases.
Common runtime adoption and installed/accounting/XML/performance gates remain.
See [CHILD_FIELD_FORMAT_ACCESS.md](CHILD_FIELD_FORMAT_ACCESS.md).

Increment 123 composes saved child capture in the SAME defaults/financial service.
Authorize every financial table/row and selected field level before providers/
SQL, including empty tables; bind the applied metadata graph before opening the
owned handle. Recheck source/ACL through cleanup, reuse one localized summary and
return a protected full table-membership binding. Compare table permission behavior
against actual15/pinned16 helpers. Related own-Company/format/cache acquisition
and adoption by all final runtime paths remain gates. See
[CHILD_CALCULATION_ACCESS.md](CHILD_CALCULATION_ACCESS.md).

Increment 122 adds caller-owned native child currency/Company evidence using
the existing financial preflight/value and metadata readers. Bind exact table/
row/index/revision and physical column membership without changing legacy bytes.
Require overlapping advance-deduction currency definitions/values to match the
financial parent. Delegate saved child inputs to the increment121 pure contract;
normal saved child READ, related formats and cache/provider composition on the
shared owned service remain next. See [CHILD_CURRENCY_SOURCE.md](CHILD_CURRENCY_SOURCE.md).

Increment 121 characterizes direct child-document currency and cache semantics
in a pure staged contract, reusing the shared precision policy. Verify own/parent
currency, child-only Company lookup, v16 parent_doc fallback, effective cache
precedence and present-but-empty setdefault behavior against actual15/pinned16.
Native/permissioned child-field acquisition remains the next explicit gate;
legacy financial metadata does not prove absent own child fields. See
[DIRECT_CHILD_CURRENCY.md](DIRECT_CHILD_CURRENCY.md).

Increment 120 adds native Company default-currency proof to the SAME owned
permissioned format pipeline, with explicit separate invoice/Company scopes.
Resolve captured child-field metadata in parent-document precision calls and
compare a supplied field-currency cache without repair. Preserve the old result
name as an alias to one shared implementation and leave old payloads unchanged.
Direct child-document/cache inheritance, other settings and accounting/XML parity
remain gates. See [FIELD_CURRENCY_ACCESS.md](FIELD_CURRENCY_ACCESS.md).

Increment 119 composes invoice-currency/locale formats with normal related READ
and the existing owned financial/default transaction. Pin source/currency/locale/
cache/revisions; recheck through cleanup and keep legacy capture methods intact.
Add an explicit nonempty-Singleton missing-Check witness without creating settings
or changing present v1 bytes. Restrict precision use to root Currency fields with
explicit invoice-currency options. Next complete Company/base/child currency,
other settings and whole-empty Singleton policy. See
[CALCULATION_FORMAT_ACCESS.md](CALCULATION_FORMAT_ACCESS.md).

Increment 118 adds a separate narrow format-metadata profile and reuses the shared
metadata SQL/customization engine, preserving all legacy v1 bytes. Read selected
Language/Currency and tabSingles values with native text signatures, bounded
preflight/CASE projections, exact presence and same-transaction rechecks. Return
the explicit v16 precision context without currency/locale discovery or cache
repair. Next bind related ACL, actor/lookup provenance, field-currency resolution
and Singleton normalization in the financial acquisition. See
[CURRENCY_FORMAT_SOURCE.md](CURRENCY_FORMAT_SOURCE.md).

Increment 117 resolves field precision from exact applied metadata and site
defaults, with a concrete caller on the protected financial result. Distinguish
v15 from pinned v16 zero/default/locale/currency behavior and detect stale document
precision cache without refreshing it. Preserve old snapshot bytes and raw
amounts; this is not fiscal/XML rounding. Add versioned locale/currency/system
acquisition before claiming complete v16 settings. See
[CALCULATION_PRECISION.md](CALCULATION_PRECISION.md).

Increment 116 composes native invoice/child data with the existing permissioned
defaults/metadata service on one fresh owned transaction. Pin exact overlapping
identity/revision/Company/status/metadata, preserve Decimal scale and parent pending
work, and reject late source/ACL drift through one translated summary. Existing
defaults-only and metadata-only operations remain intact. No XML/runtime change
or complete preparation proof. Next finish native/ORM parity and linked/effective
settings. See [CALCULATION_FINANCIAL_ACCESS.md](CALCULATION_FINANCIAL_ACCESS.md).

Increment 115 adds native invoice-owned header/child SQL acquisition with exact
metadata, ordered scope/membership/revision checks and bounded preflight/value
projections. Preserve native Decimal scale and temporal types; reject lossy
decoders instead of guessing ORM normalization. No settlement/fiscal policy or
runtime is changed. Permissioned composition, linked dependencies, ORM bridge
and financial/XML parity remain gates. See [FINANCIAL_SOURCE_SQL.md](FINANCIAL_SOURCE_SQL.md).

Increment 114 composes defaults and exact invoice/Company metadata in the existing
permissioned transaction service. Reuse one ACL/acquisition/cleanup/display path,
pin and recheck applied declarations and all selected SQL rows before protected
disclosure. Keep the original defaults-only operation intact. Other financial/
child/dependency reads and effective precision remain open; this is no complete
preparation guard or runtime activation. See [CALCULATION_CONTEXT.md](CALCULATION_CONTEXT.md).

Increment 113 adds selected locked DocType/DocField/Custom Field/Property Setter
reads and raw membership/revision binding to the existing applied matcher.
Preflight unsafe types before values and mask concurrent unsupported additions
inside SQL too; reject ambiguous changes without repair or schema writes.
This is a caller-owned dependency reader, not complete authorized source proof
or runtime activation. See [METADATA_SOURCE.md](METADATA_SOURCE.md).

Increment 112 composes defaults reads with saved invoice/Company READ, an explicit
fresh owned transaction and cache source, and protected actor/source binding.
Share one saved-record ACL/drift mechanism; keep the new graph free of CSID/owner/
route prerequisites. Preserve parent transactions/messages and one localized
failure. No provider is installed and complete preparation provenance/effective
precision/runtime integration remain gates. See
[CALCULATION_DEFAULTS_ACCESS.md](CALCULATION_DEFAULTS_ACCESS.md).

Increment 111 adds fixed-column scoped SQL reads/rechecks for currency precision,
float precision and number format, plus supplied selected-cache comparison.
Preserve raw rows/NULL/order/revisions, reject ambiguous precedence, retain caller
transaction ownership and test actual current reads/locks/phantoms/bounds on a
new guarded private server. This is one dependency, not the complete authorized
committed source reader or effective precision resolver. See
[CALCULATION_DEFAULTS.md](CALCULATION_DEFAULTS.md).

Increment 110 matches supplied baseline metadata, raw Custom Field/Property
Setter rows and applied metadata using the installed framework's bounded
non-temporal casts. Reject stale/conflicting declarations without applying
changes. Characterize actual defaults scope/list/permission/cache APIs instead
of guessing universal precedence. These are declaration/API contracts, not a
committed reader, completeness proof or effective-default resolver. See
[METADATA_RECONCILIATION.md](METADATA_RECONCILIATION.md).

Increment 109 adds explicit applied-field metadata/base definitions and a narrow
read-only document view. Raw Frappe Meta excludes default fields: require supplied
docstatus/creation definitions rather than assume columns or rewrite source data.
Observe precision/options/defaults/custom markers without applying setters or
resolving scoped defaults. Physical/committed/schema/Setter provenance and actual
runtime integration remain gates. See [SOURCE_METADATA.md](SOURCE_METADATA.md).

Increment 108 captures explicit System Settings/Global Defaults Singletons,
referenced currencies, POS Profile/payments and its own tax template. Preserve
Singleton storage without invented modified values, deduplicate currency refs
and reuse the existing tax-profile helpers without wire/precedence changes.
Still PARTIAL: effective metadata/default scope, committed capture and real
calculation/XML parity remain gates. See
[CALCULATION_SETTINGS_OBSERVATION.md](CALCULATION_SETTINGS_OBSERVATION.md).

Increment 107 adds an explicit party/address graph from a pinned settings/source
parent, with exact Company/Customer/Cost Center refs, address fields/current links
and caller-observed discovery order. Preserve submitted historical addresses and
reject inconsistent Company versions; do not invent fallback or choose address
eligibility. Still PARTIAL: committed discovery/ACL, remaining settings and actual
XML parity precede runtime adoption. See
[PARTY_ADDRESS_OBSERVATION.md](PARTY_ADDRESS_OBSERVATION.md).

Read [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) for the functional source map
and closing sequence, separate from this chronological design history.

Increment 106 adds non-secret source Company/device/linked-Company settings
observations and shared declaration checks, without a default source guard or
runtime activation. Extract the SINGLE existing alias registry without Frappe,
preserve its public object and lookup semantics, and share financial pin/scalar
helpers rather than introduce settings-to-tax coupling. See
[ISSUING_SETTINGS_OBSERVATION.md](ISSUING_SETTINGS_OBSERVATION.md).

Increment 105 adds explicit linked tax-template observations from a pinned
financial profile: exact Sales Taxes and Charges Template/Item Tax Template
sets, Company binding and ordered tax children. Missing/extra records fail,
never silently select invoice fallback. Reuse bounded typed/canonical child
helpers without changing the invoice-owned profile. Still PARTIAL/uninstalled,
not a full evidence guard, precedence choice or committed ERP snapshot. See
[TAX_DEPENDENCY_OBSERVATION.md](TAX_DEPENDENCY_OBSERVATION.md).

Increment 104 starts the financial dependency boundary with a pure versioned
invoice-owned observation: header plus ordered items/taxes/payments/advances/
deductions and explicit optional-schema presence. Preserve exact typed values,
including zero/NULL/absent/scale, without recalculation or alias selection.
This PARTIAL digest is NOT the complete preparation source hash or a default
evidence guard. Committed SQL, linked settings/templates and arithmetic/XML
parity remain gates. See [FINANCIAL_SOURCE_OBSERVATION.md](FINANCIAL_SOURCE_OBSERVATION.md).

Increment 103 reduces encrypted-custody access work by authenticating once per
entry and pinning the complete envelope and independent original at subsequent
boundaries. Preserve all source/ACL/evidence checks and independent SQL envelope
authentication. Tests assert actual decrypt counts and reject late envelope/
original mutation, including post-commit denial. No accounting policy, snapshot
provenance, runtime binding or transport permission changes.

Increment 102 adds uninstalled encrypted exact-original/ticket custody and
saved-WRITE protected retrieval feeding the existing local recovery service.
Supplied independent storage keys authenticate an immutable envelope; uncertain
storage retains the SAME ciphertext without resealing, rebuilding or retrying.
Shared source/evidence guards and source/chain/hold/ciphertext lock order remain
mandatory. No live vault, installer, runtime caller or authority transport is
enabled. Existing plaintext journals are not converted. See
[PREPARATION_CUSTODY.md](PREPARATION_CUSTODY.md).

Increment 101 adds uninstalled saved-WRITE local recovery of an exact retained
original, separate from READ review. Mandatory explicit evidence and source/ACL
guards bracket one owned atomic original/head/hold completion; uncertain commit
never regenerates or retries. Draft/cancelled sources remain review-only under
an explicit conservative local policy. No vault, authentic source verifier,
runtime hook or authority client is installed. See [PREPARATION_RECOVERY.md](PREPARATION_RECOVERY.md).

Increment 100 adds uninstalled permissioned read-only preparation review from
saved source identity after loss of the in-memory ticket. Reuse ordinary saved
READ/owner/source checks and owned rollback/close; preserve existing accepted-
archive rules. Return only pending/recorded/absent non-authorizing English metadata
and provide one display-only translated summary. No raw export, mutation,
provider/button installation or authority call. See [PREPARATION_REVIEW.md](PREPARATION_REVIEW.md).

Increment 99 adds durable pre-build no-rebuild holds and an opt-in owned
two-transaction local coordinator. Commit/close an immutable ticket BEFORE the
single local builder, then atomically record exact original/head/hold completion.
Unknown results keep the hold; reconciliation uses exact retained bytes, never
a fresh builder. Previous internal chain entry points honor pending/permanent
holds. No live writer, installer, permission facade or authority client uses it;
authenticated source/custody/operator review and installed v15/v16 remain gates.
See [DURABLE_PREPARATION.md](DURABLE_PREPARATION.md).

Increment 98 adds an uninstalled one-shot preparation coordinator: lock an
existing explicit chain, refuse a previously prepared source before building,
pin context/UUID/ICV/PIH, preserve the exact candidate before protected custody,
recheck the declared source guard and stage original/head in the caller's
transaction. It does not commit, send, supply an ERP adapter, authenticate
declarations or install a durable pre-build hold. Process-death/rollback recovery
and source/identity custody remain gates before runtime adoption. See
[ISSUANCE_PREPARATION.md](ISSUANCE_PREPARATION.md).

Increment 97 introduces explicit NEW_EGS chain state and atomic local recording
of its exact original through the shared artifact repository. No manual reset
field is added. A declared new unit starts from zero/initial PIH and records its
first candidate at one; a blank legacy field, token change or renewal cannot
select this path. Enrollment/tenant/epoch/ACL provenance and legacy-writer/runtime
integration remain gates. Automatic samples only replace the empty-PIH random
fallback with the published seed. See [ISSUING_CHAIN.md](ISSUING_CHAIN.md).

Increment 96 consolidates Sales/POS metadata and PIH/QR/signature fragments,
the six sample XML type specifications (including automatic onboarding), saved
PIH owner selection and the legacy UUID placeholder filter. Missing selected
PIH now requires review, never automatic chain initialization/reset. This guard
is not an atomic issuance preflight: legacy UUID/ICV writes can precede it.
First-chain initialization, immutable retry/rotation/concurrency and unified
synthetic/real chain policy remain open. See [SHARED_INVOICE_XML.md](SHARED_INVOICE_XML.md).

Retain the public button and hook entry points while gradually replacing their
duplicated internals with a shared, tested pipeline:

`ERP adapter -> effective settings -> immutable invoice snapshot -> amounts/tax -> XML -> signing/QR -> explicit output mode`

Adapters handle ERPNext version and document differences. The core must not read
the database, commit transactions, attach files, or send HTTP requests. Services
own those side effects explicitly. English docstrings explain invariants and
regulatory rule references; UI messages use translation keys with Arabic entries.

Operation messaging policy: collect related outcomes into one comprehensive
user-facing summary, translate only app-owned display labels for the user's UI
language, and keep generated diagnostic storage English. Original authority
payloads/codes/identifiers remain unchanged. Increment 68 adopts this policy for
the two Company batch checks and retained-event labels. Increment 69 adds the
Company single-check wrapper and Sales/POS Debug menus with a shared presenter.
Ordinary invoice/POS submission, legacy direct calls, CSR/CSID and background
boundaries still require staged adoption; original diagnostic details remain
unchanged, even when a legacy exception is localized. Increment 70 fixes Debug
POS/Background's undefined bypass read by removing an unused private selector,
without changing its actual type selection or Sales Debug. Increment 71 adds
normal saved-source/Company/File ACLs and non-destructive, uniquely named private
Debug attachments. Full File/physical rollback, retention and framework lifecycle
review remain adoption gates; observed rechecks are not atomic isolation.
See [DEBUG_ATTACHMENT_ACCESS.md](DEBUG_ATTACHMENT_ACCESS.md).
Increment 72 removes invoice reload from both Debug menus, uses one shared
saved/active-form runner, and returns normal READ-authorized private attachment
metadata from the same creation request. A sidebar-only update preserves edits;
missing metadata/refresh faults require manual review, never automatic generation.
Concurrent clicks share only the pending form request, not durable idempotency.
See [DEBUG_UI_LIFECYCLE.md](DEBUG_UI_LIFECYCLE.md). Actual browser/File/custom-hook
and installed v15/v16 lifecycle rehearsal remains a separately approved gate.
See [POS_DEBUG_LOCAL_ROUTING.md](POS_DEBUG_LOCAL_ROUTING.md).
See [MESSAGE_PRESENTATION.md](MESSAGE_PRESENTATION.md).
Increment 73 removes raw Compliance success responses from popup/API return and
uses canonical auth-free success metadata for both CSID purposes; wizard fields
display translated read-only outcomes. Error/log redaction, general CSID access,
storage/rotation and existing form save/reload remain independent gates. This is
not remote Compliance completion or credential lifecycle adoption. See
[CSID_SUCCESS_PRESENTATION.md](CSID_SUCCESS_PRESENTATION.md).
Increment 74 adds purpose-bound allowlisted HTTP-failure diagnostics and one
localized CSID error instead of raw-body/repeated throws. It removes the old
all-400-means-OTP assumption. Transport/local/200-processing failures and complete
framework log/snapshot/custody/access/lifecycle controls remain gates. See
[CSID_HTTP_FAILURE_PRESENTATION.md](CSID_HTTP_FAILURE_PRESENTATION.md).
Increment 75 adds an internal transport/local-stage boundary with request-local
child muting and best-effort progress cleanup. Raw local exceptions are no longer
the public result; partial save/commit/output and unknown outcomes require review,
not retry or rollback. Client save/reload, ignored-permission writers, protected
receipts and full framework log/snapshot/access/lifecycle remain gates. See
[CSID_LOCAL_OUTCOMES.md](CSID_LOCAL_OUTCOMES.md).
Increment 76 replaces automatic CSID pre/post-save/reload with explicit clean
saved-form input and shared in-memory pending/review guards. Device metadata
lookup is field-limited; the same server success popup includes review guidance.
Manual saves, CSR/configuration/other checks, source/access/epochs and full log
lifecycle remain gates. See [CSID_FORM_LIFECYCLE.md](CSID_FORM_LIFECYCLE.md).

Increment 77 extends shared pending/review and clean/active-source checks to both
CSR form buttons, with explicit private-key replacement consent and no automatic
save/reload or raw device console dumps. CSR replies require review, not issuance
success. Server key writes/rotation/access/logs and configuration draft staging
remain separate gates. See [CSR_FORM_LIFECYCLE.md](CSR_FORM_LIFECYCLE.md).

Increment 78 replaces Company configuration's automatic full save with one-field
unsaved draft staging. New exact saved-name/revision preparation checks READ and
WRITE through the shared ACL compatibility helper, bounds values and shares the
legacy text builder. It participates in credential pending/review policy without
becoming a credential attempt. Legacy API, server key rotation/access, device
single check and installed/whole-lifecycle gates remain. See
[CSR_CONFIGURATION_DRAFT.md](CSR_CONFIGURATION_DRAFT.md).

Increment 79 adopts one saved-device single Compliance facade with exact source
READ checks, device comparison revision and cross-Company refusal. It replaces
full Company reads/full device RPC payloads/automatic saves with a shared guarded
one-request summary runner. Pure comparison validation and form snapshot policy
are reused. Legacy generator/technical details, source/credential concurrency,
durable attempt custody/duplicate prevention and full installed lifecycle remain
gates. See [DEVICE_SINGLE_COMPLIANCE.md](DEVICE_SINGLE_COMPLIANCE.md).

Increment 80 coordinates all three Company check buttons with credential/config
pending/review and saved-form policy. One exact saved-Company/revision/mode
facade checks normal source READ and invoice ownership before existing workflow
delegation. Automatic consent distinguishes Compliance sending from local preview;
automatic mode needs no sample. Legacy direct APIs, source/credential concurrency,
related dependencies/ACL/log custody and installed acceptance remain gates. See
[COMPANY_COMPLIANCE_FORMS.md](COMPANY_COMPLIANCE_FORMS.md).

Increment 81 adds exact saved-source READ+WRITE authorization to the selected
CSR/key/CSID writers, READ-only linked Company dependency, source/abbreviation
binding and ordinary saves. CSR reads authorized saved configuration and rechecks
final access; late key/save/HTTP partial effects are not retried or speculatively
undone. Field custody, epochs/rotation, remaining cache/direct writers, broad CSR
error/log lifecycle and installed acceptance remain gates. See
[CREDENTIAL_WRITER_ACCESS.md](CREDENTIAL_WRITER_ACCESS.md).

Increment 82 gives the local key/CSR paths one stage-aware failure boundary,
with display-only translation and no raw crypto/ORM exception projection. Late
source/save failure explicitly requires partial-key review without retry/restore.
Legacy return shapes and algorithms remain; active-bundle preservation/rotation,
epochs/concurrency, full framework diagnostic custody and installed v15/v16
acceptance remain gates. See [CSR_LOCAL_OUTCOMES.md](CSR_LOCAL_OUTCOMES.md).

Increment 83 blocks shared key/CSR replacement when any saved certificate/auth/
onboarding-reference data is present or its state is unverifiable. Pre-issuance
returns/algorithms remain; no force, clearing, expiry or environment bypass is
added. Translated consent reflects the restriction. This is an observed local
presence guard, not a locked credential epoch or a staged renewal workflow;
CSID/other writers and explicit safe activation remain gates. See
[CSR_KEY_PRESERVATION.md](CSR_KEY_PRESERVATION.md).

Increment 84 protects observed saved Final auth against both CSID writers, using
a shared pure bounded presence core also adopted by the CSR guard. Recheck visible
changes before transport and response assignment; preserve late review plus any
cleanup notice in one popup. Initial issuance stays, including its characterized
shared-certificate/device-alias defects. Certificate-only unknown state, source/
credential epochs and actual staged renewal/activation remain gates; empty Final
auth is not authority to renew. See [CSID_PRESERVATION.md](CSID_PRESERVATION.md).

Increment 85 extracts shared ordered CSR construction and adds an internal
non-writing key/CSR draft. Strict new context/config/attribute preflight precedes
generation; canonical key/CSR checks and metadata do not authorize use. Existing
buttons stay guarded legacy operations, not switched to drafts. Protected pending
custody, permissions/source/epoch/issuance/activation and installed v15/v16 remain
gates; initial certificate/alias defects are not hidden. See
[CSR_DRAFT_PREPARATION.md](CSR_DRAFT_PREPARATION.md).

Increment 86 supplies separate encrypted pending-draft envelope/repository
primitives, not an installed permissioned service or runtime adoption. Caller-owned
transactions accept only exact redelivery and never replace material. The declared
manifest is not verified source/epoch evidence, and scoped SQL nonce uniqueness
does not replace independent protected keys and audited nonce/rotation policy.
Next implement saved-source/ACL/epoch-bound custody access before issuance/receipt/
activation wiring; initial certificate/alias defects remain. See
[PENDING_CSR_CUSTODY.md](PENDING_CSR_CUSTODY.md).

Increment 87 adds permissioned metadata-only saved-source stage/inspect over
pending custody, not an installed button/provider or issuance flow. Exact target
WRITE/READ and related Company READ precede resources; source/ACL rechecks and
same-transaction source locks surround storage. Caller owns commit/rollback and
must discard a failed/reentrant/interrupted handle. Linked-device implicit Company
selection is refused, not guessed. Independent source/epoch/provider provenance,
protected key/transaction provisioning, issuance/receipt/activation and installed
v15/v16 remain gates. See [PENDING_CSR_ACCESS.md](PENDING_CSR_ACCESS.md).

Increment 88 adds an unactivated single-acquisition pending resource lease with
shared fixed Unix/peer/session checks and a distinct registration/key-ID domain.
Keys follow verified target selection; callers own all post-handoff transaction
decisions/cleanup. A marker/key ID is not vault, tenant, historical epoch or current
source/ACL-aware commit authority. Next bind exact retained drafts and trustworthy
source/credential epochs to transaction/issuance/receipt coordination before any
runtime adoption. See [PENDING_CSR_PROVIDER.md](PENDING_CSR_PROVIDER.md).

Increment 89 closes the masked-Password visible-state comparison gap in internal
pending staging. Require explicit schema/backing-state expectations and compare
bounded encrypted `__Auth` observations around repository work, without decryption,
repair or public digest export. This detects stored-byte drift, not a monotonic
authoritative credential epoch or source/ACL-aware commit. Historical binding
provisioning, after-return/commit coordination, all-writer integration and installed
v15/v16 remain gates. See [PENDING_CSR_PASSWORD_STATE.md](PENDING_CSR_PASSWORD_STATE.md).

Increment 90 adds an uninstalled owned pending-save coordinator, reusing existing
source/ACL/backing/repository policy and exclusively claiming a fresh concrete
lease. Exact final checks precede one commit/close; post-close visible checks gate
metadata, not already-committed history. Unknown outcomes/late denial never imply
success, undo or automatic retry. Existing caller-owned APIs remain unchanged.
Next provide historical binding provisioning and reviewed exact local outcome
reconciliation before issuance/receipt/activation or runtime integration. See
[PENDING_CSR_TRANSACTION.md](PENDING_CSR_TRANSACTION.md).

Increment 91 adds a read-only exact-original review on a separately supplied fresh
owned lease. It shares source/ACL/backing/binding policy, distinguishes authenticated
exact/absent/conflict observations from failures, rechecks before rollback/close,
and gates metadata on post-close visible checks. No automatic save/reseal/retry or
historical-access bypass is added. Historical binding provisioning and independent
source/key/epoch/tenant provenance still precede issuance/activation integration.
See [PENDING_CSR_REVIEW.md](PENDING_CSR_REVIEW.md).

Increment 92 adds immutable exact original-source declaration/envelope pair storage
in the existing caller-owned repository, with canonical bounded lookup and no
automatic legacy backfill/rebinding. New pairs require plain INSERTs; exact
existing pairs require no rewrite. Historical preservation is not source/ACL/
epoch attestation. Next review initial permissioned binding provisioning and
owned committed-lookup integration before issuance/activation; no runtime caller
is switched. See [PENDING_CSR_SOURCE_HISTORY.md](PENDING_CSR_SOURCE_HISTORY.md).

Increment 93 adds initial binding capture through the shared saved-source/normal
ACL/backing engine and optional owned single-commit pair save. No historical
lookup is invoked for NEW creation; existing identities are refused rather than
recaptured or retried. Same-transaction captured binding/envelope/source/backing
guards precede commit; post-close visible checks gate metadata, not committed
history. Existing APIs remain and no runtime caller/provider/schema is enabled.
Next review separately owned committed-pair lookup and provenance/epoch before
issuance/activation. See [PENDING_CSR_INITIAL_CAPTURE.md](PENDING_CSR_INITIAL_CAPTURE.md).

Increment 94 links initial capture to a separately owned read-only exact-original
pair review, using the same normal ACL/source/provider/backing/cleanup policy.
Only a complete exact pair adopts its stored original declaration; absent/half/
conflicting states observe no historical match and never manufacture one from
current settings. Corruption and SQL faults remain unconfirmed. Recheck before
rollback/close and visible access before disclosure; no runtime caller is enabled.
Next review protected draft intake and source/key/tenant/epoch provenance before
issuance/activation. See [PENDING_CSR_BOUND_REVIEW.md](PENDING_CSR_BOUND_REVIEW.md).

Increment 95 connects shared preparation/sealing to authorized NEW local pair
creation, with normal ACL/source/backing/unused-ID checks before generation and
mandatory protected encrypted-original retention acknowledgment before staging.
No old credential is selected/replaced. Exact original custody precedes later
guard/commit failure; acknowledgment is explicitly not durable attestation.
Existing owned cleanup and fresh read-only review handle unknown outcomes without
regeneration/retry. No runtime caller/provider/schema is enabled. Next review
durable custody and key/source/tenant/epoch provenance before issuance integration.
See [PENDING_CSR_PREPARATION.md](PENDING_CSR_PREPARATION.md).

| Mode | Intended output | Side-effect boundary to enforce |
| --- | --- | --- |
| Phase 1 | Local QR for supported Sales/POS documents | No Phase-2 API or production hash-chain mutation |
| Debug XML | Clearly labelled diagnostic artifact | No submission, status change, or live UUID/ICV/PIH allocation |
| Local onboarding preview | Six synthetic XML/signature/QR samples | No HTTP request or customer/invoice creation |
| Compliance | Selected real-document snapshot or six synthetic samples | Compliance endpoint and Compliance CSID of the selected environment; no live invoice status/chain mutation |
| Phase 2 simplified | Signed issued artifact and reporting workflow | Durable issuance identity, authoritative stored XML/QR, controlled retries |
| Phase 2 standard | Clearance workflow and returned cleared artifact | Do not present a debug/local artifact as a cleared invoice |

These are target contracts, not claims that all existing paths already satisfy
them. Compliance is an API purpose, not a synonym for Sandbox. Environment and
credential purpose must be resolved together; local success must never fabricate
remote compliance completion or replace ZATCA's final-CSID decision.

## Migration choice

| Approach | Benefit | Risk / decision |
| --- | --- | --- |
| Keep all parallel XML/signing implementations | Small immediate patches | Divergent fixes and settings; retain only as temporary adapters |
| Replace everything in one release | One final implementation immediately | Unacceptable regression radius across tenants and tax/accounting flows |
| Shared pure core with thin, version-aware adapters | Reusable contracts and staged comparisons | Chosen; retire a legacy path only after its replacement passes the same fixtures |

Do not create permanent v15 and v16 forks of the tax/signing logic. Use capability
checks in a small compatibility layer, not scattered version-string conditions.
Reuse `ksa_compliance/field_compat.py`, `zatca_runtime.py`, and the existing tax
adapters after testing their fallback behavior; do not introduce competing
resolvers. Existing accepted signed XML is immutable evidence, not a template to
be reserialized during cleanup.

## Ordered implementation gates

### 0. Recovery and source-control safety

- Inventory all affected sites and dependent apps; preserve dirty work if found.
- Back up SQL, public/private files, original encryption configuration, app Git
  history/source, and runtime versions before implementation.
- Verify checksums, archive integrity, and an isolated sample restore. Distinguish
  SQL/file recovery from a complete Frappe application restore.
- Compare actual Git trees before merging differently named/cherry-picked
  histories. Archive recoverable references; do not delete remote branches or
  force-push as a cleanup shortcut.
- Develop in an independent worktree. Keep data, certificates, and backups out
  of GitHub. Arrange an authorized off-host encrypted copy before rollout.

### 1. Contracts, outcome handling, and characterization

- **First increment:** reject ambiguous Compliance results, transport failures,
  and malformed HTTP 406 responses in both all-type buttons. Preserve explicit
  successful validation and distinguish previous completion.
- Inventory public Sales Invoice, POS Invoice, Sales Invoice with `is_pos`,
  single/all Compliance, synthetic onboarding, debug, and scheduler entry points.
- Add scrubbed golden fixtures and side-effect assertions for each route before
  moving signing or accounting code. Never commit a customer's private key.
- Preserve warnings and request IDs in diagnostics. Separate local preparation,
  remote validation, previous completion, rejection, and unknown transport state.

### 2. Settings, fields, and credential context

- Increment 19 implements isolated encrypted version staging, not active selection
  or field migration. See [CREDENTIAL_BUNDLE_STORAGE.md](CREDENTIAL_BUNDLE_STORAGE.md).
  Caller-supplied AES-GCM keys and explicit SQL contracts have private rehearsals;
  future protected key custody, tenant permissions, transactional source/remote flow
  evidence and controlled activation must be verified before adoption.
- Increment 18 adds independent legacy purpose/field observations and a versioned
  bundle migration proposal in [CREDENTIAL_LIFECYCLE.md](CREDENTIAL_LIFECYCLE.md).
  It characterizes shared key/certificate overwrites without changing writers or
  selecting credentials. Secure storage, atomic activation, saved provenance,
  secret-bearing response redaction and restored-site migration remain gates.
- Increment 17 adds a locally bound ephemeral signing/authentication material
  snapshot and internal read-only adapter, reusing saved-owner and alias policy.
  See [CREDENTIAL_SNAPSHOT.md](CREDENTIAL_SNAPSHOT.md). Exact certificate/key/token
  binding and explicit UTC validity are implemented; cross-row atomic provenance,
  durable epoch, taxpayer/environment/trust verification and runtime adoption
  remain gates. No existing path uses the new snapshot automatically.
- Build an effective-settings registry with field, scope, default, precedence,
  legacy alias, consumer, and migration policy. Distinguish missing, blank, and
  explicit zero; do not replace a valid zero with a legacy true value.
- Cover phase, environment, company/issuing unit/POS machine, linked-company
  credentials, submission policy, B2C/B2B, branch identity/address, tax source,
  discounts, advance-payment markers, printing, and background windows.
- Resolve endpoint + credential purpose + credential version as one context.
  Check taxpayer/issuing-unit identity, expiry, and key/certificate pairing.
  Do not overwrite production credentials while preparing new onboarding ones.
- Audit `custom_certificate` versus `custom_certficate`, aliased B2C/advance
  flags, misleading background-display switches, and ineffective discount flags.
- Document each fallback; report conflicting settings instead of silently
  selecting an unrelated company/certificate. Preserve user-owned custom fields.

### 3. Amounts, advance invoices, and ERP adapters

- Increment193 adds the read-only connected advance/settlement arithmetic
  inspection. Earlier tax/discount/FX derivation, original advance eligibility,
  allocation and GL/VAT/XML reconciliation remain open integration gates.
- Normalize document data once using Decimal amounts and explicit currency
  precision. Keep exchange-rate precision separate from two-decimal amounts.
- Reconcile row discounts, document discounts, inclusive/exclusive tax, rounding,
  charges, and grand-total discounts against ERPNext's actual accounting totals.
- Support advance invoice type 386 and final-invoice deductions with original
  issue identity/time, reference UUID/number, and tax-category/rate snapshots.
- Do not infer a tax rate from rounded tax/taxable values: 0.13 / 0.87 is not
  evidence of a 14.94% tax rate. Group advance references by actual category/rate.
- Test partial/multiple advances, final invoices, cancellations, partial/cumulative
  returns, concurrent allocation, and currency/rounding residuals. VAT report,
  XML prepaid/reference amounts, GL, and outstanding receivables must reconcile.
- Resolve the reviewed risks in rounded allocation, forced Paid status, tax
  account filtering, and duplicate VAT reporting with failing tests first.
- Missing required advance schema must fail clearly; it must not silently
  produce zero deductions. Preserve legacy records until migration is approved.

### 4. XML, cryptography, and QR core

- Increment 67 extends [existing-XML reported-label writer boundaries](EXISTING_XML_REPORTED_WRITES.md).
  Eight duplicate reported-write blocks share one named adapter, while pinned-owner
  PIH/notification, response persistence, lazy success-log payload and legacy trailing
  error logging run through received-step guards. Original order/commits/409 labels
  remain; known faults add no generic post-fault persistence, not atomicity or custody.
  Other generated writers, whole-worker lifecycle and scoped log access remain gates.
- Increment 66 unifies fourteen [existing-XML rejection persistence blocks](REJECTION_PERSISTENCE.md)
  behind one named writer through the received-step guard. It preserves explicit
  UUID commit/assignment policy, including Sales simplified 404 versus POS 404.
  Known local load/text/save/commit failures cannot add generic error persistence;
  prior UUID/hook/parent commits are not undone. Success/remaining-writer faults,
  exact custody, whole-worker lifecycle and scoped log access remain gates.
- Increment 65 extends [received local-step review](RESPONSE_PROCESSING.md) to the
  four existing-XML Sales/POS Reporting APIs and preserves that signal through
  their broad public wrappers. Hide/event/presentation failures no longer add
  generic error persistence; POS raw text and Sales formatting remain unchanged.
  Normal rejection/duplicate/owner/commit policy and original artifacts stay as-is.
  Selected persistence/PIH/remaining-writer faults, worker lifecycle, exact custody
  and scoped log read/export/retention remain unfinished; no live wiring/deployment.
- Increment 64 pins the caller's diagnostic database owner/raw identity before
  metadata loading and rechecks it around source callbacks and insertion. It
  resolves a context-local proxy to its current owner; observed drift/unavailable
  contexts fail with translated review and no parent cleanup/reconnect. This is
  boundary detection, not transaction identity, hook isolation or runtime adoption.
  Same-handle commits, ABA changes, source-neutral worker lifecycle and scoped
  log read/export/retention remain gates. See [EVENT_LOG_TRANSACTION.md](EVENT_LOG_TRANSACTION.md).
- Increment 63 adds [owned-session bounded lock waits](PRIMARY_RECEIPT_PROVIDER.md)
  to the optional Unix provider only: fixed SESSION row/metadata waits, verified
  before registration locks and every cursor/commit, rejecting drift without
  repair/reconnect or GLOBAL changes. Actual private source/registration locks
  demonstrate failure/owned cleanup without changing parent work or originals.
  Source-neutral diagnostic transaction isolation, arbitrary factory policy and
  Company/source-scoped log read/export/retention remain unfinished gates.
- Increment 62 adds [saved-source diagnostic access and fresh drift checks](EVENT_LOG_TRANSACTION.md).
  Source WRITE/related READ plus Event Log CREATE precede keys/owned SQL. Exact
  request/envelope binding and fresh source-only owned reads bracket insertion;
  late changes deny metadata without claiming rollback of possible hook writes.
  Public failure is a static translated RuntimeError review, not a generic invoice
  rejection. No endpoint/worker/HTTP caller is activated. Source-neutral parent,
  bounded lock waits, full race/ACL/provenance and installed lifecycle remain gates.
- Increment 61 adds an [original-pair-bound diagnostic bridge](EVENT_LOG_TRANSACTION.md).
  It authenticates the exact original envelope, invokes read-only matching-pair
  inspection and closes owned SQL before caller-owned diagnostic hooks. Only
  archived candidate/event data is used; missing/partial/conflict/uncertain or
  undecodable originals remain review-only. No pair persistence/repair/reseal,
  replay/acceptance authority or live invoice wiring is added. Finish authorized
  source/ACL/race/provenance and whole-worker/parent integration before adoption.
- Increment 60 adds [diagnostic source schema and staged preflight](EVENT_LOG_TRANSACTION.md).
  A read-only Diagnostic Status Data field is defined in DEVELOPMENT DocType
  source with Arabic labels; no site migration/backfill/collision repair occurs.
  Staging checks ordinary table/unique fields/types/storage/widths before insert,
  failing with static translated review. The legacy wrapper is not gated/rewired.
  Physical schema, custom-field/Property Setter collisions and exact receipt/
  parent lifecycle remain adoption gates; no submission staging caller is added.
- Increment 59 adds [explicit diagnostic event staging](EVENT_LOG_TRANSACTION.md):
  normal permissions, no explicit commit/rollback/fallback/retry, same-object
  exception propagation and a closed INSERT_RETURNED result, not durability or
  acceptance. The legacy wrapper keeps its transaction/fallback/None contract;
  no submission caller is switched. Source schema status-field coverage and
  actual hook/parent/custody lifecycle remain gates before staging adoption.
- Increment 58 adds [selected rejection-persistence isolation](REJECTION_PERSISTENCE.md)
  in the four primary Sales/POS APIs. Three named adapters replace twelve
  repeated blocks, preserving normal rejection/UUID/commit policy. Known local
  loading/writing/text/commit faults cannot add generic failure writes or retry;
  previous partial commits are not undone. Next design the event logger's honest
  caller-owned result/transaction contract together with exact durable custody,
  intentional rejection and parent lifecycle, not blanket commit deletion.
- Increment 57 adds [received presentation/logging-step isolation](RESPONSE_PROCESSING.md)
  to the four primary Sales/POS APIs for ALL statuses. Formatting (including lazy
  text), event log and hide callbacks use the existing static translated local
  review signal on formerly caught errors, never generic post-fault writes or
  retry. Deliberate HTTP-rejection throws/normal writer policy remain unchanged.
  Next audit rejection-persistence/caller boundaries plus the actual event logger's
  swallowed failures/own commits, and plan intentional
  rejection mapping, durable custody and parent transaction lifecycle together;
  no working source or authority action is authorized by this development change.
- Increment 56 adds [writer/late-response evidence and pure outcome review](PRIMARY_WRITERS_AND_REVIEW.md).
  Current mutable runtime writers are distinct from staged single/pair stores.
  Actual independent private writers reproduce partial windows; original sealed
  sequence-2 responses cannot be rewritten after UNKNOWN, and independent late
  sequence-3 observations are not the strict START-only pair contract. Review
  binds exact protected input, returns states only and never authorizes actions.
  Next isolate local rejection/error-status logging failures in the four primary
  source APIs before broader parent-commit/custody integration; no runtime wiring.
- Increment 55 adds [permissioned local primary pair access](PRIMARY_RECONCILIATION_ACCESS.md).
  Shared saved invoice WRITE/related READ and exact original request/envelope
  declarations precede scoped keys/owned SQL. Source locks and final ACL checks
  bound metadata-only inspection/LOCAL persistence; partial/conflict policy stays
  review-only. Full seal fingerprinting does not change XML signatures. No
  runtime caller or provider/key installation; independent provenance and legacy
  separate-writer/lost-response review remain gates before integration.
- Increment 54 adds [exact local primary receipt pair reconciliation](PRIMARY_RECEIPT_RECONCILIATION.md).
  Read-only inspection or explicit LOCAL persistence requires the original seal,
  exact existing hold/request binding and literal source guards. Both absent
  response parts may be stored atomically; partial/different pairs are REVIEW
  ONLY. Uncertainty retains original input, never invokes transport/reseal or
  releases a hold. Permissioned paired access and authentic provenance remain
  gates; no runtime caller or schema is installed.
- Increment 53 adds a [saved-source local primary capture access boundary](PRIMARY_CAPTURE_ACCESS.md).
  Invoice WRITE/related READ and exact request/start/key binding precede resources
  and guarded owned SQL. EVERY returned core result goes to explicit trusted
  server custody before final ACL disclosure; output is metadata only. Failed or
  interrupted handoff transfers protected recovery, not an automatic retry.
  ACK is not durable proof. Paired reconciliation, pre-result observer custody,
  authentic source/epoch/provider/transport and runtime activation remain gates.
- Increment 52 adds an [auth-free exact primary observation coordinator](PRIMARY_CAPTURE.md).
  Three owned transactions bind deterministic request bytes to strict start/hold,
  close preflight before ONE synthetic observer, then store original encrypted
  custody and HTTP event atomically. No actual HTTP/auth adapter or runtime caller.
  Unknown results retain exact protected material without retry/reseal/release.
- Increment 51 adds an [atomic primary start/logical-invoice hold](PRIMARY_ATTEMPT_HOLD.md).
  One caller transaction appends an explicit first event and strictly reserves
  the same logical source across changed candidate/version/chain/environment.
  Existing/uncertain reservations never authorize reuse; no status/clock-based
  release. Test-only SQL, no runtime sender/permissioned coordinator activation.
- Increment 50 adds [permissioned encrypted local receipt custody](PRIMARY_RECEIPT_CUSTODY_ACCESS.md).
  Shared source/owned-acquisition helpers require invoice WRITE/related READ and
  exact receipt/key declarations before scoped keys/SQL. Stage retains the same
  envelope across uncertain commits; retrieval returns ciphertext only after
  rollback/close and final ACL. No runtime capture/hold/provider activation.
- Increment 49 adds [encrypted local retained-receipt custody](PRIMARY_RECEIPT_CUSTODY.md).
  Exact bounded codec/dedicated AES-GCM and immutable caller-transaction SQL keep
  one envelope for an existing attempt; identical LOCAL redelivery only. No
  journal append, HTTP, owned coordinator or permissioned retrieval is activated.
  Committed ciphertext survives owned-database crash tests; responses lost before
  the first durable commit still need a no-replay review/lost-response policy.
- Increment 48 adds an [explicit pinned Unix receipt connection provider](PRIMARY_RECEIPT_PROVIDER.md).
  Scope/socket checks precede typed local credentials; fresh direct SQL checks
  kernel peer, target/session and locked site/namespace marker before handoff,
  cursors and commit. No reconnect/fallback/discovery/runtime provisioning.
  Synthetic composition only: provisioning/custody/receipt authenticity, durable
  holds and exact transport-source-epoch binding remain gates before activation.
- Increment 47 adds [saved-source access to local primary receipt persistence](PRIMARY_RECEIPT_ACCESS.md).
  Shared archive selection retains existing metadata behavior; private receipt
  access requires invoice WRITE/related READ and exact attempt/event/predecessor
  binding, with same-transaction source locks and post-close rechecks. No runtime
  provider/scheduler activation, authentic epoch/origin claim or durable retry hold.
- Increment 46 adds [exact local primary receipt persistence/redelivery](PRIMARY_RECEIPT_PERSISTENCE.md).
  Existing journal/codecs/owned transactions preserve one exact retained response,
  including uncertain commits, without start creation, new HTTP or replay rights.
  It is not wired to primary APIs/scheduler; permissioned saved-source/attempt/
  epoch/provider binding, owned acquisition and durable review holds remain gates.
- Increment 45 adds [primary post-response local-error review](RESPONSE_PROCESSING.md).
  Previously caught local failures in existing response branches no longer run
  generic receipt overwrite/503 writes/commits. Static Arabic/English failure
  is not acceptance or a success return; no in-call retry. Exact durable receipt/
  review holds, partial parent commits and other adapters remain release gates.
- Increment 44 adds [scoped primary QR ownership/pre-request rejection](PRIMARY_QR_OWNERSHIP.md).
  Same-invoice bounded preservation/review replaces the primary attach global
  URL check. All four primary adapters reject existing schema/link issues before
  request/error persistence and POS XML writes; valid batch deferral remains.
  No authenticated source/ACL/reservation claim; receipt-aware post-response
  error handling, concurrent changes and remaining writers are still gates.
- Increment 43 removes [primary Sales/POS QR attachment DDL/invoice events](PRIMARY_QR_TRANSACTION.md).
  QR-link-only staging preserves status/UUID/business/modified fields. Legacy
  global URL reuse and caller commits/error downgrades are explicitly unresolved;
  pre-request setup checks and receipt-aware caller handling remain release gates.
  No authenticated source/recovery or working-system change is enabled.
- Increment 42 replaces [the automatic Phase-2 completion hook](PHASE2_ARTIFACT_PRESERVATION.md)
  with non-destructive metadata preservation/review. No response-based repair,
  filename cleanup, link/status change or parent transaction ownership remains
  there. Missing completion stays gated; primary attach helpers/extractor/schema/
  global URL and caller commits still need integration. Normal adapters unchanged.
- Increment 41 adds [permissioned QR source metadata/shared archive access](QR_SOURCE_ACCESS.md).
  Saved ACL/owner/source/route and exact SQL/journal observations are checked,
  without raw export or recovery activation. Advance metadata uses the same
  engine with unchanged marker/type restrictions; settlement selection/amounts
  remain untouched. Audited provider/epoch/authentic-origin/crypto gates remain.
- Increment 40 adds [exact archived-attempt QR source observations](QR_SOURCE_SELECTION.md).
  Reporting request versus clearance-returned bytes are bound to the exact
  declared journal/context/identity with lexical clock and strict bounded QR
  extraction. This is not authenticated provenance or permission to recover.
  Bind a saved-source/owner/epoch/committed-record provider and crypto validation
  before mutation; audited Phase-2 prefix deletion/reuse remains unsafe/unmodified.
- Increment 39 adds [non-destructive explicit recovery preservation/review](QR_RECOVERY_PRESERVATION.md).
  No filename/latest reconstruction, content IO, automatic re-link or commits at
  the button. Missing originals require review; trusted original-artifact recovery
  still needs implementation before re-enabling mutations. Ordinary generation
  and accounting/advance eligibility are unchanged. Audit other writers next.
- Increment 38 adds [saved-row access for explicit QR recovery](QR_REGENERATION_ACCESS.md):
  Invoice/Company/File ACL and exact ownership, bounded projection and POST-only
  mutation. Access is not provenance; increment 39 separately removes heuristic
  repair and helper commits. Installed source/ACL/File races remain gates.
- Increment 37 extends [non-destructive QR preservation to the advance print hook](ADVANCE_QR_PRESERVATION.md).
  No forced replacement or implicit final-invoice attachment cleanup; first
  generation and accounting selection/amounts remain unchanged. Explicit
  regeneration authorization/selection/commits and installed lifecycle remain gates.
- Increment 36 adds [non-destructive ordinary QR attachment preservation](QR_ATTACHMENT_PRESERVATION.md)
  for Sales/POS, replacing newest-file cleanup/global URL fallback with current
  same-invoice link preservation or explicit review. The advance print cleanup/
  force gate is addressed separately in increment 37; regeneration access/
  selection/commits and other writers remain gates.
- Increment 35 introduces [caller-owned Phase-1 QR metadata staging](PHASE1_QR_TRANSACTION.md):
  no recursive invoice save, explicit commit or schema creation in the ordinary
  generator. Next bound attachment selection/deletion and caller commit policy;
  actual File rollback, hook customizations and installed v15/v16 remain gates.
- Increment 34 adds [five-tag QR/missing-original review policy](ADVANCE_SOURCE_GAP.md)
  without changing accounting eligibility or inventing historical references.
  Audit ordinary QR attachment cleanup, explicit commit/re-entrant document saves
  and transaction ownership next. Mixed-phase bridging and actual source recovery
  still require permissioned provenance, official rule/SDK and accounting evidence.
- Increment 33 adds [permissioned metadata-only advance archive inspection](ADVANCE_SOURCE_ACCESS.md)
  with saved source/owner ACL, owned source/journal row locks and cleanup. Audited
  provider provenance, authenticated capture, missing-original policy and backend
  source export remain gates; it is not a builder replacement or acceptance grant.
- Increment 32 adds [exact archived-attempt advance source choice](ADVANCE_SOURCE_SELECTION.md):
  Reporting request versus Clearance returned bytes, pinned context/revision and
  original clock consistency. This is a pure observation, not verified source
  selection. Add a permissioned saved-source/committed-record storage boundary
  and authenticated capture evidence before adopting it in runtime settlement.
- Increment 31 adds [read-only original advance reference observations](ADVANCE_REFERENCE.md)
  and characterizes three current assembly paths. Implement permissioned immutable
  original-artifact/acceptance selection and Phase-1/legacy missing-source policy
  before adopting it. Preserve original date/time/UUID; do not apply today's
  timezone to historical references or silently invent midnight. This is not
  advance amount/GL consolidation or cryptographic proof.
- Increment 30 adds the [explicit shared issue-time contract](ISSUE_TIMESTAMP.md)
  for Sales/POS XML, ordinary/advance Phase-1 QR, Phase-2 Tag 3 and synthetic
  samples, without changing signatures or amount formulas. Capture verified
  timezone/settings epochs and audit advance settlement reference time/UUID
  bindings before extending it. Existing Frappe timezone defaults and offsetless
  legacy XML are characterized, not authoritative historical timezone evidence.
- Consolidate XML assembly only after golden comparisons for each invoice type.
- Canonicalize/hash the exact intended bytes. Test namespace context, encoding
  declarations, signature transforms, certificate digest, SignedProperties
  digest, signature verification, and final QR values independently.
- Freeze signed bytes: no cosmetic XML/whitespace rewrite after hashing/signing.
- Separate Phase-1 QR payload from Phase-2 signing requirements. Use accepted
  returned artifacts where appropriate; never select a debug attachment as live
  output. Validate QR totals for advance/rounding cases against official examples
  and SDK results before deciding the canonical source field.
- Make both Create XML for Debug actions consume the same core without allocating
  live counters or committing invoice changes.

### 5. Orchestration, persistence, and retry safety

- Increment 28 adds explicit local receipt persistence recovery only: authenticate
  retained start/receipt, require the exact committed start ciphertext, and
  append the identical receipt in one owned transaction without HTTP or resealing.
  See [COMPLIANCE_RECEIPT_RECOVERY.md](COMPLIANCE_RECEIPT_RECOVERY.md). Increment 29
  adds a [permissioned internal saved-source boundary](COMPLIANCE_RECEIPT_RECOVERY_ACCESS.md),
  sharing capture's owner/ACL/revision policy. Audited tenant/key/owned-connection
  origin, durable retained-receipt custody, lost/late-response policy and
  cross-attempt coordination remain gates; no runtime adoption exists.
- Keep encrypted credential staging separate from the artifact journal. There is
  no active-pointer/dispatch API in increment 19, and exact version reads cannot
  choose latest or fall back across environment/purpose/owner. Approval of staging
  storage is not authorization to activate credentials, migrate or replay invoices.
- Pass the ephemeral credential snapshot through a future preparation/request
  service only after transactional provenance and epoch policy are verified.
  Do not serialize its secrets into the journal, a worker job, or diagnostics.
- Increment 16 adds exact-byte storage codecs and an explicit-connection MariaDB
  repository, rehearsed with real commits/concurrency/crash recovery on its own
  private server. See [JOURNAL_REPOSITORY.md](JOURNAL_REPOSITORY.md). No schema or
  service is installed in Frappe, and no tenant database is accessed. Production
  storage permissions/encryption, migration, outbox/leases and chain allocation
  remain gates; SQL serialization is not authorization to resend an invoice.
- Increment 15 implements the pure receipt/operation/returned-XML consistency
  assessment, not authoritative receipt capture or live acceptance writes. See
  [RESPONSE_ASSESSMENT.md](RESPONSE_ASSESSMENT.md). Genuine expected 200 is success
  and 202 success with warnings; malformed/wrong-invoice observations and generic
  409 cannot authorize acceptance. Metadata matching is not crypto/accounting proof.
- Pass compliance type explicitly instead of temporarily mutating Company.
- Ensure Compliance/Debug do not overwrite a real invoice's UUID or ICV fields.
- Use durable, auditable artifact state; serialize allocation within each issuing
  unit/environment and make accepted status/PIH updates idempotent.
- Define retry behavior for unknown transport outcome versus corrected rejected
  documents. Never issue a fresh identity casually on a network retry.
- Audit scheduler company isolation, submission windows, overdue backlog, POS
  identity regeneration, hooks, and duplicate concurrent requests.
- Remove transaction commits from document hooks through service boundaries,
  not by bypassing Frappe's transaction protections.

### 6. ERPNext 15/16 compatibility and release acceptance

- Pin exact Frappe/ERPNext and dependent-app revisions for two isolated benches.
  Do not upgrade the production bench to test compatibility.
- Use the guarded offline runner during development. A full fictional-Company
  application rehearsal starts only AFTER development completion and separate
  approval for an isolated bench. Do not substitute a working client's extra
  Company or enable real CSID/Compliance calls as a test shortcut.
- The current official v16 guide requires Python 3.14+ and Node.js 24+ and
  disallows commits in document hooks. Test transaction behavior, ordering,
  permissions, translations, navigation, and DocType extension integration.
  [Frappe migration guide](https://github.com/frappe/frappe/wiki/Migrating-to-version-16)
- Test legacy item-wise tax JSON, v16 child rows, and unsaved calculated rows,
  including genuine zero tax. Avoid unconditional 15% fallbacks.
  [ERPNext tax-data migration](https://github.com/frappe/erpnext/wiki/Item-Wise-Tax-Details:-JSON-%E2%86%92-Child-Table)
- Resolve dependency constraints against the pinned branches, especially
  cryptography/lxml/pikepdf and supported wheels. Do not claim support from a
  `requires-python` change or pure unit tests alone.
- Validate fresh installation and v15-to-v16 migration, preserved customizations,
  reports, hooks, Sales/POS accounting, and English/Arabic buttons.
- Use official XML/security specifications and pinned SDK fixtures as acceptance
  evidence. Community examples are supplementary, not authority to ignore a
  mandatory rule. Record each source/revision and rule ID with its test.
  [ZATCA XML standard](https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/20230519_ZATCA_Electronic_Invoice_XML_Implementation_Standard_%20vF.pdf)
- After completed development AND isolated fictional-Company acceptance, obtain
  explicit approval for a named active-client pilot after backup/restore review,
  then another gradual rollout decision. Current authority sending remains banned
  unless explicitly changed; deployment cannot activate a prohibited send.
  A code rollback must preserve issued artifacts
  and reconcile current counters; restoring an old database blindly is unsafe.

## Minimum acceptance matrix

The user decides whether to adopt ALL changes or cancel them only after finished
development and separately approved isolated fictional-client rehearsal. Preserve
the untouched working baseline and tested-commit evidence. Adoption is not an
implicit deployment, worker restart or authority-send authorization. See
[DUMMY_REHEARSAL_DECISION.md](DUMMY_REHEARSAL_DECISION.md).

| Dimension | Required cases |
| --- | --- |
| ERP/runtime | v15 and v16 pinned benches; fresh install and upgrade |
| Source | Sales Invoice; Sales Invoice `is_pos`; POS Invoice; synthetic samples |
| Phase/type | Phase 1/2; standard/simplified invoices, credit and debit notes |
| Purpose | Debug; local preview; single/all/synthetic compliance; clearance; reporting |
| Settings | Company/POS/linked-company credentials; aliases/zero/missing; both UI languages |
| Amounts | Discount models; inclusive/exclusive; tax categories; rounding; foreign currency |
| Advance | Type 386; partial/multiple allocations; returns; GL/outstanding/VAT reconciliation |
| Failure/retry | 400/401/403/406/500; timeout; invalid body; duplicate and concurrent requests |
| Invariants | No real invoice/chain mutation in tests; immutable accepted XML; no credential leaks |

No successful mock test substitutes for v16 application/SDK checks or genuine
remote acceptance evidence. Remote acceptance remains UNVERIFIED while the user
prohibits requests. Do not perform it now, label mocks as authority PASS, or use
pilot/deployment approval as API-send authorization. If the user later explicitly
changes the ban, a separate reviewed scope/environment/purpose gate is required.
