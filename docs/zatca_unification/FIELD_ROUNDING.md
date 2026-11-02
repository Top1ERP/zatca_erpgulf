# Versioned field rounding and source bridge — 2026-11-02

The explicit multi-field extension and actual framework stage comparisons are
documented in [ROUNDING_STAGE.md](ROUNDING_STAGE.md). Single-field capture and
all previously versioned profile bytes remain available.

## Purpose and boundary

`field_rounding.round_field_value(value, precision=..., method=..., erp_major=...)`
is a pure numeric compatibility primitive. The caller supplies an effective
precision and selected method; the function neither discovers settings nor
calls Frappe, SQL, cache, a document controller or an authority endpoint. Source
Decimal observations and all old snapshot/profile bytes remain unchanged.

The three method names reuse `calculation_rounding.METHODS`. Keep one shared
legacy kernel because its upstream bodies match. Keep separate versioned
Banker's and Commercial kernels because their behavior differs. The algorithms
adapt Frappe's MIT source, with its full notice retained in the module:

- Installed Frappe15 commit `7b430f5eec8c0537f2f0cde9d30e175ae9068647`,
  `utils/data.py` SHA256
  `ed7e208185af255debbfd00983ce26ddfcff745d995cbb72acceb176eee2a248`.
- Pinned Frappe16 commit `e8d41dd0061a32ee781caefe5d0b0d2bb7c15362`,
  `utils/data.py` SHA256
  `b3a005c11cb6a42a92838711b509ecfff568455c54f9923070fc4e1651848284`.

Do not collapse these kernels into one Decimal quantize rule or execute the
installed15 helper for a declared16 operation. Version16 Commercial uses an
ULP threshold and exact Decimal quantization for sufficiently large values;
version15 uses its logarithmic epsilon. Banker's rounding also changed.

## Explicit supported domain

Accept only built-in int, float, Decimal or None. Int and Decimal use existing
source scalar bounds; finite floats allow magnitude up to 1e64 inclusive, which
also covers the derived getter of a valid 64-digit native Decimal. Precision is
None or a built-in integer from 0 through 64. Version must be integer15 or16,
and method must be an explicit known name. Bool, strings, subclasses, nonfinite
numbers, unsupported precision and missing/unknown methods are refused with one
static English code. No protected amount or setting is added to the error.

For valid inputs, match upstream numeric `flt(value, precision, method)` including
result type, float bits and signed zero. None becomes float0.0; precisionNone
converts the numeric input without rounding. This is intentionally narrower than
Frappe's general user-input parser: never remove separators, silently repair a
bad value to zero, read a fallback method or attest unconsumed invalid settings.
An unknown method is refused even for None/precisionNone, where a framework call
can return before executing its method selector. Do not describe that stricter
domain as an unconditional framework error.

This is field rounding, not smallest-Currency-fraction rounding, aggregate tax
arithmetic, XML decimal formatting or a permission to serialize floats to ZATCA.
The function does not bind independently supplied inputs to one transaction or
prove their effective controller stage. Existing precision/method/source
contracts and actual caller provenance still have to be composed explicitly.

## Actual document-rounding characterization

The offline suite executes installed15 `Document.round_floats_in` and a new
verbatim16 excerpt from the already pinned MIT Document file. It does not import
the complete16 runtime or initialize a site. Documents/metadata and dependency
getters are synthetic; the rounding method bodies and numeric helpers are real.

| Behavior | Observed consequence |
| --- | --- |
| None or an empty fieldnames list | Select all Currency/Float/Percent fields, not zero fields |
| An explicit nonempty fieldnames list | Process that supplied order, including a nonnumeric or missing field |
| System method read | Happens once before the loop, even with no numeric fields or all16 fields skipped |
| Precision | Call the owner `self.precision(fieldname, target.parentfield)`, not the child's own precision |
| NULL field passed to flt | Becomes float0.0; the separate explicit numeric-fix operation preserves NULL |
| Version16 skip list | Skipped values retain their type/NULL; no precision or set for those fields |
| Version15 skip keyword | Unsupported signature, not an equivalent skip operation |

These facts prevent combining the SAVED, NUMERIC_FIXED and rounded-field stages
into one guessed normalization. Upfront settings failure must precede any field
mutation. A controller-stage adapter must preserve field order, owner precision
cache semantics and conditional method execution, as well as the scalar result.

## Evidence and integration gate

The reviewed `test_field_rounding` suite compares actual15/pinned16 results for
ties, adjacent floats, negative amounts, Decimal scale, signed zero, subnormals,
large values, precisionNone/0/1/2/9/64, invalid-domain refusal and Decimal context
preservation. It also consumes `FieldPrecisionResolution` to retain the verified
version-specific zero-default behavior. See [STATUS.md](STATUS.md) for counts.

At increment139 the only caller was this offline suite. Staging this small primitive avoids
prematurely invoking controllers or inventing a second complete tax calculator.
It has no runtime registration, provider, RPC or financial writer. Next bind the
actual selected rounding stage to the existing owned native/source settings,
with parent/child precision-cache provenance, before amount/tax/GL/VAT/advance/
XML parity. Installed15/16 integration, SDK and authority acceptance remain open.

## Same-owned selected-field bridge — increment140

`SavedCalculationDefaultsService.capture_field_rounding_context(invoice_name,
fieldname, erp_major=15|16, doctype=..., parentfield=None, row_name=None)` adds
an optional local acquisition, without changing the fourteen existing capture
APIs. The default target is a header field; a child target must name one saved
row of an existing allowlisted financial table. Request input never chooses a
provider, handle, metadata, method override, precision or format declaration.

`FieldRoundingAcquisition` composes the existing `NumericAcquisition` graph and
`RoundingAcquisition` on the SAME owned financial/defaults transaction. Reuse
normal invoice/Company/table/child/field READ, full definition matching, native
SQL readers, System document/field READ, native/cache method comparison and
shared final rechecks/rollback/close. There is no second financial graph, source
reader, connection, cleanup engine or user-message pipeline. Unlike the scalar
primitive, this bridge consumes the saved System method, with the existing
legacy fallback and exact absence/NULL/blank witness; it offers no override.

Inspect the original authorized parent object's existing `_precision` slot using
the shared read-only cache sampler. A header field selects `main`; a child field
selects its parentfield bucket on the OWNER, not a direct child's `main` cache.
Do not call `precision()` or populate/refresh a cache. Pin container/bucket IDs,
slot type/value and initial object identity through callbacks and cleanup. An
equivalent replacement or valid warmup during the operation is still drift.
Unrelated slots and a direct child's different cache are not this operation's
precision source. The captured owner is the acquired saved parent, not proof of
identity with a future active controller's `self` object.

`SavedFieldRoundingRead` reconstructs saved numeric, method, context/version,
target membership and cache binding. Resolve precision from the same native
metadata and site defaults, and require an existing selected cache entry to
match its exact type/value. Missing cache is an absence observation, not evidence
that a future call will compute the same value. Resolve no user/global default
overlay. Only present Currency/Float/Percent fields are supported.

The result computes one `rounded_value` from the selected saved native scalar
using `round_field_value`. None becomes float0.0 without replacing the saved
None. `require_result_match(value)` compares an explicitly supplied calculation
result by type and float bits, rechecking reconstruction; Decimal/float/int
equivalence and opposite signed zero do not pass. Protected repr and refused
serialization keep this result out of normal UI/log/queue payloads.

At increment140, Version16 Currency precision needing locale/currency-format
fallback was deliberately unsupported. It failed through the existing single
localized financial summary; it does not substitute invoice currency for the
owner field's currency. Configured site precision, explicit field precision and
Float/Percent precision do not need that missing dependency. Owner-field format
acquisition and actual controller/cache-stage provenance remain the next gates.

The staged bridge and its offline suites are the new callers. It is not an RPC,
installed provider, background worker or issuance path; no controller runs, no
amount/settings source changes and no authority request occurs. Constructors
check consistency of supplied evidence, not independent atomic-origin proof or
continued freshness after disclosure. Future runtime composition must audit
providers and bind the active controller, field/currency and full amount stage.
Final test counts and SQL isolation evidence are recorded in STATUS.md.

## Lazy owner-field formats — increment141

The same capture API now completes the two standard owner-field Currency format
branches. Reuse `_requires_currency_format` in the pure precision resolver and
the acquisition, so version15, Float/Percent, explicit field precision and a
configured16 currency precision (including zero/malformed-but-present text)
never acquire these format dependencies. No new capture/RPC/provider is added.

After native site defaults on the SAME owned handle, `complete_defaults` chooses
the option from the native field definition: `currency` means the parent invoice
currency; `Company:company:default_currency` means its Company's base currency.
The child row's own currency/Company is not the input to parent.precision().
Unknown/blank option patterns and unresolved currencies remain unsupported.

Reuse `FormatAcquisition`, its metadata/cache readers, normal related READ and
native format/Company readers, with an opt-in field READ check. Authorize selected
Currency/Language/System Settings fields and Company.default_currency before
their format providers. Existing callers retain the previous default; direct-
child format callers retain their original field checks. No parallel ACL, SQL,
transaction or cleanup implementation is introduced. The existing format profile
inspects Currency/Language/System settings together; this is not a claim of the
minimum possible query set when the Currency-format flag is false.

The protected result optionally binds `SavedFieldCurrencyRead` to its exact
numeric/default/method parent and resolves root or parent-owned child precision
through that contract. Retain locale fallback when the flag is disabled or the
Currency number format is NULL/blank. Native flags absent from a nonempty System
Singleton retain the existing zero/check witness, including when its rounding
method supplies the nonempty witness. Old financial/native/profile/oracle bytes
are unchanged; optional result fields are ephemeral, not new persistent payloads.

Sample only the original owner's existing request-local field_currency key
`(parent_doctype, parent_name)[fieldname]`, including for a child field definition.
Reuse the existing cache-state/slot helpers without calling get_field_currency,
populating keys or refreshing cached documents. Preserve absent versus NULL
global containers and pin container/bucket IDs and selected values through all
callbacks/close. A present slot must exactly match the fresh selected currency;
stale, NULL/blank-blocked and invalid-type entries fail without repair. Other
child-row cache keys are not this owner's cache source. Real installed15/pinned16
helper probes establish that owner key, with only synthetic dependencies.

The existing precision-cache observation remains separate and must agree with
the newly resolved format precision. Recheck every format/Company/native/default/
method/financial source after trusted callbacks. No controller, writer, Company
creation, authority endpoint or installed runtime is activated.

This remains a fresh source-backed comparison for an acquired saved owner, not
proof of the active controller stage. Cache-reader provenance and the actual
Company get_cached_value branch when the owner field-currency cache is absent
still need runtime auditing; normal/native Company equality alone is not that
API-cache proof. Unknown option/owner-currency patterns, complete controller
membership/stage/cache identity, all-field batching/performance and fiscal/GL/
advance/XML parity remain gates before adoption. Constructors do not establish
atomic origin for independently supplied evidence or freshness after disclosure.

See [FINANCIAL_NUMERIC_VIEWS.md](FINANCIAL_NUMERIC_VIEWS.md),
[CALCULATION_PRECISION.md](CALCULATION_PRECISION.md),
[CALCULATION_ROUNDING.md](CALCULATION_ROUNDING.md) and
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).

## Combined batch142–144 follow-up

The shared parent registry now also covers party_account_currency, with a
supplemental native Link bound to the same root and transaction. Source inventory
checks cover all three standard option names across seven pinned public DocTypes
per version. Company fallback now requires an exact server-supplied API-cache
projection when no local owner field-currency entry applies. These changes do
not establish an installed provider or actual controller-stage provenance.
See [OWNER_CURRENCY_AND_CACHE.md](OWNER_CURRENCY_AND_CACHE.md) for the grouped
implementation, byte-compatibility evidence and audit commands.
