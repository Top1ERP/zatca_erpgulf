# Versioned field rounding — increment139, 2026-11-02

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

The only new caller is this offline suite. Staging this small primitive avoids
prematurely invoking controllers or inventing a second complete tax calculator.
It has no runtime registration, provider, RPC or financial writer. Next bind the
actual selected rounding stage to the existing owned native/source settings,
with parent/child precision-cache provenance, before amount/tax/GL/VAT/advance/
XML parity. Installed15/16 integration, SDK and authority acceptance remain open.

See [FINANCIAL_NUMERIC_VIEWS.md](FINANCIAL_NUMERIC_VIEWS.md),
[CALCULATION_PRECISION.md](CALCULATION_PRECISION.md),
[CALCULATION_ROUNDING.md](CALCULATION_ROUNDING.md) and
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).
