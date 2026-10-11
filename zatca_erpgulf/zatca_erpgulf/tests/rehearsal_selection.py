"""Explicit reviewed test selection; no runtime/site discovery or broad pytest."""

LOCAL_SUITES = (
    "offline_rehearsal", "issue_timestamp", "issue_timestamp_adapters", "advance_reference", "permission_compat", "compliance_capture_access", "compliance_receipt_recovery_access",
    "compliance_https", "compliance_capture", "compliance_receipt_recovery", "compliance_archive_access",
    "compliance_archive", "compliance_evidence", "credential_bundle_access",
    "credential_bundle", "credential_lifecycle", "credential_snapshot",
    "journal_storage", "journal_repository", "response_assessment",
    "dispatch_journal", "issuance_candidate", "certificate_evidence",
    "certificate_inventory", "history_evidence", "history_inventory",
    "artifact_evidence", "artifact_inventory", "generated_inventory",
    "retry_identity_contract", "background_scheduling", "generation_routes",
    "icv_identity_contract", "legacy_submission_context", "submission_context",
    "credential_selection", "field_compat", "api_route_contract", "api_routing",
    "nonproduction_isolation", "compliance_result", "compliance_api_outcomes",
    "tax_details_compat", "tax_details_regression", "qr_tlv_compliance",
    "zatca_response", "compatibility_hardening",
)
PRIVATE_SUITES = (
    "journal_repository_mariadb", "credential_bundle_mariadb",
    "compliance_archive_mariadb", "compliance_capture_mariadb",
    "compliance_https_mariadb", "compliance_capture_access_mariadb",
    "compliance_receipt_recovery_mariadb",
    "compliance_receipt_recovery_access_mariadb",
)
TEST_DIRECTORY = "zatca_erpgulf/zatca_erpgulf/tests"


def selected_paths(*, private_sql=False):
    suites = LOCAL_SUITES + (PRIVATE_SUITES if private_sql else ())
    return tuple(TEST_DIRECTORY + "/test_" + name + ".py" for name in suites)
