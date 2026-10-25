# Invoice-owned financial source observations

Increment 104 — 2026-10-25. Offline development, not runtime activation.

Follow-up increment 105 adds explicit protected observations of the exact
referenced invoice/item tax templates, including ordered taxes rows. It reuses
child capture/validation without changing this profile's wire bytes or digest;
both components remain PARTIAL. See
[TAX_DEPENDENCY_OBSERVATION.md](TAX_DEPENDENCY_OBSERVATION.md).

## Delivered scope and proof limits

The new pure observation captures an explicit invoice-owned projection for
Sales Invoice and POS Invoice. It freezes independent canonical bytes and a
domain-separated fingerprint, without retaining mutable document/meta objects.
It includes the saved source name, declared ERP major (15 or 16), parent
modified value, allowlisted header fields and ordered child contents/schema
presence. No Frappe import, database, filesystem, clock, remote operation,
identity allocation, financial calculation, document save or commit exists.

This is deliberately PARTIAL. Do NOT substitute its digest for
PreparationContext.source_snapshot_sha256 or let it return True as the complete
recovery/custody source guard. It does not authenticate a tenant/site, saved
source, transaction, snapshot completeness, credential epoch, financial
correctness, signature or ZATCA acceptance. Existing guards, typed context,
journal/custody formats and all false-only verification flags stay unchanged.
No caller/button/hook/provider/default verifier uses it.

The ERP major is an explicit declaration and fingerprint domain, not detected
installed-version compatibility. Tests use synthetic metadata for both labels.
Installed ERPNext 15/16 and SDK acceptance remain separate rehearsal gates.

## Bounded capture contract

The caller supplies an already-authorized/stable document and explicit child
metadata for every PRESENT table, including empty tables. No schema is inferred
from the first row or from a truthy value. Root/child DocTypes, configured Table
options, parent/parenttype/parentfield, contiguous integer idx and unique child
identity must agree. Items and taxes tables and a small required field set must
exist; items cannot be empty under this conservative observation contract.
This is not a tax-authority validation rule.

Optional field presence is recorded independently from value. Absent, NULL,
empty string, integer zero, string zero, false, decimal zero/scale and negative
floating zero remain distinguishable. Both standard and custom advance markers
are observed if present; neither chooses or overwrites the other.

The profile covers:

| Source component | Recorded dependency families | Still outside this component |
| --- | --- | --- |
| Invoice header | Source/party/currency/time, totals/base totals, rounding, net/grand discount selectors, return/debit/POS markers, linked templates/addresses/profile, tax/exemption/type flags, prepaid/deducted aggregates and both advance markers | Referenced records, full account/GL policy, all custom extension dependencies |
| Items | Names/descriptions, quantity/UOM, rates/base/net amounts, line/distributed discounts, item template/rate JSON, account/cost center, tax/exemption markers | Referenced item/template/UOM contents and precision policy |
| Taxes | Charge type/account/rate, amounts/base/after-discount amounts, totals, included flags, row/category/cost center and exact item-wise JSON text | Linked tax-template contents and semantic tax-rule validation |
| Payments | Mode/type/account/amount/base amount/default marker | Mode-of-payment settings and payments outside the invoice-owned rows |
| Advances | Reference type/name/row, available/allocated amounts, exchange rate/date and remarks | Linked Payment Entry/source advance, ledger allocations and available balance authenticity |
| ZATCA deductions | Advance/payment/date/status/currency, available/source totals and allocated inclusive/taxable/tax amounts | Original archived XML/receipt authenticity, source locking and settlement arithmetic |

These are observed dependency families, not an exhaustive manifest for every
legacy generator, QR, advance GL writer or deployment customization.
Review the allowlists in financial_source_observation.py before expanding the
profile. A format/meaning change requires a new profile version; do not silently
reinterpret old bytes.

Values use tagged canonical scalars. No money is quantized, recalculated or
converted through binary float. Existing float values retain their exact hex
representation; Decimal retains sign/scale; text and item-wise tax JSON retain
lexical bytes after UTF-8 encoding. Dates/times/datetimes/timedeltas retain their
types without inferring timezone. This may conservatively detect representation
drift between ORM floats/strings and DB Decimal/date/time types. A future SQL
adapter must specify and test that normalization; it must not ignore mismatches.

Bounds: 2 MiB total canonical payload, 64 KiB UTF-8 per text scalar and 4,096
child rows TOTAL across tables. Nonfinite numbers, unsupported types, oversized
numbers/text and malformed typed canonical structures fail with static errors.
The protected object redacts repr and refuses pickle; generic dataclass
serialization is not a privacy sandbox and must never be used for operator
responses, queues or logs. Raw content can contain customer/payment data.

## Local dependency evidence and unresolved policies

Read-only inspection of the local v15 source confirmed invoice child Table
options for items, taxes, payments and advances. The application's deduction
DocType defines the advance/source/allocated amount fields. No installed schema
or real Company was inspected or modified.

Current createxml.py uses line net amounts/distributed discounts under explicit
selection; xml_tax_data.py reads net/base-net amounts, item-wise rates and
referenced templates; posxml.py retains separate total/base-total/net/discount
branches. The observation records inputs instead of deciding which calculation
should win or replacing financial writers.

A policy discrepancy remains for a separate parity-focused increment:
docs/zatca_tax_source_priority_contract.md describes template-before-invoice
fallback, while the current xml_tax_data._get_invoice_level_zatca_tax_source
implementation prefers nonempty invoice fields. No precedence change or old
tax-contract test rewrite is hidden in this snapshot increment. Capture BOTH
the reference and invoice fields, then resolve and test this explicitly before
unifying accounting/XML adapters.

## Next implementation gates

1. Finish the versioned dependency inventory: referenced templates/rows, party/
   address/cost-center/POS-profile settings, effective Company/device/linked
   configuration, precision/time settings and archived advance references.
2. Define physical v15/v16 schema/alias precedence and scalar normalization.
   Preserve valid zero and distinguish missing schema from missing data.
3. Build an owned committed reader with fixed allowlisted columns, root/child/
   linked-record locks, insertion/deletion/order detection and ACL/projection
   rechecks. A parent timestamp alone is not a committed financial snapshot.
4. Bind the COMPLETE verified source/settings manifest to preparation/custody;
   retain the existing explicit guard until then. Keep counter/UUID/PIH
   ownership and authority transport separate from source fingerprinting.
5. Test XML/accounting parity separately: Sales/POS, Phase 1/2, Debug/Compliance,
   discounts/returns/mixed taxes/currencies, initial/settled/historical/returned
   advances and no-previous-invoice chains. Snapshot equality is not parity.

The new tests cover every selected header/child field, unchanged-parent child
changes, insertion/deletion/reordering, both advance markers, strict schema/
parent binding, exact typed scalars, bounds, malformed payloads, protected output
and absence of writes. See [STATUS.md](STATUS.md) for executed totals. Follow
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md): no live environment changes or
authority transport are authorized, including Sandbox/Simulation.
