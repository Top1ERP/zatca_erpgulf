# Finite mixed-number legacy tax repair — increment204

Development only. Both legacy advance reference branches now use one small
`_legacy_advance_tax_amount` helper in the existing `create_xml_final_part.py`.
It repairs the finite native Decimal/float multiplication error characterized in
[LEGACY_ADVANCE_XML.md](LEGACY_ADVANCE_XML.md). It adds no module, field, Company
setting, endpoint, database read or UI message.

## Source finding and limited contract

`ksa_compliance/tax_details.py` normalizes ordinary item rates to float for its
v15/v16 adapters. A legacy `custom_item.amount` supplied as Decimal therefore
failed at `amount * item_tax_percentage`, before its reference tax amount could
be emitted. The template branch could fail in either direction too: template
rates may be float or Decimal while the supplied amount has the other type.

The external `claudion4saudi` app/DocType definition is absent from this checkout.
Its actual deployed legacy field schema and installed lifecycle have **not**
been established here. Read-only inspection of local Frappe15 pinned source
`7b430f5eec8c0537f2f0cde9d30e175ae9068647` shows Float/Currency/Percent conversion
to `flt` in `BaseDocument._fix_numeric_types` and float-like persistence
conversion in `get_valid_dict`. Thus ordinary framework-loaded values commonly
use float; this is a supported mixed-native-input repair demonstrated with
synthetic documents, not a diagnosis of a new tenant failure. The inspected
`base_document.py` SHA256 is
`3ddaf655be1b12d4320b61760c5d87f0245a9b9ca9dff33d26a1768d5c92b049`.
No site initialization or tenant data was used to obtain that finding.

| Operand pair | Behavior |
| --- | --- |
| Existing compatible operands | Original expression and return type retained, including float bits and Decimal scale |
| Finite native Decimal amount / float rate | Convert only `str(rate)` to Decimal before the original expression |
| Finite native float amount / Decimal rate | Convert only `str(amount)` to Decimal before the original expression |
| Non-finite mixed pair, custom numeric subclass or other incompatible input | No bridge; original expression/error behavior retained |

Only exact native types enter the bridge. It never converts a Decimal to float,
coerces strings/NULL/custom objects, or turns a previously rejected non-finite
mixed pair into emitted text. It deliberately does **not** add broad non-finite
validation to already compatible old paths; their validation remains separate.

The numeric expression remains `abs(round(amount * tax_rate / 100, 2))`.
The helper does not change Decimal precision/rounding context, adopt HALF_UP
for all paths, select another tax rate, round at an extra intermediate step or
format XML. Callers still stringify the result at the same TaxAmount assignment.
Examples of newly supported arithmetic are `Decimal("20.1500")` with `15.0`
producing Decimal `3.02`, and float `-50.005` with Decimal `15.00` producing
Decimal `7.50`. Native float-only results keep their old representation.
This is an explicit application compatibility policy, not a claim that ZATCA
requires Python Decimal or float, or certification of inherited rounding rules.

The two call sites keep amount/rate argument reads at the original RHS position.
Empty regular tables still resolve their unbound last-row rate there, after the
same partial subtotal exists. Discovery, direct-allocation priority, references,
time/coercion, last-row category/rate ownership and public errors remain.
There is no save/relink, historical rewrite, ICV/PIH allocation or API dispatch.

## Offline evidence

The new `test_legacy_advance_tax_amount.py` has **273 cases**:

- 136 compatible/invalid-operand comparisons under two Decimal rounding contexts.
- 12 literal mixed-pair results, including signed zero, high-precision amount,
  tiny amount, fractional rate and both mixed directions.
- Three halfway cases preserving the caller's two Decimal rounding contexts.
- 40 non-finite/control comparisons, with original exceptions retained outside
  the finite bridge; four custom-subclass comparisons prohibit silent coercion.
- 56 native float comparisons, checking exact result bits or original errors.
- 16 complete legacy-wrapper XML cases across both mixed template directions,
  SAR/USD and synthetic v15/v16 tax-detail shapes.
- Six direct/none/both-source cases proving unused invalid legacy data is not
  consumed and direct allocation still takes priority.

The existing 621-case advance suite remains. Its 48 formerly failing plain
Decimal cases now explicitly assert the intentional repair. Other comparisons
continue to require old/new byte/read/error parity. The fixture's original
functions/hash are unchanged; they have not been updated to hide the defect.

For each repaired full-wrapper case, tests first prove the frozen mixed pair
fails, then require the new builder to succeed. A frozen successful float run
supplies all other XML bytes; only the first reference's taxable text and tax
text are replaced with explicit expected values. Complete successful ordered
attribute/get/master/app reads must match too. Test float conversion is used
solely to construct this old-run oracle, never in the runtime Decimal bridge.
All runs assert no document/database writes, commit, log or popup.

Final guarded selection: **7,039 distinct local cases passed across 39 reviewed
suites in 20.40 seconds**. This includes the 273 new cases and existing Sales/POS,
advance, tax/party, signing/QR, routing, settings, scheduling, messages and artifact
checks. Log: `/tmp/zatca-mixed-tax-regression-final-204.log`. Initial overlapping
runs are excluded. Manifest is 173 local/57 private suites; no whole-manifest or
private SQL run was needed.

AST review restores only the two numeric calls to their exact old expression,
then removes the new helper/import. The entire module matches parent
`239cf10e4cff204840261ef17f5c5068981961d6`; original final rounding, call bindings,
public handlers and frozen fixture are independently checked. Tool:
`/tmp/zatca_mixed_tax_structure_204.py`; report:
`/tmp/zatca-mixed-tax-structure-204.json`. Runtime adds 19 lines. No CPU, memory,
query-count or production-latency improvement is inferred.

## Remaining release work

This closes the finite mixed-native multiplication defect. It does not validate
the inherited last-regular-item tax rate/template for legacy advances, retire
time fallbacks, establish original-artifact/acceptance provenance, or reconcile
multi-rate/partial/return/FX settlement, GL/VAT/XML totals. External legacy app
schemas, supported installed ERPNext/Frappe15/16 lifecycles, SDK/QR acceptance and
the separately approved fictional-client rehearsal remain gates.

No live source/configuration/schema/customer data, Bench or worker changed;
no authority request occurred. The unrelated live tooltip edit was preserved.
