from __future__ import annotations

import unittest

from zatca_erpgulf.zatca_erpgulf import compatibility_preflight
from zatca_erpgulf.zatca_erpgulf.zatca_runtime import (
    ADVANCE_DEDUCTION_CHILD_DB_FIELDS,
    ADVANCE_DEDUCTION_CHILD_DOCTYPE,
    ADVANCE_DEDUCTION_CHILD_FIELDS,
    ADVANCE_DEDUCTION_PARENT_DB_FIELDS,
    ADVANCE_DEDUCTION_PARENT_FIELDS,
    ADVANCE_DEDUCTION_TABLE_FIELD,
    ADVANCE_PAYMENT_ENTRY_LINK_FIELD,
)


def _complete_snapshot():
    parent_fields = set(ADVANCE_DEDUCTION_PARENT_FIELDS)
    parent_fields.update(
        {
            compatibility_preflight.PRIMARY_MARKER_FIELD,
            compatibility_preflight.LEGACY_MARKER_FIELD,
            ADVANCE_PAYMENT_ENTRY_LINK_FIELD,
        }
    )
    parent_columns = set(ADVANCE_DEDUCTION_PARENT_DB_FIELDS)
    parent_columns.update(
        {
            compatibility_preflight.PRIMARY_MARKER_FIELD,
            compatibility_preflight.LEGACY_MARKER_FIELD,
            ADVANCE_PAYMENT_ENTRY_LINK_FIELD,
        }
    )
    return {
        "site": "test.local",
        "zatca_installed": True,
        "parent_table_exists": True,
        "parent_metadata_fields": parent_fields,
        "parent_db_columns": parent_columns,
        "parent_table_field": {
            "fieldtype": "Table",
            "options": ADVANCE_DEDUCTION_CHILD_DOCTYPE,
        },
        "child_metadata_exists": True,
        "child_table_exists": True,
        "child_metadata_fields": set(ADVANCE_DEDUCTION_CHILD_FIELDS),
        "child_db_columns": set(ADVANCE_DEDUCTION_CHILD_DB_FIELDS),
    }


class TestCompatibilityPreflightClassification(unittest.TestCase):
    def test_complete_schema_is_safe_complete(self):
        report = compatibility_preflight.classify_schema_snapshot(
            _complete_snapshot()
        )

        self.assertEqual(
            report["classification"],
            compatibility_preflight.SAFE_COMPLETE,
        )
        self.assertFalse(report["blocking"])
        self.assertTrue(report["deployment_allowed"])
        self.assertEqual(report["risk"], compatibility_preflight.RISK_INFO)
        self.assertTrue(
            report["runtime_capabilities"]["advance_deduction"]
        )
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["repair_recommendations"], [])
        for key in (
            "site",
            "classification",
            "deployment_allowed",
            "risk",
            "problems",
            "repair_recommendations",
            "runtime_capabilities",
        ):
            self.assertIn(key, report)

    def test_old_schema_without_new_metadata_is_safe_legacy(self):
        snapshot = {
            "site": "legacy.local",
            "zatca_installed": True,
            "parent_table_exists": True,
            "parent_metadata_fields": {"custom_zatca_status"},
            "parent_db_columns": {"custom_zatca_status"},
            "child_metadata_exists": False,
            "child_table_exists": False,
        }

        report = compatibility_preflight.classify_schema_snapshot(
            snapshot
        )

        self.assertEqual(
            report["classification"],
            compatibility_preflight.SAFE_LEGACY,
        )
        self.assertFalse(report["blocking"])

    def test_partial_runtime_safe_schema_is_safe_partial(self):
        snapshot = {
            "site": "partial.local",
            "zatca_installed": True,
            "parent_table_exists": True,
            "parent_metadata_fields": {
                compatibility_preflight.PRIMARY_MARKER_FIELD,
            },
            "parent_db_columns": {
                compatibility_preflight.PRIMARY_MARKER_FIELD,
            },
            "child_metadata_exists": False,
            "child_table_exists": True,
            "child_db_columns": set(ADVANCE_DEDUCTION_CHILD_DB_FIELDS),
        }

        report = compatibility_preflight.classify_schema_snapshot(
            snapshot
        )

        self.assertEqual(
            report["classification"],
            compatibility_preflight.SAFE_PARTIAL,
        )
        self.assertFalse(report["blocking"])
        self.assertTrue(
            report["capabilities"]["advance_payment_marker"]
        )
        self.assertFalse(
            report["capabilities"]["advance_deduction"]
        )

    def test_dangling_table_field_is_unsafe_structural(self):
        snapshot = _complete_snapshot()
        snapshot["child_table_exists"] = False
        snapshot["child_db_columns"] = set()

        report = compatibility_preflight.classify_schema_snapshot(
            snapshot
        )

        self.assertEqual(
            report["classification"],
            compatibility_preflight.UNSAFE_STRUCTURAL,
        )
        self.assertTrue(report["blocking"])
        self.assertFalse(report["deployment_allowed"])
        self.assertEqual(
            report["risk"],
            compatibility_preflight.RISK_CRITICAL,
        )
        codes = {
            problem["code"] for problem in report["problems"]
        }
        self.assertIn(
            "DANGLING_TABLE_FIELD_MISSING_CHILD_TABLE",
            codes,
        )
        critical = [
            problem
            for problem in report["problems"]
            if problem["code"]
            == "DANGLING_TABLE_FIELD_MISSING_CHILD_TABLE"
        ]
        self.assertEqual(critical[0]["severity"], "CRITICAL")
        self.assertIn(
            f"tab{ADVANCE_DEDUCTION_CHILD_DOCTYPE}",
            report["root_causes"]["missing_sql_tables"],
        )

    def test_missing_child_db_column_is_unsafe_structural(self):
        snapshot = _complete_snapshot()
        snapshot["child_db_columns"].remove(
            "allocated_tax_amount"
        )

        report = compatibility_preflight.classify_schema_snapshot(
            snapshot
        )

        self.assertEqual(
            report["classification"],
            compatibility_preflight.UNSAFE_STRUCTURAL,
        )
        self.assertTrue(report["blocking"])
        codes = {
            problem["code"] for problem in report["problems"]
        }
        self.assertIn("CHILD_REQUIRED_COLUMNS_MISSING", codes)

        missing_sql_columns = report["root_causes"][
            "missing_sql_columns"
        ]
        self.assertIn(
            {
                "table": f"tab{ADVANCE_DEDUCTION_CHILD_DOCTYPE}",
                "column": "allocated_tax_amount",
            },
            missing_sql_columns,
        )
        recommendation = next(
            item
            for item in report["repair_recommendations"]
            if item["issue_code"]
            == "CHILD_REQUIRED_COLUMNS_MISSING"
        )
        self.assertTrue(recommendation["why"])
        self.assertTrue(recommendation["requires"]["reload_doc"])

    def test_missing_child_field_reports_exact_metadata_and_sql_objects(self):
        snapshot = _complete_snapshot()
        snapshot["site"] = "unsafe.local"
        snapshot["child_metadata_fields"].remove("advance_invoice")
        snapshot["child_db_columns"].remove("advance_invoice")

        report = compatibility_preflight.classify_schema_snapshot(snapshot)

        self.assertEqual(
            report["root_causes"]["missing_metadata_fields"],
            [
                {
                    "doctype": ADVANCE_DEDUCTION_CHILD_DOCTYPE,
                    "fieldname": "advance_invoice",
                }
            ],
        )
        self.assertEqual(
            report["root_causes"]["missing_sql_columns"],
            [
                {
                    "table": f"tab{ADVANCE_DEDUCTION_CHILD_DOCTYPE}",
                    "column": "advance_invoice",
                }
            ],
        )
        metadata_problem = next(
            item
            for item in report["problems"]
            if item["code"]
            == "CHILD_REQUIRED_METADATA_FIELDS_MISSING"
        )
        self.assertEqual(
            metadata_problem["objects"],
            report["root_causes"]["missing_metadata_fields"],
        )
        recommendation_codes = {
            item["issue_code"]
            for item in report["repair_recommendations"]
        }
        self.assertIn(
            "CHILD_REQUIRED_METADATA_FIELDS_MISSING",
            recommendation_codes,
        )
        self.assertIn(
            "CHILD_REQUIRED_COLUMNS_MISSING",
            recommendation_codes,
        )

    def test_primary_marker_does_not_fall_back_to_legacy_column(self):
        snapshot = _complete_snapshot()
        snapshot["parent_db_columns"].remove(
            compatibility_preflight.PRIMARY_MARKER_FIELD
        )

        report = compatibility_preflight.classify_schema_snapshot(
            snapshot
        )

        self.assertFalse(
            report["capabilities"]["advance_payment_marker"]
        )
        self.assertEqual(
            report["marker"]["authoritative_field"],
            compatibility_preflight.PRIMARY_MARKER_FIELD,
        )
        self.assertFalse(report["marker"]["primary_column"])
        self.assertTrue(report["marker"]["legacy_column"])
        self.assertEqual(
            report["classification"],
            compatibility_preflight.UNSAFE_STRUCTURAL,
        )
        marker_mismatch = report["root_causes"]["marker_mismatch"]
        self.assertEqual(
            marker_mismatch["authoritative_field"],
            compatibility_preflight.PRIMARY_MARKER_FIELD,
        )
        self.assertEqual(
            marker_mismatch["issues"][0]["mismatch"],
            "metadata_without_sql_column",
        )

    def test_parent_metadata_and_sql_mismatches_are_explicit(self):
        snapshot = _complete_snapshot()
        metadata_field = "custom_zatca_advance_deduction_section"
        sql_field = "custom_zatca_prepaid_amount"
        snapshot["parent_metadata_fields"].remove(metadata_field)
        snapshot["parent_db_columns"].remove(sql_field)

        report = compatibility_preflight.classify_schema_snapshot(snapshot)

        self.assertIn(
            {
                "doctype": compatibility_preflight.SALES_INVOICE_DOCTYPE,
                "fieldname": metadata_field,
            },
            report["root_causes"]["missing_metadata_fields"],
        )
        self.assertIn(
            {
                "table": "tabSales Invoice",
                "column": sql_field,
            },
            report["root_causes"]["missing_sql_columns"],
        )
        mismatch = next(
            item
            for item in report["root_causes"][
                "parent_field_mismatches"
            ]
            if item["fieldname"] == sql_field
        )
        self.assertEqual(
            mismatch["mismatch"],
            "metadata_without_sql_column",
        )
        self.assertEqual(
            [problem["code"] for problem in report["problems"]],
            [
                recommendation["issue_code"]
                for recommendation in report[
                    "repair_recommendations"
                ]
            ],
        )
        for recommendation in report["repair_recommendations"]:
            self.assertTrue(recommendation["suggested_action"])
            self.assertTrue(recommendation["why"])

    def test_payment_entry_mismatch_is_reported_exactly(self):
        snapshot = _complete_snapshot()
        snapshot["parent_db_columns"].remove(
            ADVANCE_PAYMENT_ENTRY_LINK_FIELD
        )

        report = compatibility_preflight.classify_schema_snapshot(snapshot)

        mismatch = report["root_causes"]["payment_entry_mismatch"]
        self.assertEqual(
            mismatch["fieldname"],
            ADVANCE_PAYMENT_ENTRY_LINK_FIELD,
        )
        self.assertEqual(
            mismatch["issues"][0]["fieldname"],
            ADVANCE_PAYMENT_ENTRY_LINK_FIELD,
        )
        self.assertEqual(
            report["classification"],
            compatibility_preflight.UNSAFE_STRUCTURAL,
        )

    def test_missing_doctype_and_table_are_listed_by_exact_name(self):
        snapshot = _complete_snapshot()
        snapshot["child_metadata_exists"] = False
        snapshot["child_metadata_fields"] = set()
        snapshot["child_table_exists"] = False
        snapshot["child_db_columns"] = set()

        report = compatibility_preflight.classify_schema_snapshot(snapshot)

        self.assertEqual(
            report["root_causes"]["missing_doctypes"],
            [ADVANCE_DEDUCTION_CHILD_DOCTYPE],
        )
        self.assertEqual(
            report["root_causes"]["missing_sql_tables"],
            [f"tab{ADVANCE_DEDUCTION_CHILD_DOCTYPE}"],
        )

    def test_physical_marker_residue_is_info_risk(self):
        snapshot = {
            "site": "residue.local",
            "zatca_installed": True,
            "parent_table_exists": True,
            "parent_metadata_fields": {"custom_zatca_status"},
            "parent_db_columns": {
                "custom_zatca_status",
                compatibility_preflight.PRIMARY_MARKER_FIELD,
            },
            "child_metadata_exists": False,
            "child_table_exists": False,
        }

        report = compatibility_preflight.classify_schema_snapshot(snapshot)

        self.assertEqual(
            report["classification"],
            compatibility_preflight.SAFE_PARTIAL,
        )
        self.assertEqual(report["risk"], compatibility_preflight.RISK_INFO)
        self.assertTrue(report["deployment_allowed"])
        self.assertEqual(
            report["root_causes"]["marker_mismatch"]["issues"][0][
                "mismatch"
            ],
            "sql_column_without_metadata",
        )

    def test_app_not_installed_is_not_applicable(self):
        report = compatibility_preflight.classify_schema_snapshot(
            {
                "site": "other.local",
                "zatca_installed": False,
            }
        )

        self.assertEqual(
            report["classification"],
            compatibility_preflight.NOT_APPLICABLE,
        )
        self.assertFalse(report["blocking"])
        self.assertTrue(report["deployment_allowed"])

    def test_exit_code_is_one_only_for_unsafe_structural(self):
        safe_classifications = (
            compatibility_preflight.SAFE_COMPLETE,
            compatibility_preflight.SAFE_PARTIAL,
            compatibility_preflight.SAFE_LEGACY,
            compatibility_preflight.NOT_APPLICABLE,
        )
        for classification in safe_classifications:
            with self.subTest(classification=classification):
                self.assertEqual(
                    compatibility_preflight.deployment_exit_code(
                        {"sites": [{"classification": classification}]}
                    ),
                    0,
                )

        self.assertEqual(
            compatibility_preflight.deployment_exit_code(
                {
                    "sites": [
                        {"classification": compatibility_preflight.SAFE_COMPLETE},
                        {"classification": compatibility_preflight.UNSAFE_STRUCTURAL},
                    ]
                }
            ),
            1,
        )

    def test_table_output_has_risk_column(self):
        report = compatibility_preflight.classify_schema_snapshot(
            _complete_snapshot()
        )

        output = compatibility_preflight.format_report_table([report])

        self.assertIn("Risk", output.splitlines()[0])


if __name__ == "__main__":
    unittest.main()
