# QR monetary source alignment — increment223

Development only, 2026-11-16. Public static documentation/community discussions
were read; no invoice, Compliance, CSID or other authority API was called. No
working site, invoice/configuration/schema, Bench or worker was changed. Existing
stored QR/XML is not regenerated, deleted or replaced by this bundle.

## Reference findings before changing behavior

The [Security Features Standard v1.2, table3/p26](https://zatca1.discourse.group/uploads/short-url/mkQsWHJwK8U0EgY1JrfLeEmMWeg.pdf)
explicitly identifies QR Tag5 with XML business term BT-110. The current
[government security specification page](https://zatca.gov.sa/en/E-Invoicing/SystemsDevelopers/Pages/Security-Requirements.aspx)
links that version; direct PDF retrieval timed out, so its developer-community
copy was read. This is not a claim that an SDK was downloaded/executed.

The [SDK3.3.0 release announcement](https://zatca1.discourse.group/t/release-of-sdk-3-3-0/1137)
(January2024) explains using BT-115 for Tag4 so prepayments/rounding are included.
[Developer support on prepayment VAT](https://zatca1.discourse.group/t/clarification-on-vat-representation-in-qr-code-for-invoice-with-prepayments/4667)
(2024–2025) confirms Tag5 remains VAT before prepayment adjustment.
[Foreign-currency clarification](https://zatca1.discourse.group/t/qr-image-foreign-currency/4091)
(2024–2025) confirms document-currency amounts. These are dated first-party
technical clarifications, not a new legal interpretation or a tested current
mobile-app behavior. Generic table wording alone would wrongly suggest changing
Tag4 to TaxInclusiveAmount; the existing BT-115 mapping is deliberately retained.

The [Phase1 FAQ](https://www.zatca.gov.sa/en/RulesRegulations/Taxes/Documents/E-Invoicing%20FAQ.pdf)
defines the gross invoice/note total and VAT among the five required values.
The Phase1 adapter now uses its native saved DOC gross and VAT pair, consistent
with the document-currency guidance. This is an application source decision;
it does not fabricate XML BT-115 or infer a final settlement from paid/outstanding
or a legacy deducted-taxable field. Full Phase1 settlement/rounding/GL and scanner
acceptance still require the separately scoped rehearsal.

## Shared pure selection and exact scope

`ksa_compliance/qr_amounts.py` owns a framework-free, read-only projection.
It reads no Company, account, credential, clock, image, file or authority service.
It performs no FX conversion, allocation, VAT recalculation or invoice write.

| Producer | Monetary source |
| --- | --- |
| Ordinary Phase1 Sales/POS | grand_total and total_taxes_and_charges, both in native document currency |
| Eligible initial-advance Phase1 print hook | The same saved gross/VAT pair; no second deduction or base conversion |
| Phase2 signing/Debug/Compliance QR extraction | Unique PayableAmount/BT-115 and detailed root TaxTotal/BT-110 in DocumentCurrencyCode |

Phase1 normalizes native credit signs to positive magnitudes and formats two
decimals. Negative normal-invoice values, inconsistent native credit direction,
missing/nonfinite/boolean/unrepresentable money and invalid currency-code shape
fail instead of using zero, base fields or a guessed conversion. Saved precision
must be representable at two decimals; a higher nonzero fractional precision is
refused for review, not silently rounded. This is not complete support for every
native currency precision or VAT-account/non-VAT-charge configuration.

Native gross/VAT are scalar source observations, not proof that the entire
header, item VAT roles and GL reconcile. No tax <= payable rule is invented:
a Phase2 invoice can have zero due after prepayment and still have full BT-110.
No currency symbol/new currency tag is added to the standard TLV payload.

Phase1 initial-advance eligibility remains unchanged: submitted Sales Invoice,
phase/schema/field checks, initial-advance classification and positive legacy
deducted-taxable gate. The legacy field now affects eligibility only; it cannot
be used to recalculate an initial advance's invoice value. Final/non-initial
print paths still return untouched. The ordinary Phase1 caller's existing phase
routing remains; this bundle does not add a new phase/authorization policy.

## Phase2 ambiguity and parse controls

The selector checks direct root children, requiring one DocumentCurrencyCode,
one LegalMonetaryTotal/PayableAmount and exactly one detailed TaxTotal with
TaxSubtotal. Selected money must use the document currency and be finite,
nonnegative and representable to two decimals. Duplicates are rejected even if
identical. Line-level taxes or the first summary TaxTotal cannot supply BT-110.
Valid XML monetary text/scale is retained; whitespace is trimmed. XML is not
mutated or repaired. Detailed-subtotal arithmetic, classification, signatures,
receipts and complete XSD/Schematron remain upstream/separate responsibilities.

`generate_tlv_xml` parses without entity resolution/network access, rejects
DOCTYPE declarations and uses one static source error for malformed XML/money.
A malformed source fails before this function's Tag8/Tag9 key-material access.
The shared signing pipeline may already have hashed/signed earlier in its normal
sequence: this is **not** a new whole-pipeline pre-sign/transaction gate. No
provenance or rollback guarantee for earlier ICV/identity work is implied.

The existing field1/2 selection, shared issue-time conversion, field6/7 hash/
signature extraction, field8/9 owners, standard/simplified behavior, tag order,
TLV encoding, QR embedding and certificate/signature algorithms are unchanged.
Historical artifacts are preserved through the existing scoped reference policy.
One app-owned monetary review key has Arabic display; typed canonical errors and
one source diagnostic remain English. Other legacy error families retain their
existing boundaries; no universal all-error-message consolidation is claimed.

## Explicit previous/current results

| Simulated source | Prior222 QR | Current first-generation QR |
| --- | --- | --- |
| USD gross115/VAT15, SAR base gross431.25 | Ordinary Tag4=431.25, Tag5=15 (mixed sources) | Tag4=115.00, Tag5=15.00 (DOC pair) |
| Same initial advance, legacy deducted taxable20 | Advance Tag4=356.25 from partial SAR calculation | Native initial gross115.00, VAT15.00 |
| Normal SAR115/VAT15 | Same monetary values with legacy string scale | Canonical115.00/15.00; wire text can change |
| Native return gross-115/VAT-15 | Negative ordinary values; advance formula could deduct again | Positive115.00/15.00 without invoice mutation |
| Phase2 foreign summary56.25 first, DOC VAT1.50, due80.25 | Tag4=80.25, Tag5=56.25 | Tag4=80.25, Tag5=1.50 |
| Zero due after advance, nonzero invoice VAT | Inherited first-tax selection | Tag4=0.00; Tag5 retains full DOC VAT |
| Missing/duplicate/inconsistent money | Could choose a first node/fallback | Review error before QR-specific key extraction or image/File creation |

The existing initial-advance and ordinary first-generation formulas are frozen
in `tests/fixtures/qr_amount_adapters_82c19b6.py`, SHA256
`876daaa1b6d6b402431da3e575cc7e8e8be5f486217c97a5a4a0f9130dd41335`.
It is test-only reference code, not an unused runtime path. Existing wire parity
tests continue testing the unchanged encoder with the newly selected values;
independent frozen-adapter tests show the real previous financial differences.

## Evidence and remaining release gates

216 new cases include native scalar representations/signs/currencies, missing or
invalid money,24 frozen Phase1 adapter combinations, literal old/new values,
summary ordering/prepayment cases,44 localized ambiguous Phase2 failures,
malformed/DTD source rejection and30 localized Phase1 no-write failures. Three
cases prove a preserved owned QR bypasses even invalid current money/time.

48 cases render real current Sales, nominal and POS financial builders using
15/16-shaped source data, SAR/foreign, templates and returns, then extract QR
and run the actual TLV encoder. They decode the encoded payload, not an optical
image. XML is unsigned; public key/signature dependencies are mocked, and the
minimal fixture is not a full valid signed invoice. No SDK, actual scanner,
installed16, certificate validity or regulatory acceptance is established.

The focused new plus existing adapter selection passes437 cases. The guarded
broader run passes14,217 cases across61 reviewed suites, including216 new; six
browser suites pass1,196 synthetic cases. These are application regression
assertions, not14,217 authority validations. Structural comparison preserves
all24 earlier Python reference fixtures and350 other tracked runtime files;
all non-QR functions in the three touched adapters retain their AST bodies.
Original240 financial comparisons remain91 identical/117 changed/32 blocked,
separate from this bundle's frozen-parent comparisons. Full logs and structural
evidence are recorded in STATUS.md. No private
SQL/tenant test or whole manifest run is included. Existing artifact preservation,
phase/routing and access boundaries, full native GL/fiscal/precision/settlement,
source/settings/credential and transaction custody, installed15/16 lifecycle,
SDK/scanner acceptance and separately approved fictional-client rehearsal remain
release gates. Do not apply this development branch to working sites yet.
