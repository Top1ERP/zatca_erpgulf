# ZATCA Advance Redesign — Requirements Traceability

## 1. Document status

| Item | Value |
|---|---|
| Status | Active |
| Application | `zatca_erpgulf` |
| Initial test site | `squareangles.top1erp.com` |
| Audit document | `CURRENT_STATE_AUDIT.md` |
| Decisions document | `ARCHITECTURE_DECISIONS.md` |
| Current branch | `fix/return-credit-note-advance-validation` |

This document maps the approved redesign requirements to their current state, implementation phase, branch, and verification method.

Status values:

- Verified
- Not Implemented
- Partially Implemented
- Pending Verification
- Completed

---

## 2. Governance and delivery

| ID | Requirement | Current state | Phase | Verification |
|---|---|---|---|---|
| GOV-001 | Complete repository audit before modification | Verified | Phase 0 | Repository inventory |
| GOV-002 | Complete site and database audit before writes | Verified | Phase 0 | Read-only audit output |
| GOV-003 | Use an independent branch for each concern | Pending | All phases | Git branch review |
| GOV-004 | Keep one concern per pull request | Pending | All phases | Pull-request review |
| GOV-005 | Preserve Phase 1 behavior | Pending Verification | All phases | Phase 1 test matrix |
| GOV-006 | Preserve Phase 2 B2B behavior | Pending Verification | All phases | Clearance tests |
| GOV-007 | Preserve Phase 2 B2C behavior | Pending Verification | All phases | Reporting tests |
| GOV-008 | Test initially only on `squareangles.top1erp.com` | Active policy | All phases | Deployment record |
| GOV-009 | Show tests and Git diff before completion | Active policy | All phases | Test and Git output |
| GOV-010 | Update project documents after every phase | Active policy | All phases | Documentation diff |
| GOV-011 | Avoid ERPNext core modification without approval | Active policy | All phases | Changed-file review |
| GOV-012 | Make setup and migration idempotent | Not Implemented | All setup phases | Repeated execution |
| GOV-013 | Verify current official ZATCA specifications | Pending Verification | Before Phase 8 completion | Official source review |

---

## 3. Standard Sales Invoice advance model

| ID | Requirement | Current state | Phase | Branch | Verification |
|---|---|---|---|---|---|
| ADV-001 | Replace custom ZADV workflow with Sales Invoice | Not Implemented | Phase 2 and 10 | `feature/standard-sales-invoice-advance-core` | Workflow tests |
| ADV-002 | Use `is_advance_payment` as canonical marker | Missing on test site | Phase 2 | Same branch | Metadata test |
| ADV-003 | Reuse existing `is_advance_payment` when present | Not Implemented | Phase 2 | Same branch | Existing-field test |
| ADV-004 | Check for `custom_is_advance_payment` | Not Implemented | Phase 2 | Same branch | Compatibility test |
| ADV-005 | Prevent duplicate advance marker fields | Not Implemented | Phase 2 | Same branch | Metadata matrix |
| ADV-006 | Label field `Is Advance Payment Invoice` | Not Implemented | Phase 2 | Same branch | Metadata assertion |
| ADV-007 | Place marker after `is_debit_note` | Not Implemented | Phase 2 | Same branch | Field-order test |
| ADV-008 | Set marker No Copy | Not Implemented | Phase 2 | Same branch | Metadata assertion |
| ADV-009 | Block advance invoice containing deductions | Not Implemented | Phase 2 | Same branch | Validation test |
| ADV-010 | Block final invoice marked as initial advance | Not Implemented | Phase 2 | Same branch | Validation test |

---

## 4. Company ZATCA controls

The following obsolete fields must eventually be removed:

- `custom_zatca_advance_payment_section`
- `custom_zatca_advance_payment_enabled`
- `custom_zatca_advance_default_tc_name`
- `custom_zatca_advance_payment_submission_mode`
- `custom_zatca_advance_signing_enabled`
- `custom_zatca_advance_api_submission_enabled`

| ID | Requirement | Current state | Phase | Verification |
|---|---|---|---|---|
| CFG-001 | Use `custom_zatca_invoice_enabled` as master switch | Partially Implemented | Phase 2 | Resolver test |
| CFG-002 | Prefer `custom_phase_1_or_2` | Partially Implemented | Phase 2 | Resolver test |
| CFG-003 | Support `phase_1_or_2` as fallback | Not Implemented | Phase 2 | Compatibility test |
| CFG-004 | Use `custom_select` for ZATCA environment | Existing control | Phase 2 | Environment test |
| CFG-005 | Use general B2C submission control | Existing control | Phase 2 | B2C method test |
| CFG-006 | Remove obsolete Section Break | Present | Phase 10 | Metadata test |
| CFG-007 | Remove obsolete enable field | Present and referenced | Phase 2 and 10 | Reference scan |
| CFG-008 | Remove obsolete terms field | Present and referenced | Phase 2 and 10 | Reference scan |
| CFG-009 | Remove obsolete submission mode | Present and referenced | Phase 2 and 10 | Reference scan |
| CFG-010 | Remove obsolete signing field | Present and referenced | Phase 2 and 10 | Reference scan |
| CFG-011 | Remove obsolete API field | Present and referenced | Phase 2 and 10 | Reference scan |
| CFG-012 | Do not migrate obsolete setting values | Accepted decision | Phase 10 | Migration review |
| CFG-013 | Use standard `tc_name` and `terms` | Not Implemented | Phase 2 | Invoice creation test |

---

## 5. Phase and document classification

| ID | Requirement | Current state | Phase | Verification |
|---|---|---|---|---|
| PHASE-001 | Phase 1 advance uses standard Sales Invoice | Not Implemented | Phase 2 | Phase 1 site test |
| PHASE-002 | Phase 1 generates QR locally | Legacy-only | Phase 8 | QR test |
| PHASE-003 | Phase 1 does not use Phase 2 signing | Pending Verification | Phase 2 and 8 | Signing-path test |
| PHASE-004 | Phase 1 does not call Phase 2 APIs | Pending Verification | Phase 2 and 8 | API mock test |
| PHASE-005 | Phase 2 advance uses standard signing | Not Implemented | Phase 8 | Signed XML test |
| PHASE-006 | B2B uses clearance | General behavior exists | Phase 8 | Clearance test |
| PHASE-007 | B2C uses reporting | General behavior exists | Phase 8 | Reporting test |
| PHASE-008 | Initial advance uses type code `386` | Legacy implementation exists | Phase 8 | XML assertion |
| PHASE-009 | Final settlement invoice uses `388` | Partially Implemented | Phase 8 | XML assertion |
| PHASE-010 | Credit note uses `381` | Pending Verification | Phase 8 | XML assertion |
| PHASE-011 | Standard invoice name is `0100000` | Pending Verification | Phase 8 | XML assertion |
| PHASE-012 | Simplified invoice name is `0200000` | Pending Verification | Phase 8 | XML assertion |

---

## 6. Payment Entry linkage

| ID | Requirement | Current state | Phase | Branch | Verification |
|---|---|---|---|---|---|
| PAY-001 | Add `custom_zatca_payment_entry` | Missing | Phase 3 | `feature/advance-payment-entry-link` | Field test |
| PAY-002 | Link it to Payment Entry | Missing | Phase 3 | Same branch | Options assertion |
| PAY-003 | Keep linkage optional | Missing | Phase 3 | Same branch | Standalone test |
| PAY-004 | Enable Allow on Submit | Missing | Phase 3 | Same branch | Metadata test |
| PAY-005 | Enable No Copy | Missing | Phase 3 | Same branch | Copy test |
| PAY-006 | Show only for advance invoices | Missing | Phase 3 | Same branch | UI test |
| PAY-007 | Create advance invoice from Payment Entry | Legacy ZADV path exists | Phase 3 | Same branch | Mapping test |
| PAY-008 | Allow standalone advance invoice | Not Implemented | Phase 3 | Same branch | Standalone test |
| PAY-009 | Prevent duplicate creation | Requires replacement | Phase 3 | Same branch | Duplicate test |
| PAY-010 | Preserve source and base amounts | Pending Verification | Phase 3 | Same branch | Currency test |
| PAY-011 | Remove legacy Payment Entry ZADV link | Present | Phase 10 | `refactor/remove-zadv-doctype` | Migration test |

---

## 7. Deferred revenue and Item validation

| ID | Requirement | Current state | Phase | Verification |
|---|---|---|---|---|
| REV-001 | Prefer Default Deferred Revenue Account | Not Implemented | Phase 4 | Defaulting test |
| REV-002 | Show guidance when account is missing | Not Implemented | Phase 4 | Message test |
| REV-003 | Link guidance to Company Accounts | Not Implemented | Phase 4 | Link test |
| REV-004 | Allow manual account selection | Not Implemented | Phase 4 | Manual-account test |
| REV-005 | Show Income Account in Item grid | Not Implemented | Phase 4 | Metadata test |
| REV-006 | Set Income Account width to `1` | Not Implemented | Phase 4 | Metadata test |
| REV-007 | Try Quantity width `1` | Not Implemented | Phase 4 | Metadata test |
| REV-008 | Try Rate width `1` | Not Implemented | Phase 4 | Metadata test |
| REV-009 | Do not force more width reductions | Not Implemented | Phase 4 | Metadata review |
| REV-010 | Require one Income Account per advance | Not Implemented | Phase 4 | Validation test |
| REV-011 | Tell user to split multi-account advances | Not Implemented | Phase 4 | Message test |
| REV-012 | Block Company Default Income Account | Not Implemented | Phase 4 | Validation test |

Planned branch: `feature/advance-income-account-validation`.

---

## 8. Advance deduction and balances

| ID | Requirement | Current state | Phase | Verification |
|---|---|---|---|---|
| DED-001 | Link rows to standard advance Sales Invoices | Links legacy ZADV | Phase 5 | Metadata test |
| DED-002 | Filter by same Company | Partial legacy logic | Phase 5 | Filter test |
| DED-003 | Filter by same Customer | Partial legacy logic | Phase 5 | Filter test |
| DED-004 | Require advance marker | Not Implemented | Phase 5 | Filter test |
| DED-005 | Require unused balance | Partially Implemented | Phase 5 | Balance test |
| DED-006 | Require accepted Phase 2 status | Partially Implemented | Phase 5 | Status test |
| DED-007 | Preserve invoice currency | Partially Implemented | Phase 5 | Currency test |
| DED-008 | Preserve base or local equivalent | Partially Implemented | Phase 5 | Base amount test |
| DED-009 | Control settlement using base value | Incomplete | Phase 5 | Over-allocation test |
| DED-010 | Support partial settlement | Partially Implemented | Phase 5 | Partial test |
| DED-011 | Support full settlement | Partially Implemented | Phase 5 | Full test |
| DED-012 | Support multiple advances | Partially Implemented | Phase 5 | Many-to-one test |
| DED-013 | Account for advance credit notes | Incomplete | Phase 5 and 6 | Release tests |
| DED-014 | Prevent settlement above balance | Partially Implemented | Phase 5 | Validation test |
| DED-015 | Preserve traceable child rows | Requires redesign | Phase 5 | Database assertion |

Planned branch: `feature/advance-deduction-multicurrency`.

---

## 9. Credit notes and reversals

| ID | Requirement | Current state | Phase | Branch | Verification |
|---|---|---|---|---|---|
| CN-001 | Ordinary credit note without deductions is not blocked | Implemented and verified | Phase 1 | `fix/return-credit-note-advance-validation` | Automated validation and Draft `CN-RET-2026-00002` save |
| CN-002 | Empty deduction table does not trigger comparison | Implemented and verified | Phase 1 | Same branch | Focused automated regression test |
| CN-003 | Zero deduction is not compared to negative total | Implemented and verified | Phase 1 | Same branch | Focused automated regression test |
| CN-004 | Positive final-invoice limit remains active | Verified | Phase 1 | Same branch | Valid and excessive positive-invoice tests |
| CN-005 | Do not use unconditional bypass | Verified | Phase 1 | Same branch | Narrow return-path guard and code review |
| CN-006 | Do not blindly use absolute values | Verified | Phase 1 | Same branch | Negative return signs preserved and code review |
| CN-013 | Block positive legacy-ZATCA advance allocations applied directly to a return | Implemented and verified | Phase 1 | Same branch | Focused blocking test and Arabic validation message |
| CN-014 | Preserve dedicated advance-credit-note validation | Implemented and verified | Phase 1 | Same branch | Valid and excessive advance-credit-note tests |
| CN-007 | Allow partial advance credit note | Incomplete | Phase 6 | `feature/advance-credit-note-reversal` | Partial reversal |
| CN-008 | Allow full advance credit note | Incomplete | Phase 6 | Same branch | Full reversal |
| CN-009 | Release balance using base equivalent | Not Implemented | Phase 6 | Same branch | Currency reversal |
| CN-010 | Prevent excessive release | Not Implemented | Phase 6 | Same branch | Excess test |
| CN-011 | Reverse final-invoice settlement | Not Implemented | Phase 6 | Same branch | Final credit-note test |
| CN-012 | Preserve traceability | Not Implemented | Phase 6 | Same branch | Link assertion |

---

## 10. Final invoice accounting

| ID | Requirement | Current state | Phase | Verification |
|---|---|---|---|---|
| GL-001 | Inspect standard Sales Invoice GL first | Not Completed | Phase 7 | GL audit |
| GL-002 | Aggregate settlement by Income Account | Not Implemented | Phase 7 | GL test |
| GL-003 | Use settlement amount before tax | Not Implemented | Phase 7 | Amount assertion |
| GL-004 | Do not use full source invoice value | Not Implemented | Phase 7 | Partial test |
| GL-005 | Reduce customer balance correctly | Not Implemented | Phase 7 | Receivable test |
| GL-006 | Aggregate one row per account where feasible | Not Implemented | Phase 7 | Multi-account test |
| GL-007 | Reverse accounting on credit notes | Not Implemented | Phase 7 | Reversal test |
| GL-008 | Keep debit and credit values nonnegative | Pending | Phase 7 | GL assertion |
| GL-009 | Stop when no safe extension point exists | Active constraint | Phase 7 | Architecture review |

Planned branch: `feature/advance-final-invoice-gl`.

---

## 11. XML, QR, and debug generation

| ID | Requirement | Current state | Phase | Verification |
|---|---|---|---|---|
| XML-001 | Generate multiple `DocumentReference` elements | Pending Verification | Phase 8 | Node-count test |
| XML-002 | Do not use comma-delimited references | Pending Verification | Phase 8 | Content assertion |
| XML-003 | Include advance ID | Partially Implemented | Phase 8 | XML assertion |
| XML-004 | Include optional UUID | Partially Implemented | Phase 8 | XML assertion |
| XML-005 | Include IssueDate | Partially Implemented | Phase 8 | XML assertion |
| XML-006 | Include IssueTime | Partially Implemented | Phase 8 | XML assertion |
| XML-007 | Include DocumentTypeCode `386` | Partially Implemented | Phase 8 | XML assertion |
| XML-008 | Make `PrepaidAmount` tax inclusive | Partially Implemented | Phase 8 | Total assertion |
| XML-009 | Group adjustments by VAT category and rate | Pending Verification | Phase 8 | VAT test |
| XML-010 | Support many-to-one advances | Partially Implemented | Phase 8 | XML test |
| XML-011 | Debug XML uses production logic | Not Implemented | Phase 8 | Parity test |
| QR-001 | QR represents current invoice only | Requires replacement | Phase 8 | QR data test |
| QR-002 | Preserve Phase 1 QR behavior | Pending Verification | Phase 8 | Phase 1 test |
| QR-003 | Preserve Phase 2 QR behavior | Pending Verification | Phase 8 | Phase 2 test |

Planned branch: `feature/advance-zatca-xml`.

---

## 12. Report, Workspace, and visibility

| ID | Requirement | Current state | Phase | Verification |
|---|---|---|---|---|
| RPT-001 | Add advance settlement report | Missing | Phase 9 | Report test |
| RPT-002 | Filter by Company | Missing | Phase 9 | Filter test |
| RPT-003 | Filter by Advance Invoice | Missing | Phase 9 | Filter test |
| RPT-004 | Filter by Customer | Missing | Phase 9 | Filter test |
| RPT-005 | Filter by Final Invoice | Missing | Phase 9 | Filter test |
| RPT-006 | Show all rows when filters are empty | Missing | Phase 9 | Empty-filter test |
| RPT-007 | Show original and remaining base balance | Missing | Phase 9 | Amount test |
| RPT-008 | Place shortcut below POS warnings report | Missing | Phase 9 | Workspace test |
| WS-001 | Keep only `ZATCA` | Duplicate exists | Phase 9 | Metadata test |
| WS-002 | Remove `ZATCA ERPGulf` | Present | Phase 9 | Migration test |
| WS-003 | Prevent duplicate recreation | Current fixture risk | Phase 9 | Repeated migrate |
| VIS-001 | Show Phase 2 fields only when ZATCA is enabled | Requires normalization | Phase 9 | UI test |
| VIS-002 | Show Phase 2 fields only for Phase 2 | Requires normalization | Phase 9 | UI test |
| VIS-003 | Support both phase fieldnames | Not Implemented | Phase 9 | Compatibility test |

Planned branches:

- `feature/advance-report`
- `fix/zatca-workspace-deduplication`
- `feature/zatca-phase2-field-visibility`

---

## 13. Company abbreviation fields

| ID | Requirement | Current state | Phase | Verification |
|---|---|---|---|---|
| ABBR-001 | Check existing `abbr` | Not Implemented | Phase 9 | Metadata test |
| ABBR-002 | Check existing `custom_abbr` | Not Implemented | Phase 9 | Metadata test |
| ABBR-003 | Add nothing when either exists | Not Implemented | Phase 9 | Matrix test |
| ABBR-004 | Do not rename `custom_abbr` | Active requirement | Phase 9 | Migration test |
| ABBR-005 | Add exact fieldname `abbr` | Missing on test site | Phase 9 | Metadata assertion |
| ABBR-006 | Fetch from `company.abbr` | Missing | Phase 9 | Fetch test |
| ABBR-007 | Use Data fieldtype | Missing | Phase 9 | Metadata assertion |
| ABBR-008 | Make field hidden | Missing | Phase 9 | Metadata assertion |
| ABBR-009 | Make field translatable | Missing | Phase 9 | Metadata assertion |
| ABBR-010 | Place after Company | Missing | Phase 9 | Field-order test |
| ABBR-011 | Apply to all twelve target DocTypes | Missing | Phase 9 | Twelve-DocType matrix |

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

Planned branch: `feature/company-abbr-fields`.

---

## 14. Sales Invoice naming series

| ID | Requirement | Current state | Phase | Verification |
|---|---|---|---|---|
| SERIES-001 | Add `ADV-.abbr.-.YYYY.-` | Missing | Phase 9 | Options assertion |
| SERIES-002 | Check all existing lines for `ADV` | Not Implemented | Phase 9 | Existing-option test |
| SERIES-003 | Prevent duplicate ADV series | Not Implemented | Phase 9 | Repeated setup |
| SERIES-004 | Preserve existing Sales Invoice series | Existing options verified | Phase 9 | Before-and-after test |

Planned branch: `feature/advance-sales-invoice-naming-series`.

---

## 15. Legacy removal

| ID | Requirement | Current state | Phase | Verification |
|---|---|---|---|---|
| LEG-001 | Preserve audit snapshot before deletion | Not Executed | Phase 10 | Snapshot |
| LEG-002 | Take database and files backup | Not Executed | Phase 10 | Backup verification |
| LEG-003 | Repeat reference audit | Not Executed | Phase 10 | Precondition output |
| LEG-004 | Clear legacy Payment Entry fields | Not Executed | Phase 10 | Database assertion |
| LEG-005 | Remove or detach QR using Frappe APIs | Not Executed | Phase 10 | File assertion |
| LEG-006 | Delete `ZADV-SA-2026-00001` using Frappe APIs | Not Executed | Phase 10 | Existence test |
| LEG-007 | Verify Comment and Version handling | Not Executed | Phase 10 | Dependency audit |
| LEG-008 | Remove Series only when no documents remain | Not Executed | Phase 10 | Series assertion |
| LEG-009 | Remove legacy Print Format | Present | Phase 10 | Metadata test |
| LEG-010 | Remove legacy JavaScript | Present | Phase 10 | Repository scan |
| LEG-011 | Remove legacy Python controllers | Present | Phase 10 | Repository scan |
| LEG-012 | Remove legacy hooks | Present | Phase 10 | Hook scan |
| LEG-013 | Remove legacy translations | Present | Phase 10 | Translation scan |
| LEG-014 | Remove legacy fixtures | Present | Phase 10 | Fixture scan |
| LEG-015 | Remove all schema links | Three links exist | Phase 5 and 10 | Metadata query |
| LEG-016 | Remove old DocType last | Present | Phase 10 | Clean migration |
| LEG-017 | Do not delete business documents using SQL | Active constraint | Phase 10 | Code review |

Planned branch: `refactor/remove-zadv-doctype`.

---

## 16. Rollout verification

| ID | Requirement | Current state | Phase | Verification |
|---|---|---|---|---|
| ROL-001 | Run full application tests | Pending | Phase 11 | Test output |
| ROL-002 | Test clean installation | Pending | Phase 11 | Clean-site result |
| ROL-003 | Test migration from Square Angles state | Pending | Phase 11 | Migration output |
| ROL-004 | Repeat migration for idempotency | Pending | Phase 11 | Second-run output |
| ROL-005 | Verify Phase 1 end-to-end | Pending | Phase 11 | Site results |
| ROL-006 | Verify Phase 2 B2B end-to-end | Pending | Phase 11 | Clearance results |
| ROL-007 | Verify Phase 2 B2C end-to-end | Pending | Phase 11 | Reporting results |
| ROL-008 | Verify GL and cancellation | Pending | Phase 11 | GL comparison |
| ROL-009 | Rehearse rollback | Pending | Phase 11 | Rollback record |
| ROL-010 | Obtain approval before wider rollout | Pending | Phase 11 | Approval record |

---

## 17. Current next requirement

The first implementation requirement is `CN-001`.

Ordinary credit notes without advance deductions must not be blocked by advance-total validation.

Planned branch:

`fix/return-credit-note-advance-validation`

No legacy document, field, Workspace, File, or Series record will be deleted in that phase.

---

## 18. Traceability maintenance

After every implementation phase:

1. update affected requirement rows;
2. record implementation commits;
3. record executed tests;
4. update current-state statuses;
5. update `ARCHITECTURE_DECISIONS.md` when decisions change;
6. update `TEST_MATRIX.md`;
7. update `CURRENT_STATUS.md`.

A requirement may be marked `Completed` only after its acceptance tests pass and the relevant Git diff has been reviewed.

---

## Phase 1 evidence record

Branch:

```text
fix/return-credit-note-advance-validation
```

Evidence:

```text
12 focused tests passed
10 existing regression tests passed
22 total automated tests passed
py_compile passed
Draft CN-RET-2026-00002 saved against SINV-2026-00024
No migration or schema change
```

Remaining site evidence not claimed:

- ordinary credit-note Submit;
- ordinary credit-note Cancel and GL reversal;
- ordinary positive Sales Invoice Submit.
