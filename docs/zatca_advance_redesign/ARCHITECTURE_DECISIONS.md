# ZATCA Advance Redesign — Architecture Decisions

## 1. Document status

| Item | Value |
|---|---|
| Status | Active |
| Application | `zatca_erpgulf` |
| Initial test site | `squareangles.top1erp.com` |
| Related audit | `CURRENT_STATE_AUDIT.md` |
| Repository state | Phase 1 merged into `main` through PR `#27` at `63f8952` |

This document records the architectural decisions governing the migration from the custom `ZATCA Advance Tax Invoice` workflow to standard Sales Invoice documents.

Decisions marked `Accepted` are implementation requirements.

Decisions marked `Open` require additional technical inspection or user approval before implementation.

---

## ADR-ADV-001 — Use standard Sales Invoice for advance invoices

### Status

Accepted

### Decision

The custom:

```text
ZATCA Advance Tax Invoice
```

DocType will be retired.

The following transactions will use standard Sales Invoice documents:

- initial advance-payment invoice;
- final invoice that applies one or more advances;
- credit note against an initial advance invoice;
- credit note against a final invoice.

### Rationale

Using standard Sales Invoice provides:

- standard accounting behavior;
- standard customer ledger integration;
- standard return and credit-note behavior;
- standard currency and exchange-rate fields;
- standard tax calculation;
- standard printing and permissions;
- standard ZATCA signing and submission paths;
- lower long-term maintenance cost.

### Consequences

The migration must replace or remove all links that currently reference:

```text
ZATCA Advance Tax Invoice
```

The old DocType must not be deleted until all code, metadata, document links, fixtures, and artifacts have been migrated or removed.

---

## ADR-ADV-002 — Canonical advance-payment marker

### Status

Accepted

### Decision

The canonical Sales Invoice marker is:

```text
is_advance_payment
```

Required field metadata:

| Property | Value |
|---|---|
| Label | `Is Advance Payment Invoice` |
| Fieldname | `is_advance_payment` |
| Fieldtype | `Check` |
| Insert after | `is_debit_note` |
| No Copy | `1` |

### Installation rules

For every site:

1. inspect whether `is_advance_payment` already exists;
2. inspect whether `custom_is_advance_payment` already exists;
3. reuse an existing `is_advance_payment`;
4. do not create a second marker when `custom_is_advance_payment` already exists;
5. create `is_advance_payment` only when neither field exists;
6. do not create `custom_is_advance_payment` on new sites.

### Compatibility resolver

During the compatibility period, application logic may use:

```python
is_advance_payment = bool(
    doc.get("is_advance_payment")
    or doc.get("custom_is_advance_payment")
)
```

The compatibility fallback must be removed only after confirming that no supported site depends on `custom_is_advance_payment`.

---

## ADR-ADV-003 — Remove obsolete Company advance settings

### Status

Accepted

### Decision

Remove the following Company fields:

```text
custom_zatca_advance_payment_section
custom_zatca_advance_payment_enabled
custom_zatca_advance_default_tc_name
custom_zatca_advance_payment_submission_mode
custom_zatca_advance_signing_enabled
custom_zatca_advance_api_submission_enabled
```

### Replacement controls

The redesigned workflow will use:

```text
custom_zatca_invoice_enabled
custom_phase_1_or_2
phase_1_or_2
custom_select
custom_send_invoice_to_zatca
```

The phase resolver will prefer:

```text
custom_phase_1_or_2
```

and use:

```text
phase_1_or_2
```

only as a compatibility fallback when that field exists.

### No value migration

Values stored in the obsolete advance-specific fields will not be migrated.

They do not represent independent business transactions and can conflict with the general Company ZATCA configuration.

### Removal sequence

1. remove Python references;
2. remove JavaScript references;
3. remove UI dependencies;
4. remove Property Setter generation;
5. remove fixture and synchronization references;
6. remove translation entries;
7. delete Custom Field and Property Setter records;
8. execute migration;
9. verify that no reference remains.

---

## ADR-ADV-004 — No separate advance signing or API switches

### Status

Accepted

### Decision

The redesigned workflow will not introduce separate controls for:

- advance invoice signing;
- advance invoice API submission;
- advance invoice local-only mode;
- advance invoice ZATCA environment.

### Phase 1 behavior

When the Company is configured for Phase 1:

- use standard Sales Invoice submission;
- generate the Phase 1 QR;
- do not execute Phase 2 signing;
- do not call Phase 2 reporting or clearance APIs.

### Phase 2 behavior

When the Company is configured for Phase 2:

- use the normal Sales Invoice signing pipeline;
- use the normal ZATCA environment;
- use normal clearance for standard B2B invoices;
- use normal reporting for simplified B2C invoices;
- use the general B2C submission method where applicable.

---

## ADR-ADV-005 — Do not use a separate advance terms template

### Status

Accepted

### Decision

The obsolete Company field:

```text
custom_zatca_advance_default_tc_name
```

will be removed without a replacement advance-specific field.

Advance Sales Invoices will use the standard Sales Invoice fields:

```text
tc_name
terms
```

### Rationale

Terms and Conditions are already part of the standard Sales Invoice model.

A separate Company-level advance terms setting creates duplicated configuration and unnecessary coupling to the legacy DocType.

---

## ADR-ADV-006 — Optional Payment Entry relationship

### Status

Accepted

### Decision

Add the following field to Sales Invoice:

```text
custom_zatca_payment_entry
```

Required metadata:

| Property | Value |
|---|---|
| Label | `ZATCA Payment Entry` |
| Fieldtype | Link |
| Options | `Payment Entry` |
| Allow on Submit | `1` |
| No Copy | `1` |
| Required | No |

The field will be visible only when the invoice is marked as an advance-payment invoice.

### Relationship direction

The canonical relationship is:

```text
Sales Invoice.custom_zatca_payment_entry
    → Payment Entry
```

### Supported creation paths

An advance Sales Invoice may be:

1. created from a Payment Entry; or
2. created independently without a Payment Entry.

### Legacy relationship

The following legacy relationship will eventually be removed:

```text
Payment Entry.custom_zatca_advance_tax_invoice
    → ZATCA Advance Tax Invoice
```

---

## ADR-ADV-007 — Advance invoices are mutually exclusive with advance deductions

### Status

Accepted

### Decision

A Sales Invoice marked as an initial advance invoice must not contain rows in:

```text
custom_zatca_advance_deduction_details
```

A final invoice containing advance deductions must not be marked as:

```text
is_advance_payment
```

### Validation rules

Block saving or submitting when:

```text
is_advance_payment = 1
```

and the advance deduction table contains meaningful rows or amounts.

Block saving or submitting a final settlement invoice when it is also marked as an initial advance invoice.

---

## ADR-ADV-008 — Advance invoice type codes

### Status

Accepted

### Decision

Use the following ZATCA document type codes:

| Transaction | Code |
|---|---:|
| Initial advance invoice | `386` |
| Final invoice containing advance adjustment | `388` |
| Credit note | `381` |

Invoice type names:

| Invoice classification | Name |
|---|---|
| Standard B2B | `0100000` |
| Simplified B2C | `0200000` |

The final XML implementation remains subject to verification against current official ZATCA specifications.

---

## ADR-ADV-009 — Advance revenue account

### Status

Accepted

### Decision

Advance invoices represent unearned revenue.

The application should prefer the Company:

```text
Default Deferred Revenue Account
```

### Missing deferred revenue account

When no deferred revenue account is configured:

1. show a clear user message;
2. link the user to the Company Accounts configuration;
3. explain that customer advances are unearned revenue;
4. allow the user to continue and choose an account manually.

### Prohibited account

Block saving an advance invoice when an Item Income Account equals the Company Default Income Account.

### Single-account rule

All Item rows in one advance invoice must use the same Income Account.

When the business transaction requires multiple deferred-revenue accounts, the user must create separate advance invoices.

---

## ADR-ADV-010 — Item grid visibility

### Status

Accepted

### Decision

For advance Sales Invoices:

- display Income Account in the Item grid;
- configure Income Account column width as `1`;
- first try Quantity column width `1`;
- first try Rate column width `1`.

The application must not force further column-width changes solely to reduce total visible widths below ten.

When the grid still exceeds the preferred visible-width total, show configuration instructions instead of silently modifying additional columns.

---

## ADR-ADV-011 — Link deductions to standard advance Sales Invoices

### Status

Accepted

### Decision

The deduction child table will reference standard Sales Invoice advance invoices instead of:

```text
ZATCA Advance Tax Invoice
```

### Eligibility rules

A selectable advance invoice must:

- belong to the same Company;
- belong to the same Customer;
- be marked as an advance invoice;
- have an unused available balance;
- meet applicable ZATCA status requirements;
- not be fully reversed by credit notes.

### Phase 2 status eligibility

Phase 2 advance invoices must normally have an accepted status such as:

```text
Cleared
Reported
```

The exact accepted-value list will be normalized during implementation after auditing all current status values.

---

## ADR-ADV-012 — Settlement uses base or local equivalent

### Status

Accepted

### Decision

Available-balance control and settlement accounting will use the Company currency or base equivalent.

The child table must preserve both:

- source invoice currency values;
- base or local currency values.

### Rationale

The final invoice may use a different transaction currency or exchange rate from the original advance invoice.

Comparing only transaction-currency amounts would permit incorrect settlement or over-allocation.

---

## ADR-ADV-013 — Credit notes release advance balance

### Status

Accepted

### Decision

A credit note against an initial advance invoice may be:

- full; or
- partial.

The credited base or local equivalent releases the corresponding unused advance balance.

A credit note must not release more than the original advance or more than the currently reversible amount.

### Final invoice credit note

A credit note against a final invoice must reverse:

- the advance settlement;
- the related deferred-revenue accounting effect;
- the corresponding available-balance consumption.

The reversal must remain traceable to the original final invoice and the affected advance invoices.

---

## ADR-ADV-014 — Ordinary credit notes must remain independent

### Status

Accepted

### Decision

An ordinary credit note that has no advance deduction rows must not be subjected to positive final-invoice advance-total validation.

A zero or empty deduction table must not be compared against a negative return invoice total.

### Prohibited implementation shortcuts

The correction must not:

- add an unconditional return that bypasses all credit-note controls;
- convert all invoice and settlement values to absolute values without context;
- disable settlement validation for positive final invoices;
- disable advance-balance release validation.

---

## ADR-ADV-015 — Final invoice accounting by Income Account

### Status

Accepted in principle

### Decision

Settlement accounting should aggregate applied advance amounts by the Income Account of the source advance invoice.

Use the settlement amount before tax, not the entire original advance invoice value.

Where technically feasible, produce one aggregated debit row per affected deferred-revenue account.

### Constraint

The implementation must first inspect and compare standard ERPNext Sales Invoice GL generation.

No ERPNext core modification is permitted without a separate architecture decision.

### Stop condition

Stop implementation and document the limitation when no safe supported extension point can produce the required GL behavior.

---

## ADR-ADV-016 — GL debit and credit values remain nonnegative

### Status

Accepted

### Decision

GL Entry debit and credit fields must contain nonnegative absolute values.

Direction is represented by selecting the correct debit or credit field, not by placing negative values in those fields.

Credit-note reversal logic must swap the accounting direction where appropriate.

---

## ADR-ADV-017 — XML uses multiple DocumentReference elements

### Status

Accepted

### Decision

When a final invoice applies multiple advance invoices, generate multiple XML:

```text
DocumentReference
```

elements.

Do not place multiple invoice IDs inside a single comma-delimited field.

Each reference should contain, where available:

- advance invoice ID;
- advance invoice UUID;
- IssueDate;
- IssueTime;
- DocumentTypeCode `386`.

---

## ADR-ADV-018 — PrepaidAmount is tax inclusive

### Status

Accepted

### Decision

The XML:

```text
PrepaidAmount
```

must represent the applied advance amount inclusive of VAT.

Related taxable and VAT values remain available for reconciliation and adjustment-line generation.

Final implementation remains subject to current official ZATCA schema verification.

---

## ADR-ADV-019 — VAT adjustment grouping

### Status

Accepted

### Decision

Zero-value or adjustment lines generated for advance settlement will be grouped by:

- VAT category; and
- VAT rate.

Different VAT categories or rates must not be combined into one adjustment group.

---

## ADR-ADV-020 — Debug XML uses production business logic

### Status

Accepted

### Decision

The action:

```text
Create XML for Debug
```

must use the same:

- advance classification;
- references;
- totals;
- VAT grouping;
- deduction logic;
- type-code logic

as the normal XML generation path.

Debug generation may bypass API transmission, but it must not use a separate simplified business model.

---

## ADR-ADV-021 — QR represents only the current invoice

### Status

Accepted

### Decision

A QR code generated for an advance Sales Invoice must represent only the current Sales Invoice.

It must not encode or reuse unrelated Payment Entry, legacy ZADV, final invoice, or previous invoice QR data.

Phase 1 and Phase 2 QR behavior must continue to follow their respective standard paths.

---

## ADR-ADV-022 — Canonical ZATCA Workspace

### Status

Accepted

### Decision

Keep:

```text
ZATCA
```

Remove and prevent recreation of:

```text
ZATCA ERPGulf
```

### Implementation requirement

Correct both:

- fixture selection; and
- installation or update reconciliation.

Running migration or setup repeatedly must not recreate the obsolete duplicate Workspace.

---

## ADR-ADV-023 — Advance settlement report

### Status

Accepted

### Decision

Add a report for advance settlement and remaining balances.

Required filters:

- Company;
- Advance Invoice;
- Customer;
- Final Invoice.

When all filters are empty, the report should show all permitted records.

Required information includes:

- advance invoice;
- original amount;
- currency;
- base or local equivalent;
- consuming final invoices;
- amount applied;
- credited or reversed amount;
- remaining available balance;
- ZATCA status.

The Workspace shortcut will be placed below:

```text
ZATCA POS Invoices with warnings
```

---

## ADR-ADV-024 — Phase 2-only field visibility

### Status

Accepted

### Decision

Approved Phase 2-only Sales Invoice fields are visible only when:

```text
ZATCA E-Invoicing is enabled
```

and:

```text
Company phase = Phase-2
```

The visibility resolver must support both known phase fieldnames:

```text
custom_phase_1_or_2
phase_1_or_2
```

Field visibility must not depend on the obsolete advance-specific Company settings.

---

## ADR-ABBR-001 — Exact abbreviation fieldname

### Status

Accepted

### Decision

Use the exact fieldname:

```text
abbr
```

for the twelve approved standard transaction DocTypes.

### Guard

For each DocType:

1. check for `abbr`;
2. check for `custom_abbr`;
3. add nothing when either exists;
4. do not rename an existing `custom_abbr`;
5. otherwise add `abbr`.

Required metadata:

| Property | Value |
|---|---|
| Label | `abbr` |
| Fieldname | `abbr` |
| Fieldtype | Data |
| Fetch From | `company.abbr` |
| Hidden | `1` |
| Translatable | `1` |
| Insert after | `company` |

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

---

## ADR-ADV-025 — ADV Sales Invoice naming series

### Status

Accepted

### Decision

Add:

```text
ADV-.abbr.-.YYYY.-
```

to Sales Invoice naming-series options.

### Guard

Before adding the option, inspect every existing Sales Invoice naming-series line.

When any line contains the substring:

```text
ADV
```

do not add another ADV series automatically.

The operation must be idempotent.

---

## ADR-ADV-026 — Legacy ZADV document cleanup

### Status

Accepted in principle

### Target document

```text
ZADV-SA-2026-00001
```

### Preconditions

Before deletion:

1. repeat the reference audit;
2. create a structured audit snapshot;
3. take database and files backups;
4. confirm there are still no GL Entries;
5. confirm there are still no deduction or allocation rows;
6. confirm no new Sales Invoice references appeared;
7. record linked Payment Entry values;
8. record QR File and history records.

### Cleanup direction

The cleanup should:

1. clear legacy fields on the linked Payment Entry;
2. remove or detach the QR File using Frappe APIs;
3. delete the legacy ZADV document using Frappe APIs;
4. verify handling of Comment and Version records;
5. remove the legacy Series only when no legacy document remains.

Direct SQL deletion of the business document is prohibited.

---

## ADR-ADV-027 — Remove legacy DocType only after link migration

### Status

Accepted

### Decision

Do not delete:

```text
ZATCA Advance Tax Invoice
```

until:

- Payment Entry links are removed;
- Sales Invoice links are changed;
- child-table links are changed;
- Print Format is removed;
- scripts and hooks are removed;
- fixtures are removed;
- translations are removed;
- no document reference remains.

Deleting the DocType before these steps would leave broken metadata and migration failures.

---

## ADR-ADV-028 — Initial testing is restricted to Square Angles

### Status

Accepted

### Decision

Initial implementation, migration, and destructive testing will be performed only on:

```text
squareangles.top1erp.com
```

No other tenant site will be migrated until:

- tests pass;
- site behavior is verified;
- XML and QR behavior is verified;
- accounting results are approved;
- rollback has been tested;
- the user approves rollout.

---

## ADR-ADV-029 — No silent ERPNext core modifications

### Status

Accepted

### Decision

The implementation will use:

- application hooks;
- Custom Fields;
- Property Setters where appropriate;
- supported controllers;
- document events;
- supported accounting extension points;
- patches and setup routines owned by `zatca_erpgulf`.

No ERPNext core file may be modified without:

1. documenting why supported extension points are insufficient;
2. evaluating upgrade impact;
3. creating a separate architecture decision;
4. receiving explicit user approval.

---

## ADR-ADV-030 — Idempotent installation and migration

### Status

Accepted

### Decision

All setup and migration operations must be safe to run repeatedly.

This includes:

- marker-field creation;
- Payment Entry field creation;
- obsolete field removal;
- Workspace reconciliation;
- `abbr` field creation;
- naming-series updates;
- report installation;
- Property Setter synchronization;
- legacy cleanup guards.

Repeated execution must not create duplicate fields, naming-series lines, Workspaces, reports, or records.

---

## Open decision 1 — Child-table fieldname normalization

### Status

Open

The existing child table fieldname is:

```text
zatca_advance_tax_invoice
```

It currently links to the legacy DocType.

Options under consideration:

1. retain the fieldname and change its options to Sales Invoice;
2. add a new natural fieldname and migrate existing data;
3. replace the child DocType completely.

The decision requires inspection of:

- current field usage in Python;
- current field usage in XML generation;
- current fixtures;
- existing data across sites;
- migration complexity;
- report requirements.

---

## Open decision 2 — Final invoice GL integration point

### Status

Open

The exact supported ERPNext extension point for aggregating settlement by source Income Account has not yet been selected.

Before deciding, inspect:

- standard Sales Invoice GL output;
- return invoice GL output;
- hooks around `get_gl_entries`;
- controller override implications;
- compatibility with taxes and multi-currency;
- cancellation and reposting behavior.

---

## Open decision 3 — Legacy cleanup delivery mechanism

### Status

Open

Possible mechanisms:

1. an idempotent Frappe patch;
2. a controlled administrative command;
3. a migration helper with explicit site targeting.

The selected mechanism must:

- run only when preconditions pass;
- generate a clear audit log;
- stop safely when unexpected references exist;
- support rollback from backup;
- avoid affecting unrelated tenant sites.

---

## Open decision 4 — SaaS provisioning integration

### Status

Open

The correct integration point for new-site and company setup has not yet been selected.

Candidate locations include:

- `zatca_erpgulf` installation hooks;
- `saas_quota` post-provisioning workflow;
- SaaS Manager provisioning commands;
- a shared idempotent setup function invoked by those workflows.

No location will be selected without auditing the current provisioning sequence.

---

## Open decision 5 — Exact report implementation

### Status

Open

The report architecture may use:

- Query Report;
- Script Report;
- Query Builder;
- server-side aggregation functions.

The decision depends on:

- multi-currency calculations;
- credit-note reversal calculations;
- ZATCA status filtering;
- balance performance;
- permission enforcement;
- traceability requirements.

---

## Decision governance

Every future change to an accepted decision must record:

- the previous decision;
- the new decision;
- the reason for the change;
- affected requirements;
- affected tests;
- migration implications;
- rollback implications.

No implementation phase is complete until this document, `REQUIREMENTS_TRACEABILITY.md`, `TEST_MATRIX.md`, and `CURRENT_STATUS.md` are updated.

---

## Phase 1 decision record — sign-aware return validation

### Decision

Ordinary Sales Invoice returns do not enter the positive final-invoice ZATCA advance-deduction calculation.

### Rationale

Returns preserve negative invoice and tax signs. Comparing a zero or positive advance-deduction amount against a negative return total is not a valid settlement limit and caused the observed regression.

### Rules

1. Preserve negative return signs.
2. Do not apply a blind `abs()` conversion to general advance-deduction validation.
3. Ignore zero allocations before resolving linked ZATCA advance documents.
4. Block positive allocations linked to the legacy ZATCA advance flow when applied directly to a return.
5. Do not block positive non-ZATCA allocations through this validator.
6. Remove stale ZATCA advance VAT-deduction tax rows from returns.
7. Clear derived advance-deduction detail and total fields on returns.
8. Preserve VAT and total limits for positive final invoices.
9. Preserve the dedicated `advance_credit_note.py` validation for valid and excessive advance credit notes.

### Scope boundary

This decision fixes the ordinary return regression only.

It does not implement the future final-invoice settlement reversal architecture, which remains assigned to the dedicated credit-note reversal phase.

### Verification

```text
12 focused Phase 1 tests passed
10 existing regression tests passed
Draft CN-RET-2026-00002 saved successfully
No migration or schema change
```
