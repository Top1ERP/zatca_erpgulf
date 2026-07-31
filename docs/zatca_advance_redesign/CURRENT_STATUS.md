# ZATCA Advance Redesign — Current Status

## 1. Status summary

| Item | Current value |
|---|---|
| Overall status | Phase 0 documentation complete; implementation not started |
| Application | `zatca_erpgulf` |
| Initial test site | `squareangles.top1erp.com` |
| Current branch | `audit/zatca-advance-current-state` |
| Baseline commit | `a8a6b07da3a11946fba1ee70015da18147e83ce9` |
| Application code modified | No |
| Database data modified | No |
| Database migration executed | No |
| Legacy document deleted | No |
| Destructive cleanup started | No |
| Wider rollout approved | No |

The repository and initial-site read-only audit are complete.

The external verification of current official ZATCA specifications is still pending and must be completed before final XML compliance decisions are accepted.

---

## 2. Current milestone

Current milestone:

```text
Phase 0 — Audit and planning
```

Current activity:

```text
Prepare Phase 1 ordinary credit-note regression implementation.
```

Immediate implementation after documentation approval:

```text
Phase 1 — Ordinary credit-note regression
```

Planned branch:

```text
fix/return-credit-note-advance-validation
```

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

The current uncommitted changes are documentation files under:

```text
docs/zatca_advance_redesign/
```

No application source file has been intentionally modified during Phase 0.

---

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
| Phase 1 regression tests | Not Run |
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

## 17. Critical known regression

Problem:

```text
Advance total 0.00 exceeds Sales Invoice total -36000.00
```

Impact:

An ordinary Sales Invoice credit note may be blocked when the advance deduction table is empty or zero.

Approved correction scope:

- ordinary credit note without deductions must pass;
- empty or zero deductions must not trigger comparison with a negative total;
- positive final-invoice limits must remain active;
- advance reversal controls must remain active;
- no broad bypass;
- no blind absolute-value conversion.

Status:

```text
Confirmed and documented; fix not started
```

---

## 18. Phase status table

| Phase | Scope | Status |
|---|---|---|
| Phase 0 | Audit and planning | In progress |
| Phase 1 | Ordinary credit-note regression | Not started |
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

Until Phase 0 is completed and reviewed:

- do not run `bench migrate`;
- do not delete Custom Fields;
- do not delete Property Setters;
- do not delete Workspaces;
- do not delete the legacy ZADV document;
- do not delete its QR File;
- do not clear linked Payment Entry fields;
- do not remove the old DocType;
- do not change naming series;
- do not deploy redesign changes to other sites.

---

## 22. Current verification commands

After all documentation files are created, the review must include:

```bash
git status --short
find docs/zatca_advance_redesign -maxdepth 1 -type f -name '*.md' -printf '%f\n' | sort
wc -l docs/zatca_advance_redesign/*.md
```

Because the files are currently untracked, ordinary `git diff` does not show their contents.

Review untracked files with an appropriate no-index diff or add intent-to-add only after deciding to do so.

No documentation commit should be created before:

- all files exist;
- their endings are complete;
- formatting is checked;
- content is reviewed.

---

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

The committed documentation change must contain only these eight files.

---

## 24. Immediate next implementation action

After all Phase 0 documentation is reviewed and committed:

1. create or update the integration baseline;
2. create:

```text
fix/return-credit-note-advance-validation
```

3. implement only the ordinary credit-note regression fix;
4. add focused tests;
5. run the baseline and regression tests;
6. review the full diff;
7. update status, traceability, decisions, and test documents.

---

## 25. Completion statement

Phase 0 audit and planning documentation is complete.

No implementation or destructive migration has started.

Current official ZATCA verification remains a mandatory later gate before Phase 8 XML and compliance acceptance.
