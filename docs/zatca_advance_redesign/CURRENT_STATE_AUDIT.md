# ZATCA Advance Redesign — Current-State Audit

## 1. Document status

| Item | Value |
|---|---|
| Status | Complete |
| Audit date | 2026-07-29 |
| Application | `zatca_erpgulf` |
| Initial test site | `squareangles.top1erp.com` |
| Audit branch | `audit/zatca-advance-current-state` |
| Application code changed | No |
| Database data changed | No |
| Database migration executed | No |
| Legacy document deleted | No |

This document records the verified repository, metadata, database, and test state before implementing the standard Sales Invoice advance-payment redesign.

---

## 2. Audit scope

The audit covered:

- Git repository baseline;
- installed application versions;
- existing automated tests;
- advance-payment code references;
- hooks and execution paths;
- Company ZATCA settings;
- Sales Invoice advance-related fields;
- Payment Entry advance-related fields;
- legacy `ZATCA Advance Tax Invoice` records;
- attached files and QR artifacts;
- GL Entries;
- advance allocations;
- deduction child rows;
- Comments, Communications, Versions, and ToDo records;
- schema links to the legacy DocType;
- naming series;
- ZATCA Workspaces, Dashboards, and Reports;
- `abbr` and `custom_abbr` fields on the twelve target DocTypes.

The audit was read-only.

---

## 3. Repository baseline

| Item | Value |
|---|---|
| Repository path | `/home/top1erp/erpnext-v15/frappe-bench/apps/zatca_erpgulf` |
| Branch | `audit/zatca-advance-current-state` |
| Baseline commit | `a8a6b07da3a11946fba1ee70015da18147e83ce9` |
| Baseline short commit | `a8a6b07` |
| Origin divergence at audit start | `0 0` |
| Working tree before documentation | Clean |

The baseline commit contains the merged ZATCA layout and ZADV naming-series regression tests from pull request number 25.

---

## 4. Runtime environment

| Component | Version |
|---|---|
| Frappe | `15.103.0` |
| ERPNext | `15.101.2` |
| HRMS available on bench | `15.58.4` |
| ZATCA application | `3.0` |
| Python | `3.10.14` |
| Node.js | `18.20.8` |
| npm | `10.8.2` |

Applications installed on `squareangles.top1erp.com`:

- `frappe`
- `erpnext`
- `saas_quota`
- `zatca_erpgulf`

---

## 5. Baseline tests

The pre-redesign baseline test run completed successfully:

```text
Ran 10 tests in 0.115s

OK
```

This result is the reference baseline for all subsequent implementation phases.

A later phase must not be accepted when these tests regress without an explicitly approved change to the expected behavior.

---

## 6. Existing general Company ZATCA controls

The following general ZATCA controls exist on Company:

| Fieldname | Fieldtype | Physical column |
|---|---|---|
| `custom_zatca_invoice_enabled` | Check | Yes |
| `custom_select` | Select | Yes |
| `custom_phase_1_or_2` | Select | Yes |
| `custom_send_invoice_to_zatca` | Select | Yes |

The compatibility field:

```text
phase_1_or_2
```

does not exist on `squareangles.top1erp.com`.

The redesigned application must nevertheless support it as a fallback on sites where it exists.

---

## 7. Square Angles Company configuration

Company:

```text
Square Angles Contacting Company
```

Current general ZATCA values:

| Field | Value |
|---|---|
| Company abbreviation | `SA` |
| `custom_zatca_invoice_enabled` | `1` |
| `custom_phase_1_or_2` | `Phase-1` |
| `custom_select` | `Production` |
| `custom_send_invoice_to_zatca` | `Live` |

The redesigned advance workflow will use these general controls.

---

## 8. Obsolete Company advance settings

The following six obsolete Custom Fields currently exist:

1. `custom_zatca_advance_payment_section`
2. `custom_zatca_advance_payment_enabled`
3. `custom_zatca_advance_default_tc_name`
4. `custom_zatca_advance_payment_submission_mode`
5. `custom_zatca_advance_signing_enabled`
6. `custom_zatca_advance_api_submission_enabled`

### Physical schema

| Fieldname | Fieldtype | Custom Field exists | Physical column exists |
|---|---|---:|---:|
| `custom_zatca_advance_payment_section` | Section Break | Yes | No |
| `custom_zatca_advance_payment_enabled` | Check | Yes | Yes |
| `custom_zatca_advance_default_tc_name` | Link | Yes | Yes |
| `custom_zatca_advance_payment_submission_mode` | Select | Yes | Yes |
| `custom_zatca_advance_signing_enabled` | Check | Yes | Yes |
| `custom_zatca_advance_api_submission_enabled` | Check | Yes | Yes |

The Section Break correctly has no physical database column because it is a layout field.

### Current Square Angles values

| Field | Value |
|---|---|
| Advance workflow enabled | `1` |
| Advance submission mode | `Submit to ZATCA` |
| Advance signing enabled | `1` |
| Advance API submission enabled | `0` |
| Advance default terms template | `Albilad Bank` |

These values are not authoritative for the redesigned workflow and will not be migrated.

The current Company is configured as Phase 1 through the general phase field, while the obsolete advance settings independently contain submission and signing choices. This confirms that the advance-specific switches create a second, potentially conflicting configuration path.

---

## 9. Obsolete Company field references

The obsolete fields are currently referenced in:

- `setup_customizations.py`;
- legacy advance-payment JavaScript;
- legacy advance-payment controller code;
- advance debug-generation code;
- Property Setters;
- translation records;
- layout and customization synchronization logic.

The fields must not be deleted before removing all runtime and synchronization references.

Required removal order:

1. replace code dependencies;
2. replace UI dependencies;
3. remove Property Setter creation;
4. remove fixture and synchronization references;
5. remove translations;
6. delete Custom Field and Property Setter records;
7. migrate the schema;
8. verify that no code or metadata reference remains.

---

## 10. Approved replacement for obsolete Company settings

The standard advance Sales Invoice workflow will use:

```text
custom_zatca_invoice_enabled
```

as the master ZATCA enablement control.

The phase resolver will use:

```text
custom_phase_1_or_2
```

with compatibility fallback to:

```text
phase_1_or_2
```

when the fallback field exists.

The environment will continue to use:

```text
custom_select
```

The existing B2C/POS submission method will continue to use:

```text
custom_send_invoice_to_zatca
```

There will be no separate advance-only controls for:

- local-only mode;
- signing;
- API submission;
- default Terms and Conditions.

---

## 11. Canonical Sales Invoice advance marker

The following fields do not exist on `squareangles.top1erp.com`:

- `is_advance_payment`
- `custom_is_advance_payment`

The user confirmed that `is_advance_payment` exists on other sites.

The canonical marker for the redesign is therefore:

```text
is_advance_payment
```

Required metadata:

| Property | Value |
|---|---|
| Label | `Is Advance Payment Invoice` |
| Fieldname | `is_advance_payment` |
| Fieldtype | `Check` |
| Insert after | `is_debit_note` |
| No Copy | `1` |

Installation and update logic must:

1. use existing `is_advance_payment` when present;
2. check for existing `custom_is_advance_payment`;
3. avoid adding duplicate marker fields;
4. create `is_advance_payment` only when neither field exists;
5. use temporary compatibility logic when an existing site depends on `custom_is_advance_payment`;
6. never create `custom_is_advance_payment` on new sites.

---

## 12. Existing relevant Sales Invoice fields

The following relevant fields exist:

| Fieldname | Status |
|---|---|
| `is_debit_note` | Exists |
| `is_return` | Exists |
| `return_against` | Exists |
| `custom_is_advance_credit_note` | Exists |
| `custom_advance_invoice_reference` | Exists |
| `custom_zatca_advance_deduction_details` | Exists |
| `custom_zatca_status_notification` | Exists |
| `custom_uuid` | Exists |

The following required fields are absent on the initial test site:

| Fieldname | Status |
|---|---|
| `is_advance_payment` | Missing |
| `custom_is_advance_payment` | Missing |
| `custom_zatca_payment_entry` | Missing |

---

## 13. Existing legacy schema links

Three schema links currently point to:

```text
ZATCA Advance Tax Invoice
```

### Payment Entry link

```text
Payment Entry.custom_zatca_advance_tax_invoice
```

Current options:

```text
ZATCA Advance Tax Invoice
```

### Sales Invoice reference link

```text
Sales Invoice.custom_advance_invoice_reference
```

Current options:

```text
ZATCA Advance Tax Invoice
```

### Deduction child-table link

```text
ZATCA Sales Invoice Advance Deduction.zatca_advance_tax_invoice
```

Current options:

```text
ZATCA Advance Tax Invoice
```

These links must be migrated, replaced, or removed before deleting the legacy DocType.

---

## 14. Legacy advance DocType and print format

The following legacy DocType exists:

```text
ZATCA Advance Tax Invoice
```

One active standard Jinja Print Format exists:

| Property | Value |
|---|---|
| Name | `ZATCA Advance Tax Invoice` |
| DocType | `ZATCA Advance Tax Invoice` |
| Module | `Zatca Erpgulf` |
| Standard | `Yes` |
| Disabled | `0` |
| Print format type | `Jinja` |

The Print Format must be removed as part of the final legacy-removal phase, after the workflow is moved to standard Sales Invoice.

---

## 15. Legacy ZADV document

One legacy document exists:

```text
ZADV-SA-2026-00001
```

### Main values

| Property | Value |
|---|---|
| Company | `Square Angles Contacting Company` |
| Customer | `Nour Al-Hadaf Construction Co` |
| Payment Entry | `ACC-PAY-2026-00028` |
| Posting date | `2026-06-29` |
| Currency | `SAR` |
| Taxable amount | `188866.20` |
| Tax amount | `28329.93` |
| Total amount | `217196.13` |
| Base taxable amount | `188866.20` |
| Base tax amount | `28329.93` |
| Base total amount | `217196.13` |
| Invoice type code | `386` |
| Status field | `Final` |
| ZATCA status | `Phase 1 QR Created` |
| ZATCA UUID | None |
| Full response | None |

The document represents a Phase 1 advance tax invoice.

---

## 16. Legacy QR artifact

The document has one attached public QR File:

```text
/files/QR-Phase1-ZATCA-Advance-ZADV-SA-2026-00001.png
```

File details:

| Property | Value |
|---|---|
| File name | `QR-Phase1-ZATCA-Advance-ZADV-SA-2026-00001.png` |
| Attached field | `qr_code` |
| Private | `0` |
| File size | `564` bytes |
| File record | `3502a8b3b9` |

The file must be preserved in the pre-removal backup and removed or detached using Frappe document APIs during controlled cleanup.

---

## 17. Linked Payment Entry

The legacy ZADV document is linked to:

```text
ACC-PAY-2026-00028
```

Important Payment Entry values:

| Property | Value |
|---|---|
| Company | `Square Angles Contacting Company` |
| Payment type | `Receive` |
| Party type | `Customer` |
| Party | `Nour Al-Hadaf Construction Co` |
| Posting date | `2026-06-29` |
| Paid amount | `217196.13` |
| Received amount | `217196.13` |
| Source exchange rate | `1.0` |
| Target exchange rate | `1.0` |
| Legacy advance marker | `1` |
| Legacy advance invoice | `ZADV-SA-2026-00001` |
| Legacy advance status | `Phase 1 QR Created` |
| Legacy UUID | None |

The legacy Payment Entry fields must not be cleared until the cleanup phase has:

1. created an audit snapshot;
2. taken a site backup;
3. repeated the reference audit;
4. confirmed that no new settlement depends on the document.

---

## 18. Advance allocations and deduction references

No standard Sales Invoice Advance allocations reference the linked Payment Entry:

```text
Count: 0
```

No rows in the custom advance deduction child table reference the legacy document:

```text
Count: 0
```

This indicates that the advance has not been allocated through either audited settlement mechanism.

---

## 19. Accounting entries

No GL Entries exist with:

```text
voucher_type = ZATCA Advance Tax Invoice
voucher_no = ZADV-SA-2026-00001
```

Result:

```text
Count: 0
```

The legacy ZADV document is therefore not itself an accounting voucher in the audited state.

The linked Payment Entry remains a separate accounting document and must not be deleted as part of removing the ZADV document.

---

## 20. Other legacy document dependencies

### Dependencies found

- one linked Payment Entry;
- one QR File;
- one attachment Comment;
- two Version records;
- one legacy Series record.

### Comments

One Attachment Comment exists for:

```text
ZADV-SA-2026-00001
```

### Versions

Two Version records exist:

| Owner | Creation |
|---|---|
| `joseph.rouphaiel@sqmc-sa.com` | `2026-07-26 13:04:27.005516` |
| `Administrator` | `2026-07-26 13:15:00.505038` |

### Dependencies not found

- no GL Entries;
- no standard Sales Invoice Advance allocations;
- no custom advance deduction rows;
- no Communications;
- no ToDo references.

The document may be eligible for controlled removal, but it is not an orphan because the Payment Entry, QR File, Comment, Versions, and Series still exist.

---

## 21. Legacy naming series

The legacy Series record is:

```text
ZADV-SA-2026-
```

Current value:

```text
1
```

Current Sales Invoice naming-series options are:

```text
SINV-.YYYY.-
CN-RET-.YYYY.-.
DN-.YYYY.-
```

No existing Sales Invoice naming-series option contains the substring:

```text
ADV
```

The approved future Sales Invoice naming series is:

```text
ADV-.abbr.-.YYYY.-
```

It must be added only when no existing Sales Invoice naming-series line contains `ADV`.

---

## 22. Workspace duplication

Two public ZATCA Workspaces currently exist:

| Name | Label | Module | Public | Hidden |
|---|---|---|---:|---:|
| `ZATCA` | `ZATCA` | `Zatca Erpgulf` | `1` | `0` |
| `ZATCA ERPGulf` | `ZATCA ERPGulf` | `Zatca Erpgulf` | `1` | `0` |

The canonical Workspace is:

```text
ZATCA
```

The obsolete duplicate is:

```text
ZATCA ERPGulf
```

The application currently contains fixture behavior capable of recreating the obsolete Workspace. Both fixture selection and synchronization logic must be corrected.

---

## 23. Existing ZATCA dashboard and reports

The following ZATCA Dashboard exists:

```text
ZATCA Dashboard
```

Existing reports identified during the audit include:

- `ZATCA POS Invoices with warnings`
- `ZATCA Sales Invoices with warnings`
- `Zatca Status Report`

The future advance settlement report must be placed in the canonical `ZATCA` Workspace below:

```text
ZATCA POS Invoices with warnings
```

---

## 24. Abbreviation-field audit

The following twelve target DocTypes contain neither `abbr` nor `custom_abbr` on `squareangles.top1erp.com`:

1. Sales Invoice
2. Purchase Invoice
3. Journal Entry
4. Payment Entry
5. Purchase Order
6. Material Request
7. Request for Quotation
8. Supplier Quotation
9. Quotation
10. Sales Order
11. Blanket Order
12. Payment Request

This result applies only to the initial test site.

Installation and update logic must independently check both fieldnames on every site:

```text
abbr
custom_abbr
```

When either field exists, no new abbreviation field may be added.

An existing `custom_abbr` must not be renamed.

---

## 25. Current critical credit-note regression

The current advance deduction validation can incorrectly block an ordinary negative Sales Invoice return.

Observed validation message:

```text
Advance total 0.00 exceeds Sales Invoice total -36000.00
```

The problematic behavior compares:

- a zero or empty advance deduction amount; against
- a negative return invoice total.

The correction must satisfy all of the following:

1. an ordinary credit note without advance deductions is not blocked;
2. an empty deduction table is not blocked;
3. a zero deduction total is not compared against a negative invoice total;
4. positive final-invoice deduction limits remain enforced;
5. valid advance-credit-note reversal controls remain enforced;
6. the correction must not use a broad unconditional bypass;
7. the correction must not blindly convert every value to an absolute value.

This regression is the first implementation concern after the audit documentation is merged.

---

## 26. Audit conclusions

The current custom advance-payment implementation is distributed across:

- a custom ZADV DocType;
- a custom Print Format;
- Company fields;
- Payment Entry fields;
- Sales Invoice fields;
- deduction child-table fields;
- Python controllers;
- JavaScript;
- hooks;
- XML and QR generation;
- Property Setters;
- translations;
- fixtures;
- tests;
- Workspace records.

Deleting the legacy DocType or Company fields before replacing these dependencies would create broken metadata, runtime errors, or migration failures.

The safe implementation sequence is:

1. document and approve the current state;
2. fix the ordinary credit-note regression;
3. establish the standard Sales Invoice advance foundation;
4. add optional Payment Entry linkage;
5. implement deferred-revenue validation;
6. migrate deduction logic to standard Sales Invoices;
7. implement credit-note reversals;
8. implement and verify final-invoice GL behavior;
9. update XML, QR, and debug-generation logic;
10. add the report and normalize Workspaces and fields;
11. remove the legacy ZADV implementation;
12. complete full regression and rollout testing.

---

## 27. Read-only audit declaration

During this audit:

- no Sales Invoice was changed;
- no Payment Entry was changed;
- no Company field was deleted;
- no Custom Field was deleted;
- no Property Setter was deleted;
- no Workspace was deleted;
- no QR File was deleted;
- no ZADV document was deleted;
- no Series record was deleted;
- no migration was executed;
- no application behavior was changed.

The repository and site audit is complete enough to proceed to architecture and implementation documentation.
