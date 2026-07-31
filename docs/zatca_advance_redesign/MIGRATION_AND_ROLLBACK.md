# ZATCA Advance Redesign — Migration and Rollback

## 1. Document status

| Item | Value |
|---|---|
| Status | Active |
| Application | `zatca_erpgulf` |
| Initial migration site | `squareangles.top1erp.com` |
| Audit document | `CURRENT_STATE_AUDIT.md` |
| Decisions document | `ARCHITECTURE_DECISIONS.md` |
| Traceability document | `REQUIREMENTS_TRACEABILITY.md` |
| Implementation plan | `IMPLEMENTATION_PLAN.md` |
| Current branch | `audit/zatca-advance-current-state` |

This document defines the safe migration and rollback process for replacing the custom `ZATCA Advance Tax Invoice` workflow with standard Sales Invoice documents.

It covers:

- schema changes;
- Custom Field and Property Setter changes;
- legacy document cleanup;
- Payment Entry link cleanup;
- QR File handling;
- Workspace normalization;
- naming-series changes;
- `abbr` field creation;
- report installation;
- rollback triggers;
- rollback execution;
- evidence and verification requirements.

---

## 2. Migration objective

The target state is:

- standard Sales Invoice represents initial advance invoices;
- standard Sales Invoice represents final invoices with advance settlement;
- standard Sales Invoice credit notes handle advance reversals;
- the legacy `ZATCA Advance Tax Invoice` DocType is removed;
- obsolete Company advance settings are removed;
- obsolete Payment Entry links are removed;
- deduction links point to standard Sales Invoices;
- only the canonical `ZATCA` Workspace remains;
- required `abbr` fields and ADV naming series are installed idempotently;
- Phase 1 and Phase 2 behavior remain operational.

---

## 3. Safety invariants

The following invariants apply to every migration step.

### 3.1 Site isolation

Initial destructive migration is restricted to:

```text
squareangles.top1erp.com
```

No other site may receive destructive changes until the migration is accepted on the initial site.

### 3.2 No silent cross-site rollout

A bench-wide code deployment does not authorize running destructive patches on every site.

Site migration must be explicitly targeted and logged.

### 3.3 Backup before destructive actions

No destructive step may run before:

- database backup succeeds;
- public and private files backup succeeds;
- backup files are verified to exist;
- application Git commit is recorded;
- site configuration is recorded;
- pre-migration audit passes.

### 3.4 Frappe APIs for business documents

Business documents and attached File records must be deleted or changed through supported Frappe APIs.

Direct SQL deletion of business documents is prohibited.

### 3.5 Stop on unexpected references

Migration must stop when unexpected references are found.

It must not guess that a reference is safe to ignore.

### 3.6 Idempotency

Every setup, patch, and cleanup operation must be safe to run repeatedly.

A repeated run must not:

- create duplicate fields;
- create duplicate Property Setters;
- duplicate naming-series options;
- recreate obsolete Workspaces;
- duplicate reports;
- delete unrelated records;
- change already-migrated values incorrectly.

### 3.7 Accounting preservation

The linked Payment Entry is an accounting document and must not be deleted as part of removing the legacy ZADV document.

### 3.8 No migration of obsolete configuration values

The following obsolete Company values are not migrated into new controls:

```text
custom_zatca_advance_payment_enabled
custom_zatca_advance_default_tc_name
custom_zatca_advance_payment_submission_mode
custom_zatca_advance_signing_enabled
custom_zatca_advance_api_submission_enabled
```

The redesigned workflow uses the general Company ZATCA controls.

---

## 4. Known initial-site baseline

Initial site:

```text
squareangles.top1erp.com
```

Company:

```text
Square Angles Contacting Company
```

Company abbreviation:

```text
SA
```

Legacy document:

```text
ZADV-SA-2026-00001
```

Linked Payment Entry:

```text
ACC-PAY-2026-00028
```

Legacy QR URL:

```text
/files/QR-Phase1-ZATCA-Advance-ZADV-SA-2026-00001.png
```

Legacy Series:

```text
ZADV-SA-2026-
```

Current Series value:

```text
1
```

Canonical Workspace to keep:

```text
ZATCA
```

Duplicate Workspace to remove:

```text
ZATCA ERPGulf
```

---

## 5. Migration delivery model

Migration is divided into three categories.

### 5.1 Non-destructive setup

Examples:

- creating guarded Custom Fields;
- creating Property Setters;
- adding a report;
- adding the ADV naming-series option;
- adding `abbr` when neither supported field exists;
- installing compatibility resolvers.

These operations may be delivered through idempotent setup functions or patches.

### 5.2 Behavioral migration

Examples:

- changing validation logic;
- changing advance balance calculations;
- changing Payment Entry mapping;
- changing XML generation;
- changing GL behavior.

These changes require tests before site migration.

### 5.3 Destructive cleanup

Examples:

- deleting obsolete Custom Fields;
- deleting obsolete Property Setters;
- clearing legacy Payment Entry fields;
- deleting the legacy ZADV document;
- deleting the old Print Format;
- deleting the legacy DocType;
- deleting the duplicate Workspace;
- deleting the old Series.

These operations require backups, precondition checks, and explicit site targeting.

---

## 6. Required migration artifacts

Before destructive migration, preserve the following artifacts.

### 6.1 Git state

Record:

- repository path;
- current branch;
- current commit;
- origin/main commit;
- working-tree status;
- application version.

### 6.2 Bench and application versions

Record:

- Frappe version;
- ERPNext version;
- `zatca_erpgulf` version;
- Python version;
- Node.js version.

### 6.3 Site state

Record:

- installed applications;
- Company ZATCA controls;
- existing Custom Fields;
- existing Property Setters;
- Workspaces;
- Reports;
- naming-series options;
- Series records;
- ZADV records;
- linked Payment Entries;
- File records;
- Comments;
- Versions;
- Communications;
- ToDos;
- GL Entries;
- deduction rows;
- Sales Invoice Advance rows.

### 6.4 Backup evidence

Record:

- database backup path;
- public files backup path;
- private files backup path;
- backup creation timestamp;
- backup file sizes;
- optional checksum values.

### 6.5 Test evidence

Record:

- baseline test command;
- baseline test output;
- migration-specific test output;
- post-migration test output.

---

## 7. Pre-migration gate

The migration must not begin until all checks below pass.

### 7.1 Repository gate

- working tree is clean except approved migration artifacts;
- branch is correct;
- commit is recorded;
- no unreviewed application diff exists;
- `git diff --check` passes.

### 7.2 Test gate

- baseline tests pass;
- phase-specific tests pass;
- migration tests pass;
- no unresolved test failure exists.

### 7.3 Site gate

- target site is exactly `squareangles.top1erp.com`;
- Company configuration is recorded;
- no unexpected ZADV document exists;
- no unexpected legacy reference exists;
- no active migration lock exists;
- maintenance window is approved.

### 7.4 Backup gate

- fresh database backup exists;
- fresh file backups exist;
- backup files are readable;
- storage has sufficient free space;
- restore procedure is understood.

### 7.5 User approval gate

Explicit approval is required before:

- deleting the legacy ZADV document;
- deleting the old DocType;
- deleting obsolete Company fields;
- deleting the duplicate Workspace;
- deleting the old Series.

---

## 8. Backup procedure

### 8.1 Backup scope

The backup must include:

- database;
- public files;
- private files;
- site configuration;
- encryption key where required by the environment;
- application commit reference.

### 8.2 Backup timing

Create the final migration backup immediately before destructive execution.

A backup created much earlier is not sufficient when new transactions may have been posted.

### 8.3 Backup verification

Verify:

- files exist;
- file sizes are greater than zero;
- timestamps match the migration window;
- archives can be listed;
- database dump is not empty.

### 8.4 Backup retention

Keep:

- pre-migration backup;
- immediate post-migration backup;
- rollback rehearsal backup where applicable.

Do not delete the pre-migration backup until wider rollout is approved.

---

## 9. Dry-run requirement

Every destructive migration routine must support a read-only dry-run or equivalent precondition report.

### 9.1 Dry-run output

The dry-run must show:

- target site;
- target Company;
- target ZADV documents;
- linked Payment Entries;
- linked Sales Invoices;
- linked deduction rows;
- GL Entry count;
- File count;
- Comment count;
- Version count;
- Communication count;
- ToDo count;
- Series values;
- fields to remove;
- Property Setters to remove;
- Workspaces to remove;
- whether each precondition passes.

### 9.2 Dry-run behavior

The dry-run must not:

- update documents;
- delete records;
- migrate schema;
- clear cache as a substitute for migration;
- change Series values;
- modify files.

### 9.3 Dry-run result

A dry-run result is either:

```text
READY
```

or:

```text
BLOCKED
```

When blocked, list every blocking condition.

---

## 10. Schema migration sequence

Schema migration must follow dependency order.

### 10.1 Additive changes first

Add:

- canonical advance marker when required;
- Payment Entry link on Sales Invoice;
- required deduction fields;
- compatibility helpers;
- `abbr` fields where allowed;
- report and Workspace updates;
- naming-series option.

### 10.2 Behavioral code second

Deploy code that:

- reads new fields;
- supports compatibility fields;
- no longer depends on obsolete settings;
- supports standard Sales Invoice advances;
- supports standard deduction links;
- supports new reports.

### 10.3 Data transition third

Transition:

- deduction references;
- Payment Entry relationships;
- balances and status references;
- report data source.

### 10.4 Destructive cleanup last

Only after new behavior is verified:

- clear obsolete values;
- remove obsolete fields;
- remove legacy document;
- remove legacy Print Format;
- remove old DocType;
- remove obsolete Series.

---

## 11. Canonical advance marker migration

Canonical field:

```text
is_advance_payment
```

Compatibility field:

```text
custom_is_advance_payment
```

### 11.1 Site field matrix

| Existing state | Migration action |
|---|---|
| `is_advance_payment` exists | Reuse it |
| Only `custom_is_advance_payment` exists | Do not create duplicate; use compatibility resolver |
| Neither exists | Create `is_advance_payment` |
| Both exist | Stop and audit values before cleanup |

### 11.2 Data migration rule

Do not copy values automatically between the two marker fields without a site-level audit.

When both fields exist, compare:

- record count with standard marker;
- record count with custom marker;
- records with conflicting values;
- submitted documents;
- cancelled documents.

### 11.3 Rollback

The additive marker field does not normally require immediate deletion during rollback.

Rollback may restore old behavior while retaining an unused additive field, unless its presence causes a verified issue.

---

## 12. Payment Entry link migration

New canonical relationship:

```text
Sales Invoice.custom_zatca_payment_entry
    → Payment Entry
```

Legacy relationship:

```text
Payment Entry.custom_zatca_advance_tax_invoice
    → ZATCA Advance Tax Invoice
```

### 12.1 Migration rules

- do not delete the Payment Entry;
- record all legacy Payment Entry values;
- do not clear legacy fields until standard relationship is verified;
- do not create duplicate advance invoices;
- preserve Company, party, currency, and amounts.

### 12.2 Initial legacy record

For:

```text
ACC-PAY-2026-00028
```

record at minimum:

- docstatus;
- payment type;
- Company;
- party type;
- party;
- posting date;
- paid amount;
- received amount;
- exchange rates;
- legacy advance marker;
- legacy ZADV link;
- legacy status;
- legacy UUID.

### 12.3 Clearing legacy fields

Legacy fields may be cleared only after:

- target standard Sales Invoice state is approved;
- no report depends on legacy fields;
- no code reads legacy fields;
- backup exists;
- cleanup audit is recorded.

### 12.4 Rollback

When rollback occurs after clearing legacy fields:

- restore exact values from the audit snapshot;
- verify the Payment Entry remains submitted;
- verify GL Entries remain unchanged;
- verify no duplicate ZADV link was introduced.

---

## 13. Deduction child-table migration

Current legacy link:

```text
ZATCA Sales Invoice Advance Deduction.zatca_advance_tax_invoice
    → ZATCA Advance Tax Invoice
```

Target link:

```text
Sales Invoice
```

### 13.1 Decision gate

Before changing schema, choose one approved strategy:

1. retain fieldname and change Link options;
2. add a new field and migrate rows;
3. replace the child DocType.

### 13.2 Migration checks

Before changing Link options:

- count existing rows;
- list every linked document;
- confirm whether any row points to ZADV;
- confirm whether any row already contains Sales Invoice names;
- confirm field usage in Python, JavaScript, reports, and XML.

### 13.3 Zero-row initial state

The initial audit found no deduction row referencing:

```text
ZADV-SA-2026-00001
```

This reduces initial-site data risk but does not remove the need for a cross-site audit before wider rollout.

### 13.4 Rollback

Rollback must restore:

- original Link options;
- original fieldname usage;
- original row values;
- original code compatibility.

---

## 14. Obsolete Company field removal

Fields to remove:

```text
custom_zatca_advance_payment_section
custom_zatca_advance_payment_enabled
custom_zatca_advance_default_tc_name
custom_zatca_advance_payment_submission_mode
custom_zatca_advance_signing_enabled
custom_zatca_advance_api_submission_enabled
```

### 14.1 Removal order

1. remove Python reads and writes;
2. remove JavaScript reads and writes;
3. remove UI dependencies;
4. remove Property Setter generation;
5. remove fixture references;
6. remove setup synchronization;
7. remove translation entries;
8. verify repository search is clean;
9. export current field values;
10. delete Custom Field records;
11. delete related Property Setter records;
12. run migration;
13. verify metadata and columns;
14. run tests.

### 14.2 Section Break handling

The Section Break has no database column.

Its cleanup is a metadata operation only.

### 14.3 Data export

Export field values before removal even though they will not be migrated.

The export provides:

- audit evidence;
- rollback source;
- incident analysis data.

### 14.4 Rollback

To roll back removed fields:

1. restore field definitions;
2. restore Property Setters;
3. run migration;
4. restore exported values;
5. restore compatible application code;
6. clear cache;
7. verify Company form behavior.

---

## 15. Legacy ZADV document cleanup

Target:

```text
ZADV-SA-2026-00001
```

### 15.1 Required preconditions

Confirm immediately before deletion:

- target document still exists;
- values match the audit snapshot;
- no GL Entries exist for the ZADV voucher;
- no standard Sales Invoice Advance rows reference the Payment Entry unexpectedly;
- no deduction rows reference the ZADV;
- no Sales Invoice Link field references the ZADV;
- no new Communication exists;
- no new ToDo exists;
- File, Comment, and Version counts are recorded;
- backup is current.

### 15.2 Cleanup method

Use supported Frappe document APIs.

Do not use direct SQL to delete the ZADV business document.

### 15.3 QR File handling

Record:

- File name;
- File URL;
- file size;
- privacy flag;
- attached doctype;
- attached name;
- attached field;
- physical file existence.

Then remove or detach the File through Frappe APIs according to the approved cleanup behavior.

### 15.4 Comment and Version handling

Before deletion, determine standard Frappe behavior for:

- attachment Comments;
- Version records.

Record before-and-after counts.

Do not silently assume all history records are cascaded.

### 15.5 Payment Entry preservation

The linked Payment Entry remains in place.

Only obsolete custom fields may be cleared after all preconditions pass.

### 15.6 Rollback

A rollback after ZADV deletion requires:

- restoring database backup; or
- recreating the exact document and dependencies from a complete snapshot.

Database restore is the preferred rollback for destructive document deletion.

Manual reconstruction is not the primary rollback method.

---

## 16. Legacy Print Format removal

Legacy Print Format:

```text
ZATCA Advance Tax Invoice
```

### 16.1 Preconditions

Before removal:

- no active workflow uses the old DocType;
- no print button references it;
- no user documentation instructs its use;
- no fixture recreates it.

### 16.2 Rollback

Restore the Print Format record or fixture and verify Jinja rendering.

---

## 17. Legacy DocType removal

Legacy DocType:

```text
ZATCA Advance Tax Invoice
```

### 17.1 Removal gate

Do not remove the DocType until:

- no document remains;
- no Link field points to it;
- no Dynamic Link depends on it;
- no Print Format uses it;
- no JavaScript references it;
- no Python controller references it;
- no hook references it;
- no report references it;
- no fixture references it;
- no translation entry is required;
- no Workspace link references it.

### 17.2 Final repository scan

Search at minimum for:

```text
ZATCA Advance Tax Invoice
ZADV
custom_zatca_advance_tax_invoice
custom_advance_invoice_reference
zatca_advance_tax_invoice
```

Every remaining match must be classified as:

- intentionally retained migration documentation;
- compatibility code with approved expiry;
- obsolete code that blocks removal.

### 17.3 Rollback

Restoring the DocType requires:

- restoring its JSON and controller files;
- restoring hooks and fixtures;
- restoring Custom Fields and Property Setters;
- running migration;
- restoring records from backup.

---

## 18. Legacy Series cleanup

Legacy prefix:

```text
ZADV-SA-2026-
```

### 18.1 Preconditions

Remove the Series record only when:

- no legacy ZADV document remains;
- no code generates ZADV names;
- no rollback rehearsal still requires the prefix;
- backup exists.

### 18.2 Rollback

Restore the exact Series value:

```text
1
```

for the initial audited site when rolling back to the pre-migration state.

---

## 19. Workspace migration

Canonical Workspace:

```text
ZATCA
```

Duplicate Workspace:

```text
ZATCA ERPGulf
```

### 19.1 Migration sequence

1. compare both Workspace contents;
2. preserve required shortcuts and cards;
3. move required content into `ZATCA`;
4. correct fixture filters;
5. correct setup synchronization;
6. delete `ZATCA ERPGulf`;
7. run setup again;
8. verify duplicate is not recreated.

### 19.2 Rollback

When rollback is required:

- restore the duplicate Workspace only when old code still requires it;
- restore old fixture behavior;
- verify no user customization is lost.

---

## 20. `abbr` field migration

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

### 20.1 Guard

For each DocType:

- check `abbr`;
- check `custom_abbr`;
- add nothing when either exists;
- do not rename `custom_abbr`;
- otherwise create exact fieldname `abbr`.

### 20.2 Rollback

Because this is additive, rollback may leave the field in place when harmless.

When removal is required:

- verify no naming series depends on it;
- verify no document stores required data only in it;
- remove the Custom Field;
- run migration.

---

## 21. ADV naming-series migration

Required option:

```text
ADV-.abbr.-.YYYY.-
```

### 21.1 Guard

Read all existing Sales Invoice naming-series lines.

When any line contains:

```text
ADV
```

do not add another option automatically.

### 21.2 Preservation

Preserve all existing options and ordering unless an approved decision changes the order.

### 21.3 Rollback

Remove only the exact option added by this migration.

Do not remove a pre-existing ADV option.

Before removal, verify no Sales Invoice was created using the new series.

---

## 22. Report migration

New report requirements include filters for:

- Company;
- Advance Invoice;
- Customer;
- Final Invoice.

### 22.1 Installation

Install the report idempotently.

Do not create duplicate Report records.

### 22.2 Workspace shortcut

Add the report below:

```text
ZATCA POS Invoices with warnings
```

### 22.3 Rollback

Remove only the report and Workspace shortcut created by this redesign.

Do not delete unrelated reports.

---

## 23. Migration execution stages

### Stage A — Preflight

- confirm target site;
- confirm Git state;
- run tests;
- run dry-run;
- take backup;
- verify backup;
- record approval.

### Stage B — Additive schema

- create guarded fields;
- create Property Setters;
- add report;
- add naming series;
- update canonical Workspace content.

### Stage C — Behavioral activation

- activate standard Sales Invoice advance path;
- activate Payment Entry mapping;
- activate deduction balance logic;
- activate XML and QR logic;
- activate GL logic after approval.

### Stage D — Verification

- create controlled test documents;
- compare metadata;
- compare balances;
- compare GL Entries;
- inspect XML;
- inspect QR;
- inspect reports;
- verify cancellation.

### Stage E — Destructive cleanup

- clear legacy Payment Entry fields;
- remove legacy QR and ZADV document;
- remove obsolete fields;
- remove duplicate Workspace;
- remove legacy Print Format;
- remove old DocType;
- remove old Series.

### Stage F — Final verification

- run migrate;
- run migrate again;
- run tests;
- run repository scans;
- run site scans;
- record final status.

---

## 24. Migration transaction boundaries

Where technically safe, group related database changes into controlled transaction boundaries.

### 24.1 Commit only after validation

Do not commit destructive changes before post-change checks pass.

### 24.2 Roll back on exception

When any unexpected exception occurs:

- roll back the current database transaction;
- stop processing;
- record the exception;
- do not continue to the next cleanup item.

### 24.3 File-system limitation

Database rollback does not automatically restore deleted physical files.

Therefore File deletion must occur only after:

- file backup exists;
- metadata snapshot exists;
- database changes are coordinated.

---

## 25. Rollback triggers

Rollback is required or strongly indicated when any of the following occurs.

### 25.1 Critical functional triggers

- Sales Invoice submit fails broadly;
- ordinary credit notes are blocked;
- Phase 1 QR fails;
- Phase 2 signing fails;
- B2B clearance fails due to migration logic;
- B2C reporting fails due to migration logic;
- duplicate advance invoices are created;
- advance balances are incorrect;
- cancellations cannot complete.

### 25.2 Accounting triggers

- GL Entries do not balance;
- customer receivable is incorrect;
- deferred revenue is posted to the wrong account;
- partial settlement uses the full source amount;
- credit-note reversal posts in the wrong direction;
- debit or credit values are negative unexpectedly.

### 25.3 Data-integrity triggers

- legacy references remain after DocType deletion;
- unrelated documents are modified;
- File records are orphaned unexpectedly;
- duplicate Workspaces appear;
- duplicate fields appear;
- naming series is duplicated;
- migration is not idempotent.

### 25.4 Operational triggers

- backup is invalid;
- migration is run on the wrong site;
- unexpected ZADV documents are found;
- site becomes unavailable;
- migration cannot be completed inside the approved window.

---

## 26. Rollback levels

### Level 1 — Code rollback only

Use when:

- no schema change occurred;
- no data change occurred;
- only application behavior changed.

Actions:

1. redeploy previous approved commit;
2. restart required services;
3. clear cache where appropriate;
4. run smoke tests.

### Level 2 — Additive schema rollback

Use when:

- new fields or reports were added;
- no destructive data cleanup occurred.

Actions:

1. redeploy previous code;
2. leave harmless additive fields temporarily, or remove them safely;
3. remove new reports or Property Setters when required;
4. run migration;
5. verify metadata.

### Level 3 — Data-transition rollback

Use when:

- references or values were migrated;
- legacy records still exist.

Actions:

1. redeploy compatible code;
2. restore values from snapshots;
3. restore old Link options;
4. restore legacy relationships;
5. run validation and tests.

### Level 4 — Destructive cleanup rollback

Use when:

- ZADV document was deleted;
- legacy fields were deleted;
- QR File was deleted;
- old DocType was deleted.

Preferred action:

```text
Restore the complete pre-migration database and files backup.
```

Then deploy the matching pre-migration application commit.

---

## 27. Full rollback procedure

### 27.1 Declare rollback

Record:

- reason;
- time;
- affected site;
- migration stage reached;
- last successful check;
- current application commit.

### 27.2 Stop writes

Put the site into an approved maintenance state before restoring data.

### 27.3 Preserve failed state

Before restoration, preserve:

- current logs;
- traceback;
- database snapshot where feasible;
- changed files;
- Git state;
- migration output.

### 27.4 Restore application code

Checkout or deploy the exact pre-migration commit.

### 27.5 Restore database and files

Restore:

- pre-migration database;
- public files;
- private files;
- required site configuration.

### 27.6 Run matching migration

Run migration using the application version corresponding to the restored database.

### 27.7 Verify restored state

Confirm:

- legacy ZADV document exists;
- linked Payment Entry fields are restored;
- QR File exists;
- old Company fields exist;
- old Workspace state matches baseline;
- Series value matches baseline;
- baseline tests pass.

### 27.8 Reopen site

Remove maintenance state only after smoke tests pass.

---

## 28. Rollback verification matrix

| Area | Required verification |
|---|---|
| Application | Pre-migration commit deployed |
| Database | Restore completed without error |
| Files | Public and private files restored |
| ZADV | Legacy document exists when restoring old state |
| Payment Entry | Legacy link and status restored |
| QR | File and File record restored |
| Company fields | Obsolete fields restored when reverting fully |
| Workspace | Pre-migration Workspace state restored |
| Series | `ZADV-SA-2026-` value restored |
| Tests | Baseline tests pass |
| Site | Login and document access work |

---

## 29. Post-migration verification

### 29.1 Metadata

Verify:

- marker field state;
- Payment Entry link field;
- deduction Link options;
- obsolete Company fields removed when scheduled;
- old DocType removed when scheduled;
- only one ZATCA Workspace;
- report exists once;
- abbreviation fields follow guards;
- ADV naming series exists once.

### 29.2 Functional behavior

Verify:

- standalone advance invoice;
- Payment Entry-created advance invoice;
- initial advance submit;
- final settlement invoice;
- partial settlement;
- full settlement;
- multiple advances;
- partial advance credit note;
- full advance credit note;
- final invoice credit note;
- cancellation.

### 29.3 Accounting

Verify:

- receivable;
- deferred revenue;
- revenue recognition;
- tax;
- multi-currency base amounts;
- credit-note reversal;
- cancellation reversal.

### 29.4 ZATCA

Verify:

- Phase 1 QR;
- Phase 2 standard B2B clearance;
- Phase 2 simplified B2C reporting;
- invoice type codes;
- references;
- PrepaidAmount;
- VAT grouping;
- debug XML parity.

### 29.5 Reporting

Verify:

- filters;
- permissions;
- original amount;
- applied amount;
- credited amount;
- remaining balance;
- status.

---

## 30. Idempotency verification

Run each setup or migration routine at least twice on the test site.

Second execution must show:

- no duplicate Custom Fields;
- no duplicate Property Setters;
- no duplicate naming-series option;
- no duplicate report;
- no duplicate Workspace;
- no repeated destructive deletion error;
- no changed balances;
- no altered unrelated data.

---

## 31. Logging requirements

Migration logs must include:

- timestamp;
- site;
- user or execution identity;
- application commit;
- operation name;
- dry-run or execute mode;
- precondition result;
- records inspected;
- records changed;
- records skipped;
- errors;
- final result.

Do not log secrets, private keys, certificates, or full authentication payloads.

---

## 32. Error-handling requirements

### 32.1 Expected missing item

When an item was already removed by a prior successful run:

- record it as already complete;
- continue only when idempotency rules allow.

### 32.2 Unexpected missing item

When an expected dependency is missing:

- stop;
- record the discrepancy;
- do not infer the desired state.

### 32.3 Unexpected additional item

When additional ZADV documents or references exist:

- stop;
- list them;
- require a new migration plan.

### 32.4 Partial failure

When database changes succeed but file cleanup fails:

- stop;
- do not proceed to DocType deletion;
- restore or reconcile the File state before continuing.

---

## 33. Multi-site rollout requirements

Before wider rollout:

1. inventory every tenant site;
2. classify its marker fields;
3. classify its Company phase fields;
4. count ZADV documents;
5. count legacy links;
6. count deduction rows;
7. count old Workspaces;
8. inspect naming-series options;
9. inspect `abbr` and `custom_abbr`;
10. create a site-specific migration report.

Sites with unexpected data require separate approval.

---

## 34. Rollout waves

### Wave 0

```text
squareangles.top1erp.com
```

Purpose:

- initial development;
- destructive migration rehearsal;
- rollback rehearsal.

### Wave 1

A small set of low-risk internal or controlled sites.

Requirements:

- no unexpected ZADV data;
- backups verified;
- user approval.

### Wave 2

Phase 1 production sites.

### Wave 3

Phase 2 B2B and B2C sites.

No wave proceeds until the previous wave is accepted.

---

## 35. Change freeze during destructive migration

During the destructive migration window, avoid:

- creating new advance invoices;
- editing linked Payment Entries;
- submitting final invoices using advances;
- creating credit notes against affected documents;
- changing Company ZATCA settings.

The freeze may be implemented operationally or through temporary maintenance controls.

---

## 36. Final acceptance criteria

Migration is accepted only when:

- all planned schema changes are present;
- all obsolete schema is removed at the approved phase;
- no broken references remain;
- legacy cleanup evidence is preserved;
- baseline and new tests pass;
- repeated migration is idempotent;
- Phase 1 behavior passes;
- Phase 2 B2B behavior passes;
- Phase 2 B2C behavior passes;
- accounting is approved;
- report balances reconcile;
- rollback rehearsal succeeds;
- Git diff and status are reviewed;
- documentation is updated;
- the user approves wider rollout.

---

## 37. Current migration status

| Item | Status |
|---|---|
| Repository audit | Complete |
| Initial-site read-only audit | Complete |
| Baseline tests | Passed |
| Migration implementation | Not started |
| Destructive cleanup | Not started |
| Backup for destructive cleanup | Not yet created |
| Rollback rehearsal | Not started |
| Wider rollout | Not approved |

---

## 38. Immediate next step

The immediate implementation phase is the ordinary credit-note regression fix on:

```text
fix/return-credit-note-advance-validation
```

That phase has:

- no database migration;
- no schema deletion;
- no ZADV deletion;
- no Workspace deletion;
- no Series deletion.

Destructive migration remains blocked until the standard Sales Invoice workflow is implemented, tested, and approved.
