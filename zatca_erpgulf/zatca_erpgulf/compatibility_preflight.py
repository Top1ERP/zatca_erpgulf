from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import frappe

from zatca_erpgulf.zatca_erpgulf.zatca_runtime import (
    ADVANCE_DEDUCTION_CHILD_DB_FIELDS,
    ADVANCE_DEDUCTION_CHILD_DOCTYPE,
    ADVANCE_DEDUCTION_CHILD_FIELDS,
    ADVANCE_DEDUCTION_PARENT_DB_FIELDS,
    ADVANCE_DEDUCTION_PARENT_FIELDS,
    ADVANCE_DEDUCTION_TABLE_FIELD,
    ADVANCE_PAYMENT_ENTRY_LINK_FIELD,
)


APP_NAME = "zatca_erpgulf"
SALES_INVOICE_DOCTYPE = "Sales Invoice"
PRIMARY_MARKER_FIELD = "is_advance_payment"
LEGACY_MARKER_FIELD = "custom_is_advance_payment"

SAFE_COMPLETE = "SAFE_COMPLETE"
SAFE_LEGACY = "SAFE_LEGACY"
SAFE_PARTIAL = "SAFE_PARTIAL"
UNSAFE_STRUCTURAL = "UNSAFE_STRUCTURAL"
NOT_APPLICABLE = "NOT_APPLICABLE"

RISK_CRITICAL = "CRITICAL"
RISK_HIGH = "HIGH"
RISK_MEDIUM = "MEDIUM"
RISK_INFO = "INFO"
RISK_ORDER = {
    RISK_INFO: 0,
    RISK_MEDIUM: 1,
    RISK_HIGH: 2,
    RISK_CRITICAL: 3,
}

OLD_SHARED_PARENT_FIELD = "custom_zatca_status"
NEW_PARENT_METADATA_FIELDS = frozenset(ADVANCE_DEDUCTION_PARENT_FIELDS) - {
    OLD_SHARED_PARENT_FIELD
}
NEW_PARENT_DB_FIELDS = frozenset(ADVANCE_DEDUCTION_PARENT_DB_FIELDS) - {
    OLD_SHARED_PARENT_FIELD
}


class CompatibilityPreflightError(RuntimeError):
    """Raised when deployment must stop because structural schema is unsafe."""


def _as_set(values) -> set[str]:
    return {str(value) for value in (values or ()) if value}


def _coverage(required, available) -> dict[str, Any]:
    required_set = _as_set(required)
    available_set = _as_set(available)
    missing = sorted(required_set - available_set)
    return {
        "present": len(required_set) - len(missing),
        "required": len(required_set),
        "missing": missing,
        "complete": not missing,
    }


def _problem(
    problems: list[dict[str, Any]],
    severity: str,
    code: str,
    message: str,
    objects: list[dict[str, Any]] | None = None,
) -> None:
    problems.append(
        {
            "severity": severity,
            "code": code,
            "message": message,
            "objects": objects or [],
        }
    )


def _metadata_field(doctype: str, fieldname: str) -> dict[str, str]:
    return {"doctype": doctype, "fieldname": fieldname}


def _sql_column(doctype: str, column: str) -> dict[str, str]:
    return {"table": f"tab{doctype}", "column": column}


def _repair_recommendation(problem: dict[str, Any]) -> dict[str, Any]:
    code = problem["code"]
    defaults = {
        "suggested_action": (
            "Review the listed objects and reconcile metadata with the physical "
            "schema in a controlled maintenance window."
        ),
        "why": "The preflight detected an explicit compatibility issue.",
        "complexity": "MEDIUM",
        "repair_risk": "MEDIUM",
        "requires": {
            "reload_doc": "conditional",
            "patch": "conditional",
            "migrate": "conditional",
            "manual_intervention": True,
        },
    }
    recommendations = {
        "APP_NOT_INSTALLED": {
            "suggested_action": "No schema repair is required for this Site.",
            "why": "The deployment gate does not apply when zatca_erpgulf is not installed.",
            "complexity": "NONE",
            "repair_risk": "NONE",
            "requires": {
                "reload_doc": False,
                "patch": False,
                "migrate": False,
                "manual_intervention": False,
            },
        },
        "SALES_INVOICE_DOCTYPE_MISSING": {
            "suggested_action": (
                "Restore the Sales Invoice DocType metadata from the owning ERPNext "
                "application, then rerun the preflight."
            ),
            "why": "ZATCA cannot operate safely without the parent DocType metadata.",
            "complexity": "HIGH",
            "repair_risk": "HIGH",
            "requires": {
                "reload_doc": True,
                "patch": "conditional",
                "migrate": "conditional",
                "manual_intervention": True,
            },
        },
        "SALES_INVOICE_TABLE_MISSING": {
            "suggested_action": (
                "Stop deployment and use the approved ERPNext schema recovery or "
                "migration path to restore tabSales Invoice."
            ),
            "why": "The parent transaction table is absent; this is broader than an optional ZATCA field mismatch.",
            "complexity": "HIGH",
            "repair_risk": "HIGH",
            "requires": {
                "reload_doc": "conditional",
                "patch": "conditional",
                "migrate": True,
                "manual_intervention": True,
            },
        },
        "PARENT_REQUIRED_METADATA_FIELDS_MISSING": {
            "suggested_action": (
                "Reload the owning Sales Invoice custom-field metadata and verify "
                "each listed field before rerunning the preflight."
            ),
            "why": "The deployed metadata is older or only partially loaded compared with the ZATCA schema contract.",
            "complexity": "LOW",
            "repair_risk": "LOW",
            "requires": {
                "reload_doc": True,
                "patch": False,
                "migrate": "conditional",
                "manual_intervention": True,
            },
        },
        "PARENT_REQUIRED_SQL_COLUMNS_MISSING": {
            "suggested_action": (
                "Apply the approved custom-field/schema synchronization path for "
                "the listed Sales Invoice columns."
            ),
            "why": "The optional feature cannot store its parent values until every required physical column exists.",
            "complexity": "MEDIUM",
            "repair_risk": "MEDIUM",
            "requires": {
                "reload_doc": True,
                "patch": "conditional",
                "migrate": "conditional",
                "manual_intervention": True,
            },
        },
        "CHILD_REQUIRED_METADATA_FIELDS_MISSING": {
            "suggested_action": (
                f"Reload DocType {ADVANCE_DEDUCTION_CHILD_DOCTYPE} from its application JSON, "
                "then verify every listed field."
            ),
            "why": "The child DocType metadata is incomplete relative to the application definition.",
            "complexity": "LOW",
            "repair_risk": "LOW",
            "requires": {
                "reload_doc": True,
                "patch": False,
                "migrate": "conditional",
                "manual_intervention": True,
            },
        },
        "CHILD_REQUIRED_COLUMNS_MISSING": {
            "suggested_action": (
                f"Reload DocType {ADVANCE_DEDUCTION_CHILD_DOCTYPE}, verify the listed SQL columns, "
                "and use an approved schema patch or migration only if reload-doc does not synchronize them."
            ),
            "why": "Metadata/table creation was only partially applied, so guarded code cannot make document loading structurally safe.",
            "complexity": "LOW-MEDIUM",
            "repair_risk": "MEDIUM",
            "requires": {
                "reload_doc": True,
                "patch": "conditional",
                "migrate": "conditional",
                "manual_intervention": True,
            },
        },
        "DANGLING_CHILD_DOCTYPE_METADATA": {
            "suggested_action": (
                f"Reload DocType {ADVANCE_DEDUCTION_CHILD_DOCTYPE} before enabling the parent Table field."
            ),
            "why": "The parent Table field points to child metadata that is not registered.",
            "complexity": "LOW-MEDIUM",
            "repair_risk": "MEDIUM",
            "requires": {
                "reload_doc": True,
                "patch": "conditional",
                "migrate": "conditional",
                "manual_intervention": True,
            },
        },
        "DANGLING_TABLE_FIELD_MISSING_CHILD_TABLE": {
            "suggested_action": (
                f"Reload DocType {ADVANCE_DEDUCTION_CHILD_DOCTYPE} and follow the approved migration/schema-sync path to create its table."
            ),
            "why": "Frappe may try to load the declared child table before runtime capability guards execute.",
            "complexity": "MEDIUM",
            "repair_risk": "MEDIUM",
            "requires": {
                "reload_doc": True,
                "patch": "conditional",
                "migrate": "conditional",
                "manual_intervention": True,
            },
        },
        "CHILD_DOCTYPE_TABLE_MISSING": {
            "suggested_action": (
                f"Use the approved reload/migration path for {ADVANCE_DEDUCTION_CHILD_DOCTYPE} to create its physical table."
            ),
            "why": "Registered child metadata without a physical table is structurally inconsistent.",
            "complexity": "MEDIUM",
            "repair_risk": "MEDIUM",
            "requires": {
                "reload_doc": True,
                "patch": "conditional",
                "migrate": "conditional",
                "manual_intervention": True,
            },
        },
        "AUTHORITATIVE_MARKER_COLUMN_MISSING": {
            "suggested_action": (
                "Synchronize the authoritative marker field to its Sales Invoice SQL column; do not substitute the legacy marker."
            ),
            "why": "Backend priority selects the primary metadata field and intentionally forbids legacy fallback once it exists.",
            "complexity": "LOW-MEDIUM",
            "repair_risk": "MEDIUM",
            "requires": {
                "reload_doc": True,
                "patch": "conditional",
                "migrate": "conditional",
                "manual_intervention": True,
            },
        },
        "PAYMENT_LINK_COLUMN_MISSING": {
            "suggested_action": (
                f"Synchronize {ADVANCE_PAYMENT_ENTRY_LINK_FIELD} metadata with its Sales Invoice SQL column."
            ),
            "why": "Metadata advertises an active Payment Entry link that cannot be queried or stored physically.",
            "complexity": "LOW-MEDIUM",
            "repair_risk": "MEDIUM",
            "requires": {
                "reload_doc": True,
                "patch": "conditional",
                "migrate": "conditional",
                "manual_intervention": True,
            },
        },
        "DECLARED_PARENT_COLUMNS_MISSING": {
            "suggested_action": (
                "Synchronize each listed stored Sales Invoice field to its physical SQL column."
            ),
            "why": "Metadata exists but SQL is missing, usually indicating an interrupted or incomplete schema synchronization.",
            "complexity": "LOW-MEDIUM",
            "repair_risk": "MEDIUM",
            "requires": {
                "reload_doc": True,
                "patch": "conditional",
                "migrate": "conditional",
                "manual_intervention": True,
            },
        },
        "DEDUCTION_TABLE_FIELD_INVALID": {
            "suggested_action": (
                f"Correct {ADVANCE_DEDUCTION_TABLE_FIELD} to a Table field targeting {ADVANCE_DEDUCTION_CHILD_DOCTYPE}, then reload its owning metadata."
            ),
            "why": "A wrong fieldtype or options target changes document-loading behavior and cannot be handled by a runtime guard.",
            "complexity": "MEDIUM",
            "repair_risk": "MEDIUM",
            "requires": {
                "reload_doc": True,
                "patch": "conditional",
                "migrate": "conditional",
                "manual_intervention": True,
            },
        },
        "ORPHAN_PHYSICAL_COLUMNS": {
            "suggested_action": "Review the listed SQL-only columns during a later cleanup window; do not drop them automatically.",
            "why": "Physical residue is normally harmless but should be reconciled with the intended metadata lifecycle.",
            "complexity": "LOW",
            "repair_risk": "LOW",
            "requires": {
                "reload_doc": False,
                "patch": False,
                "migrate": False,
                "manual_intervention": True,
            },
        },
        "OPTIONAL_SCHEMA_PARTIAL": {
            "suggested_action": "Repair the explicitly listed missing objects before enabling the affected optional capabilities.",
            "why": "Runtime guards keep standard transactions safe, but the optional feature remains unavailable.",
            "complexity": "CONDITIONAL",
            "repair_risk": "CONDITIONAL",
            "requires": {
                "reload_doc": "conditional",
                "patch": "conditional",
                "migrate": "conditional",
                "manual_intervention": True,
            },
        },
        "SITE_INSPECTION_FAILED": {
            "suggested_action": "Resolve the reported connection/inspection error and rerun the read-only preflight.",
            "why": "Deployment safety cannot be established when the Site cannot be inspected.",
            "complexity": "CONDITIONAL",
            "repair_risk": "CONDITIONAL",
            "requires": {
                "reload_doc": False,
                "patch": False,
                "migrate": False,
                "manual_intervention": True,
            },
        },
    }
    values = recommendations.get(code, defaults)
    return {
        "issue_code": code,
        "objects": problem.get("objects", []),
        **values,
    }


def _site_risk(problems: list[dict[str, Any]]) -> str:
    return max(
        (problem["severity"] for problem in problems),
        key=lambda severity: RISK_ORDER[severity],
        default=RISK_INFO,
    )


def _empty_root_causes() -> dict[str, Any]:
    return {
        "missing_metadata_fields": [],
        "missing_sql_columns": [],
        "missing_doctypes": [],
        "missing_sql_tables": [],
        "parent_field_mismatches": [],
        "marker_mismatch": None,
        "payment_entry_mismatch": None,
    }


def _not_applicable_report(site: str) -> dict[str, Any]:
    runtime_capabilities = {
        "advance_payment_marker": False,
        "advance_payment_entry_link": False,
        "advance_deduction": False,
    }
    problems = [
        {
            "severity": RISK_INFO,
            "code": "APP_NOT_INSTALLED",
            "message": "zatca_erpgulf is not installed; site is not applicable.",
            "objects": [{"app": APP_NAME}],
        }
    ]
    return {
        "site": site,
        "zatca_installed": False,
        "classification": NOT_APPLICABLE,
        "blocking": False,
        "deployment_allowed": True,
        "risk": RISK_INFO,
        "runtime_capabilities": runtime_capabilities,
        "capabilities": runtime_capabilities,
        "marker": {
            "primary_metadata": False,
            "legacy_metadata": False,
            "primary_column": False,
            "legacy_column": False,
            "authoritative_field": None,
            "physical_column": False,
        },
        "payment_link": {
            "metadata": False,
            "physical_column": False,
        },
        "parent": {
            "table_exists": None,
            "metadata": _coverage(ADVANCE_DEDUCTION_PARENT_FIELDS, ()),
            "db_columns": _coverage(ADVANCE_DEDUCTION_PARENT_DB_FIELDS, ()),
            "table_field": None,
        },
        "child": {
            "doctype_metadata": None,
            "table_exists": None,
            "metadata": _coverage(ADVANCE_DEDUCTION_CHILD_FIELDS, ()),
            "db_columns": _coverage(ADVANCE_DEDUCTION_CHILD_DB_FIELDS, ()),
        },
        "root_causes": _empty_root_causes(),
        "problems": problems,
        "repair_recommendations": [
            _repair_recommendation(problem) for problem in problems
        ],
    }


def classify_schema_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Classify a read-only metadata/SQL snapshot.

    Blocking structural mismatches:
    - an authoritative marker, Payment Entry link, or stored parent field is
      declared in metadata without its physical Sales Invoice SQL column;
    - the deduction Table field points at missing child metadata or table;
    - child metadata exists without its table;
    - child metadata and table exist but a runtime-required SQL column is
      missing.

    Missing optional metadata with no dangerous declaration is SAFE_LEGACY or
    SAFE_PARTIAL because runtime capability guards disable the feature.
    """
    site = str(snapshot.get("site") or "")
    if snapshot.get("zatca_installed") is False:
        return _not_applicable_report(site)

    parent_fields = _as_set(snapshot.get("parent_metadata_fields"))
    parent_columns = _as_set(snapshot.get("parent_db_columns"))
    child_fields = _as_set(snapshot.get("child_metadata_fields"))
    child_columns = _as_set(snapshot.get("child_db_columns"))

    parent_meta_exists = bool(
        snapshot.get("parent_metadata_exists", True)
    )
    parent_table_exists = bool(snapshot.get("parent_table_exists"))
    child_meta_exists = bool(snapshot.get("child_metadata_exists"))
    child_table_exists = bool(snapshot.get("child_table_exists"))

    primary_metadata = PRIMARY_MARKER_FIELD in parent_fields
    legacy_metadata = LEGACY_MARKER_FIELD in parent_fields
    primary_column = bool(
        parent_table_exists
        and PRIMARY_MARKER_FIELD in parent_columns
    )
    legacy_column = bool(
        parent_table_exists
        and LEGACY_MARKER_FIELD in parent_columns
    )
    authoritative_marker = (
        PRIMARY_MARKER_FIELD
        if primary_metadata
        else LEGACY_MARKER_FIELD
        if legacy_metadata
        else None
    )
    marker_column = bool(
        authoritative_marker
        and parent_table_exists
        and authoritative_marker in parent_columns
    )
    marker_capability = bool(authoritative_marker and marker_column)

    payment_link_metadata = ADVANCE_PAYMENT_ENTRY_LINK_FIELD in parent_fields
    payment_link_column = bool(
        parent_table_exists
        and ADVANCE_PAYMENT_ENTRY_LINK_FIELD in parent_columns
    )
    payment_link_capability = bool(
        marker_capability
        and payment_link_metadata
        and payment_link_column
    )

    parent_metadata = _coverage(
        ADVANCE_DEDUCTION_PARENT_FIELDS,
        parent_fields,
    )
    parent_db_columns = _coverage(
        ADVANCE_DEDUCTION_PARENT_DB_FIELDS,
        parent_columns,
    )
    child_metadata = _coverage(
        ADVANCE_DEDUCTION_CHILD_FIELDS,
        child_fields,
    )
    child_db_columns = _coverage(
        ADVANCE_DEDUCTION_CHILD_DB_FIELDS,
        child_columns,
    )

    table_field = snapshot.get("parent_table_field") or {}
    table_field_present = ADVANCE_DEDUCTION_TABLE_FIELD in parent_fields
    table_field_type = str(table_field.get("fieldtype") or "")
    table_field_options = str(table_field.get("options") or "")
    table_field_valid = bool(
        table_field_present
        and table_field_type == "Table"
        and table_field_options == ADVANCE_DEDUCTION_CHILD_DOCTYPE
    )

    missing_metadata_fields = [
        *(
            _metadata_field(SALES_INVOICE_DOCTYPE, fieldname)
            for fieldname in parent_metadata["missing"]
        ),
        *(
            _metadata_field(ADVANCE_DEDUCTION_CHILD_DOCTYPE, fieldname)
            for fieldname in child_metadata["missing"]
        ),
    ]
    missing_sql_columns = [
        *(
            _sql_column(SALES_INVOICE_DOCTYPE, fieldname)
            for fieldname in (
                parent_db_columns["missing"]
                if parent_table_exists
                else ()
            )
        ),
        *(
            _sql_column(ADVANCE_DEDUCTION_CHILD_DOCTYPE, fieldname)
            for fieldname in (
                child_db_columns["missing"]
                if child_table_exists
                else ()
            )
        ),
    ]
    missing_doctypes = []
    if not parent_meta_exists:
        missing_doctypes.append(SALES_INVOICE_DOCTYPE)
    if not child_meta_exists:
        missing_doctypes.append(ADVANCE_DEDUCTION_CHILD_DOCTYPE)

    missing_sql_tables = []
    if not parent_table_exists:
        missing_sql_tables.append(f"tab{SALES_INVOICE_DOCTYPE}")
    if not child_table_exists:
        missing_sql_tables.append(
            f"tab{ADVANCE_DEDUCTION_CHILD_DOCTYPE}"
        )

    parent_field_mismatches = []
    parent_stored_fields = {
        *ADVANCE_DEDUCTION_PARENT_DB_FIELDS,
        PRIMARY_MARKER_FIELD,
        LEGACY_MARKER_FIELD,
        ADVANCE_PAYMENT_ENTRY_LINK_FIELD,
    }
    for fieldname in sorted(parent_stored_fields):
        metadata_exists = fieldname in parent_fields
        sql_column_exists = bool(
            parent_table_exists and fieldname in parent_columns
        )
        if metadata_exists != sql_column_exists:
            parent_field_mismatches.append(
                {
                    "doctype": SALES_INVOICE_DOCTYPE,
                    "fieldname": fieldname,
                    "metadata_exists": metadata_exists,
                    "sql_table": f"tab{SALES_INVOICE_DOCTYPE}",
                    "sql_column_exists": sql_column_exists,
                    "mismatch": (
                        "metadata_without_sql_column"
                        if metadata_exists
                        else "sql_column_without_metadata"
                    ),
                }
            )
    if table_field_present and not table_field_valid:
        parent_field_mismatches.append(
            {
                "doctype": SALES_INVOICE_DOCTYPE,
                "fieldname": ADVANCE_DEDUCTION_TABLE_FIELD,
                "metadata_exists": True,
                "actual_fieldtype": table_field_type or None,
                "actual_options": table_field_options or None,
                "expected_fieldtype": "Table",
                "expected_options": ADVANCE_DEDUCTION_CHILD_DOCTYPE,
                "mismatch": "metadata_definition_mismatch",
            }
        )

    marker_issues = [
        mismatch
        for mismatch in parent_field_mismatches
        if mismatch.get("fieldname")
        in {PRIMARY_MARKER_FIELD, LEGACY_MARKER_FIELD}
    ]
    marker_mismatch = (
        {
            "authoritative_field": authoritative_marker,
            "issues": marker_issues,
        }
        if marker_issues
        else None
    )
    payment_entry_issues = [
        mismatch
        for mismatch in parent_field_mismatches
        if mismatch.get("fieldname")
        == ADVANCE_PAYMENT_ENTRY_LINK_FIELD
    ]
    payment_entry_mismatch = (
        {
            "fieldname": ADVANCE_PAYMENT_ENTRY_LINK_FIELD,
            "issues": payment_entry_issues,
        }
        if payment_entry_issues
        else None
    )
    root_causes = {
        "missing_metadata_fields": missing_metadata_fields,
        "missing_sql_columns": missing_sql_columns,
        "missing_doctypes": missing_doctypes,
        "missing_sql_tables": missing_sql_tables,
        "parent_field_mismatches": parent_field_mismatches,
        "marker_mismatch": marker_mismatch,
        "payment_entry_mismatch": payment_entry_mismatch,
    }

    deduction_capability = bool(
        marker_capability
        and parent_table_exists
        and parent_metadata["complete"]
        and parent_db_columns["complete"]
        and child_meta_exists
        and child_table_exists
        and child_metadata["complete"]
        and child_db_columns["complete"]
    )

    problems: list[dict[str, Any]] = []

    if not parent_meta_exists:
        _problem(
            problems,
            RISK_CRITICAL,
            "SALES_INVOICE_DOCTYPE_MISSING",
            "Sales Invoice DocType metadata is missing.",
            [{"doctype": SALES_INVOICE_DOCTYPE}],
        )

    if not parent_table_exists:
        _problem(
            problems,
            RISK_CRITICAL,
            "SALES_INVOICE_TABLE_MISSING",
            "Physical Sales Invoice table is missing.",
            [{"table": f"tab{SALES_INVOICE_DOCTYPE}"}],
        )

    if authoritative_marker and not marker_column:
        _problem(
            problems,
            RISK_CRITICAL,
            "AUTHORITATIVE_MARKER_COLUMN_MISSING",
            (
                f"Metadata declares authoritative marker {authoritative_marker}, "
                "but its physical Sales Invoice column is missing. Legacy fallback "
                "is intentionally not used."
            ),
            [
                _metadata_field(
                    SALES_INVOICE_DOCTYPE,
                    authoritative_marker,
                ),
                _sql_column(
                    SALES_INVOICE_DOCTYPE,
                    authoritative_marker,
                ),
            ],
        )

    if payment_link_metadata and not payment_link_column:
        _problem(
            problems,
            RISK_CRITICAL,
            "PAYMENT_LINK_COLUMN_MISSING",
            (
                f"Metadata declares {ADVANCE_PAYMENT_ENTRY_LINK_FIELD}, but the "
                "physical Sales Invoice column is missing."
            ),
            [
                _metadata_field(
                    SALES_INVOICE_DOCTYPE,
                    ADVANCE_PAYMENT_ENTRY_LINK_FIELD,
                ),
                _sql_column(
                    SALES_INVOICE_DOCTYPE,
                    ADVANCE_PAYMENT_ENTRY_LINK_FIELD,
                ),
            ],
        )

    missing_declared_parent_columns = sorted(
        fieldname
        for fieldname in ADVANCE_DEDUCTION_PARENT_DB_FIELDS
        if fieldname in parent_fields and fieldname not in parent_columns
    )
    if missing_declared_parent_columns:
        _problem(
            problems,
            RISK_CRITICAL,
            "DECLARED_PARENT_COLUMNS_MISSING",
            (
                "Stored Sales Invoice metadata fields have no physical columns: "
                + ", ".join(missing_declared_parent_columns)
            ),
            [
                _sql_column(SALES_INVOICE_DOCTYPE, fieldname)
                for fieldname in missing_declared_parent_columns
            ],
        )

    if table_field_present and not table_field_valid:
        _problem(
            problems,
            RISK_CRITICAL,
            "DEDUCTION_TABLE_FIELD_INVALID",
            (
                f"{ADVANCE_DEDUCTION_TABLE_FIELD} is not a Table field pointing "
                f"to {ADVANCE_DEDUCTION_CHILD_DOCTYPE}."
            ),
            [
                _metadata_field(
                    SALES_INVOICE_DOCTYPE,
                    ADVANCE_DEDUCTION_TABLE_FIELD,
                )
            ],
        )

    if table_field_present and not child_meta_exists:
        _problem(
            problems,
            RISK_CRITICAL,
            "DANGLING_CHILD_DOCTYPE_METADATA",
            (
                f"Sales Invoice metadata declares {ADVANCE_DEDUCTION_TABLE_FIELD}, "
                f"but child DocType metadata {ADVANCE_DEDUCTION_CHILD_DOCTYPE} "
                "does not exist."
            ),
            [{"doctype": ADVANCE_DEDUCTION_CHILD_DOCTYPE}],
        )

    if table_field_present and not child_table_exists:
        _problem(
            problems,
            RISK_CRITICAL,
            "DANGLING_TABLE_FIELD_MISSING_CHILD_TABLE",
            (
                f"Sales Invoice metadata declares {ADVANCE_DEDUCTION_TABLE_FIELD}, "
                f"but physical table tab{ADVANCE_DEDUCTION_CHILD_DOCTYPE} is "
                "missing. Document.load_from_db may fail before runtime guards."
            ),
            [{"table": f"tab{ADVANCE_DEDUCTION_CHILD_DOCTYPE}"}],
        )

    if child_meta_exists and not child_table_exists:
        _problem(
            problems,
            RISK_CRITICAL,
            "CHILD_DOCTYPE_TABLE_MISSING",
            (
                f"Child DocType metadata {ADVANCE_DEDUCTION_CHILD_DOCTYPE} exists, "
                "but its physical SQL table is missing."
            ),
            [{"table": f"tab{ADVANCE_DEDUCTION_CHILD_DOCTYPE}"}],
        )

    if (
        child_meta_exists
        and child_table_exists
        and child_db_columns["missing"]
    ):
        _problem(
            problems,
            RISK_CRITICAL,
            "CHILD_REQUIRED_COLUMNS_MISSING",
            (
                "Child metadata and table exist, but runtime-required SQL columns "
                "are missing: " + ", ".join(child_db_columns["missing"])
            ),
            [
                _sql_column(
                    ADVANCE_DEDUCTION_CHILD_DOCTYPE,
                    fieldname,
                )
                for fieldname in child_db_columns["missing"]
            ],
        )

    blocking = any(
        problem["severity"] == RISK_CRITICAL
        for problem in problems
    )

    metadata_footprint = bool(
        {PRIMARY_MARKER_FIELD, LEGACY_MARKER_FIELD}.intersection(parent_fields)
        or ADVANCE_PAYMENT_ENTRY_LINK_FIELD in parent_fields
        or NEW_PARENT_METADATA_FIELDS.intersection(parent_fields)
        or child_meta_exists
    )
    physical_footprint = bool(
        {PRIMARY_MARKER_FIELD, LEGACY_MARKER_FIELD}.intersection(parent_columns)
        or ADVANCE_PAYMENT_ENTRY_LINK_FIELD in parent_columns
        or NEW_PARENT_DB_FIELDS.intersection(parent_columns)
        or child_table_exists
    )
    deduction_metadata_footprint = bool(
        NEW_PARENT_METADATA_FIELDS.intersection(parent_fields)
        or child_meta_exists
    )
    deduction_physical_footprint = bool(
        NEW_PARENT_DB_FIELDS.intersection(parent_columns)
        or child_table_exists
    )

    if deduction_metadata_footprint or deduction_physical_footprint:
        if parent_metadata["missing"]:
            _problem(
                problems,
                RISK_HIGH,
                "PARENT_REQUIRED_METADATA_FIELDS_MISSING",
                "Required advance-deduction Sales Invoice metadata fields are missing.",
                [
                    _metadata_field(SALES_INVOICE_DOCTYPE, fieldname)
                    for fieldname in parent_metadata["missing"]
                ],
            )
        if parent_table_exists and parent_db_columns["missing"]:
            _problem(
                problems,
                RISK_HIGH,
                "PARENT_REQUIRED_SQL_COLUMNS_MISSING",
                "Required advance-deduction Sales Invoice SQL columns are missing.",
                [
                    _sql_column(SALES_INVOICE_DOCTYPE, fieldname)
                    for fieldname in parent_db_columns["missing"]
                ],
            )
        if child_metadata["missing"]:
            _problem(
                problems,
                RISK_HIGH,
                "CHILD_REQUIRED_METADATA_FIELDS_MISSING",
                "Required child DocType metadata fields are missing.",
                [
                    _metadata_field(
                        ADVANCE_DEDUCTION_CHILD_DOCTYPE,
                        fieldname,
                    )
                    for fieldname in child_metadata["missing"]
                ],
            )

    orphan_parent_columns = [
        mismatch
        for mismatch in parent_field_mismatches
        if mismatch["mismatch"] == "sql_column_without_metadata"
    ]
    if orphan_parent_columns:
        _problem(
            problems,
            RISK_INFO,
            "ORPHAN_PHYSICAL_COLUMNS",
            "Physical Sales Invoice columns exist without matching metadata.",
            [
                _sql_column(
                    SALES_INVOICE_DOCTYPE,
                    mismatch["fieldname"],
                )
                for mismatch in orphan_parent_columns
            ],
        )

    if blocking:
        classification = UNSAFE_STRUCTURAL
    elif (
        marker_capability
        and payment_link_capability
        and deduction_capability
    ):
        classification = SAFE_COMPLETE
    elif not metadata_footprint and not physical_footprint:
        classification = SAFE_LEGACY
    else:
        classification = SAFE_PARTIAL

    if classification == SAFE_PARTIAL:
        missing_parts = []
        if not marker_capability:
            missing_parts.append("advance marker capability")
        if not payment_link_capability:
            missing_parts.append("Payment Entry link capability")
        if not deduction_capability:
            missing_parts.append("advance deduction capability")
        _problem(
            problems,
            (
                RISK_INFO
                if physical_footprint and not metadata_footprint
                else RISK_HIGH
            ),
            "OPTIONAL_SCHEMA_PARTIAL",
            (
                "Optional schema is incomplete; runtime hardening disables the "
                "unavailable feature parts: " + ", ".join(missing_parts)
            ),
            [
                {"runtime_capability": capability}
                for capability in missing_parts
            ],
        )

    runtime_capabilities = {
        "advance_payment_marker": marker_capability,
        "advance_payment_entry_link": payment_link_capability,
        "advance_deduction": deduction_capability,
    }
    deployment_allowed = not blocking
    risk = _site_risk(problems)

    return {
        "site": site,
        "zatca_installed": True,
        "classification": classification,
        "blocking": blocking,
        "deployment_allowed": deployment_allowed,
        "risk": risk,
        "runtime_capabilities": runtime_capabilities,
        "capabilities": runtime_capabilities,
        "marker": {
            "primary_metadata": primary_metadata,
            "legacy_metadata": legacy_metadata,
            "primary_column": primary_column,
            "legacy_column": legacy_column,
            "authoritative_field": authoritative_marker,
            "physical_column": marker_column,
        },
        "payment_link": {
            "metadata": payment_link_metadata,
            "physical_column": payment_link_column,
        },
        "parent": {
            "table_exists": parent_table_exists,
            "metadata": parent_metadata,
            "db_columns": parent_db_columns,
            "table_field": {
                "present": table_field_present,
                "fieldtype": table_field_type or None,
                "options": table_field_options or None,
                "valid": table_field_valid,
            },
        },
        "child": {
            "doctype_metadata": child_meta_exists,
            "table_exists": child_table_exists,
            "metadata": child_metadata,
            "db_columns": child_db_columns,
        },
        "root_causes": root_causes,
        "problems": problems,
        "repair_recommendations": [
            _repair_recommendation(problem) for problem in problems
        ],
    }


def _meta_fieldnames(meta) -> set[str]:
    return {
        str(field.fieldname)
        for field in (getattr(meta, "fields", None) or ())
        if getattr(field, "fieldname", None)
    }


def inspect_current_site(site: str | None = None) -> dict[str, Any]:
    """Inspect the connected Site using metadata and schema reads only."""
    site = str(site or getattr(frappe.local, "site", "") or "")
    installed_apps = set(frappe.get_installed_apps())
    if APP_NAME not in installed_apps:
        return _not_applicable_report(site)

    parent_table_exists = bool(
        frappe.db.table_exists(SALES_INVOICE_DOCTYPE)
    )
    parent_columns = (
        set(frappe.db.get_table_columns(SALES_INVOICE_DOCTYPE))
        if parent_table_exists
        else set()
    )

    parent_meta_exists = bool(
        frappe.db.exists("DocType", SALES_INVOICE_DOCTYPE)
    )
    parent_meta = (
        frappe.get_meta(SALES_INVOICE_DOCTYPE)
        if parent_meta_exists
        else None
    )
    parent_fields = _meta_fieldnames(parent_meta) if parent_meta else set()

    table_field = (
        parent_meta.get_field(ADVANCE_DEDUCTION_TABLE_FIELD)
        if parent_meta
        else None
    )

    child_meta_exists = bool(
        frappe.db.exists("DocType", ADVANCE_DEDUCTION_CHILD_DOCTYPE)
    )
    child_meta = (
        frappe.get_meta(ADVANCE_DEDUCTION_CHILD_DOCTYPE)
        if child_meta_exists
        else None
    )
    child_fields = _meta_fieldnames(child_meta) if child_meta else set()

    child_table_exists = bool(
        frappe.db.table_exists(ADVANCE_DEDUCTION_CHILD_DOCTYPE)
    )
    child_columns = (
        set(frappe.db.get_table_columns(ADVANCE_DEDUCTION_CHILD_DOCTYPE))
        if child_table_exists
        else set()
    )

    return classify_schema_snapshot(
        {
            "site": site,
            "zatca_installed": True,
            "parent_table_exists": parent_table_exists,
            "parent_metadata_exists": parent_meta_exists,
            "parent_metadata_fields": parent_fields,
            "parent_db_columns": parent_columns,
            "parent_table_field": {
                "fieldtype": getattr(table_field, "fieldtype", None),
                "options": getattr(table_field, "options", None),
            }
            if table_field
            else None,
            "child_metadata_exists": child_meta_exists,
            "child_table_exists": child_table_exists,
            "child_metadata_fields": child_fields,
            "child_db_columns": child_columns,
        }
    )


def _inspection_failure(site: str, error: Exception) -> dict[str, Any]:
    report = _not_applicable_report(site)
    problem = {
        "severity": RISK_CRITICAL,
        "code": "SITE_INSPECTION_FAILED",
        "message": (
            "Site could not be inspected safely: "
            f"{type(error).__name__}: {error}"
        ),
        "objects": [{"site": site}],
    }
    report.update(
        {
            "zatca_installed": None,
            "classification": UNSAFE_STRUCTURAL,
            "blocking": True,
            "deployment_allowed": False,
            "risk": RISK_CRITICAL,
            "problems": [problem],
            "repair_recommendations": [
                _repair_recommendation(problem)
            ],
        }
    )
    return report


def discover_sites(sites_path: str | Path) -> list[str]:
    sites_directory = Path(sites_path).resolve()
    return sorted(
        path.parent.name
        for path in sites_directory.glob("*/site_config.json")
        if path.is_file()
    )


def scan_bench_sites(sites_path: str | Path) -> dict[str, Any]:
    """Connect to every Bench Site and perform SELECT/metadata reads only."""
    sites_directory = Path(sites_path).resolve()
    reports = []
    previous_directory = Path.cwd()

    try:
        os.chdir(sites_directory)
        for site in discover_sites(sites_directory):
            try:
                frappe.init(
                    site=site,
                    sites_path=str(sites_directory),
                    force=True,
                )
                frappe.connect(set_admin_as_user=False)
                frappe.flags.read_only = True
                reports.append(inspect_current_site(site))
            except Exception as error:
                reports.append(_inspection_failure(site, error))
            finally:
                try:
                    frappe.destroy()
                except Exception:
                    pass
    finally:
        os.chdir(previous_directory)

    installed_reports = [
        report
        for report in reports
        if report["zatca_installed"] is True
    ]
    blocking_sites = [
        report["site"]
        for report in reports
        if report["blocking"]
    ]

    counts: dict[str, int] = {}
    for report in reports:
        classification = report["classification"]
        counts[classification] = counts.get(classification, 0) + 1

    return {
        "sites_path": str(sites_directory),
        "total_sites": len(reports),
        "zatca_installed_sites": len(installed_reports),
        "classification_counts": counts,
        "blocking_sites": blocking_sites,
        "deployment_allowed": not blocking_sites,
        "sites": reports,
    }


def _yes_no(value) -> str:
    if value is None:
        return "N/A"
    return "YES" if value else "NO"


def _coverage_text(value: dict[str, Any]) -> str:
    return f"{value['present']}/{value['required']}"


def format_report_table(reports: list[dict[str, Any]]) -> str:
    headers = [
        "Site",
        "ZATCA Installed",
        "Marker Capability",
        "Payment Link Capability",
        "Deduction Capability",
        "Parent Metadata",
        "Parent DB Columns",
        "Child Metadata",
        "Child Table",
        "Child DB Columns",
        "Classification",
        "Risk",
        "Problems",
    ]
    rows = []

    for report in reports:
        problems = ",".join(
            problem["code"] for problem in report["problems"]
        ) or "-"
        rows.append(
            [
                report["site"],
                _yes_no(report["zatca_installed"]),
                _yes_no(
                    report["runtime_capabilities"][
                        "advance_payment_marker"
                    ]
                ),
                _yes_no(
                    report["runtime_capabilities"][
                        "advance_payment_entry_link"
                    ]
                ),
                _yes_no(
                    report["runtime_capabilities"][
                        "advance_deduction"
                    ]
                ),
                _coverage_text(report["parent"]["metadata"]),
                _coverage_text(report["parent"]["db_columns"]),
                (
                    _coverage_text(report["child"]["metadata"])
                    if report["child"]["doctype_metadata"] is not None
                    else "N/A"
                ),
                _yes_no(report["child"]["table_exists"]),
                (
                    _coverage_text(report["child"]["db_columns"])
                    if report["child"]["table_exists"] is not None
                    else "N/A"
                ),
                report["classification"],
                report["risk"],
                problems,
            ]
        )

    widths = [
        max(len(headers[index]), *(len(str(row[index])) for row in rows))
        for index in range(len(headers))
    ]

    def render(row) -> str:
        return " | ".join(
            str(value).ljust(widths[index])
            for index, value in enumerate(row)
        )

    separator = "-+-".join("-" * width for width in widths)
    return "\n".join(
        [render(headers), separator, *(render(row) for row in rows)]
    )


def run_current_site(
    raise_on_unsafe: bool = True,
) -> dict[str, Any]:
    """Bench-execute entry point for one connected Site."""
    report = inspect_current_site()
    print(format_report_table([report]))
    print(json.dumps(report, indent=2, sort_keys=True))

    if raise_on_unsafe and report["blocking"]:
        raise CompatibilityPreflightError(
            f"Deployment blocked by unsafe Site {report['site']}."
        )

    return report


def _default_sites_path() -> Path:
    return Path(__file__).resolve().parents[4] / "sites"


def deployment_exit_code(result: dict[str, Any]) -> int:
    """Return 1 only when at least one Site is UNSAFE_STRUCTURAL."""
    reports = result.get("sites")
    if reports is None:
        reports = [result]
    return int(
        any(
            report.get("classification") == UNSAFE_STRUCTURAL
            for report in reports
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only ZATCA compatibility preflight for every Bench Site."
        )
    )
    parser.add_argument(
        "--sites-path",
        default=str(_default_sites_path()),
        help="Bench sites directory.",
    )
    parser.add_argument(
        "--format",
        choices=("table", "json", "both"),
        default="both",
        help="Report output format.",
    )
    parser.add_argument(
        "--installed-only",
        action="store_true",
        help="Hide not-applicable Sites from output after scanning all Sites.",
    )
    args = parser.parse_args(argv)

    result = scan_bench_sites(args.sites_path)
    reports = result["sites"]
    if args.installed_only:
        reports = [
            report
            for report in reports
            if report["zatca_installed"] is not False
        ]

    if args.format in {"table", "both"}:
        print(format_report_table(reports))
        print(
            "\nSummary: "
            f"total={result['total_sites']} "
            f"installed={result['zatca_installed_sites']} "
            f"blocking={len(result['blocking_sites'])} "
            f"deployment_allowed={result['deployment_allowed']}"
        )

    if args.format in {"json", "both"}:
        output = dict(result)
        output["sites"] = reports
        print(json.dumps(output, indent=2, sort_keys=True))

    return deployment_exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
