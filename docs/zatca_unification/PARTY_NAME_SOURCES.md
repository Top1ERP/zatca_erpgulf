# Party display sources and Phase1 QR boundaries — increment224

Development only, 2026-11-16. No working site, schema, invoice, configuration,
worker or Bench was changed. No authority API or tenant SQL was used. These
changes do not authorize deployment, artifact repair or a Compliance request.

## One registry, two distinct contracts

`field_alias_registry.FIELD_ALIAS_GROUPS` now holds `display_aliases` for Company
and Customer Arabic names. Existing `canonical`, `doctype` and `aliases` values
are unchanged. Schema-first readers still use the first existing field, even
when blank or false. Rendering retains its historical value-fallback order:

| Group | Display order |
| --- | --- |
| Company Arabic name | company_name_in_arabic, custom_company_name_in_arabic, custom__company_name_in_arabic__ |
| Customer Arabic name | customer_name_in_arabic, custom_customer_name_in_arabic, zatca_customer_name_in_arabic |

Do not use the rendering list for credentials, phase flags or schema creation.
Conversely, replacing display fallback with `get_alias_value` would change legal
names when both native-style and custom fields exist. The old registry SHA256
test still pins the complete old schema dictionary after excluding only the two
new display metadata entries. Existing issuing/party observation field sets and
profile payloads are not reordered or versioned by this metadata addition.

`ksa_compliance/party_names.py` owns framework-free field selection, comparison
normalization, script classification and ordered duplicate filtering. Existing
Sales/POS helper names remain wrappers; their comparison callback is still
resolved at invocation time. Unicode normalization is comparison-only: it does
not rewrite output names, transliterate, select a legal issuer or validate VAT.

## Compatibility distinctions intentionally preserved

| Caller | Existing behavior retained |
| --- | --- |
| Sales XML name fields | Skip missing/None/stripped-empty values; stringify present zero |
| POS XML name fields | Check truthiness before stripping; whitespace can stop fallback |
| Phase1 QR fields | Keep first truthy raw name, including outer whitespace |
| Sales duplicate names | Existing suffix vocabulary, Arabic tatweel removal, cross-script guard and similarity >=0.90 |
| POS duplicate names | Existing smaller vocabulary and similarity >0.90; no new script guard |
| Ordinary Phase1 QR | Arabic name required; no new English fallback |
| Initial-advance Phase1 QR | Existing English fallback, now after all three Arabic aliases |

Blank-name policy, invalid/non-string names and deduplication equivalence are
not newly certified fiscal rules. Keeping these differences prevents an
unrelated silent change to XML and signed bytes. A later strict-name policy
needs explicit before/after review. Customer identity, address source, VAT and
registration rules, XML PartyName placement/order and legal-name fallback remain.

## First-generation QR source observation

Ordinary Sales/POS QR now loads Company once for name and Tax ID rather than
reading individual aliases and VAT through separate scalar SQL calls. The
initial-advance hook reuses its already loaded fresh Company for both values.
No temporary seller is created. The compatibility `get_company_arabic_name`
wrapper remains callable and returns the same raw selection, using a loaded
Company instead of per-field SQL; the generator no longer calls that wrapper.

The loaded object is a bounded local source observation, not an immutable saved
revision or an authorization/certificate snapshot. The advance hook retains its
earlier cached Company phase observation before eligibility/artifact inspection,
then checks the fresh Company's phase again before using its seller fields. A
cached Phase1 observation cannot override a fresh explicit Phase2. A cached
Phase2 still stops earlier, conservatively preserving the existing artifact path.
No SQL performance benchmark, full transaction isolation, legal taxpayer match,
credential binding or complete phase/source custody is established.

| Situation | Previous223 | Current224 |
| --- | --- | --- |
| Only third Company Arabic alias populated on an initial advance | English company_name | Third Arabic alias |
| Valid first/second alias, ordinary/advance QR | Existing name and money | Same tag values and money |
| Ordinary QR Company observation | Separate field/VAT reads | Name/VAT from one loaded Company |
| Missing name and/or Tax ID | First missing-field error; advance text was untranslated | One translated review; one English diagnostic lists missing scalar fields |
| Explicit Phase2 with integration disabled | Advance print could generate Phase1; direct ordinary helper lacked its own phase gate | No Phase1 substitute |

The third-alias change modifies QR Tag1 on newly generated eligible initial
advances; it does not replace an owned QR, rewrite XML, change amounts, reduce
VAT or alter an advance settlement. The amount/currency policy from223 remains.

## Phase boundary and historical artifacts

An explicit resolved Phase2 now stops ordinary QR creation and advance print QR
creation, independently of enablement. Resolution uses the canonical phase
reader: preferred custom field wins even when blank; the legacy field supplies
a value only when the preferred field is absent. Blank/unknown phase behavior
is retained rather than guessed as Phase2. This is not a universal enablement,
authorization or submission routing rewrite.

Stored same-invoice owned QR references still bypass fresh seller validation;
ambiguous references retain REVIEW without deletion/relinking. No full-name
validation is applied retroactively. Advance classification, schema/submission/
positive-deducted-taxable eligibility, force behavior, File visibility, metadata
updates, caller transaction ownership and final/non-initial return paths remain.

The generic seller review is translated at display time; the typed canonical
error and fixed missing-field labels are English. No raw Company/VAT value is
included in the diagnostic. This uses the existing typed-source error channel;
its historical VAT-source log title is retained, not a new logging subsystem.
Other legacy error families are not globally consolidated by this bundle.

## Evidence and remaining gates

The frozen parent functions live in
`tests/fixtures/party_name_adapters_a53b85b.py`, SHA256
`9f0c757d55d96bd6bf5b86251e6e9e2e21e2100291835a7e72f3a52df92f7e37`.
They are test-only reference code. Comparisons cover exact lazy name reads,
Unicode/noise/blank differences, override binding, real reference/party/payment
XML, decoded Phase1 QR values, local English/Arabic errors, preserved artifacts
and phase alias/enablement combinations. XML remains unsigned and QR image/File
dependencies are mocked; these are not installed15/16, scanner or SDK evidence.
Final counts/logs and structural scope are recorded in STATUS.md.

The final guarded run passes15,710 cases across65 reviewed suites, including364
new cases. Focused440 cases (the new suite plus existing source-gap observations)
and1,200 browser cases pass. No private SQL or whole-manifest run is included.
All25 earlier Python reference fixtures and349 other tracked runtime files remain
byte-identical. The original240 financial record stays91 identical/117 changed/
32 blocked, separate from the new parent-name comparisons. Three stale223 money
expectations in the newly included source-gap suite were updated to11.50; frozen
monetary reference functions and original financial expectations were not edited.

Complete saved settings/credential/phase custody, VAT roles/precision/GL/fiscal
and settlement behavior, installed15/16 lifecycle, SDK/scanner acceptance and
separately approved fictional-client rehearsal remain release gates. Never
infer authority acceptance from these synthetic cases or a locally present QR.
