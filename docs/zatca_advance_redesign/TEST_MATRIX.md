# ZATCA Advance Redesign — Test Matrix

## 1. Document status

| Item | Value |
|---|---|
| Status | Active |
| Application | `zatca_erpgulf` |
| Initial test site | `squareangles.top1erp.com` |
| Audit document | `CURRENT_STATE_AUDIT.md` |
| Decisions document | `ARCHITECTURE_DECISIONS.md` |
| Traceability document | `REQUIREMENTS_TRACEABILITY.md` |
| Implementation plan | `IMPLEMENTATION_PLAN.md` |
| Migration document | `MIGRATION_AND_ROLLBACK.md` |
| Current branch | `fix/return-credit-note-advance-validation` |

This document defines the required automated, integration, site, accounting, XML, QR, migration, rollback, and regression tests for the standard Sales Invoice advance-payment redesign.

A phase is not complete until:

1. its required tests are executed;
2. all critical tests pass;
3. failures are explained and approved;
4. test evidence is recorded;
5. the related Git diff is reviewed;
6. affected project documents are updated.

---

## 2. Test status values

| Status | Meaning |
|---|---|
| `Not Run` | Test has not been executed |
| `Passed` | Actual result matches expected result |
| `Failed` | Actual result does not match expected result |
| `Blocked` | Test cannot run because a prerequisite is missing |
| `Not Applicable` | Test does not apply to the selected phase or site |
| `Pending Review` | Output exists but requires technical or accounting review |

---

## 3. Severity levels

| Severity | Meaning |
|---|---|
| Critical | Data loss, accounting imbalance, invalid ZATCA submission, broken submit/cancel, or cross-site impact |
| High | Incorrect balance, wrong eligibility, duplicate invoice, broken migration, or major workflow failure |
| Medium | Incorrect UI visibility, metadata, report value, or noncritical compatibility issue |
| Low | Cosmetic, wording, ordering, or documentation issue |

Any Critical failure blocks phase completion and rollout.

---

## 4. Test environments

### 4.1 Repository baseline

| Item | Value |
|---|---|
| Repository | `zatca_erpgulf` |
| Baseline commit | `a8a6b07da3a11946fba1ee70015da18147e83ce9` |
| Baseline branch | `audit/zatca-advance-current-state` |
| Baseline tests | 10 passed |
| Baseline result | `Ran 10 tests in 0.115s — OK` |

### 4.2 Initial test site

```text
squareangles.top1erp.com
```

### 4.3 Initial Company

```text
Square Angles Contacting Company
```

### 4.4 Initial legacy document

```text
ZADV-SA-2026-00001
```

### 4.5 Initial linked Payment Entry

```text
ACC-PAY-2026-00028
```

### 4.6 Additional environment classes required later

- clean test site;
- migrated Phase 1 site;
- migrated Phase 2 B2B site;
- migrated Phase 2 B2C site;
- multi-currency site;
- site containing existing `is_advance_payment`;
- site containing existing `custom_is_advance_payment`;
- site containing existing `abbr`;
- site containing existing `custom_abbr`;
- site containing an existing ADV naming-series option.

---

## 5. Test-data policy

### 5.1 Production-like testing

Initial testing may use the audited Square Angles configuration, but destructive test data must be controlled and documented.

### 5.2 No unapproved tenant impact

Do not create, submit, cancel, migrate, or delete advance documents on other tenant sites without explicit approval.

### 5.3 Reusable fixtures

Automated tests should create their own isolated documents and clean them up using supported test mechanisms.

### 5.4 Deterministic values

Use stable values for:

- tax rates;
- exchange rates;
- invoice totals;
- advance amounts;
- credit-note amounts;
- posting dates;
- expected GL values;
- expected XML values.

---

## 6. Baseline regression suite

| ID | Test | Severity | Expected result | Status |
|---|---|---|---|---|
| BASE-001 | Run existing `zatca_erpgulf` test suite before changes | Critical | All baseline tests pass | Passed |
| BASE-002 | Run baseline suite after each phase | Critical | No unexplained regression | Passed |
| BASE-003 | Compile changed Python files | High | No syntax or import error | Passed |
| BASE-004 | Validate changed JSON files | High | Valid JSON | Not Applicable |
| BASE-005 | Run `git diff --check` | High | No whitespace or conflict errors | Passed after final-newline normalization |
| BASE-006 | Review changed-file list | High | Only intended files changed | Passed |
| BASE-007 | Review full phase diff | High | No unrelated behavior change | Passed |

---

## 7. Phase 1 — Ordinary credit-note regression tests

### 7.1 Automated validation tests

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| CN-R-001 | Ordinary return invoice with no deduction rows | Critical | Save and submit are not blocked by advance-total validation | Passed — automated validation; site Submit remains CN-S-001 Not Run |
| CN-R-002 | Ordinary return invoice with empty deduction child table | Critical | No advance-total comparison occurs | Passed |
| CN-R-003 | Ordinary return invoice with zero-value child rows | Critical | Zero total is not compared with negative invoice total | Passed |
| CN-R-004 | Positive final invoice with deduction above total | Critical | Validation blocks the document | Passed |
| CN-R-005 | Positive final invoice with valid deduction | Critical | Validation passes | Passed |
| CN-R-006 | Advance-related credit note with valid reversal | High | Advance reversal validation remains active | Passed |
| CN-R-007 | Advance-related credit note above reversible amount | Critical | Validation blocks excessive reversal | Passed |
| CN-R-008 | Ordinary non-return invoice without deductions | High | Existing submit behavior remains unchanged | Passed — automated validation; site Submit remains CN-S-003 Not Run |

### 7.2 Code-review checks

| ID | Check | Severity | Expected result | Status |
|---|---|---|---|---|
| CN-C-001 | No unconditional bypass for every return | High | Condition is narrow and contextual | Passed |
| CN-C-002 | No blind `abs()` normalization | High | Signs retain business meaning | Passed |
| CN-C-003 | Positive-invoice limit still executes | Critical | Existing protection remains | Passed |
| CN-C-004 | No database or schema change in Phase 1 | High | Diff contains validation and tests only | Passed |

### 7.3 Site smoke tests

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| CN-S-001 | Create ordinary credit note on test site | Critical | Submit succeeds when otherwise valid | Not Run |
| CN-S-002 | Cancel ordinary credit note | High | Cancel succeeds and GL reverses normally | Not Run |
| CN-S-003 | Submit ordinary positive invoice | High | Unaffected | Not Run |
| CN-S-004 | Save ordinary Draft credit note on the initial test site | Critical | Draft saves without the zero-versus-negative advance error | Passed — `CN-RET-2026-00002` against `SINV-2026-00024` |

---

## 8. Phase 2 — Advance marker metadata tests

### 8.1 Field-existence matrix

| ID | Initial field state | Expected action | Severity | Status |
|---|---|---|---|---|
| MARK-001 | Neither marker exists | Create exact `is_advance_payment` | Critical | Not Run |
| MARK-002 | `is_advance_payment` exists | Reuse it | Critical | Not Run |
| MARK-003 | Only `custom_is_advance_payment` exists | Do not create duplicate | Critical | Not Run |
| MARK-004 | Both fields exist | Stop or use audited compatibility handling | Critical | Not Run |

### 8.2 Marker metadata

| ID | Property | Expected value | Severity | Status |
|---|---|---|---|---|
| MARK-005 | Fieldname | `is_advance_payment` | Critical | Not Run |
| MARK-006 | Label | `Is Advance Payment Invoice` | Medium | Not Run |
| MARK-007 | Fieldtype | Check | High | Not Run |
| MARK-008 | Insert after | `is_debit_note` | Medium | Not Run |
| MARK-009 | No Copy | `1` | High | Not Run |
| MARK-010 | Duplicate fields after second setup run | None | Critical | Not Run |

### 8.3 Compatibility resolver

| ID | Standard value | Custom value | Expected resolved value | Severity | Status |
|---|---:|---:|---:|---|---|
| MARK-011 | 0 | 0 | 0 | High | Not Run |
| MARK-012 | 1 | 0 | 1 | High | Not Run |
| MARK-013 | 0 | 1 | 1 | High | Not Run |
| MARK-014 | 1 | 1 | 1 | High | Not Run |
| MARK-015 | Standard field absent, custom 1 | 1 | High | Not Run |

---

## 9. Phase 2 — Company resolver tests

### 9.1 Enablement

| ID | `custom_zatca_invoice_enabled` | Expected | Severity | Status |
|---|---:|---|---|---|
| CFG-T-001 | 0 | Advance ZATCA behavior disabled | Critical | Not Run |
| CFG-T-002 | 1 | Advance ZATCA behavior enabled | Critical | Not Run |

### 9.2 Phase resolution

| ID | `custom_phase_1_or_2` | `phase_1_or_2` | Expected | Severity | Status |
|---|---|---|---|---|---|
| CFG-T-003 | Phase-1 | Missing | Phase-1 | Critical | Not Run |
| CFG-T-004 | Phase-2 | Missing | Phase-2 | Critical | Not Run |
| CFG-T-005 | Missing | Phase-1 | Phase-1 | Critical | Not Run |
| CFG-T-006 | Missing | Phase-2 | Phase-2 | Critical | Not Run |
| CFG-T-007 | Phase-1 | Phase-2 | Prefer custom field | High | Not Run |
| CFG-T-008 | Empty | Empty | Controlled missing-phase result | High | Not Run |

### 9.3 Environment and B2C method

| ID | Scenario | Expected | Severity | Status |
|---|---|---|---|---|
| CFG-T-009 | Read `custom_select` | Existing environment is used | High | Not Run |
| CFG-T-010 | Read `custom_send_invoice_to_zatca` | Existing B2C method is used | High | Not Run |
| CFG-T-011 | Obsolete advance controls conflict | General controls win | Critical | Not Run |

---

## 10. Phase 2 — Advance/final mutual-exclusion tests

| ID | Advance marker | Deduction rows | Expected result | Severity | Status |
|---|---:|---|---|---|---|
| MUT-001 | 1 | None | Allowed | High | Not Run |
| MUT-002 | 1 | Empty rows | Allowed when rows are not meaningful | High | Not Run |
| MUT-003 | 1 | Positive meaningful deduction | Blocked | Critical | Not Run |
| MUT-004 | 0 | Positive meaningful deduction | Allowed when all other rules pass | Critical | Not Run |
| MUT-005 | 1 | Zero-value meaningful row | Defined behavior verified | High | Not Run |
| MUT-006 | Return invoice | Deduction reversal rows | Controlled by credit-note rules | Critical | Not Run |

---

## 11. Phase 3 — Payment Entry field metadata tests

| ID | Property | Expected value | Severity | Status |
|---|---|---|---|---|
| PAY-M-001 | Fieldname | `custom_zatca_payment_entry` | Critical | Not Run |
| PAY-M-002 | Fieldtype | Link | High | Not Run |
| PAY-M-003 | Options | `Payment Entry` | Critical | Not Run |
| PAY-M-004 | Allow on Submit | `1` | High | Not Run |
| PAY-M-005 | No Copy | `1` | High | Not Run |
| PAY-M-006 | Required | No | Critical | Not Run |
| PAY-M-007 | Visibility | Advance invoices only | Medium | Not Run |
| PAY-M-008 | Second setup run | No duplicate field | Critical | Not Run |

---

## 12. Phase 3 — Payment Entry mapping tests

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| PAY-F-001 | Create from submitted Receive Payment Entry | Critical | Advance Sales Invoice is created correctly | Not Run |
| PAY-F-002 | Create from non-Receive Payment Entry | High | Blocked or excluded according to approved logic | Not Run |
| PAY-F-003 | Create standalone advance invoice | Critical | Payment Entry link may remain empty | Not Run |
| PAY-F-004 | Same Company and Customer | Critical | Mapping succeeds | Not Run |
| PAY-F-005 | Company mismatch | Critical | Mapping is blocked | Not Run |
| PAY-F-006 | Customer mismatch | Critical | Mapping is blocked | Not Run |
| PAY-F-007 | Duplicate active advance from same Payment Entry | Critical | Duplicate is blocked | Not Run |
| PAY-F-008 | Existing cancelled mapped invoice | High | Approved recreation behavior is enforced | Not Run |
| PAY-F-009 | Copy advance invoice | High | Payment Entry link is not copied | Not Run |
| PAY-F-010 | Update link after submit | High | Allowed only within approved validation | Not Run |

---

## 13. Phase 3 — Payment Entry amount and currency tests

| ID | Currency scenario | Expected result | Severity | Status |
|---|---|---|---|---|
| PAY-C-001 | Company currency Payment Entry | Source and base amounts match | Critical | Not Run |
| PAY-C-002 | Foreign-currency Payment Entry | Exchange rates are preserved | Critical | Not Run |
| PAY-C-003 | Paid and received amounts differ by currency | Correct side is mapped | Critical | Not Run |
| PAY-C-004 | Missing exchange rate | Controlled validation or defaulting | High | Not Run |
| PAY-C-005 | Rounding difference | Within approved precision | High | Not Run |
| PAY-C-006 | Zero amount | Blocked | Critical | Not Run |
| PAY-C-007 | Negative amount | Blocked | Critical | Not Run |

---

## 14. Phase 4 — Deferred revenue defaulting tests

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| REV-D-001 | Company deferred account exists | High | Item Income Account defaults correctly | Not Run |
| REV-D-002 | Company deferred account missing | High | Guidance appears | Not Run |
| REV-D-003 | User chooses manual valid account | High | Save may continue | Not Run |
| REV-D-004 | Ordinary Sales Invoice | Critical | Existing income-account behavior is unaffected | Not Run |
| REV-D-005 | Advance invoice with multiple items | High | Same deferred account is applied or validated | Not Run |

---

## 15. Phase 4 — Income Account validation tests

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| REV-V-001 | All rows use one deferred account | Critical | Allowed | Not Run |
| REV-V-002 | Rows use two different accounts | Critical | Blocked with split-invoice guidance | Not Run |
| REV-V-003 | Row uses Company Default Income Account | Critical | Blocked | Not Run |
| REV-V-004 | Row uses a different ordinary income account | High | Approved behavior enforced | Not Run |
| REV-V-005 | Missing Income Account | High | Standard validation or guidance occurs | Not Run |
| REV-V-006 | Return advance invoice | High | Correct account behavior preserved | Not Run |

---

## 16. Phase 4 — Item grid metadata tests

| ID | Field | Expected width | Severity | Status |
|---|---|---:|---|---|
| GRID-001 | Income Account | 1 | Medium | Not Run |
| GRID-002 | Quantity | 1 | Medium | Not Run |
| GRID-003 | Rate | 1 | Medium | Not Run |
| GRID-004 | Other columns | Not silently reduced | Medium | Not Run |
| GRID-005 | Repeated setup | No duplicate Property Setter | High | Not Run |
| GRID-006 | Ordinary invoice grid | No unintended visibility regression | High | Not Run |

---

## 17. Phase 5 — Deduction link metadata tests

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| DED-M-001 | Child Link options after migration | Critical | Points to Sales Invoice | Not Run |
| DED-M-002 | Old ZADV options remain | Critical | No, after approved migration | Not Run |
| DED-M-003 | Existing rows preserved | Critical | Values remain traceable | Not Run |
| DED-M-004 | Second setup run | Critical | No duplicate fields or rows | Not Run |
| DED-M-005 | Repository references | High | No unapproved legacy runtime reference | Not Run |

---

## 18. Phase 5 — Advance eligibility tests

| ID | Scenario | Eligible | Severity | Status |
|---|---|---:|---|---|
| ELIG-001 | Same Company, same Customer, marked advance, open balance | Yes | Critical | Not Run |
| ELIG-002 | Different Company | No | Critical | Not Run |
| ELIG-003 | Different Customer | No | Critical | Not Run |
| ELIG-004 | Not marked advance | No | Critical | Not Run |
| ELIG-005 | Fully consumed | No | Critical | Not Run |
| ELIG-006 | Fully credited | No | Critical | Not Run |
| ELIG-007 | Partially credited with remaining balance | Yes | High | Not Run |
| ELIG-008 | Phase 2 status Cleared | Yes | Critical | Not Run |
| ELIG-009 | Phase 2 status Reported | Yes | Critical | Not Run |
| ELIG-010 | Phase 2 rejected or failed status | No | Critical | Not Run |
| ELIG-011 | Cancelled advance invoice | No | Critical | Not Run |
| ELIG-012 | Draft advance invoice | No | Critical | Not Run |

---

## 19. Phase 5 — Available-balance tests

| ID | Original advance | Applied | Credited | Expected available | Severity | Status |
|---|---:|---:|---:|---:|---|---|
| BAL-001 | 1,000 | 0 | 0 | 1,000 | Critical | Not Run |
| BAL-002 | 1,000 | 400 | 0 | 600 | Critical | Not Run |
| BAL-003 | 1,000 | 1,000 | 0 | 0 | Critical | Not Run |
| BAL-004 | 1,000 | 400 | 100 | Approved formula verified | Critical | Not Run |
| BAL-005 | 1,000 | 0 | 1,000 | 0 | Critical | Not Run |
| BAL-006 | 1,000 | 800 | 300 | Over-release/over-use prevented | Critical | Not Run |
| BAL-007 | Multiple consuming invoices | Sum reconciles | Critical | Not Run |
| BAL-008 | Cancelled consuming invoice | Consumption is released | Critical | Not Run |
| BAL-009 | Cancelled credit note | Release is reversed | Critical | Not Run |

---

## 20. Phase 5 — Settlement tests

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| SET-001 | Partial settlement | Critical | Remaining balance is correct | Not Run |
| SET-002 | Full settlement | Critical | Remaining balance is zero | Not Run |
| SET-003 | Settlement above balance | Critical | Blocked | Not Run |
| SET-004 | Two advances on one final invoice | Critical | Both references and balances are correct | Not Run |
| SET-005 | One advance on two final invoices | Critical | Aggregate consumption is correct | Not Run |
| SET-006 | Duplicate advance row on same final invoice | High | Blocked or consolidated by approved design | Not Run |
| SET-007 | Zero applied amount | High | Ignored or blocked consistently | Not Run |
| SET-008 | Negative applied amount on ordinary final invoice | Critical | Blocked | Not Run |
| SET-009 | Final invoice cancellation | Critical | Consumed balance is released | Not Run |

---

## 21. Phase 5 — Multicurrency tests

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| FX-001 | Advance and final invoice in Company currency | Critical | Source and base values match | Not Run |
| FX-002 | Advance in foreign currency, final in Company currency | Critical | Base settlement is correct | Not Run |
| FX-003 | Advance and final in same foreign currency, different rates | Critical | Base control prevents over-allocation | Not Run |
| FX-004 | Advance and final in different foreign currencies | Critical | Base/local equivalent governs | Not Run |
| FX-005 | Partial settlement with rounding | High | Remaining amount respects precision | Not Run |
| FX-006 | Credit note at different rate | Critical | Release uses approved base logic | Not Run |
| FX-007 | Exchange-rate field missing | High | Controlled validation | Not Run |

---

## 22. Phase 6 — Initial advance credit-note tests

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| ACN-001 | Partial credit note | Critical | Partial available balance is released correctly | Not Run |
| ACN-002 | Full credit note | Critical | Available balance becomes zero | Not Run |
| ACN-003 | Credit above original amount | Critical | Blocked | Not Run |
| ACN-004 | Credit above currently reversible amount | Critical | Blocked | Not Run |
| ACN-005 | Credit after partial settlement | Critical | Only valid reversible amount is released | Not Run |
| ACN-006 | Cancel partial credit note | Critical | Released balance is reversed | Not Run |
| ACN-007 | Multi-currency credit note | Critical | Base release is correct | Not Run |
| ACN-008 | Ordinary credit note | Critical | Not treated as advance reversal | Not Run |

---

## 23. Phase 6 — Final invoice credit-note tests

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| FCN-001 | Full credit note against final settlement invoice | Critical | Advance consumption is reversed | Not Run |
| FCN-002 | Partial credit note against final invoice | Critical | Proportional or approved reversal occurs | Not Run |
| FCN-003 | Multiple advances on original final invoice | Critical | Correct advances are released | Not Run |
| FCN-004 | Cancel final credit note | Critical | Reversal release is undone | Not Run |
| FCN-005 | Credit note above original final invoice | Critical | Standard validation blocks | Not Run |
| FCN-006 | Traceability links | High | Original final and advances are identifiable | Not Run |

---

## 24. Phase 7 — Standard GL baseline tests

Before custom GL logic, capture standard ERPNext results.

| ID | Document | Severity | Expected result | Status |
|---|---|---|---|---|
| GL-B-001 | Normal Sales Invoice | Critical | Standard balanced GL recorded | Not Run |
| GL-B-002 | Sales Invoice with VAT | Critical | Receivable, revenue, and tax reconcile | Not Run |
| GL-B-003 | Return Sales Invoice | Critical | Standard reversal recorded | Not Run |
| GL-B-004 | Multi-currency Sales Invoice | Critical | Account and base currencies reconcile | Not Run |
| GL-B-005 | Cancel Sales Invoice | Critical | GL is reversed | Not Run |
| GL-B-006 | Repost accounting ledger | High | Stable result | Not Run |

---

## 25. Phase 7 — Advance GL tests

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| GL-A-001 | Initial advance invoice | Critical | Approved deferred-revenue accounting | Not Run |
| GL-A-002 | Partial settlement | Critical | Only settled pre-tax amount is transferred | Not Run |
| GL-A-003 | Full settlement | Critical | Full eligible pre-tax amount is transferred | Not Run |
| GL-A-004 | Two advances, same account | Critical | One aggregated row where feasible | Not Run |
| GL-A-005 | Advances from different accounts | Critical | Correct row per source account | Not Run |
| GL-A-006 | Customer receivable | Critical | Final balance is correct | Not Run |
| GL-A-007 | Tax handling | Critical | VAT is not double recognized | Not Run |
| GL-A-008 | Credit note reversal | Critical | Opposite accounting direction | Not Run |
| GL-A-009 | Cancellation | Critical | Settlement GL is reversed | Not Run |
| GL-A-010 | Debit and credit values | Critical | Nonnegative values only | Not Run |
| GL-A-011 | Partial settlement source value | Critical | Full source invoice value is not used | Not Run |
| GL-A-012 | Multi-currency settlement | Critical | Base GL amounts reconcile | Not Run |

---

## 26. Phase 7 — Accounting reconciliation checks

For every GL scenario verify:

| ID | Check | Severity | Status |
|---|---|---|---|
| GL-R-001 | Total debit equals total credit | Critical | Not Run |
| GL-R-002 | Customer receivable matches invoice outstanding | Critical | Not Run |
| GL-R-003 | Deferred revenue balance is correct | Critical | Not Run |
| GL-R-004 | Recognized revenue is correct | Critical | Not Run |
| GL-R-005 | Tax payable is correct | Critical | Not Run |
| GL-R-006 | Account currency is correct | Critical | Not Run |
| GL-R-007 | Base currency is correct | Critical | Not Run |
| GL-R-008 | Cancellation restores prior balances | Critical | Not Run |
| GL-R-009 | Credit note restores prior balances | Critical | Not Run |

---

## 27. Phase 8 — XML classification tests

| ID | Scenario | Expected code/name | Severity | Status |
|---|---|---|---|---|
| XML-C-001 | Initial standard B2B advance | `386` / `0100000` | Critical | Not Run |
| XML-C-002 | Initial simplified B2C advance | `386` / `0200000` | Critical | Not Run |
| XML-C-003 | Final settlement standard invoice | `388` / approved name | Critical | Not Run |
| XML-C-004 | Final settlement simplified invoice | `388` / approved name | Critical | Not Run |
| XML-C-005 | Credit note | `381` | Critical | Not Run |
| XML-C-006 | Ordinary invoice without advances | Existing classification unchanged | Critical | Not Run |

All codes and names require confirmation against current official ZATCA specifications before final acceptance.

---

## 28. Phase 8 — DocumentReference tests

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| XML-R-001 | One applied advance | Critical | One `DocumentReference` | Not Run |
| XML-R-002 | Two applied advances | Critical | Two separate references | Not Run |
| XML-R-003 | Three applied advances | High | Three separate references | Not Run |
| XML-R-004 | Missing optional UUID | High | Valid reference without invalid placeholder | Not Run |
| XML-R-005 | UUID present | High | Correct UUID included | Not Run |
| XML-R-006 | IssueDate | High | Source date included | Not Run |
| XML-R-007 | IssueTime | High | Source time included where available | Not Run |
| XML-R-008 | DocumentTypeCode | Critical | `386` per advance reference | Not Run |
| XML-R-009 | Comma-delimited IDs | Critical | Not used | Not Run |
| XML-R-010 | Duplicate advance row | High | No duplicate XML reference after approved validation | Not Run |

---

## 29. Phase 8 — PrepaidAmount and VAT tests

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| XML-P-001 | Single advance with VAT | Critical | `PrepaidAmount` includes VAT | Not Run |
| XML-P-002 | Multiple advances | Critical | Aggregate prepaid amount reconciles | Not Run |
| XML-P-003 | Partial application | Critical | Only applied tax-inclusive amount included | Not Run |
| XML-P-004 | Full application | Critical | Full eligible tax-inclusive amount included | Not Run |
| XML-P-005 | Mixed VAT rates | Critical | Adjustment groups remain separate | Not Run |
| XML-P-006 | Mixed VAT categories | Critical | Categories remain separate | Not Run |
| XML-P-007 | Zero-rated and standard-rated | Critical | Correct separate groups | Not Run |
| XML-P-008 | Rounding | High | XML totals reconcile within allowed precision | Not Run |

---

## 30. Phase 8 — Phase 1 QR tests

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| QR-P1-001 | Initial advance invoice | Critical | Phase 1 QR generated | Not Run |
| QR-P1-002 | Final settlement invoice | Critical | Current invoice QR generated | Not Run |
| QR-P1-003 | Credit note | High | Correct current-document QR behavior | Not Run |
| QR-P1-004 | Linked Payment Entry exists | Critical | QR does not represent Payment Entry | Not Run |
| QR-P1-005 | Legacy ZADV exists during compatibility | Critical | QR does not reuse legacy QR | Not Run |
| QR-P1-006 | Regenerate QR | High | Deterministic current-document data | Not Run |

---

## 31. Phase 8 — Phase 2 submission tests

### 31.1 B2B clearance

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| B2B-001 | Initial advance invoice | Critical | Clearance request succeeds | Not Run |
| B2B-002 | Final settlement invoice | Critical | Clearance request succeeds | Not Run |
| B2B-003 | Advance credit note | Critical | Clearance behavior matches specification | Not Run |
| B2B-004 | Invalid reference | Critical | Controlled rejection with clear status | Not Run |
| B2B-005 | Retry | High | No duplicate submission corruption | Not Run |

### 31.2 B2C reporting

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| B2C-001 | Initial advance invoice | Critical | Reporting succeeds | Not Run |
| B2C-002 | Final settlement invoice | Critical | Reporting succeeds | Not Run |
| B2C-003 | Advance credit note | Critical | Reporting behavior matches specification | Not Run |
| B2C-004 | Background method | High | General configured method is honored | Not Run |
| B2C-005 | Live method | High | General configured method is honored | Not Run |

---

## 32. Phase 8 — Debug XML parity tests

| ID | Check | Severity | Expected result | Status |
|---|---|---|---|---|
| DBG-001 | Type code | Critical | Same as production path | Not Run |
| DBG-002 | Invoice type name | Critical | Same as production path | Not Run |
| DBG-003 | References | Critical | Same as production path | Not Run |
| DBG-004 | PrepaidAmount | Critical | Same as production path | Not Run |
| DBG-005 | VAT groups | Critical | Same as production path | Not Run |
| DBG-006 | Totals | Critical | Same as production path | Not Run |
| DBG-007 | API transmission | High | Skipped only where intended | Not Run |

---

## 33. Phase 9A — Report metadata tests

| ID | Check | Severity | Expected result | Status |
|---|---|---|---|---|
| RPT-M-001 | Report exists | High | Exactly one Report record | Not Run |
| RPT-M-002 | Module | Medium | Correct ZATCA module | Not Run |
| RPT-M-003 | Permissions | Critical | ERPNext permissions respected | Not Run |
| RPT-M-004 | Second setup run | High | No duplicate report | Not Run |
| RPT-M-005 | Workspace shortcut | Medium | Present once | Not Run |

---

## 34. Phase 9A — Report filter tests

| ID | Filter | Severity | Expected result | Status |
|---|---|---|---|---|
| RPT-F-001 | Company | High | Only selected Company | Not Run |
| RPT-F-002 | Advance Invoice | High | Only selected advance | Not Run |
| RPT-F-003 | Customer | High | Only selected Customer | Not Run |
| RPT-F-004 | Final Invoice | High | Only selected final invoice | Not Run |
| RPT-F-005 | No filters | High | All permitted rows | Not Run |
| RPT-F-006 | Combined filters | High | Correct intersection | Not Run |
| RPT-F-007 | Unauthorized Company | Critical | No unauthorized data | Not Run |

---

## 35. Phase 9A — Report amount tests

| ID | Check | Severity | Expected result | Status |
|---|---|---|---|---|
| RPT-A-001 | Original source amount | Critical | Matches source advance | Not Run |
| RPT-A-002 | Original base amount | Critical | Matches source base value | Not Run |
| RPT-A-003 | Applied amount | Critical | Matches active settlement rows | Not Run |
| RPT-A-004 | Credited amount | Critical | Matches active credit notes | Not Run |
| RPT-A-005 | Remaining amount | Critical | Reconciles to source currency | Not Run |
| RPT-A-006 | Remaining base amount | Critical | Reconciles to Company currency | Not Run |
| RPT-A-007 | Cancelled documents | Critical | Excluded or reversed correctly | Not Run |
| RPT-A-008 | Multiple final invoices | High | All consumption displayed | Not Run |

---

## 36. Phase 9B — Workspace tests

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| WS-T-001 | Canonical `ZATCA` Workspace | High | Exists and visible | Not Run |
| WS-T-002 | Duplicate `ZATCA ERPGulf` | High | Removed at approved phase | Not Run |
| WS-T-003 | Run setup again | Critical | Duplicate not recreated | Not Run |
| WS-T-004 | Run migrate again | Critical | Duplicate not recreated | Not Run |
| WS-T-005 | Required shortcuts | High | Preserved in canonical Workspace | Not Run |
| WS-T-006 | User permissions | High | Existing access remains valid | Not Run |

---

## 37. Phase 9C — Phase 2 field-visibility tests

| ID | Enabled | Phase | Expected visibility | Severity | Status |
|---|---:|---|---|---|---|
| VIS-T-001 | 0 | Phase-1 | Hidden | High | Not Run |
| VIS-T-002 | 0 | Phase-2 | Hidden | High | Not Run |
| VIS-T-003 | 1 | Phase-1 | Hidden | High | Not Run |
| VIS-T-004 | 1 | Phase-2 | Visible | High | Not Run |
| VIS-T-005 | 1 | Fallback field Phase-2 | Visible | High | Not Run |
| VIS-T-006 | Company changed on form | Re-evaluated | Correct refresh | Medium | Not Run |
| VIS-T-007 | Obsolete fields changed | No effect | General controls remain authoritative | High | Not Run |

---

## 38. Phase 9D — `abbr` field matrix

For each of the twelve target DocTypes execute all applicable cases.

| ID | Existing fields | Expected action | Severity | Status |
|---|---|---|---|---|
| ABBR-T-001 | Neither exists | Add exact `abbr` | High | Not Run |
| ABBR-T-002 | `abbr` exists | Add nothing | Critical | Not Run |
| ABBR-T-003 | `custom_abbr` exists | Add nothing | Critical | Not Run |
| ABBR-T-004 | Both exist | Stop or audited handling | Critical | Not Run |
| ABBR-T-005 | Second setup run | No duplicate | Critical | Not Run |

### Metadata checks

| ID | Property | Expected | Severity | Status |
|---|---|---|---|---|
| ABBR-M-001 | Fieldname | `abbr` | High | Not Run |
| ABBR-M-002 | Label | `abbr` | Medium | Not Run |
| ABBR-M-003 | Fieldtype | Data | High | Not Run |
| ABBR-M-004 | Fetch From | `company.abbr` | High | Not Run |
| ABBR-M-005 | Hidden | `1` | Medium | Not Run |
| ABBR-M-006 | Translatable | `1` | Medium | Not Run |
| ABBR-M-007 | Insert after | `company` | Medium | Not Run |

### Fetch behavior

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| ABBR-F-001 | Company selected | High | Company abbreviation fetched | Not Run |
| ABBR-F-002 | Company changed | High | Value refreshes | Not Run |
| ABBR-F-003 | Existing custom field | Critical | Existing value is preserved | Not Run |

---

## 39. Phase 9E — ADV naming-series tests

| ID | Existing naming-series state | Expected result | Severity | Status |
|---|---|---|---|---|
| SER-T-001 | No line contains `ADV` | Add `ADV-.abbr.-.YYYY.-` | Critical | Not Run |
| SER-T-002 | Exact target exists | Add nothing | Critical | Not Run |
| SER-T-003 | Different line contains `ADV` | Add nothing automatically | High | Not Run |
| SER-T-004 | Second setup run | No duplicate | Critical | Not Run |
| SER-T-005 | Existing non-ADV lines | Preserved | Critical | Not Run |
| SER-T-006 | Create advance invoice | Name resolves Company abbreviation | Critical | Not Run |
| SER-T-007 | Missing abbreviation | Controlled naming failure or guidance | High | Not Run |
| SER-T-008 | Ordinary invoice | Existing series remains available | High | Not Run |

---

## 40. Phase 10 — Legacy cleanup precondition tests

| ID | Precondition | Severity | Expected result | Status |
|---|---|---|---|---|
| LEG-P-001 | Exact target site | Critical | `squareangles.top1erp.com` | Not Run |
| LEG-P-002 | Backup exists | Critical | Database and files backups verified | Not Run |
| LEG-P-003 | Target ZADV exists | Critical | Expected document only | Not Run |
| LEG-P-004 | No ZADV GL Entries | Critical | Count zero | Not Run |
| LEG-P-005 | No deduction references | Critical | Count zero | Not Run |
| LEG-P-006 | No unexpected Sales Invoice links | Critical | Count zero | Not Run |
| LEG-P-007 | Payment Entry recorded | Critical | Snapshot complete | Not Run |
| LEG-P-008 | QR File recorded | High | Snapshot complete | Not Run |
| LEG-P-009 | Comment and Version counts recorded | High | Snapshot complete | Not Run |
| LEG-P-010 | Dry run result | Critical | `READY` | Not Run |

Any failed precondition must block destructive cleanup.

---

## 41. Phase 10 — Legacy cleanup execution tests

| ID | Operation | Severity | Expected result | Status |
|---|---|---|---|---|
| LEG-E-001 | Clear obsolete Payment Entry fields | Critical | Exact target fields cleared only | Not Run |
| LEG-E-002 | Preserve Payment Entry document | Critical | Document and GL remain intact | Not Run |
| LEG-E-003 | Remove or detach QR File | High | Approved File behavior occurs | Not Run |
| LEG-E-004 | Delete ZADV using Frappe API | Critical | Document removed | Not Run |
| LEG-E-005 | Comment handling | High | Matches documented Frappe behavior | Not Run |
| LEG-E-006 | Version handling | High | Matches documented Frappe behavior | Not Run |
| LEG-E-007 | Remove old Print Format | High | Record removed and not recreated | Not Run |
| LEG-E-008 | Remove schema links | Critical | No Link options point to old DocType | Not Run |
| LEG-E-009 | Remove old DocType last | Critical | Clean migration succeeds | Not Run |
| LEG-E-010 | Remove old Series | High | Removed only when no ZADV remains | Not Run |
| LEG-E-011 | Run cleanup second time | Critical | Safe idempotent result | Not Run |

---

## 42. Phase 10 — Obsolete Company-field removal tests

For each obsolete field:

| ID | Check | Severity | Expected result | Status |
|---|---|---|---|---|
| OLD-F-001 | Python references removed | Critical | No runtime reference | Not Run |
| OLD-F-002 | JavaScript references removed | Critical | No runtime reference | Not Run |
| OLD-F-003 | Property Setter references removed | High | No recreation | Not Run |
| OLD-F-004 | Fixture references removed | High | No recreation | Not Run |
| OLD-F-005 | Translation references removed | Medium | No obsolete UI entry | Not Run |
| OLD-F-006 | Custom Field record removed | High | Absent after migrate | Not Run |
| OLD-F-007 | Physical column handling | High | Matches Frappe migration behavior | Not Run |
| OLD-F-008 | Second migrate | Critical | Field not recreated | Not Run |

Obsolete fields:

```text
custom_zatca_advance_payment_section
custom_zatca_advance_payment_enabled
custom_zatca_advance_default_tc_name
custom_zatca_advance_payment_submission_mode
custom_zatca_advance_signing_enabled
custom_zatca_advance_api_submission_enabled
```

---

## 43. Migration dry-run tests

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| MIG-D-001 | Correct initial site and expected state | Critical | `READY` | Not Run |
| MIG-D-002 | Wrong site | Critical | `BLOCKED` | Not Run |
| MIG-D-003 | Unexpected second ZADV document | Critical | `BLOCKED` with list | Not Run |
| MIG-D-004 | Unexpected GL Entry | Critical | `BLOCKED` | Not Run |
| MIG-D-005 | Unexpected deduction reference | Critical | `BLOCKED` | Not Run |
| MIG-D-006 | Missing backup | Critical | `BLOCKED` | Not Run |
| MIG-D-007 | Already migrated state | High | Safe already-complete result | Not Run |
| MIG-D-008 | Dry run | Critical | No data or file mutation | Not Run |

---

## 44. Migration idempotency tests

| ID | Operation | Severity | Expected second-run result | Status |
|---|---|---|---|---|
| IDEM-001 | Marker setup | Critical | No duplicate field | Not Run |
| IDEM-002 | Payment Entry field setup | Critical | No duplicate field | Not Run |
| IDEM-003 | Property Setter setup | High | No duplicate setter | Not Run |
| IDEM-004 | Report installation | High | No duplicate report | Not Run |
| IDEM-005 | Workspace reconciliation | Critical | One canonical Workspace | Not Run |
| IDEM-006 | `abbr` setup | Critical | No duplicate field | Not Run |
| IDEM-007 | Naming-series setup | Critical | No duplicate option | Not Run |
| IDEM-008 | Legacy cleanup | Critical | Already-complete result, no error | Not Run |
| IDEM-009 | Full migrate twice | Critical | Same final state | Not Run |

---

## 45. Rollback tests

### 45.1 Code-only rollback

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| RB-C-001 | Revert Phase 1 code | High | Baseline behavior restored | Not Run |
| RB-C-002 | Restart and clear cache | High | Site operates normally | Not Run |
| RB-C-003 | Baseline tests | Critical | Pass | Not Run |

### 45.2 Additive-schema rollback

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| RB-A-001 | Leave harmless additive field | Medium | Old code still functions | Not Run |
| RB-A-002 | Remove additive field | High | Migration succeeds | Not Run |
| RB-A-003 | Remove new report | Medium | Unrelated reports remain | Not Run |
| RB-A-004 | Remove ADV option | High | Only migration-added option removed | Not Run |

### 45.3 Full destructive rollback

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| RB-F-001 | Restore database backup | Critical | Restore succeeds | Not Run |
| RB-F-002 | Restore public files | Critical | QR and public assets restored | Not Run |
| RB-F-003 | Restore private files | Critical | Private assets restored | Not Run |
| RB-F-004 | Deploy matching commit | Critical | Application matches database | Not Run |
| RB-F-005 | Run matching migrate | Critical | Succeeds | Not Run |
| RB-F-006 | Verify ZADV exists | Critical | Legacy document restored | Not Run |
| RB-F-007 | Verify Payment Entry legacy fields | Critical | Exact values restored | Not Run |
| RB-F-008 | Verify QR File | High | File and record restored | Not Run |
| RB-F-009 | Verify Workspace and Series | High | Baseline restored | Not Run |
| RB-F-010 | Run baseline tests | Critical | Pass | Not Run |

---

## 46. Clean-install tests

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| CLEAN-001 | Install app on clean site | Critical | Installation succeeds | Not Run |
| CLEAN-002 | Marker creation | Critical | Correct guarded field state | Not Run |
| CLEAN-003 | Payment Entry field | High | Created once | Not Run |
| CLEAN-004 | Old ZADV DocType | Critical | Absent in final design | Not Run |
| CLEAN-005 | Old Company fields | High | Absent in final design | Not Run |
| CLEAN-006 | Canonical Workspace | High | Exists once | Not Run |
| CLEAN-007 | Duplicate Workspace | High | Absent | Not Run |
| CLEAN-008 | Report | High | Exists once | Not Run |
| CLEAN-009 | `abbr` fields | High | Follow guards | Not Run |
| CLEAN-010 | ADV naming series | High | Added only when allowed | Not Run |
| CLEAN-011 | Run setup twice | Critical | Idempotent | Not Run |

---

## 47. Upgrade and compatibility tests

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| COMP-001 | Existing site with standard marker | Critical | No duplicate marker | Not Run |
| COMP-002 | Existing site with custom marker | Critical | Compatibility works | Not Run |
| COMP-003 | Existing site with both markers | Critical | Migration blocks or resolves safely | Not Run |
| COMP-004 | Existing site with fallback phase field | High | Correct phase | Not Run |
| COMP-005 | Existing site with `custom_abbr` | High | Preserved | Not Run |
| COMP-006 | Existing site with existing ADV series | High | No duplicate | Not Run |
| COMP-007 | Existing site with only canonical Workspace | High | No unnecessary change | Not Run |
| COMP-008 | Existing site with unexpected ZADV data | Critical | Site-specific migration blocked | Not Run |

---

## 48. Permissions and security tests

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| SEC-001 | User without Sales Invoice create permission | Critical | Cannot create advance invoice | Not Run |
| SEC-002 | User without Payment Entry read permission | High | Link data is not exposed improperly | Not Run |
| SEC-003 | User without Company access | Critical | Cannot view report data | Not Run |
| SEC-004 | Report permission query | Critical | User permissions enforced | Not Run |
| SEC-005 | Cleanup command permissions | Critical | Restricted to authorized administrator | Not Run |
| SEC-006 | Migration logs | High | No secrets or keys logged | Not Run |
| SEC-007 | File cleanup | High | Only target QR File affected | Not Run |

---

## 49. Performance tests

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| PERF-001 | Report with no filters and moderate dataset | Medium | Acceptable response time | Not Run |
| PERF-002 | Eligibility query with many advance invoices | High | No excessive query count | Not Run |
| PERF-003 | Final invoice with multiple advances | High | Submit completes acceptably | Not Run |
| PERF-004 | Balance calculation across many settlements | High | Correct and performant | Not Run |
| PERF-005 | Repeated Workspace/setup reconciliation | Medium | No unnecessary writes | Not Run |
| PERF-006 | Migration dry run | Medium | Completes without locking excessively | Not Run |

---

## 50. Concurrency tests

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| CON-001 | Two final invoices consume same remaining advance | Critical | One is blocked or serialized safely | Not Run |
| CON-002 | Credit note while settlement submits | Critical | No negative or duplicated balance | Not Run |
| CON-003 | Duplicate Payment Entry mapping requests | Critical | One active advance invoice | Not Run |
| CON-004 | Migration during active document writes | Critical | Migration is blocked by operational controls | Not Run |

---

## 51. Cancellation and amendment tests

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| CAN-001 | Cancel initial advance invoice | Critical | Balance and GL reverse correctly | Not Run |
| CAN-002 | Cancel partially consumed advance | Critical | Blocked or handled by approved rule | Not Run |
| CAN-003 | Cancel final settlement invoice | Critical | Advance balance is released | Not Run |
| CAN-004 | Cancel advance credit note | Critical | Released balance is reversed | Not Run |
| CAN-005 | Amend cancelled advance invoice | High | Links and marker behave correctly | Not Run |
| CAN-006 | Copy amended document | High | No Copy fields are cleared | Not Run |

---

## 52. Translation and UI text tests

| ID | Scenario | Severity | Expected result | Status |
|---|---|---|---|---|
| I18N-001 | English UI | Medium | English labels and messages | Not Run |
| I18N-002 | Arabic UI | Medium | Approved Arabic translations | Not Run |
| I18N-003 | Non-Arabic UI | Medium | Arabic text is not forced | Not Run |
| I18N-004 | Obsolete labels | Medium | Removed with obsolete fields | Not Run |
| I18N-005 | UI labels/help containing `ERPNext` | Medium | None in redesigned custom UI text | Not Run |
| I18N-006 | Validation messages | High | Clear and actionable | Not Run |

---

## 53. Repository scan tests

At each relevant phase, scan for unexpected runtime references.

| ID | Pattern | Expected final result | Severity | Status |
|---|---|---|---|---|
| SCAN-001 | `ZATCA Advance Tax Invoice` | Documentation or approved migration references only | Critical | Not Run |
| SCAN-002 | `ZADV` | Documentation or approved migration references only | High | Not Run |
| SCAN-003 | `custom_zatca_advance_tax_invoice` | Removed from runtime | Critical | Not Run |
| SCAN-004 | `custom_advance_invoice_reference` | Migrated or removed as approved | Critical | Not Run |
| SCAN-005 | `zatca_advance_tax_invoice` | Migrated or documented | Critical | Not Run |
| SCAN-006 | Obsolete Company fieldnames | No runtime/setup recreation | Critical | Not Run |
| SCAN-007 | `ZATCA ERPGulf` | No fixture or setup recreation | High | Not Run |

---

## 54. Documentation tests

| ID | Check | Severity | Expected result | Status |
|---|---|---|---|---|
| DOC-001 | Current status updated | High | Matches actual implementation | Not Run |
| DOC-002 | Traceability updated | High | Affected rows updated | Not Run |
| DOC-003 | Decisions updated | High | New or changed decisions recorded | Not Run |
| DOC-004 | Test results recorded | High | Commands and results included | Not Run |
| DOC-005 | Migration document updated | High | Actual behavior matches plan | Not Run |
| DOC-006 | No phase marked complete early | Critical | Completion follows evidence | Not Run |

---

## 55. Required evidence format

For each executed test batch record:

```text
Date:
Branch:
Commit:
Site:
Command:
Test IDs:
Result:
Failures:
Artifacts:
Reviewer:
```

For site tests also record:

```text
Company:
Document names:
Posting dates:
Currencies:
Exchange rates:
Expected totals:
Actual totals:
Expected GL:
Actual GL:
Expected ZATCA status:
Actual ZATCA status:
```

---

## 56. Phase exit criteria

### Phase 1

- all `CN-R-*` critical tests pass;
- baseline tests pass;
- no schema change;
- Git diff reviewed.

### Phase 2

- marker matrix passes;
- Company resolver passes;
- mutual-exclusion tests pass;
- setup idempotency passes.

### Phase 3

- Payment Entry metadata and mapping pass;
- duplicate prevention passes;
- standalone path passes;
- currency mapping passes.

### Phase 4

- deferred revenue defaulting passes;
- Income Account validation passes;
- ordinary invoices remain unaffected.

### Phase 5

- eligibility, balance, settlement, and multicurrency tests pass;
- no over-allocation;
- reportable traceability exists.

### Phase 6

- partial and full credit-note reversals pass;
- final-invoice reversal passes;
- ordinary credit notes remain unaffected.

### Phase 7

- GL balances;
- customer receivable is correct;
- deferred revenue is correct;
- cancellation and credit-note reversal pass;
- accounting approval is recorded.

### Phase 8

- official ZATCA verification is complete;
- XML schema and totals pass;
- Phase 1 QR passes;
- B2B clearance passes;
- B2C reporting passes;
- debug parity passes.

### Phase 9

- report, Workspace, visibility, abbreviation, and series tests pass;
- repeated setup is idempotent.

### Phase 10

- backups verified;
- dry run returns `READY`;
- destructive cleanup passes;
- no legacy runtime references remain;
- clean and repeated migration pass;
- rollback rehearsal passes.

### Phase 11

- full matrix critical tests pass;
- rollout wave approval is recorded.

---

## 57. Current execution status

| Test group | Status |
|---|---|
| Baseline tests | Passed |
| Audit read-only checks | Passed |
| Phase 1 regression tests | Passed — 12 focused tests; site Submit/Cancel still Not Run |
| Phase 2 foundation tests | Not Run |
| Phase 3 Payment Entry tests | Not Run |
| Phase 4 deferred revenue tests | Not Run |
| Phase 5 deduction tests | Not Run |
| Phase 6 credit-note tests | Not Run |
| Phase 7 accounting tests | Not Run |
| Phase 8 XML and QR tests | Not Run |
| Phase 9 report and metadata tests | Not Run |
| Phase 10 migration tests | Not Run |
| Rollback rehearsal | Not Run |
| Wider rollout tests | Not Run |

---

## 58. Phase 1 execution evidence and remaining tests

Completed automated batch:

```text
CN-R-001 through CN-R-008: Passed
CN-C-001 through CN-C-004: Passed
Focused tests: 12 passed
Existing regression tests: 10 passed
Total automated tests: 22 passed
```

Completed site evidence:

```text
CN-S-004: Passed
Site: squareangles.top1erp.com
Draft Credit Note: CN-RET-2026-00002
Return Against: SINV-2026-00024
```

Remaining site smoke tests:

```text
CN-S-001: Not Run
CN-S-002: Not Run
CN-S-003: Not Run
```

No migration, schema deletion, ZADV deletion, Workspace deletion, or Series deletion was part of Phase 1.
