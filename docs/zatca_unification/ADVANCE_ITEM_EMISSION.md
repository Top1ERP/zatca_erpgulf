# Shared Sales/advance regular-line emission — increment202

Development only. Four public Sales item builders now use one regular-line XML
emitter inside the existing `create_xml_final_part.py`. This extends the ordinary
[Sales item consolidation](SALES_ITEM_CONSOLIDATION.md) to the two advance-named
wrappers without replacing their reference tails, acquisition or monetary rules.
No installed app, customer data, schema or authority request is involved.

## Shared work and retained ownership

`_append_sales_invoice_line` emits the regular item line from the already
calculated net amount, precise price, tax amount and rate supplied by its caller.
Ordinary/template paths share that implementation, including the regular item
prefix used by `item_data_advance_invoice` and
`item_data_with_template_advance_invoice`.

The callers retain template/tax-detail acquisition and the original numeric
helpers. Advance wrappers still bind their last-loop `item_tax_percentage` and
`item_tax_template` locally, then run the unchanged direct-reference/legacy-copy
tail. Empty-loop behavior is preserved; no replacement rate/template is invented.
The original last-loop dependency and legacy-time behavior still require fiscal
review, rather than being certified by parity.

| Internal layout | Used by | Preserved construction behavior |
| --- | --- | --- |
| `ordinary` | Shared ordinary Sales item loop | Unit converted to text; amount node created and currency set before formatting its text |
| `advance_plain` | Plain advance-named wrapper | Quantity text evaluated before raw unit access and quantity-node construction; amount text formatted before currency read/node construction |
| `advance_template` | Template advance-named wrapper | Unit converted to text after quantity-node creation; amount text formatted before currency read/node construction |

These are private compatibility controls, not Company settings, fiscal modes,
credential choices or new public endpoints. Unknown internal layouts fail before
a line is appended. The helper does not discover advances, choose an issuer,
allocate identities, persist, display, sign or send.

## Evaluation order matters on failure

The old `SubElement(...).text = expression` statements evaluate the right-hand
expression before creating the assignment target. Separate node/set/text
statements do the reverse. Successful XML can match while a failed formatter or
field read leaves different partial XML or consumes fields in a different order.

`_append_sales_line_amount` preserves that distinction explicitly with a deferred
text formatter. Name and tax-percent creation retain the same distinction, and
the raw-unit path evaluates quantity before unit access. Category source reads
keep their original repeated/plain versus once/template behavior. This is not a
new arithmetic, rounding, validation or error-recovery policy.

Public signatures/error handlers and generator import paths remain. Existing
high-precision price helpers, Decimal/float policy, currency fallback, categories,
direct-reference duplicate handling and original issue dates remain unchanged.
Direct allocation still short-circuits installed-app and legacy-reference reads
when the original condition does so. No forced relink, historical repair,
allocation, GL entry, ICV/PIH or credential change is added.

## Offline evidence

`tests/fixtures/advance_item_builders_03b4982.py` freezes the two original advance
functions from `03b4982195b8bb614125f8b87c2cd460958902bb`. Its hash is checked
before compilation with explicit synthetic dependencies. It is deliberate
test-only reference data, not a runtime module or a fixture installed on sites.
The ordinary frozen reference from increment201 remains in use too.

**425 new local cases** verify:

- 384 combinations across plain/template, SAR/USD, synthetic v15/v16 tax-detail
  shapes, zero/positive/negative quantities, none/direct/legacy/both reference
  sources, Company-currency declaration and differing last-row rates/templates.
  Complete XML bytes, attribute and `.get` read order, master-read order and
  installed-app query behavior match the old code.
- Historical 2020 reference dates and direct-over-legacy precedence, without
  fetching an unused second legacy-copy record.
- Legacy time fallbacks/failures, empty regular/copy/legacy tables, blank
  reference and retained empty-loop errors.
- All four public builders under targeted unit, first/last currency, name,
  price and percent failures. Error type/message and partial XML match, with
  explicit source-read order checks. The test helper reports only synthetic
  role/field names for read-order diagnostics.

An initial strict read-order check caught a first-draft quantity/unit ordering
difference; the emitter was corrected to the original assignment evaluation
order. That assertion remains. No production source or accepted artifact was
used to discover or fix it.

Final guarded selection: **6,570 distinct local cases passed across 38 reviewed
suites**, including those 425 new cases and the 544 ordinary frozen-reference
cases. Existing advance-reference, document tax, party, signing/QR, source/issuer,
Debug/Compliance, scheduling, settings, messages and artifact checks also passed.
Initial overlapping runs are not added to that count. Final log:
`/tmp/zatca-advance-lines-regression-final-202.log`. The manifest is now 172 local/
57 private suites; this was neither a whole-manifest nor native SQL run.

AST review against `03b4982195b8bb614125f8b87c2cd460958902bb` normalizes only the
three regular-line emission spans and the updated ordinary-helper docstring.
Acquisition, complete advance tails, public signatures/error handlers and every
other module node match. Each emitter's numeric/source/template/layout bindings
are checked separately; the frozen reference matches the original functions.
Tool: `/tmp/zatca_advance_line_structure_202.py`; report:
`/tmp/zatca-advance-lines-structure-202.json`. Runtime source is 11 lines shorter,
with no additional runtime module. This is structural consolidation, not a
measured CPU, memory, query-count or production-latency improvement claim.

## Remaining release work

Legacy reference-tail consolidation/retirement, its last-loop/time semantics,
complete direct allocation/eligibility/GL and Sales/POS fiscal reconciliation,
effective settings/aliases, first-chain/retry/credential guarantees, SDK checks,
installed ERPNext/Frappe 15/16 and separately approved fictional-client rehearsal
remain open. Matching inherited output does not certify every characterized
input or authorize rollout.

No live source, configuration, schema, customer data, Bench or worker changed;
no authority request occurred. The unrelated live tooltip edit was preserved.
