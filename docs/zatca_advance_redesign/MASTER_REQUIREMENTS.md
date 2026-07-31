# ZATCA Advance Redesign — Master Requirements

## 1. Document control

| Item | Value |
|---|---|
| Status | Active master specification |
| Application | `zatca_erpgulf` |
| Target platform | Frappe / ERPNext v15 |
| Initial implementation site | `squareangles.top1erp.com` |
| Initial Company | `Square Angles Contacting Company` |
| Current planning branch | `audit/zatca-advance-current-state` |
| Baseline commit | `a8a6b07da3a11946fba1ee70015da18147e83ce9` |
| Primary audit | `CURRENT_STATE_AUDIT.md` |
| Architecture decisions | `ARCHITECTURE_DECISIONS.md` |
| Traceability | `REQUIREMENTS_TRACEABILITY.md` |
| Implementation plan | `IMPLEMENTATION_PLAN.md` |
| Migration and rollback | `MIGRATION_AND_ROLLBACK.md` |
| Test matrix | `TEST_MATRIX.md` |
| Current status | `CURRENT_STATUS.md` |

This document is the authoritative functional and technical requirements specification for redesigning the ZATCA advance-payment workflow in `zatca_erpgulf`.

It consolidates:

- approved user requirements;
- verified current-state findings;
- accepted architecture decisions;
- migration constraints;
- testing and rollout requirements.

Where this document conflicts with an earlier informal note, this document governs after review and approval.

Official ZATCA regulatory verification remains mandatory before final XML and compliance acceptance.

---

## 2. Purpose

The redesign must replace the current custom advance-invoice implementation based on:

```text
ZATCA Advance Tax Invoice
```

with a standard Sales Invoice-based workflow.

The target solution must:

- use standard ERPNext accounting documents;
- preserve Phase 1 behavior;
- preserve Phase 2 B2B clearance behavior;
- preserve Phase 2 B2C reporting behavior;
- support advance invoices, final settlement invoices, and credit notes;
- support partial and full settlements;
- support multiple advances against one final invoice;
- support multicurrency;
- maintain accounting traceability;
- remove obsolete custom fields and duplicate configuration;
- safely retire the legacy ZADV DocType;
- remain idempotent across install, migrate, and update operations.

---

## 3. Primary business objective

The application must represent customer advance tax invoices using standard Sales Invoice documents instead of a separate custom accounting-like document.

The redesign must provide a coherent flow:

1. receive or recognize a customer advance;
2. issue an initial advance tax invoice;
3. optionally link that invoice to a Payment Entry;
4. later apply part or all of the advance to a final Sales Invoice;
5. issue credit notes when all or part of the advance or final invoice is reversed;
6. maintain the available unused advance balance;
7. generate correct accounting entries;
8. generate correct ZATCA XML and QR artifacts;
9. report the advance lifecycle and remaining balance.

---

## 4. Non-negotiable delivery controls

### 4.1 Full audit before modification

No application or database change may begin without:

- repository audit;
- hook and execution-path audit;
- field and metadata audit;
- site data audit;
- existing test baseline;
- dependency inventory.

The repository and initial-site audit are complete.

### 4.2 Initial site restriction

Initial implementation, migration, destructive cleanup, and rollout rehearsal are restricted to:

```text
squareangles.top1erp.com
```

No other site may receive destructive migration until the initial site passes all required acceptance criteria.

### 4.3 One concern per branch and pull request

Each independent technical concern must use a separate branch and pull request.

Examples:

- ordinary credit-note regression;
- standard advance foundation;
- Payment Entry linkage;
- deferred revenue validation;
- deduction and multicurrency;
- credit-note reversal;
- GL integration;
- XML and QR;
- report;
- Workspace cleanup;
- field visibility;
- abbreviation fields;
- naming series;
- legacy removal.

### 4.4 No silent core modification

ERPNext core files must not be modified without:

1. documented technical necessity;
2. extension-point analysis;
3. upgrade-impact analysis;
4. a separate architecture decision;
5. explicit user approval.

### 4.5 No completion without evidence

A phase is not complete until:

- relevant tests pass;
- `git diff --check` passes;
- changed-file list is reviewed;
- full diff is reviewed;
- affected documentation is updated;
- site result is verified where applicable.

### 4.6 Read-only audit rule

Audit scripts must not:

- modify documents;
- run migrations;
- delete records;
- clear legacy values;
- remove files;
- change naming series.

### 4.7 Idempotency

All setup and migration routines must be safe to run repeatedly.

Repeated execution must not create:

- duplicate fields;
- duplicate Property Setters;
- duplicate Workspaces;
- duplicate reports;
- duplicate naming-series options;
- duplicate advance invoices;
- duplicate legacy cleanup actions.

---

## 5. Verified baseline

### 5.1 Runtime versions

| Component | Version |
|---|---|
| Frappe | `15.103.0` |
| ERPNext | `15.101.2` |
| HRMS | `15.58.4` |
| `zatca_erpgulf` | `3.0` |
| Python | `3.10.14` |
| Node.js | `18.20.8` |
| npm | `10.8.2` |

### 5.2 Installed applications on the initial site

- `frappe`
- `erpnext`
- `saas_quota`
- `zatca_erpgulf`

### 5.3 Baseline test result

```text
Ran 10 tests in 0.115s

OK
```

### 5.4 Initial Company state

Company:

```text
Square Angles Contacting Company
```

Relevant values:

| Field | Value |
|---|---|
| `abbr` | `SA` |
| `custom_zatca_invoice_enabled` | `1` |
| `custom_phase_1_or_2` | `Phase-1` |
| `custom_select` | `Production` |
| `custom_send_invoice_to_zatca` | `Live` |

The fallback field:

```text
phase_1_or_2
```

does not exist on the initial site.

---

## 6. Target document architecture

### 6.1 Standard Sales Invoice

The following transactions must use standard Sales Invoice:

- initial advance-payment invoice;
- final invoice applying one or more advances;
- credit note against an initial advance invoice;
- credit note against a final settlement invoice.

### 6.2 Legacy DocType retirement

The custom:

```text
ZATCA Advance Tax Invoice
```

must eventually be removed.

It must not be removed until:

- all links are migrated;
- all runtime references are removed;
- all fixtures are removed;
- all hooks are removed;
- all reports and print formats are migrated;
- all legacy documents are safely handled;
- migration and rollback tests pass.

### 6.3 Standard accounting behavior

The redesign must rely on standard Sales Invoice and Payment Entry accounting behavior wherever possible.

Custom accounting logic must be limited, documented, and tested.

---

## 7. Canonical advance marker

### 7.1 Canonical field

Use:

```text
is_advance_payment
```

### 7.2 Required metadata

| Property | Value |
|---|---|
| Label | `Is Advance Payment Invoice` |
| Fieldname | `is_advance_payment` |
| Fieldtype | Check |
| Insert after | `is_debit_note` |
| No Copy | `1` |

### 7.3 Existing-site guard

For every site:

1. check whether `is_advance_payment` exists;
2. check whether `custom_is_advance_payment` exists;
3. reuse existing `is_advance_payment`;
4. do not create a duplicate when `custom_is_advance_payment` exists;
5. create `is_advance_payment` only when neither exists;
6. never create `custom_is_advance_payment` on new sites.

### 7.4 Compatibility resolver

During the compatibility period, application logic may resolve the marker as:

```python
bool(
    doc.get("is_advance_payment")
    or doc.get("custom_is_advance_payment")
)
```

The exact implementation must handle absent fields safely.

### 7.5 Both-fields conflict

When both marker fields exist:

- audit all Sales Invoice records;
- identify conflicting values;
- do not automatically overwrite data;
- block destructive cleanup until conflicts are resolved.

### 7.6 Mutual exclusion

An initial advance invoice must not contain meaningful advance-deduction rows.

A final invoice containing advance deductions must not be marked as an initial advance invoice.

---

## 8. Company ZATCA controls

### 8.1 Master enablement

Use:

```text
custom_zatca_invoice_enabled
```

### 8.2 Phase resolution

Prefer:

```text
custom_phase_1_or_2
```

Fallback:

```text
phase_1_or_2
```

The fallback is used only when the preferred field is absent or empty according to the approved resolver.

### 8.3 Environment

Use:

```text
custom_select
```

### 8.4 B2C submission method

Use:

```text
custom_send_invoice_to_zatca
```

### 8.5 No advance-only control set

The redesign must not create separate advance-only controls for:

- enablement;
- Phase 1 or Phase 2;
- environment;
- signing;
- API submission;
- local-only mode;
- B2C submission method;
- Terms and Conditions.

---

## 9. Obsolete Company fields

The following fields must be removed after all runtime references are eliminated:

```text
custom_zatca_advance_payment_section
custom_zatca_advance_payment_enabled
custom_zatca_advance_default_tc_name
custom_zatca_advance_payment_submission_mode
custom_zatca_advance_signing_enabled
custom_zatca_advance_api_submission_enabled
```

### 9.1 No value migration

Values stored in these obsolete fields must not be migrated to the general Company controls.

### 9.2 Removal order

1. remove Python dependencies;
2. remove JavaScript dependencies;
3. remove UI dependencies;
4. remove Property Setter creation;
5. remove fixture references;
6. remove setup synchronization;
7. remove translation entries;
8. export existing values;
9. delete Custom Field records;
10. delete Property Setter records;
11. run migration;
12. verify fields are not recreated.

### 9.3 Section Break

The Section Break has no database column and is removed as metadata only.

---

## 10. Terms and Conditions

The redesign must use standard Sales Invoice fields:

```text
tc_name
terms
```

The obsolete Company field:

```text
custom_zatca_advance_default_tc_name
```

must not be replaced by another advance-only setting.

---

## 11. Phase 1 behavior

When Company phase resolves to Phase 1:

- the advance is a standard Sales Invoice;
- the invoice uses the standard Phase 1 local flow;
- the Phase 1 QR is generated;
- Phase 2 signing is not executed;
- Phase 2 clearance is not called;
- Phase 2 reporting is not called;
- QR data represents only the current invoice.

Phase 1 behavior must remain compatible with ordinary Sales Invoices and credit notes.

---

## 12. Phase 2 behavior

When Company phase resolves to Phase 2:

- standard Sales Invoice signing is used;
- the configured ZATCA environment is used;
- standard B2B invoices use clearance;
- simplified B2C invoices use reporting;
- the general B2C submission method is honored;
- accepted ZATCA status is stored consistently;
- retry behavior must not create duplicate submissions.

---

## 13. ZATCA document classification

Subject to current official ZATCA verification, use:

| Transaction | Document type code |
|---|---:|
| Initial advance invoice | `386` |
| Final invoice applying an advance | `388` |
| Credit note | `381` |

Subject to current official ZATCA verification, use:

| Classification | Invoice type name |
|---|---|
| Standard B2B | `0100000` |
| Simplified B2C | `0200000` |

These values must not be treated as finally accepted until official-source verification is completed and recorded.

---

## 14. Payment Entry linkage

### 14.1 New field

Add to Sales Invoice:

```text
custom_zatca_payment_entry
```

### 14.2 Required metadata

| Property | Value |
|---|---|
| Label | `ZATCA Payment Entry` |
| Fieldtype | Link |
| Options | `Payment Entry` |
| Allow on Submit | `1` |
| No Copy | `1` |
| Required | No |

### 14.3 Visibility

The field is visible only when the invoice is marked as an advance invoice.

### 14.4 Canonical direction

Use:

```text
Sales Invoice.custom_zatca_payment_entry
    → Payment Entry
```

### 14.5 Optional relationship

An advance Sales Invoice may:

- be created from a Payment Entry; or
- exist independently without a Payment Entry.

### 14.6 Mapping requirements

When created from a Payment Entry, preserve:

- Company;
- Customer;
- posting date where appropriate;
- currency;
- paid amount;
- received amount;
- source exchange rate;
- target exchange rate;
- base or local equivalent.

### 14.7 Duplicate prevention

The same Payment Entry must not silently generate multiple active advance Sales Invoices.

Approved behavior for cancelled or amended mapped invoices must be explicit and tested.

### 14.8 Legacy link

The legacy relationship:

```text
Payment Entry.custom_zatca_advance_tax_invoice
    → ZATCA Advance Tax Invoice
```

must eventually be removed.

The Payment Entry itself must never be deleted during legacy ZADV cleanup.

---

## 15. Initial advance invoice behavior

An initial advance invoice must:

- be a standard Sales Invoice;
- have the advance marker enabled;
- use type code `386`;
- optionally link to a Payment Entry;
- use a valid deferred revenue or equivalent account;
- use one Income Account across all Item rows;
- not contain advance deduction rows;
- follow standard Phase 1 or Phase 2 submission behavior;
- maintain source and base currency totals;
- support partial or full credit notes.

---

## 16. Deferred revenue account requirements

### 16.1 Preferred default

Use Company:

```text
Default Deferred Revenue Account
```

as the preferred account for advance invoice Item rows.

### 16.2 Missing default

When no default deferred revenue account exists:

- show a clear explanation;
- provide a link to Company Accounts configuration;
- explain that the amount is unearned revenue;
- allow the user to choose an account manually.

### 16.3 Prohibited account

Block an advance invoice when an Item Income Account equals the Company Default Income Account.

### 16.4 One-account rule

All Item rows on one initial advance invoice must use the same Income Account.

When the business transaction requires multiple deferred revenue accounts, the user must create separate advance invoices.

### 16.5 Ordinary Sales Invoices

The custom advance-account behavior must not alter ordinary Sales Invoice account selection.

---

## 17. Item grid requirements

For advance invoices:

- Income Account must be visible in the Item grid;
- Income Account column width should be `1`;
- Quantity width should first be set to `1`;
- Rate width should first be set to `1`.

The application must not force additional unrelated column-width changes merely to reach a preferred total width.

When layout remains crowded, provide user guidance instead of silently modifying more fields.

---

## 18. Final invoice and deduction model

### 18.1 Standard final invoice

A final settlement invoice is a standard Sales Invoice that contains advance deduction rows and is not marked as an initial advance invoice.

### 18.2 Source document

Each deduction row must reference a standard advance Sales Invoice.

### 18.3 Current legacy link

The current child field:

```text
ZATCA Sales Invoice Advance Deduction.zatca_advance_tax_invoice
```

links to the old DocType.

The approved migration strategy for the child field remains an implementation decision that must be finalized before schema change.

### 18.4 Eligibility filters

A selectable advance invoice must:

- belong to the same Company;
- belong to the same Customer;
- be submitted;
- not be cancelled;
- be marked as an advance invoice;
- have a positive available balance;
- meet required Phase 2 status when applicable;
- not be fully reversed.

### 18.5 Phase 2 statuses

Accepted statuses are expected to include:

```text
Cleared
Reported
```

The exact accepted list must be normalized from current application values and verified before implementation.

### 18.6 Partial and full settlement

The final invoice must support:

- partial use of one advance;
- full use of one advance;
- multiple advances on one final invoice;
- one advance consumed by multiple final invoices over time.

### 18.7 Duplicate row handling

The same advance must not be double-counted through duplicate deduction rows.

The design must either block duplicates or consolidate them deterministically.

---

## 19. Available balance calculation

The solution must calculate the unused advance balance from:

- original advance amount;
- active settlement amounts;
- active credit-note amounts;
- cancellations and reversals.

The available balance must never become negative.

The exact formula must be documented and tested for:

- no settlement;
- partial settlement;
- full settlement;
- partial credit note;
- full credit note;
- settlement followed by credit note;
- cancelled final invoice;
- cancelled credit note.

---

## 20. Multicurrency requirements

### 20.1 Preserve both currencies

The solution must preserve:

- source document currency values;
- Company or base currency equivalents.

### 20.2 Required values

Where applicable, retain:

- source total;
- source taxable amount;
- source tax amount;
- conversion rate;
- base total;
- base taxable amount;
- base tax amount;
- applied source amount;
- applied base amount;
- remaining source amount;
- remaining base amount.

### 20.3 Balance control

Settlement eligibility and over-allocation control must use the base or local equivalent.

Transaction currency alone is not sufficient when exchange rates differ.

### 20.4 Rounding

Rounding behavior must use ERPNext precision and be tested for:

- partial settlement;
- different exchange rates;
- final residual balance;
- credit-note release.

---

## 21. Credit note against initial advance

A credit note against an initial advance invoice may be:

- partial; or
- full.

It must:

- reference the original advance invoice;
- use standard Sales Invoice return behavior;
- release the correct available balance;
- preserve source and base currency values;
- prevent reversal above the currently reversible amount;
- use the correct ZATCA type code and flow;
- reverse accounting correctly;
- support cancellation.

---

## 22. Credit note against final invoice

A credit note against a final settlement invoice must:

- reference the final invoice;
- reverse the related advance consumption;
- release affected advance balances;
- reverse related deferred revenue accounting;
- preserve traceability to each affected advance;
- support partial or full credit according to approved allocation logic;
- prevent excessive reversal;
- support cancellation of the credit note.

---

## 23. Ordinary credit-note regression

The current regression:

```text
Advance total 0.00 exceeds Sales Invoice total -36000.00
```

must be fixed first.

The fix must satisfy:

- ordinary credit note without deduction rows is not blocked;
- empty deduction table is not blocked;
- zero deduction total is not compared with a negative invoice total;
- valid positive final-invoice deduction limits remain active;
- valid advance credit-note controls remain active.

The fix must not:

- bypass all return validation;
- use a broad unconditional return;
- blindly convert all values to absolute values;
- disable settlement protection.

The first implementation branch is:

```text
fix/return-credit-note-advance-validation
```

---

## 24. Final invoice accounting objective

Applied advance amounts must be recognized through accounting logic that:

- identifies the source deferred revenue Income Account;
- uses the applied amount before tax;
- reduces customer receivable correctly;
- recognizes revenue correctly;
- avoids double tax recognition;
- supports multiple source accounts;
- supports partial settlement;
- supports credit-note and cancellation reversal.

---

## 25. GL aggregation requirements

Where technically feasible, create one aggregated GL row per affected source deferred revenue account.

The implementation must not create one unnecessary GL row per child row when aggregation is safe.

The accounting design must first inspect standard ERPNext Sales Invoice GL generation.

---

## 26. GL sign requirements

GL debit and credit fields must contain nonnegative values.

Direction must be represented by choosing the debit or credit field.

Credit-note and cancellation reversal must swap direction appropriately.

Negative debit or credit values must not be used as a shortcut.

---

## 27. GL stop condition

When no supported extension point can safely implement the required accounting:

- stop implementation;
- document the limitation;
- do not patch ERPNext core silently;
- present the architecture options for approval.

---

## 28. XML advance references

A final invoice applying multiple advances must generate multiple XML:

```text
DocumentReference
```

elements.

Do not combine multiple IDs into a comma-delimited string.

Each reference should include, where available:

- advance invoice ID;
- advance invoice UUID;
- IssueDate;
- IssueTime;
- DocumentTypeCode `386`.

---

## 29. XML PrepaidAmount

Subject to official ZATCA verification:

```text
PrepaidAmount
```

must represent the applied advance amount inclusive of VAT.

The XML must reconcile:

- applied taxable amount;
- applied tax amount;
- tax-inclusive prepaid amount;
- final payable amount.

---

## 30. VAT grouping

Advance adjustment or zero-value lines must be grouped by:

- VAT category;
- VAT rate.

Different categories or rates must not be combined into one group.

The implementation must support, where applicable:

- standard-rated;
- zero-rated;
- exempt;
- out-of-scope;
- mixed-rate invoices.

---

## 31. Debug XML parity

The action:

```text
Create XML for Debug
```

must use the same business logic as production generation for:

- document classification;
- references;
- totals;
- PrepaidAmount;
- VAT grouping;
- deduction logic;
- type codes;
- invoice type names.

Debug mode may skip API transmission, but it must not calculate different business data.

---

## 32. QR requirements

### 32.1 Current document only

QR data must represent only the current Sales Invoice.

It must not reuse or encode:

- Payment Entry data as the invoice;
- legacy ZADV QR data;
- a final invoice when generating an advance invoice QR;
- a previous invoice QR.

### 32.2 Phase 1

Phase 1 QR generation must remain operational.

### 32.3 Phase 2

Phase 2 QR behavior must remain compatible with signed and accepted invoice output.

### 32.4 Regeneration

Regenerating a QR must produce deterministic current-document data without cross-document contamination.

---

## 33. ZATCA status handling

The redesign must:

- preserve existing standard status behavior;
- normalize advance invoice status eligibility;
- distinguish accepted, pending, rejected, and failed states;
- prevent use of rejected or invalid Phase 2 advance invoices;
- preserve UUID and response data where applicable;
- avoid duplicate reporting or clearance submissions.

Exact status values must be audited from the current application before final implementation.

---

## 34. Advance settlement report

A new report must show advance usage and remaining balances.

### 34.1 Required filters

- Company;
- Advance Invoice;
- Customer;
- Final Invoice.

### 34.2 Empty filters

When all filters are empty, show all rows permitted by user permissions.

### 34.3 Required columns

At minimum:

- Company;
- Customer;
- advance invoice;
- posting date;
- currency;
- original amount;
- original base amount;
- taxable amount;
- tax amount;
- final invoice;
- amount applied;
- base amount applied;
- credited amount;
- remaining amount;
- remaining base amount;
- ZATCA status;
- settlement status.

### 34.4 Permissions

The report must respect standard ERPNext Company and document permissions.

### 34.5 Workspace placement

Place the report shortcut below:

```text
ZATCA POS Invoices with warnings
```

in the canonical ZATCA Workspace.

---

## 35. Workspace normalization

Keep:

```text
ZATCA
```

Remove:

```text
ZATCA ERPGulf
```

The obsolete Workspace must not be recreated by:

- fixtures;
- install hooks;
- update hooks;
- setup synchronization;
- migration.

Required shortcuts and cards must be preserved in the canonical Workspace.

---

## 36. Phase 2-only field visibility

Approved Phase 2-only fields must be visible only when:

```text
custom_zatca_invoice_enabled = 1
```

and resolved Company phase is:

```text
Phase-2
```

The visibility resolver must support:

```text
custom_phase_1_or_2
phase_1_or_2
```

Obsolete advance-specific controls must not affect visibility.

The UI must re-evaluate visibility when Company changes.

---

## 37. Company abbreviation fields

### 37.1 Target DocTypes

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

### 37.2 Guard

For each DocType:

1. check for `abbr`;
2. check for `custom_abbr`;
3. add nothing when either exists;
4. do not rename `custom_abbr`;
5. otherwise add exact fieldname `abbr`.

### 37.3 Required metadata

| Property | Value |
|---|---|
| Label | `abbr` |
| Fieldname | `abbr` |
| Fieldtype | Data |
| Fetch From | `company.abbr` |
| Hidden | `1` |
| Translatable | `1` |
| Insert after | `company` |

### 37.4 Initial-site state

Neither field exists on any of the twelve target DocTypes on the initial test site.

### 37.5 Idempotency

Repeated setup must not create duplicates.

---

## 38. Sales Invoice ADV naming series

Add:

```text
ADV-.abbr.-.YYYY.-
```

only when no existing Sales Invoice naming-series line contains:

```text
ADV
```

### 38.1 Preserve existing options

Do not remove or alter existing Sales Invoice series.

### 38.2 Existing ADV option

When any existing line contains `ADV`, do not add another automatically.

### 38.3 Repeated setup

Repeated setup must not duplicate the option.

### 38.4 Naming behavior

The series must resolve the Company abbreviation correctly.

---

## 39. Legacy ZADV baseline

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

Legacy QR:

```text
/files/QR-Phase1-ZATCA-Advance-ZADV-SA-2026-00001.png
```

Legacy Series:

```text
ZADV-SA-2026-
```

Series value:

```text
1
```

---

## 40. Legacy dependency baseline

Confirmed dependencies:

- one linked Payment Entry;
- one QR File;
- one attachment Comment;
- two Version records;
- one Series record.

Not found:

- ZADV GL Entries;
- standard Sales Invoice Advance allocations;
- custom deduction rows referencing the legacy document;
- Communications;
- ToDos.

The document must not be treated as an orphan.

---

## 41. Legacy schema links

The following links currently point to the old DocType:

```text
Payment Entry.custom_zatca_advance_tax_invoice
Sales Invoice.custom_advance_invoice_reference
ZATCA Sales Invoice Advance Deduction.zatca_advance_tax_invoice
```

These links must be migrated or removed before deleting the old DocType.

---

## 42. Legacy Print Format

The active standard Jinja Print Format:

```text
ZATCA Advance Tax Invoice
```

must be removed after the workflow is fully migrated.

It must not be removed while users still require the legacy document.

---

## 43. Legacy cleanup preconditions

Before destructive cleanup:

1. repeat reference audit;
2. confirm exact target site;
3. confirm exact target document;
4. export audit snapshot;
5. take database backup;
6. take public files backup;
7. take private files backup;
8. verify backup files;
9. record Git commit;
10. confirm no new GL Entries;
11. confirm no new deduction references;
12. confirm no new allocation references;
13. confirm no new Sales Invoice links;
14. record Payment Entry values;
15. record File, Comment, and Version values;
16. obtain explicit approval.

---

## 44. Legacy cleanup order

1. preserve pre-removal evidence;
2. clear obsolete Payment Entry fields;
3. remove or detach QR File through Frappe APIs;
4. delete ZADV document through Frappe APIs;
5. verify Comment and Version handling;
6. remove legacy Print Format;
7. remove legacy JavaScript;
8. remove legacy Python controllers;
9. remove legacy hooks;
10. remove obsolete translations;
11. remove obsolete fixtures;
12. remove obsolete Company fields;
13. remove obsolete Property Setters;
14. remove legacy Payment Entry fields;
15. remove or migrate schema links;
16. remove legacy DocType last;
17. remove legacy Series only when no document remains.

Direct SQL deletion of the business document is prohibited.

---

## 45. Migration requirements

### 45.1 Additive changes first

Add guarded fields, reports, Workspace content, and naming series before destructive cleanup.

### 45.2 Behavioral activation second

Activate the standard Sales Invoice workflow and verify it.

### 45.3 Data transition third

Transition links, balances, and references.

### 45.4 Destructive cleanup last

Delete obsolete schema and legacy records only after successful verification.

### 45.5 Dry run

Destructive migration must support a read-only dry run that returns:

```text
READY
```

or:

```text
BLOCKED
```

with explicit reasons.

### 45.6 Site targeting

Destructive migration must require explicit site targeting.

### 45.7 Transaction safety

Unexpected exceptions must roll back the current database transaction and stop further cleanup.

---

## 46. Backup requirements

The final pre-migration backup must include:

- database;
- public files;
- private files;
- site configuration;
- application commit reference.

Backup verification must include:

- file existence;
- nonzero size;
- correct timestamp;
- readable archive contents;
- nonempty database dump.

The pre-migration backup must remain available until wider rollout is approved.

---

## 47. Rollback requirements

### 47.1 Code-only rollback

For phases without schema or data changes:

- deploy the previous commit;
- restart services;
- clear cache where required;
- run smoke tests.

### 47.2 Additive schema rollback

Harmless additive fields may remain temporarily when old code still functions.

When removal is required:

- remove only migration-added metadata;
- run migration;
- verify existing documents.

### 47.3 Destructive rollback

After ZADV, File, field, or DocType deletion, the preferred rollback is:

```text
Restore the full pre-migration database and files backup.
```

Then deploy the matching pre-migration application commit.

### 47.4 Preserve failed state

Before restoration, preserve:

- logs;
- traceback;
- migration output;
- current Git state;
- failed database snapshot where feasible.

---

## 48. Testing requirements

The test matrix must cover:

- baseline regression;
- ordinary credit notes;
- marker field matrix;
- Company resolver;
- Payment Entry mapping;
- deferred revenue accounts;
- Item grid metadata;
- eligibility;
- available balance;
- partial and full settlement;
- multicurrency;
- initial advance credit notes;
- final invoice credit notes;
- standard GL baseline;
- custom advance GL;
- XML classification;
- multiple references;
- PrepaidAmount;
- VAT grouping;
- Phase 1 QR;
- Phase 2 B2B clearance;
- Phase 2 B2C reporting;
- debug XML parity;
- report permissions and values;
- Workspace idempotency;
- field visibility;
- abbreviation fields;
- naming series;
- legacy cleanup;
- migration dry run;
- migration idempotency;
- rollback;
- clean installation;
- upgrade compatibility;
- permissions;
- concurrency;
- cancellation;
- translations;
- repository scans.

---

## 49. Accounting acceptance

Accounting is not accepted until tests confirm:

- total debit equals total credit;
- customer receivable is correct;
- deferred revenue is correct;
- recognized revenue is correct;
- tax payable is correct;
- base currency is correct;
- account currency is correct;
- partial settlement uses only the applied amount;
- cancellation reverses correctly;
- credit notes reverse correctly.

Accounting approval must be recorded before wider rollout.

---

## 50. ZATCA acceptance

ZATCA behavior is not accepted until:

- official current specifications are reviewed;
- XML schema validates;
- type codes are verified;
- invoice type names are verified;
- multiple references are correct;
- PrepaidAmount is verified;
- VAT grouping is correct;
- Phase 1 QR is correct;
- B2B clearance passes;
- B2C reporting passes;
- debug XML matches production business logic.

---

## 51. Permissions and security

The redesign must respect:

- Sales Invoice permissions;
- Payment Entry permissions;
- Company permissions;
- report permissions;
- file permissions;
- administrator-only migration permissions.

Migration logs must not contain:

- private keys;
- certificates;
- passwords;
- tokens;
- full authentication payloads.

Cleanup must affect only explicitly identified records.

---

## 52. Concurrency requirements

The design must prevent race conditions such as:

- two final invoices consuming the same remaining advance;
- simultaneous credit note and settlement;
- duplicate Payment Entry mapping requests;
- migration running while affected documents are being posted.

The implementation must use appropriate validation, locking, or transactional checks.

---

## 53. Performance requirements

The solution must avoid:

- excessive query counts;
- repeated full-table scans during normal form use;
- slow unfiltered report behavior;
- unnecessary writes during repeated setup;
- long-running locks during migration.

Performance tests must cover realistic advance and settlement volumes.

---

## 54. Translation and UI requirements

### 54.1 Language behavior

Arabic translations must appear only when Arabic is selected.

English UI must remain English.

### 54.2 Obsolete labels

Labels and help text for removed fields must be removed.

### 54.3 Product wording

Custom UI labels and help text must not contain the word:

```text
ERPNext
```

unless required in technical documentation rather than user-facing UI.

### 54.4 Validation messages

Messages must be:

- clear;
- actionable;
- specific to the failed rule;
- translated where applicable.

---

## 55. Clean installation requirements

On a clean final-design site:

- the standard marker is created only when needed;
- Payment Entry link field exists once;
- old ZADV DocType is absent;
- obsolete Company fields are absent;
- canonical ZATCA Workspace exists once;
- duplicate Workspace is absent;
- advance report exists once;
- abbreviation fields follow guards;
- ADV naming series follows guards;
- repeated setup remains idempotent.

---

## 56. Existing-site compatibility

The migration must support sites with:

- existing `is_advance_payment`;
- existing `custom_is_advance_payment`;
- both marker fields;
- preferred phase field;
- fallback phase field;
- existing `abbr`;
- existing `custom_abbr`;
- existing ADV naming series;
- one or both ZATCA Workspaces;
- legacy ZADV documents;
- legacy deduction rows.

Unexpected site states must block automatic destructive migration and require a site-specific plan.

---

## 57. SaaS provisioning

The final design must integrate with the existing SaaS provisioning workflow through an audited, idempotent setup function.

The exact integration point remains open pending audit of:

- `zatca_erpgulf` install hooks;
- `saas_quota` provisioning;
- SaaS Manager commands;
- site post-provisioning flow.

No provisioning integration may be chosen by assumption.

---

## 58. Open implementation decisions

The following decisions remain open:

### 58.1 Deduction child field

Choose whether to:

- retain the existing fieldname and change Link options;
- add a new field and migrate;
- replace the child DocType.

### 58.2 Final invoice GL extension point

Select the supported ERPNext extension point after auditing standard GL generation.

### 58.3 Legacy cleanup mechanism

Choose among:

- idempotent patch;
- controlled administrative command;
- site-targeted migration helper.

### 58.4 SaaS provisioning integration

Select the correct provisioning entry point after audit.

### 58.5 Report architecture

Choose Query Report, Script Report, Query Builder, or server-side aggregation based on permissions, multicurrency, and performance.

### 58.6 Both-marker-field resolution

Define the final site migration policy when both marker fields exist with conflicting data.

---

## 59. Explicitly out of scope without separate approval

The redesign must not silently include:

- unrelated ERPNext core changes;
- unrelated ZATCA refactors;
- unrelated field renaming;
- mass migration of all tenant sites;
- deletion of unrelated Workspaces;
- deletion of unrelated reports;
- redesign of ordinary Sales Invoice accounting;
- replacement of standard Payment Entry accounting;
- changes to unrelated naming series;
- broad translation cleanup outside the redesign;
- deletion of unrelated File records;
- automatic modification of existing `custom_abbr`.

---

## 60. Branch plan

| Concern | Branch |
|---|---|
| Integration | `epic/zatca-standard-advance-invoices` |
| Audit and planning | `audit/zatca-advance-current-state` |
| Credit-note regression | `fix/return-credit-note-advance-validation` |
| Standard advance foundation | `feature/standard-sales-invoice-advance-core` |
| Payment Entry link | `feature/advance-payment-entry-link` |
| Income Account validation | `feature/advance-income-account-validation` |
| Deduction and multicurrency | `feature/advance-deduction-multicurrency` |
| Credit-note reversal | `feature/advance-credit-note-reversal` |
| Final invoice GL | `feature/advance-final-invoice-gl` |
| XML and QR | `feature/advance-zatca-xml` |
| Report | `feature/advance-report` |
| Workspace | `fix/zatca-workspace-deduplication` |
| Phase 2 visibility | `feature/zatca-phase2-field-visibility` |
| Abbreviation fields | `feature/company-abbr-fields` |
| Naming series | `feature/advance-sales-invoice-naming-series` |
| Legacy removal | `refactor/remove-zadv-doctype` |

---

## 61. Phase order

1. Phase 0 — Audit and planning
2. Phase 1 — Ordinary credit-note regression
3. Phase 2 — Standard Sales Invoice foundation
4. Phase 3 — Payment Entry linkage
5. Phase 4 — Deferred revenue validation
6. Phase 5 — Deduction and multicurrency
7. Phase 6 — Credit-note reversals
8. Phase 7 — Final invoice GL
9. Phase 8 — XML, QR, and debug generation
10. Phase 9A — Advance settlement report
11. Phase 9B — Workspace deduplication
12. Phase 9C — Phase 2 visibility
13. Phase 9D — Company abbreviation fields
14. Phase 9E — ADV naming series
15. Phase 10 — Legacy ZADV removal
16. Phase 11 — Full regression and rollout

The order may change only through an updated architecture decision and traceability review.

---

## 62. Rollout waves

### Wave 0

```text
squareangles.top1erp.com
```

Purpose:

- initial implementation;
- migration rehearsal;
- destructive cleanup rehearsal;
- rollback rehearsal.

### Wave 1

Small controlled internal or low-risk sites.

### Wave 2

Phase 1 production sites.

### Wave 3

Phase 2 B2B and B2C sites.

No wave may begin until the previous wave is accepted.

---

## 63. Global acceptance criteria

The redesign is complete only when:

- standard Sales Invoice fully replaces the legacy workflow;
- ordinary credit-note regression is fixed;
- Phase 1 behavior passes;
- Phase 2 B2B behavior passes;
- Phase 2 B2C behavior passes;
- Payment Entry linkage works;
- standalone advance invoices work;
- deferred revenue validation works;
- partial and full settlements work;
- multiple advances work;
- multicurrency works;
- credit-note reversals work;
- GL entries are approved;
- XML and QR are approved;
- report balances reconcile;
- duplicate Workspace is removed;
- Phase 2 field visibility is correct;
- abbreviation fields are idempotent;
- ADV naming series is idempotent;
- obsolete fields are removed;
- legacy document and DocType are safely removed;
- repeated migrate succeeds;
- clean installation succeeds;
- rollback rehearsal succeeds;
- documentation is current;
- wider rollout receives explicit approval.

---

## 64. Current project state

| Area | Status |
|---|---|
| Repository audit | Complete |
| Initial-site audit | Complete |
| Baseline tests | Passed |
| Architecture decisions | Documented |
| Traceability | Documented |
| Implementation plan | Documented |
| Migration and rollback | Documented |
| Test matrix | Documented |
| Current status | Documented |
| Master requirements | This document |
| Official ZATCA verification | Pending |
| Implementation | Not started |
| Destructive migration | Not started |
| Wider rollout | Not approved |

---

## 65. Immediate next action

After all Phase 0 documentation files are uploaded, validated, reviewed, and committed:

1. create the integration baseline as approved;
2. create branch:

```text
fix/return-credit-note-advance-validation
```

3. implement only the ordinary credit-note regression fix;
4. add focused tests;
5. run baseline and regression tests;
6. review the full diff;
7. update:
   - `CURRENT_STATUS.md`
   - `REQUIREMENTS_TRACEABILITY.md`
   - `TEST_MATRIX.md`
   - `ARCHITECTURE_DECISIONS.md` when needed.

No schema deletion, legacy ZADV deletion, Workspace deletion, or naming-series change is part of the immediate next phase.

---

## 66. Master-specification maintenance

Any approved scope change must update:

- this document;
- `ARCHITECTURE_DECISIONS.md`;
- `REQUIREMENTS_TRACEABILITY.md`;
- `IMPLEMENTATION_PLAN.md`;
- `TEST_MATRIX.md`;
- `CURRENT_STATUS.md`;
- `MIGRATION_AND_ROLLBACK.md` when migration behavior changes.

A requirement may be marked completed only when its acceptance tests pass and the relevant implementation diff has been reviewed.
