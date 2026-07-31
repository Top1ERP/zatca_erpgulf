# ZATCA Advance Redesign — Implementation Plan

## 1. Document status

| Item | Value |
|---|---|
| Status | Active |
| Application | `zatca_erpgulf` |
| Initial test site | `squareangles.top1erp.com` |
| Audit document | `CURRENT_STATE_AUDIT.md` |
| Decisions document | `ARCHITECTURE_DECISIONS.md` |
| Traceability document | `REQUIREMENTS_TRACEABILITY.md` |
| Current branch | `audit/zatca-advance-current-state` |

This plan defines the implementation order for replacing the custom ZATCA advance-payment workflow with standard Sales Invoice documents.

No phase may be marked complete before:

1. tests are executed;
2. `git diff --check` passes;
3. `git diff --stat` is reviewed;
4. the relevant full Git diff is reviewed;
5. affected project documents are updated;
6. the initial site result is verified where applicable.

---

## 2. Branching policy

Each technical concern uses an independent branch.

Audit and planning branch:

```text
audit/zatca-advance-current-state
```

Future integration branch:

```text
epic/zatca-standard-advance-invoices
```

One pull request must not combine unrelated concerns such as:

- credit-note validation;
- Workspace cleanup;
- abbreviation fields;
- naming-series changes;
- XML generation;
- legacy DocType deletion.

---

## 3. Site policy

Initial implementation and destructive testing are restricted to:

```text
squareangles.top1erp.com
```

No other tenant site may receive schema changes, legacy cleanup, Workspace deletion, naming-series modification, or redesigned settlement behavior until the relevant phase passes its acceptance criteria.

---

## 4. Phase 0 — Audit and planning

### Branch

```text
audit/zatca-advance-current-state
```

### Scope

- establish Git baseline;
- inventory repository files and hooks;
- inventory advance-related code;
- inspect Company, Sales Invoice, Payment Entry, and child-table fields;
- inspect Workspaces, Reports, naming series, and abbreviation fields;
- inspect the existing ZADV document and dependencies;
- run baseline tests;
- document requirements, decisions, migration, tests, and status.

### Deliverables

- `MASTER_REQUIREMENTS.md`
- `CURRENT_STATE_AUDIT.md`
- `ARCHITECTURE_DECISIONS.md`
- `REQUIREMENTS_TRACEABILITY.md`
- `IMPLEMENTATION_PLAN.md`
- `MIGRATION_AND_ROLLBACK.md`
- `TEST_MATRIX.md`
- `CURRENT_STATUS.md`

### Acceptance criteria

- repository baseline recorded;
- test site audited read-only;
- baseline tests pass;
- no application code changed;
- no database write or migration executed;
- no legacy record deleted;
- documentation reviewed.

### Current status

Audit execution and the eight Phase 0 documentation files are complete. Implementation has not started.

---

## 5. Phase 1 — Ordinary credit-note regression

### Branch

```text
fix/return-credit-note-advance-validation
```

### Problem

A normal Sales Invoice credit note may be blocked when a zero advance total is compared against a negative return total.

Observed message:

```text
Advance total 0.00 exceeds Sales Invoice total -36000.00
```

### Scope

- locate the exact validation path and callers;
- isolate ordinary credit notes from final-invoice advance validation;
- preserve advance-related credit-note controls;
- add focused regression tests.

### Constraints

Do not:

- add a broad unconditional return;
- skip all validation for every return invoice;
- blindly apply `abs()` to all values;
- disable positive final-invoice settlement limits;
- disable advance-balance release validation.

### Required tests

1. ordinary credit note with no deduction rows;
2. ordinary credit note with empty child table;
3. ordinary credit note with zero child-row values;
4. positive final invoice with excessive deduction;
5. valid positive final invoice deduction;
6. advance-related credit-note path remains active;
7. baseline tests remain green.

### Acceptance criteria

- ordinary credit note is not blocked;
- empty or zero deductions are ignored correctly;
- positive settlement validation remains active;
- no unrelated code changes;
- tests pass;
- documentation is updated.

### Database changes

None.

### Destructive actions

None.

---

## 6. Phase 2 — Standard Sales Invoice advance foundation

### Branch

```text
feature/standard-sales-invoice-advance-core
```

### Scope

- introduce canonical advance marker resolution;
- add guarded `is_advance_payment` creation;
- support existing `custom_is_advance_payment`;
- use general Company ZATCA controls;
- remove new-path runtime dependency on obsolete advance controls;
- implement advance/final-invoice mutual exclusion;
- establish document classification helpers;
- establish type-code selection foundation;
- use standard Sales Invoice Terms fields.

### Marker setup rules

1. inspect `is_advance_payment`;
2. inspect `custom_is_advance_payment`;
3. reuse existing `is_advance_payment`;
4. avoid duplicate creation;
5. create `is_advance_payment` only when neither exists;
6. do not create `custom_is_advance_payment` on new sites.

### Company control resolver

Prefer:

```text
custom_phase_1_or_2
```

Fallback:

```text
phase_1_or_2
```

Other controls:

```text
custom_zatca_invoice_enabled
custom_select
custom_send_invoice_to_zatca
```

### Validation rules

Block:

- an initial advance invoice containing meaningful deduction rows;
- a final invoice with deductions that is also marked as an advance invoice.

### Limitation

Do not delete the legacy ZADV DocType or fields in this phase.

### Acceptance criteria

- marker resolver works for supported field combinations;
- no duplicate marker is created;
- Company phase resolution is correct;
- old workflow remains temporarily available;
- setup is idempotent;
- tests pass.

---

## 7. Phase 3 — Payment Entry linkage

### Branch

```text
feature/advance-payment-entry-link
```

### Scope

Add `custom_zatca_payment_entry` to Sales Invoice.

### Required metadata

| Property | Value |
|---|---|
| Fieldtype | Link |
| Options | `Payment Entry` |
| Allow on Submit | `1` |
| No Copy | `1` |
| Required | No |
| Visibility | Advance invoices only |

### Supported paths

1. create an advance Sales Invoice from a submitted Receive Payment Entry;
2. create an advance Sales Invoice independently;
3. link a Payment Entry after invoice creation where allowed.

### Mapping requirements

Preserve:

- Company;
- Customer;
- posting date where appropriate;
- currency;
- paid and received amounts;
- source and target exchange rates;
- base or local equivalent.

### Acceptance criteria

- field metadata is correct;
- standalone invoice works;
- mapping works;
- duplicate creation is blocked safely;
- tests pass.

---

## 8. Phase 4 — Deferred revenue and Item validation

### Branch

```text
feature/advance-income-account-validation
```

### Scope

- prefer Company Default Deferred Revenue Account;
- guide the user when it is missing;
- display Income Account in the Item grid;
- enforce one Income Account per advance invoice;
- block Company Default Income Account;
- normalize selected Item grid widths.

### Grid configuration

| Field | Width |
|---|---:|
| Income Account | `1` |
| Quantity | `1` |
| Rate | `1` |

Do not force additional unrelated width changes.

### Acceptance criteria

- defaulting works;
- missing-default guidance works;
- one-account validation works;
- default income account is blocked;
- ordinary Sales Invoices are unaffected;
- tests pass.

---

## 9. Phase 5 — Deduction model and multicurrency

### Branch

```text
feature/advance-deduction-multicurrency
```

### Scope

- point deduction rows to standard advance Sales Invoices;
- calculate available balances;
- support partial and full settlement;
- support multiple advances;
- preserve currency and base values;
- apply eligibility filters;
- prevent over-allocation.

### Eligibility requirements

A selectable advance invoice must:

- belong to the same Company;
- belong to the same Customer;
- be marked as an advance invoice;
- have an available balance;
- meet required ZATCA status;
- not be fully reversed.

### Currency requirements

Preserve source and base values, including applied and remaining amounts. Settlement control must use the base or local equivalent.

### Status normalization

Accepted Phase 2 values are expected to include:

```text
Reported
Cleared
```

The exact status list must be verified against current application values before implementation.

### Child-table decision

Before implementation, decide whether to:

1. retain the existing fieldname and change its Link options;
2. add a new field and migrate data;
3. replace the child DocType.

### Acceptance criteria

- correct Company and Customer filtering;
- correct available balance;
- correct partial and full settlement;
- multiple advances supported;
- over-allocation blocked;
- source and base values reconcile;
- tests pass.

---

## 10. Phase 6 — Credit-note reversals

### Branch

```text
feature/advance-credit-note-reversal
```

### Scope

- support partial and full credit notes against initial advances;
- release available balance;
- reverse final-invoice settlement;
- maintain traceability;
- prevent excessive release.

### Acceptance criteria

- partial reversal works;
- full reversal works;
- excessive reversal is blocked;
- released balance is correct;
- final invoice reversal is traceable;
- ordinary credit notes remain unaffected;
- tests pass.

---

## 11. Phase 7 — Final invoice GL integration

### Branch

```text
feature/advance-final-invoice-gl
```

### Mandatory audit

Inspect standard ERPNext GL behavior for:

1. normal Sales Invoice;
2. Sales Invoice with taxes;
3. return Sales Invoice;
4. multi-currency Sales Invoice;
5. cancellation;
6. reposting.

### Accounting objective

For applied advances:

- identify the source deferred-revenue Income Account;
- use the settlement amount before tax;
- aggregate by account;
- reduce customer receivable correctly;
- create one aggregated row per account where feasible.

### GL requirements

- debit and credit values remain nonnegative;
- direction is represented by debit or credit selection;
- credit-note reversal uses the opposite direction;
- partial settlement must not use the full source invoice value.

### Core modification rule

No ERPNext core modification without a separate architecture decision and explicit approval.

### Stop condition

Stop implementation when no supported extension point can safely provide the required accounting behavior.

### Acceptance criteria

- GL entries match approved expectations;
- partial settlement is correct;
- customer balance is correct;
- cancellation and reversal are correct;
- tests pass.

---

## 12. Phase 8 — XML, QR, and debug generation

### Branch

```text
feature/advance-zatca-xml
```

### Scope

- initial advance invoice XML;
- final settlement invoice XML;
- credit-note XML;
- multiple advance references;
- PrepaidAmount;
- VAT grouping;
- Phase 1 QR;
- Phase 2 signing and submission;
- debug XML parity.

### Document type codes

| Transaction | Code |
|---|---:|
| Initial advance invoice | `386` |
| Final settlement invoice | `388` |
| Credit note | `381` |

### Invoice type names

| Classification | Name |
|---|---|
| Standard B2B | `0100000` |
| Simplified B2C | `0200000` |

These values must be verified against current official ZATCA documentation before phase completion.

### Document references

Generate one `DocumentReference` per applied advance invoice and include, where available:

- ID;
- UUID;
- IssueDate;
- IssueTime;
- DocumentTypeCode `386`.

Do not use comma-delimited IDs.

### Other rules

- `PrepaidAmount` is tax inclusive;
- adjustment lines are grouped by VAT category and rate;
- debug XML uses the same business logic as production;
- QR represents only the current invoice.

### Acceptance criteria

- XML schema passes;
- Phase 1 QR passes;
- B2B clearance path passes;
- B2C reporting path passes;
- multiple references are correct;
- totals reconcile;
- debug and production logic match;
- tests pass.

---

## 13. Phase 9A — Advance settlement report

### Branch

```text
feature/advance-report
```

### Filters

- Company;
- Advance Invoice;
- Customer;
- Final Invoice.

### Required output

- advance invoice;
- customer;
- Company;
- currency;
- original and base amounts;
- applied invoices and amounts;
- credited amount;
- remaining source and base balances;
- ZATCA status;
- settlement status.

### Workspace placement

Place the report below:

```text
ZATCA POS Invoices with warnings
```

### Acceptance criteria

- filters work;
- empty filters show all permitted rows;
- permissions are respected;
- balances reconcile;
- performance is acceptable;
- tests pass.

---

## 14. Phase 9B — Workspace deduplication

### Branch

```text
fix/zatca-workspace-deduplication
```

Keep:

```text
ZATCA
```

Remove and prevent recreation of:

```text
ZATCA ERPGulf
```

### Acceptance criteria

- only one ZATCA Workspace exists;
- repeated setup does not recreate the duplicate;
- reports and shortcuts remain available;
- tests pass.

---

## 15. Phase 9C — Phase 2 field visibility

### Branch

```text
feature/zatca-phase2-field-visibility
```

Approved Phase 2 fields are visible only when ZATCA is enabled and the resolved Company phase is `Phase-2`.

Support both phase fieldnames:

```text
custom_phase_1_or_2
phase_1_or_2
```

### Acceptance criteria

- fields hide when ZATCA is disabled;
- fields hide in Phase 1;
- fields show in Phase 2;
- compatibility fallback works;
- tests pass.

---

## 16. Phase 9D — Company abbreviation fields

### Branch

```text
feature/company-abbr-fields
```

### Target DocTypes

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

### Guard

For each DocType:

1. check `abbr`;
2. check `custom_abbr`;
3. add nothing when either exists;
4. do not rename `custom_abbr`;
5. otherwise add exact fieldname `abbr`.

### Required metadata

| Property | Value |
|---|---|
| Label | `abbr` |
| Fieldname | `abbr` |
| Fieldtype | Data |
| Fetch From | `company.abbr` |
| Hidden | `1` |
| Translatable | `1` |
| Insert after | `company` |

### Acceptance criteria

- all twelve DocTypes inspected;
- no duplicate fields;
- existing `custom_abbr` preserved;
- value fetch works;
- repeated setup is idempotent;
- tests pass.

---

## 17. Phase 9E — ADV naming series

### Branch

```text
feature/advance-sales-invoice-naming-series
```

Required series:

```text
ADV-.abbr.-.YYYY.-
```

Before adding, inspect every existing Sales Invoice naming-series line. When any line contains `ADV`, do not add another ADV series automatically.

### Acceptance criteria

- series added when absent;
- existing series preserved;
- duplicate not added;
- abbreviation resolves correctly;
- repeated setup is idempotent;
- tests pass.

---

## 18. Phase 10 — Legacy ZADV removal

### Branch

```text
refactor/remove-zadv-doctype
```

### Preconditions

1. repeat reference audits;
2. export structured evidence;
3. take database and files backups;
4. record application commit;
5. confirm no new GL Entries;
6. confirm no new allocations or deductions;
7. confirm no new Sales Invoice references.

### Target legacy document

```text
ZADV-SA-2026-00001
```

### Cleanup order

1. record linked Payment Entry values;
2. clear obsolete Payment Entry fields;
3. remove or detach QR File through Frappe APIs;
4. delete the legacy ZADV document through Frappe APIs;
5. verify Comment and Version handling;
6. remove legacy Print Format;
7. remove legacy client scripts and Python controllers;
8. remove legacy hooks, translations, and fixtures;
9. remove obsolete Company Custom Fields and Property Setters;
10. remove legacy Payment Entry fields;
11. remove or migrate schema links;
12. remove legacy DocType last;
13. remove legacy Series only when no document remains.

### Prohibited operation

Do not directly delete business documents using SQL.

### Acceptance criteria

- no old DocType or broken Link options remain;
- no obsolete fields or fixtures remain;
- clean migrate succeeds;
- repeated migrate succeeds;
- Phase 1 and Phase 2 tests pass.

---

## 19. Phase 11 — Full regression and rollout

### Scope

- full application test suite;
- clean installation;
- migration from current Square Angles state;
- repeated migration;
- Phase 1 end-to-end;
- Phase 2 B2B end-to-end;
- Phase 2 B2C end-to-end;
- multi-currency settlement;
- partial and full credit notes;
- final-invoice cancellation;
- GL reconciliation;
- XML and QR verification;
- report verification;
- rollback rehearsal.

### Rollout condition

No wider deployment until:

- all critical tests pass;
- accounting is approved;
- XML and QR behavior is approved;
- rollback is demonstrated;
- the user explicitly approves rollout.

---

## 20. Documentation maintenance

After every phase update:

- `CURRENT_STATUS.md`
- `ARCHITECTURE_DECISIONS.md`
- `REQUIREMENTS_TRACEABILITY.md`
- `TEST_MATRIX.md`

Also update:

- `MIGRATION_AND_ROLLBACK.md` when migration behavior changes;
- `MASTER_REQUIREMENTS.md` only when approved scope changes.

---

## 21. Immediate next implementation branch

After the audit documentation is reviewed and merged, create:

```text
fix/return-credit-note-advance-validation
```

That branch is limited to the ordinary credit-note regression.

It must not:

- delete ZADV records;
- delete Company fields;
- delete Workspaces;
- run legacy cleanup;
- change XML architecture;
- add abbreviation fields;
- change naming series.
