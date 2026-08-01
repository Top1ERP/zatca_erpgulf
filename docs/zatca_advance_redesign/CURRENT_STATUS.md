# ZATCA Advance Redesign — Current Status

## 1. Status summary

| Item | Current value |
|---|---|
| Overall status | Phase 1 complete and merged through PR `#27`; Phase 2 is the next implementation phase |
| Application | `zatca_erpgulf` |
| Initial test site | `squareangles.top1erp.com` |
| Repository state | Phase 1 merged into `main` through PR `#27` at `63f8952` |
| Audit baseline commit | `a8a6b07da3a11946fba1ee70015da18147e83ce9` |
| Phase 0 merge commit | `9b36794` |
| Application code modified | Yes — return-aware advance-deduction validation |
| Database data modified | Yes — controlled Draft `CN-RET-2026-00002` created for site verification |
| Database migration executed | No |
| Database schema modified | No |
| Legacy document deleted | No |
| Destructive cleanup started | No |
| Wider rollout approved | No |

Phase 1 corrects the ordinary Sales Invoice return regression without changing schema, legacy ZADV records, Workspaces, naming series, XML architecture, or accounting migrations.

Current official ZATCA specification verification remains pending and is still required before Phase 8 XML and compliance acceptance.

## 2. Current milestone

Current milestone:

```text
Phase 1 — Ordinary credit-note regression
```

Current activity:

```text
Prepare the independent Phase 2 branch and complete its pre-implementation audit before modifying application code.
```

Next implementation phase:

```text
Phase 2 — Standard Sales Invoice advance foundation
```

Planned next branch:

```text
feature/standard-sales-invoice-advance-core
```

## 3. Repository baseline

| Item | Value |
|---|---|
| Repository path | `/home/top1erp/erpnext-v15/frappe-bench/apps/zatca_erpgulf` |
| Phase 1 merged target branch | `main` |
| Phase 1 implementation branch base | `9b36794` |
| Phase 0 documentation commit | `63c2298` |
| Audit baseline commit | `a8a6b07da3a11946fba1ee70015da18147e83ce9` |
| Working tree before Phase 1 | Clean |

Phase 1 committed files include:

```text
zatca_erpgulf/translations/ar.csv
zatca_erpgulf/zatca_erpgulf/advance_deduction.py
zatca_erpgulf/zatca_erpgulf/tests/test_advance_deduction_return_validation.py
docs/zatca_advance_redesign/ARCHITECTURE_DECISIONS.md
docs/zatca_advance_redesign/CURRENT_STATUS.md
docs/zatca_advance_redesign/IMPLEMENTATION_PLAN.md
docs/zatca_advance_redesign/REQUIREMENTS_TRACEABILITY.md
docs/zatca_advance_redesign/TEST_MATRIX.md
```

No migration, schema deletion, ZADV deletion, Workspace deletion, naming-series change, or cross-site rollout occurred.

## 4. Runtime baseline

| Component | Version |
|---|---|
| Frappe | `15.103.0` |
| ERPNext | `15.101.2` |
| HRMS available on bench | `15.58.4` |
| `zatca_erpgulf` | `3.0` |
| Python | `3.10.14` |
| Node.js | `18.20.8` |
| npm | `10.8.2` |

Applications installed on the initial test site:

- `frappe`
- `erpnext`
- `saas_quota`
- `zatca_erpgulf`

---

## 5. Baseline test result

The recorded pre-redesign test result is:

```text
Ran 10 tests in 0.115s

OK
```

Current test status:

| Test group | Status |
|---|---|
| Existing baseline tests | Passed |
| Phase 1 regression tests | Passed — 12 focused tests |
| Phase 2 foundation tests | Not Run |
| Payment Entry tests | Not Run |
| Deferred revenue tests | Not Run |
| Deduction and multicurrency tests | Not Run |
| Credit-note reversal tests | Not Run |
| GL tests | Not Run |
| XML and QR tests | Not Run |
| Report and metadata tests | Not Run |
| Migration tests | Not Run |
| Rollback rehearsal | Not Run |

---

## 6. Documentation status

### Completed files

| File | Status |
|---|---|
| `CURRENT_STATE_AUDIT.md` | Created and integrity-checked |
| `ARCHITECTURE_DECISIONS.md` | Created and integrity-checked |
| `REQUIREMENTS_TRACEABILITY.md` | Created and integrity-checked |
| `IMPLEMENTATION_PLAN.md` | Created and integrity-checked |
| `MIGRATION_AND_ROLLBACK.md` | Created and integrity-checked |
| `TEST_MATRIX.md` | Created and integrity-checked |
| `CURRENT_STATUS.md` | Created and integrity-checked |
| `MASTER_REQUIREMENTS.md` | Created and integrity-checked |

### Remaining files

None.

### Verified documentation checks

- eight Markdown files exist;
- total documented lines before this status update were `8392`;
- no unexpected non-Markdown file exists;
- no accidental ChatGPT `id` attributes were found;
- no trailing whitespace was found;
- Markdown fences are balanced;
- all files end with a newline;
- content-integrity checks passed;
- `git diff --check` passed;
- no file content is staged yet;
- the diff contains documentation additions only.

### Documentation completion

The eight Phase 0 documents have been created, integrity-checked, reviewed as a documentation-only diff, and prepared as one documentation change.

No application source file, database record, schema object, Workspace, File, Series, or legacy document was changed during Phase 0.

---

## 7. Initial-site Company state

Company:

```text
Square Angles Contacting Company
```

Current relevant values:

| Field | Value |
|---|---|
| Company abbreviation | `SA` |
| `custom_zatca_invoice_enabled` | `1` |
| `custom_phase_1_or_2` | `Phase-1` |
| `custom_select` | `Production` |
| `custom_send_invoice_to_zatca` | `Live` |

Compatibility phase field on this site:

```text
phase_1_or_2
```

Status:

```text
Missing
```

---

## 8. Obsolete Company fields

The following obsolete advance-specific Company fields still exist:

```text
custom_zatca_advance_payment_section
custom_zatca_advance_payment_enabled
custom_zatca_advance_default_tc_name
custom_zatca_advance_payment_submission_mode
custom_zatca_advance_signing_enabled
custom_zatca_advance_api_submission_enabled
```

Current status:

| Concern | Status |
|---|---|
| Code references removed | No |
| JavaScript references removed | No |
| Property Setter creation removed | No |
| Fixture references removed | No |
| Translation references removed | No |
| Custom Fields deleted | No |
| Physical columns removed | No |
| Values migrated | Not planned |

These fields must remain until all runtime and setup dependencies are removed.

---

## 9. Canonical advance marker

Approved canonical marker:

```text
is_advance_payment
```

Initial test-site state:

| Field | Status |
|---|---|
| `is_advance_payment` | Missing |
| `custom_is_advance_payment` | Missing |

Approved guard:

1. reuse `is_advance_payment` when present;
2. inspect `custom_is_advance_payment`;
3. create no duplicate;
4. create `is_advance_payment` only when neither exists;
5. keep temporary compatibility where required.

Implementation status:

```text
Not started
```

---

## 10. Payment Entry relationship

Approved new relationship:

```text
Sales Invoice.custom_zatca_payment_entry
    → Payment Entry
```

Initial test-site state:

```text
custom_zatca_payment_entry is missing
```

Legacy relationship still present:

```text
Payment Entry.custom_zatca_advance_tax_invoice
    → ZATCA Advance Tax Invoice
```

Implementation status:

```text
Not started
```

---

## 11. Legacy schema links

The following schema links still point to the legacy DocType:

1. `Payment Entry.custom_zatca_advance_tax_invoice`
2. `Sales Invoice.custom_advance_invoice_reference`
3. `ZATCA Sales Invoice Advance Deduction.zatca_advance_tax_invoice`

Current status:

```text
Not migrated
```

The legacy DocType cannot be removed while these links remain.

---

## 12. Legacy ZADV state

Legacy document:

```text
ZADV-SA-2026-00001
```

Key values:

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
| Type code | `386` |
| Status | `Final` |
| ZATCA status | `Phase 1 QR Created` |
| UUID | None |

Current cleanup status:

| Action | Status |
|---|---|
| Pre-removal backup | Not created |
| Destructive dry run | Not executed |
| Payment Entry fields cleared | No |
| QR File removed | No |
| ZADV document deleted | No |
| Print Format removed | No |
| Legacy DocType removed | No |
| Legacy Series removed | No |

---

## 13. Legacy dependency state

Confirmed dependencies:

- one linked Payment Entry;
- one QR File;
- one attachment Comment;
- two Version records;
- one Series record.

Not found in the audit:

- ZADV GL Entries;
- standard Sales Invoice Advance allocations;
- custom deduction rows referencing the legacy document;
- Communications;
- ToDos.

The legacy document is not an orphan because active dependency records still exist.

---

## 14. Workspace state

Current public Workspaces:

```text
ZATCA
ZATCA ERPGulf
```

Approved target:

| Workspace | Target state |
|---|---|
| `ZATCA` | Keep |
| `ZATCA ERPGulf` | Remove and prevent recreation |

Implementation status:

```text
Not started
```

---

## 15. Naming-series state

Current Sales Invoice options:

```text
SINV-.YYYY.-
CN-RET-.YYYY.-.
DN-.YYYY.-
```

Approved future option:

```text
ADV-.abbr.-.YYYY.-
```

Current status:

```text
No Sales Invoice naming-series line contains ADV.
```

Implementation status:

```text
Not started
```

---

## 16. Abbreviation-field state

None of the twelve target DocTypes has either:

```text
abbr
custom_abbr
```

on the initial test site.

Target DocTypes:

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

Implementation status:

```text
Not started
```

---

## 17. Critical regression resolution

Original problem:

```text
Advance total 0.00 exceeds Sales Invoice total -36000.00
```

Root cause:

- `validate_sales_invoice_advance_deductions` runs for every Sales Invoice;
- ordinary returns contain negative invoice totals;
- the old positive-invoice limit compared a zero or positive advance total against a negative return total;
- VAT extraction considered only positive tax rows, which is appropriate for positive final invoices but not a valid return-invoice limit.

Implemented behavior:

- ordinary returns bypass positive final-invoice advance-deduction calculations;
- return signs remain negative and are not normalized with a blind `abs()`;
- zero allocations do not trigger ZATCA advance lookup;
- positive allocations linked to the legacy ZATCA advance flow are blocked on returns;
- derived advance-deduction rows and totals are cleared for returns;
- positive final-invoice VAT and total limits remain active;
- `advance_credit_note.py` continues to validate valid and excessive advance credit notes.

Verification evidence:

```text
12 focused Phase 1 tests passed
10 existing regression tests passed
22 total automated tests passed
py_compile passed
Arabic translation count = 1
Draft site save passed: CN-RET-2026-00002 against SINV-2026-00024
```

Remaining manual smoke tests:

- site Submit of an otherwise valid ordinary credit note;
- site Cancel and GL reversal;
- site Submit of an ordinary positive invoice.

Status:

```text
Complete and merged through PR `#27` at merge commit `63f8952`; automated validation and Draft site-save evidence are recorded.
```

## 18. Phase status table

| Phase | Scope | Status |
|---|---|---|
| Phase 0 | Audit and planning | Complete and merged |
| Phase 1 | Ordinary credit-note regression | Complete — merged through PR `#27` at `63f8952` |
| Phase 2 | Standard Sales Invoice foundation | Not started |
| Phase 3 | Payment Entry linkage | Not started |
| Phase 4 | Deferred revenue validation | Not started |
| Phase 5 | Deduction and multicurrency | Not started |
| Phase 6 | Credit-note reversals | Not started |
| Phase 7 | Final-invoice GL | Not started |
| Phase 8 | XML, QR, and debug generation | Not started |
| Phase 9A | Advance settlement report | Not started |
| Phase 9B | Workspace deduplication | Not started |
| Phase 9C | Phase 2 visibility | Not started |
| Phase 9D | Company abbreviation fields | Not started |
| Phase 9E | ADV naming series | Not started |
| Phase 10 | Legacy ZADV removal | Not started |
| Phase 11 | Full regression and rollout | Not started |

---

## 19. Branch plan

| Concern | Planned branch |
|---|---|
| Integration | `epic/zatca-standard-advance-invoices` |
| Credit-note regression | `fix/return-credit-note-advance-validation` |
| Standard advance foundation | `feature/standard-sales-invoice-advance-core` |
| Payment Entry link | `feature/advance-payment-entry-link` |
| Income Account validation | `feature/advance-income-account-validation` |
| Deduction and multicurrency | `feature/advance-deduction-multicurrency` |
| Credit-note reversal | `feature/advance-credit-note-reversal` |
| Final-invoice GL | `feature/advance-final-invoice-gl` |
| XML and QR | `feature/advance-zatca-xml` |
| Report | `feature/advance-report` |
| Workspace | `fix/zatca-workspace-deduplication` |
| Phase 2 visibility | `feature/zatca-phase2-field-visibility` |
| Abbreviation fields | `feature/company-abbr-fields` |
| Naming series | `feature/advance-sales-invoice-naming-series` |
| Legacy removal | `refactor/remove-zadv-doctype` |

---

## 20. Regulatory verification status

The following implementation decisions require verification against current official ZATCA documents before Phase 8 completion:

- initial advance invoice type code;
- final settlement invoice type code;
- credit-note type code;
- standard and simplified invoice type names;
- multiple `DocumentReference` structure;
- `PrepaidAmount` treatment;
- VAT adjustment grouping;
- Phase 2 clearance and reporting behavior.

Current status:

```text
Pending external official-source verification
```

Repository and site audit completion does not replace regulatory-source verification.

---

## 21. Current restrictions

During Phase 1 final review:

- do not run `bench migrate`;
- do not delete Custom Fields;
- do not delete Property Setters;
- do not delete Workspaces;
- do not delete the legacy ZADV document;
- do not delete its QR File;
- do not clear linked Payment Entry fields;
- do not remove the old DocType;
- do not change naming series;
- do not deploy the redesign to other tenant sites;
- do not combine Phase 2 work into this branch.

## 22. Current verification commands

Phase 1 final review must include:

```bash
python -m py_compile \
  zatca_erpgulf/zatca_erpgulf/advance_deduction.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_advance_deduction_return_validation.py

git diff --check
git status --short
git diff --stat
git diff --name-status
git --no-pager diff
```

Automated evidence must retain:

```text
Ran 12 tests — OK
Ran 5 tests — OK
Ran 5 tests — OK
```

The site verification record is:

```text
squareangles.top1erp.com
Draft Credit Note: CN-RET-2026-00002
Return Against: SINV-2026-00024
Save result: Passed
```

## 23. Documentation outcome

All eight Phase 0 documentation files exist and have passed:

- file-count verification;
- line-count verification;
- final-newline checks;
- trailing-whitespace checks;
- Markdown-fence checks;
- accidental-paste checks;
- content-integrity checks;
- staged diff checks.

The Phase 1 implementation merge contained only the eight approved files listed above.

---

## 24. Immediate next implementation action

The next implementation phase is:

```text
Phase 2 — Standard Sales Invoice advance foundation
```

Create the independent branch from the latest `main`:

```text
feature/standard-sales-invoice-advance-core
```

Before modifying application code:

1. confirm `main` is clean and synchronized with `origin/main`;
2. audit the existing standard Sales Invoice advance paths;
3. map Phase 2 requirements to the current implementation;
4. define the Phase 2 acceptance tests;
5. keep Payment Entry linkage, deferred revenue, multicurrency settlement,
   credit-note reversal, XML redesign, and legacy deletion outside the
   Phase 2 branch unless explicitly approved.

No Phase 2 implementation belongs in the Phase 1 closure branch.

## 25. Completion statement

Phase 0 audit and planning documentation was merged through PR `#26`.

Phase 1 ordinary credit-note regression work is complete and merged:

| Item | Value |
|---|---|
| Implementation branch | `fix/return-credit-note-advance-validation` |
| Implementation commit | `882cac5ce7673ab33deff4f0169e19c570e802a9` |
| Pull Request | `#27` |
| Merge commit | `63f8952cc4e0337ba0554889b239e9f62c1752e5` |
| Merged at | `2026-08-01T00:18:57Z` |
| Target branch | `main` |
| Focused tests | 12 passed |
| Existing regression tests | 10 passed |
| Total automated tests | 22 passed |
| Draft site save | Passed — `CN-RET-2026-00002` |
| Migration or schema change | None |

Manual site Submit, Cancel, and GL-reversal smoke tests remain explicitly
recorded as not run. They are not represented as completed evidence.

Current official ZATCA verification remains a mandatory later gate before
Phase 8 XML and compliance acceptance.

The next implementation phase is Phase 2 on an independent branch created
from the updated `main`.
