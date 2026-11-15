# Native Sales currency binding — increment221

Development only, 2026-11-15. No site/schema/configuration/invoice changes,
worker restart, tenant SQL, deployment or authority API request. No extra custom
field is added. Signing, transport and attachment boundaries in the new route
checks are simulated. This does not establish installed16 or SDK acceptance.

## Defect and intended changes

Native Sales Invoice and POS Invoice schemas in the inspected15/16 commits do
not contain `company_currency`. Their base-money fields use
`Company:company:default_currency`; document-money fields use `currency`.
An older Sales helper instead uses:

```python
invoice.currency == getattr(invoice, "company_currency", invoice.currency)
```

If the attribute is physically absent, this comparison always succeeds and
selects base net amounts as document-currency line values. For two USD100-net
lines and a SAR conversion factor3.75, the old line sum is750 labelled USD;
the correct document line sum is200. A NULL/blank existing helper attribute is
different: the old comparison is false, so that particular amount error is not
present. The new adapter handles absent/NULL/blank by checking Company.

This correction intentionally extends beyond the optional VAT selector from220:
ordinary/nominal Sales and primary advance item builders with a real Company
and foreign currency now bind missing helper metadata to that Company's currency.
No optional VAT field is needed for this native foreign-currency correction.
Original supplied invoice/master amounts remain unchanged.

| Example, no discount | Increment220 result | New result |
| --- | --- | --- |
| Two foreign100-net lines, helper absent | Line sum750 from base nets | Line sum200 from document nets |
| Ordinary Sales using5/15 item VAT | Header payable220, inconsistent lines750 | Header payable220, consistent lines200 |
| Nominal plain15%, helper absent | Nominal payable112.50 in document currency | Nominal payable30.00 in document currency |
| Nominal item5/15%, helper absent | Nominal payable75.00 in document currency | Nominal payable20.00 in document currency |
| Explicit selected VAT, helper absent | Refusal `declared_vat_currency_context` | Generation after Company's SAR binding and full source checks |
| Selected VAT with conflicting Company/helper currency | Some invoice helper declarations masked Company | Refusal before signing; no currency substitution or source repair |

The nominal SAR summary retains its prior base-net VAT policy: this increment
changes document-currency amount selection, not nominal offset or accounting-tax
calculation. Existing nominal regulatory/GL review gates remain. The financial
matrix with an existing explicit valid helper remains byte-identical. The
original pre-development240-case oracle remains separate, with earlier deltas
still visible rather than claimed as global parity.

## One policy and a local rendering adapter

`ksa_compliance/invoice_currency.py` owns a small pure binding policy. The
Company owns accounting currency; a nonblank invoice helper can confirm it but
cannot override it. Missing/malformed declarations, conflicts and a non-SAR
accounting Company fail in the supported scope. Conversion rate, party-account
currency, POS Profile, another Company or user display currency do not supply a
fallback. No amounts are converted or recalculated by this policy.

`DeclaredVatContext` owns one builder's Company observation and local
`CurrencyRenderDocument`. The view supplies checked `company_currency` only;
other reads delegate to the original document. Its attribute is frozen, but it
is **not** a frozen source snapshot, authorization grant or transaction receipt.
It is not installed on the invoice, cached globally or passed to signing,
settlement/reference services or persistence. Reference and signer assertions
verify that those services still receive the original saved invoice.

For foreign native inputs without a helper, bind before the first primary line.
This also fixes an unselected single-row companion preceding a selected template,
without preloading/reordering the item-template reads. Company is read at most
once per affected builder context; independent totals/lines can still have
separate contexts. This is a reader-call invariant, not a SQL/latency benchmark.

Explicit VAT source verification now checks Company even with an existing
invoice helper. Selected POS uses the same pure policy and reuses its already
loaded Company. Its existing early unsupported-accounting-currency error remains
where it already applied. The included-price selected preflight also checks
Company; it does not authorize submission or waive native account/rate/money
requirements.

## Entry points and preserved boundaries

- Ordinary plain/template Sales item builders use the view for net/unit-net
  selection. Primary lines in both advance builders do the same; direct and
  legacy advance reference tails retain their existing source and calculations.
- Plain/template nominal tax breakdowns use the same binding for document nets;
  their existing base-net calculations, category grouping and OOS offsets remain.
- Generic native rate readers, Decimal/rounding expressions, discount allocation,
  VAT subtotals, FX conversion, QR, signing, ICV/PIH/UUID, routing and accepted
  artifacts remain unchanged.
- Historical221 behavior (extended in [increment222](SALES_MONETARY_CONTROLS.md)):
  existing explicit helper bindings without VAT selection retain their old
  policy. A contradictory explicit helper in that legacy scope still needs
  broader migration/reconciliation review; this is not universal currency repair.
- Partial public-helper inputs with no Company keep their old fallback/read and
  partial-error behavior. Full native invoice sources have a Company. Missing
  or unreadable Company evidence is not permission to assume SAR.

The new app-owned review key is translated for Arabic display. English error
codes/canonical diagnostics remain untranslated; Debug returns one summary and
avoids a second log. No authority payload or Account/Currency identifier is
translated. Missing native Company evidence and conflicting overrides never
reach signing in the new route checks.

## Evidence and remaining work

365 new cases cover the pure policy,288 combinations of15/16 native source
shapes, absent/NULL/blank metadata, ordinary/nominal/advance builders,
plain/legacy/selected/first-companion sources, inclusive prices, discounts and
returns. Twelve explicit frozen220 money comparisons and three prior-refusal
comparisons expose the intended deltas. Four schema/hash checks verify standard
field ownership using installed15 source and cached pinned16 source.

Eighteen real generation/Compliance/Debug compositions use real financial
builders with mocked parties/signing/transport. Nine valid examples bind USD
amounts correctly and sign with the original source; nine Company conflicts
stop before signing and return/raise one source error. Debug creates a synthetic
attachment only for success. No network dispatch occurs.

Frozen220 files are test-only, not runtime dependencies:

- `currency_builders_9223294.py`: SHA256
  `709501e27ad910f8d217535a8b92c75392c8393adcaf1e4910baade5d2850713`;
- `currency_context_9223294.py`: SHA256
  `140dcc7d32d8127945d5352e30354d9e8379563f2f47ca518006c6e520548db1`.

The focused new/existing declared-source run passes901 cases. The existing
428-case document-tax selector suite passes after supplying the native Company
currency record its synthetic fixture previously omitted; its assertions are
unchanged. The guarded broad run passes13,401 distinct cases across59 suites in65.42s,
including365 new. Six browser suites pass1,188 synthetic cases: Debug104,
Debug lifecycle164, Company messages108, Company form292, device128 and template
VAT392. The manifest lists193 local/57 private suites. Original240 remains
91 identical/117 changed/32 blocked; the new native missing-helper cases are
separate. AST restoration proves five Sales builders only change source binding,
and POS only adds its selected currency check. Native VAT/rate/discount/FX math
and all22 preexisting reference fixtures remain unchanged. Logs:
`/tmp/zatca-currency-221-regression-final.log`, `/tmp/zatca-currency-221-focused.log`,
`/tmp/zatca-currency-221-document-review.log`; structural evidence:
`/tmp/zatca-currency-221-structure.json`. No
whole-manifest or tenant database run occurs. Installed15/16 fresh/upgrade
lifecycle, complete GL/fiscal variants, native currency/defaults provenance,
source/settings/credential and transaction custody, SDK and separately approved
fictional-client rehearsal remain release gates. No universal completion claim.
