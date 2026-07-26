# ZATCA Tax Source Priority Contract

## Purpose

This document defines the canonical tax-source priority contract used by `zatca_erpgulf` when resolving ZATCA VAT category and exemption reason values for Sales Invoice XML generation.

The purpose is to prevent future regressions in XML generation, validation, and VAT reporting behavior.

## Scope

This contract applies to Sales Invoice tax-category source resolution for:

- XML tax breakdown without Item Tax Template.
- XML tax breakdown with Item Tax Template.
- Sales Invoice validation before save or submit.
- Regression tests covering ZATCA tax-source priority.

This document does not cover ZATCA API submission, certificate handling, CSID handling, QR generation, or clearance/reporting transport behavior.

## Canonical Priority Rules

### 1. Item Tax Template has highest priority when all item rows use it

If every Sales Invoice item row has an `Item Tax Template`, ZATCA tax category and exemption reason must be resolved from each row's linked Item Tax Template.

In this mode:

- XML tax breakdown is grouped by Item Tax Template category, rate, and exemption reason.
- Sales Invoice-level ZATCA fields must not override Item Tax Template values.
- Sales Taxes and Charges Template values must not override Item Tax Template values.

Relevant implementation:

- `zatca_erpgulf/zatca_erpgulf/xml_tax_data.py`
  - `_get_tax_breakdown_with_template`
  - `tax_data_with_template`

### 2. Sales Taxes and Charges Template has priority when no item rows use Item Tax Template

If no Sales Invoice item row has an `Item Tax Template`, ZATCA tax category and exemption reason must be resolved from the linked `Sales Taxes and Charges Template`, when that template has `custom_zatca_tax_category`.

Relevant implementation:

- `zatca_erpgulf/zatca_erpgulf/xml_tax_data.py`
  - `_get_invoice_level_zatca_tax_source`
  - `_get_tax_breakdown_without_template`
  - `tax_data`

### 3. Sales Invoice fields are fallback only

Sales Invoice ZATCA fields are used only when:

- Item Tax Template mode is not active.
- The linked Sales Taxes and Charges Template has no `custom_zatca_tax_category`.

Fallback fields:

- `Sales Invoice.custom_zatca_tax_category`
- `Sales Invoice.custom_exemption_reason_code`

Relevant implementation:

- `zatca_erpgulf/zatca_erpgulf/xml_tax_data.py`
  - `_get_invoice_level_zatca_tax_source`

### 4. Mixed Item Tax Template usage is invalid

A Sales Invoice must not mix item rows where some rows have `Item Tax Template` and other rows do not.

If any one item row has an Item Tax Template, all item rows must have an Item Tax Template.

This is a validation error.

Relevant implementation:

- `zatca_erpgulf/zatca_erpgulf/tax_error.py`
  - `validate_zatca_tax_category_and_exemption_reason`

### 5. Exemption reason is required for non-standard VAT categories

For ZATCA categories that require an exemption reason, the corresponding exemption reason code must be present on the selected source.

Examples include:

- Zero Rated
- Exempted
- Services outside scope of tax / Not subject to VAT

The selected source depends on the priority rules above.

### 6. Excise templates are not safely inferred as VAT categories

KSA Excise templates must not be automatically inferred as VAT categories during sync or backfill unless a future explicit rule is added.

Current behavior:

- Excise templates are skipped by the ZATCA backfill process when no safe inference exists.
- This skip is intentional and must not be treated as a sync error.

Relevant implementation:

- `zatca_erpgulf/setup_customizations.py`
  - `infer_zatca_source_values_from_tax_template`
  - `sync_existing_tax_template_zatca_values`

## Regression Tests

The canonical regression tests for this contract are located at:

`zatca_erpgulf/zatca_erpgulf/tests/test_zatca_tax_source_priority.py`

The test pack verifies:

1. Sales Taxes and Charges Template overrides Sales Invoice fallback when it has ZATCA category.
2. Sales Invoice fallback is used when Sales Taxes and Charges Template has no ZATCA category.
3. Tax breakdown without Item Tax Template uses Sales Taxes Template or invoice fallback source.
4. Tax breakdown with Item Tax Template groups by Item Tax Template category, rate, and exemption reason.
5. Mixed Item Tax Template rows are rejected.
6. Validation assertions are language-independent for Arabic and English site translations.

## Validation Command

Run the test pack with:

    bench --site <site-name> set-config allow_tests true

    bench --site <site-name> run-tests \
      --module zatca_erpgulf.zatca_erpgulf.tests.test_zatca_tax_source_priority

    bench --site <site-name> set-config allow_tests false

Validated sites during v35:

- `squareangles.top1erp.com`
- `usfc.top1erp.com`

Expected result:

    .....
    ----------------------------------------------------------------------
    Ran 5 tests

    OK

## Production Impact

This contract document is documentation only.

It does not change:

- XML generation code.
- Validation code.
- Fixtures.
- Hooks.
- Custom fields.
- Migrations.
- ZATCA submission behavior.

## Maintenance Rule

Any future change to ZATCA tax-source behavior must update both:

1. This contract document.
2. `test_zatca_tax_source_priority.py`

A change to implementation without updating the contract and tests should be considered incomplete.
