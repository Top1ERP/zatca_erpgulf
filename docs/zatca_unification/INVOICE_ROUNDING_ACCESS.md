# Permissioned invoice rounding inspection — increment133, 2026-11-01

## Purpose and fixed entry point

`SavedCalculationDefaultsService.capture_invoice_rounding_context(invoice_name,
erp_major=..., doctype=...)` returns `SavedInvoiceRoundingContext` on the SAME
owned context/defaults/financial transaction. This is staged inspection, not an
active invoice/global rounding selector, amount calculation or build/submission
authorization. It accepts the existing actor/role policy, Sales/POS Invoice,
declared15/16 and site defaults only; other capture APIs retain their contracts.

The sole new server dependency is
`invoice_rounding_metadata_reader(scope, (invoice_doctype,))`, returning exactly
one `INVOICE_ROUNDING_PROFILE` applied metadata object. No request chooses a
field/profile, supplies a document/cache or selects a connection. No adapter,
whitelist, hook, frontend, schema or runtime caller is installed.

Known callers are the two new `test_calculation_invoice_rounding_access` suites
in the offline manifest. Native controls reuse [INVOICE_ROUNDING_SOURCE.md](INVOICE_ROUNDING_SOURCE.md).
Runtime promotion requires the integration gates below; remove the stage if it
is not adopted into the final owned preparation path.

## Reused full financial graph READ

The result includes financial data, so authorizing only the four rounding fields
would be insufficient. `FinancialGraphAccess` extracts the existing ordinary
parent/table/row/field READ and metadata-membership checks from ChildAcquisition.
ChildAcquisition retains its public constructor, link profile, optional selected
field work and native currency-link acquisition. The new root operation reuses
the graph access without calling a child metadata provider or child-link SQL.

Require normal saved invoice/Company READ, each returned financial table and
row READ, and field-level READ BEFORE metadata/default/cache/factory callbacks.
Empty tables still require their normal table permission probe. The common graph
retains its existing saved-row/link observation and permission projection; these
rows are access evidence, not a new native child currency resolution/proof.
Parent service ownership, cleanup and message aggregation remain shared.

For the four selected controls, also require ordinary field READ and capture
permission levels plus the complete selected applied definitions with the shared
metadata projector. This includes the additional is_consolidated field omitted
from financial/v1. Bind normal metadata identity to the invoice DocType and match
the new applied metadata callback to that exact initial definition snapshot.
Check overlapping definitions against the financial metadata before native SQL.

## Initial and fresh saved-document getters

Retain the initial authorized invoice object as the Check getter source. Pin its
minimal saved owner/revision/status projection and compare both that object and
fresh normal access rechecks through cleanup. Fetching an equal fresh document
must not hide a changed getter on the original authorized object.

The fixed getters are is_consolidated and disable_rounded_total. Present Check
fields require canonical normalized int0/1; absent definitions require getter
None. Do not coerce None/bool/text/float values into an expected Check or repair
an unexpected in-memory attribute. A native stored NULL Check still normalizes
to int0, separately from its original raw tag. This differs from interpreting
the old financial snapshot's omission as a consolidation decision.

Never read normal rounded_total/rounding_adjustment money getters, recalculate
amounts, warm precision/currency caches or convert Decimal money to float. Raw
amounts remain in the existing native financial graph. Capturing permission to
read an amount does not establish equivalence with a normal ERP amount/cache.

## Shared native and cleanup sequence

1. Authorize the saved financial graph and selected control fields; pin original
   normal definitions, permission levels, owner/revision and Check getters.
2. Obtain narrow applied control metadata, then existing financial metadata.
   Recheck ordinary source access after every trusted callback boundary.
3. Use one fresh owned connection with initial rollback. Read existing context,
   native financial graph and bound optional controls on that SAME handle.
4. Compare exact native-derived Check projections to the original/fresh getters;
   read the existing scoped defaults and compare their configured API projection.
5. Complete all trusted metadata/cache callbacks BEFORE final native checks of
   EVERY source. Recheck raw financial/child/metadata/optional-column controls and
   ordinary actor/source/field access, then build the protected partial result.
6. Perform shared rollback/close, recheck original/fresh getters and all normal
   access, then disclose. Reject late mutation/access loss without source writes.

The operation does not acquire unused Global Defaults, System rounding method,
locale, Currency or own-child currency-link evidence. It never commits, refreshes
a cache, fixes a field, retries a request, changes a source or contacts an authority.
Ambient pending work is preserved; pending work on a fresh owned handle is
discarded by its initial rollback. Normal/native observations are not an atomic
freeze or a promise of freshness after disclosure. Trusted runtime/provider
origin and callbacks still require audit; this is not a Python sandbox.

Failures reuse one existing translated financial summary and preserve parent
messages/flags; internal codes remain static English. Interrupt priority and
cleanup are retained. Saved result repr is protected, pickle is refused and
reconstruction binds the financial parent, native controls, graph membership and
exact normalized Check tuple. No complete ERP or preparation fingerprint is claimed.

## Closing gates

The additional source/normal READ/getter binding is implemented for this optional
inspection. Active consumed-dependency selection still requires the guarded
controller policy plus amount/ORM/cache provenance and actual invoice Currency
fraction/method sources. Do not always apply global settings, infer consolidation
from is_pos, or replace a saved invoice Check with a normal document default.

Complete financial/tax/advance/FX/GL/VAT/XML/QR/signature/frontend parity, trusted
runtime installation, real isolated15/16/SDK/performance and release evidence
remain before separately approved fictional-Company rehearsal/adoption.
See [PLAN.md](PLAN.md), [STATUS.md](STATUS.md) and
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).
