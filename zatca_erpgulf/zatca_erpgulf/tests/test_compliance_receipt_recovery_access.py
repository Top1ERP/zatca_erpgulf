"""Permissioned local recovery with fake saved rows/owned SQL; no real send."""

import csv
import json
import pickle
from dataclasses import replace
from datetime import timedelta
from inspect import signature
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import compliance_capture_access as source_access
from zatca_erpgulf.zatca_erpgulf import compliance_receipt_recovery_access as access
from zatca_erpgulf.zatca_erpgulf.compliance_evidence import STEP_CLASSIFICATION
from zatca_erpgulf.zatca_erpgulf.compliance_receipt_recovery import ComplianceReceiptRecovery, ComplianceReceiptRecoveryError
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_capture_access import (
    capture_operator, scenario_for, operator, materials, cipher, archive_cipher,
    PermissionDenied, InspectionFailed, SELLER, NOW,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_archive import archive_record


@pytest.fixture
def recovery_operator(capture_operator, monkeypatch):
    monkeypatch.setattr(access, "frappe", capture_operator.runtime)
    monkeypatch.setattr(access, "_", lambda text: text)
    return capture_operator


def scenario_for_recovery(operator, material, cipher, archive_cipher, *, committed=False, **options):
    scenario = scenario_for(operator, material, cipher, archive_cipher, **options)
    original = scenario.factory.side_effect
    def acquire():
        database = original()
        if database.index == 2:  # Guarded capture's THIRD (receipt) transaction.
            def unknown():
                if committed:
                    database._commit()
                raise RuntimeError("PRIVATE-SECRET original receipt commit uncertain")
            database.commit.side_effect = unknown
        return database
    scenario.factory.side_effect = acquire
    scenario.retained = scenario.collect()
    assert scenario.retained.state == "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY"
    scenario.factory.side_effect = original
    scenario.recovery_resources = access.ComplianceReceiptRecoveryResources(scenario.resources.scope, cipher, archive_cipher,
                                                                           scenario.factory)
    scenario.recovery_provider = Mock(return_value=scenario.recovery_resources)
    scenario.recovery_service = access.StagedComplianceReceiptRecoveryService(scenario.resources.scope, scenario.recovery_provider)
    def persist(result=None):
        return scenario.recovery_service.persist_receipt("TC", scenario.source, scenario.retained if result is None else result)
    scenario.persist = persist
    return scenario


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("step", list(STEP_CLASSIFICATION))
@pytest.mark.parametrize("source", ["implicit", "company", "sales", "pos", "device", "linked"])
def test_shared_saved_policy_one_recovery_transaction_and_no_transport(recovery_operator, materials, cipher, archive_cipher, monkeypatch, environment, step, source):
    scenario = scenario_for_recovery(recovery_operator, materials[0], cipher, archive_cipher,
                                    environment=environment, step=step, source=source)
    scenario.transport.side_effect = AssertionError("No second HTTP call")
    scenario.clock.side_effect = AssertionError("No recovery clock")
    monkeypatch.setattr(archive_cipher, "seal", Mock(side_effect=AssertionError("No resealing")))
    result = scenario.persist()
    assert result == replace(scenario.retained, state="RECEIPT_CAPTURED_OBSERVATION")
    assert scenario.rows[scenario.identity, 2] == archive_record(scenario.retained.receipt_envelope)
    assert len(scenario.connections) == 4 and all(database.closed for database in scenario.connections)
    assert scenario.events[-2:] == [("commit", 3), ("close", 3)]
    statements = [sql for index, sql, _ in scenario.sql if index == 3]
    assert sum("FROM `tabCompany`" in sql for sql in statements) >= 2
    assert next(index for index, sql in enumerate(statements) if "FROM `tabCompany`" in sql) < next(
        index for index, sql in enumerate(statements) if sql.startswith("SELECT slot_sha256"))
    assert all(value is False for name, value in result.diagnostic_projection().items() if name.endswith(("_authorized", "_verified")))
    assert scenario.transport.call_count == 1 and scenario.clock.call_count == 3
    recovery_operator.runtime.db.commit.assert_not_called()
    recovery_operator.runtime.db.rollback.assert_not_called()
    for document in recovery_operator.documents.values():
        document.save.assert_not_called()
        document.db_set.assert_not_called()
        document.check_permission.assert_not_called()


@pytest.mark.parametrize("committed", [False, True])
@pytest.mark.parametrize("status", [200, 202, 400, 401, 406, 500])
def test_both_commit_outcomes_and_rejected_receipts_are_storage_only(recovery_operator, materials, cipher, archive_cipher, committed, status):
    scenario = scenario_for_recovery(recovery_operator, materials[0], cipher, archive_cipher, committed=committed, status=status)
    result = scenario.persist()
    assert result.observation.http_status == status and result.state == "RECEIPT_CAPTURED_OBSERVATION"
    assert scenario.persist() == result and scenario.transport.call_count == 1
    assert result.diagnostic_projection()["compliance_completion_verified"] is False


@pytest.mark.parametrize("identity", [("Company", "SOURCE"), ("Sales Invoice", "SI"),
    ("ZATCA Multiple Setting", "OWNER"), ("Company", "OWNER")])
@pytest.mark.parametrize("operation", ["read", "write"])
def test_every_saved_row_acl_precedes_provider_and_crypto(recovery_operator, materials, cipher, archive_cipher, monkeypatch, identity, operation):
    scenario = scenario_for_recovery(recovery_operator, materials[0], cipher, archive_cipher, source="linked")
    recovery_operator.denied_operations.add((*identity, operation))
    opening = Mock(wraps=archive_cipher.open)
    monkeypatch.setattr(archive_cipher, "open", opening)
    with pytest.raises(PermissionDenied, match=access.DENIED_MESSAGE) as error:
        scenario.persist()
    assert error.value.__context__ is None
    scenario.recovery_provider.assert_not_called()
    opening.assert_not_called()
    assert scenario.factory.call_count == 3 and scenario.transport.call_count == 1


@pytest.mark.parametrize("user,roles,site", [("Guest", ["System Manager"], "private.test"),
    ("manager@example.test", [], "private.test"), ("Administrator", [], "other.test"),
    (None, ["System Manager"], "private.test"), ("", ["System Manager"], "private.test")])
def test_bound_actor_is_required_before_saved_reads_or_key_provider(recovery_operator, materials, cipher, archive_cipher, user, roles, site):
    scenario = scenario_for_recovery(recovery_operator, materials[0], cipher, archive_cipher)
    recovery_operator.runtime.get_doc.reset_mock()
    recovery_operator.runtime.session.user, recovery_operator.runtime.local.site = user, site
    recovery_operator.runtime.get_roles.return_value = roles
    with pytest.raises(PermissionDenied, match=access.DENIED_MESSAGE):
        scenario.persist()
    recovery_operator.runtime.get_doc.assert_not_called()
    scenario.recovery_provider.assert_not_called()


@pytest.mark.parametrize("fault", ["wrong_type", "namespace", "captured", "owner", "kind", "taxpayer", "environment", "route", "source", "revision"])
def test_pure_input_and_current_saved_binding_cannot_fall_back_before_provider(recovery_operator, materials, cipher, archive_cipher, fault):
    scenario = scenario_for_recovery(recovery_operator, materials[0], cipher, archive_cipher, source="sales")
    result = scenario.retained
    if fault == "wrong_type":
        result = {}
    elif fault == "captured":
        result = replace(result, state="RECEIPT_CAPTURED_OBSERVATION")
    elif fault == "namespace":
        scenario.recovery_service._scope = access.CredentialStorageScope("private.test", str(uuid4()))
    elif fault in ("owner", "kind", "source"):
        if fault == "owner":
            recovery_operator.documents["ZATCA Multiple Setting", "OWNER"].values.update(
                custom__use_company_certificate__keys=1, custom_linked_doctype="OWNER")
        elif fault == "kind":
            recovery_operator.documents["Sales Invoice", "SI"].values["custom_zatca_pos_name"] = None
        else:
            recovery_operator.documents["Sales Invoice", "SI"].values["company"] = "OTHER"
    else:
        key, value = {"taxpayer": ("tax_id", "OTHER"), "environment": ("custom_select", "Sandbox"),
            "route": ("custom_production_url", "https://other.invalid/core"), "revision": ("modified", None)}[fault]
        recovery_operator.documents["Company", "SOURCE"].values[key] = value
    with pytest.raises(InspectionFailed, match=access.FAILED_MESSAGE) as error:
        scenario.persist(result)
    assert error.value.__context__ is None
    scenario.recovery_provider.assert_not_called()
    assert scenario.factory.call_count == 3


@pytest.mark.parametrize("change", ["exception", "scope", "type", "actor", "site", "acl", "revision"])
def test_provider_or_saved_context_drift_stops_before_sql(recovery_operator, materials, cipher, archive_cipher, change):
    scenario = scenario_for_recovery(recovery_operator, materials[0], cipher, archive_cipher)
    def provider(scope):
        if change == "exception":
            raise RuntimeError("PRIVATE-SECRET provider failure")
        if change == "scope":
            return replace(scenario.recovery_resources, scope=access.CredentialStorageScope(scope.site, str(uuid4())))
        if change == "type":
            return scenario.resources  # A capture provider has transport; reject it.
        if change == "actor":
            recovery_operator.runtime.session.user = "other@example.test"
        elif change == "site":
            recovery_operator.runtime.local.site = "other.test"
        elif change == "acl":
            recovery_operator.denied_operations.add(("Company", "SOURCE", "write"))
        else:
            recovery_operator.documents["Company", "SOURCE"].values["modified"] += timedelta(seconds=1)
        return scenario.recovery_resources
    scenario.recovery_provider.side_effect = provider
    with pytest.raises(PermissionDenied if change in ("actor", "site", "acl") else InspectionFailed) as error:
        scenario.persist()
    assert error.value.__context__ is None and "PRIVATE-SECRET" not in str(error.value)
    assert scenario.factory.call_count == 3 and scenario.transport.call_count == 1


@pytest.mark.parametrize("phase", ["acquire", "archive", "close"])
@pytest.mark.parametrize("change", ["acl", "actor", "role", "revision"])
def test_current_access_rechecked_around_storage_and_after_close(recovery_operator, materials, cipher, archive_cipher, phase, change):
    scenario = scenario_for_recovery(recovery_operator, materials[0], cipher, archive_cipher)
    original = scenario.factory.side_effect
    def mutate():
        if change == "acl":
            recovery_operator.denied_operations.add(("Company", "SOURCE", "write"))
        elif change == "actor":
            recovery_operator.runtime.session.user = "other@example.test"
        elif change == "role":
            recovery_operator.runtime.get_roles.return_value = []
        else:
            recovery_operator.documents["Company", "SOURCE"].values["modified"] += timedelta(seconds=1)
    def acquire():
        database = original()
        if phase == "acquire":
            mutate()
        elif phase == "archive":
            execute = database.cursor.return_value.execute.side_effect
            def query(sql, values=None):
                execute(sql, values)
                if sql.startswith("INSERT INTO zatca_compliance_archive_v1"):
                    mutate()
            database.cursor.return_value.execute.side_effect = query
        else:
            close = database.close.side_effect
            def release():
                close()
                mutate()
            database.close.side_effect = release
        return database
    scenario.factory.side_effect = acquire
    with pytest.raises(InspectionFailed if change == "revision" else PermissionDenied) as error:
        scenario.persist()
    assert error.value.__context__ is None and scenario.connections[-1].closed
    # Permission loss after a successful commit cannot undo captured evidence.
    assert ((scenario.identity, 2) in scenario.rows) is (phase == "close")
    assert scenario.transport.call_count == 1


@pytest.mark.parametrize("change", ["taxpayer", "route", "source_link", "owner_link", "flag", "revision", "missing"])
def test_locked_sql_detects_stale_frappe_projection_without_archiving_receipt(recovery_operator, materials, cipher, archive_cipher, change):
    scenario = scenario_for_recovery(recovery_operator, materials[0], cipher, archive_cipher, source="sales")
    if change == "missing":
        scenario.sql_documents.pop(("Sales Invoice", "SI"))
    else:
        identity, key, value = {
            "taxpayer": (("Company", "SOURCE"), "tax_id", "OTHER"),
            "route": (("Company", "SOURCE"), "custom_production_url", "https://other.invalid/core"),
            "source_link": (("Sales Invoice", "SI"), "custom_zatca_pos_name", None),
            "owner_link": (("ZATCA Multiple Setting", "OWNER"), "custom_linked_doctype", "OTHER"),
            "flag": (("ZATCA Multiple Setting", "OWNER"), source_access.FLAG_FIELD, 1),
            "revision": (("Company", "SOURCE"), "modified", NOW.replace(tzinfo=None) + timedelta(seconds=1)),
        }[change]
        scenario.sql_documents[identity][key] = value
    assert scenario.persist() is scenario.retained
    assert (scenario.identity, 2) not in scenario.rows
    scenario.connections[-1].commit.assert_not_called()
    scenario.connections[-1].rollback.assert_called_once()
    scenario.connections[-1].close.assert_called_once()


@pytest.mark.parametrize("envelope_name", ["start_envelope", "receipt_envelope"])
def test_ciphertext_authentication_after_acl_but_before_sql(recovery_operator, materials, cipher, archive_cipher, envelope_name):
    scenario = scenario_for_recovery(recovery_operator, materials[0], cipher, archive_cipher)
    sealed = getattr(scenario.retained, envelope_name)
    sealed = replace(sealed, ciphertext=sealed.ciphertext[:-1] + bytes([sealed.ciphertext[-1] ^ 1]))
    result = replace(scenario.retained, **{envelope_name: sealed})
    with pytest.raises(InspectionFailed, match=access.FAILED_MESSAGE) as error:
        scenario.persist(result)
    assert error.value.__context__ is None
    scenario.recovery_provider.assert_called_once()
    assert scenario.factory.call_count == 3


@pytest.mark.parametrize("phase", ["source", "archive"])
@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_interruptions_keep_caller_input_and_cleanup_owned_sql(recovery_operator, materials, cipher, archive_cipher, phase, interruption):
    scenario = scenario_for_recovery(recovery_operator, materials[0], cipher, archive_cipher)
    original = scenario.factory.side_effect
    def acquire():
        database = original()
        execute = database.cursor.return_value.execute.side_effect
        def query(sql, values=None):
            if (phase == "source" and sql.startswith("SELECT `modified`")) or (
                    phase == "archive" and sql.startswith("INSERT INTO zatca_compliance_archive_v1")):
                raise interruption()
            execute(sql, values)
        database.cursor.return_value.execute.side_effect = query
        return database
    scenario.factory.side_effect = acquire
    with pytest.raises(interruption):
        scenario.persist()
    assert scenario.retained.state == "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY"
    scenario.connections[-1].rollback.assert_called_once()
    scenario.connections[-1].close.assert_called_once()


@pytest.mark.parametrize("version", [15, 16])
def test_both_quiet_permission_signatures_use_same_saved_row_policy(recovery_operator, materials, cipher, archive_cipher, monkeypatch, version):
    scenario = scenario_for_recovery(recovery_operator, materials[0], cipher, archive_cipher)
    calls = []
    if version == 15:
        def permission(doctype, operation, *, doc, user, raise_exception):
            assert raise_exception is False
            calls.append((doctype, operation, doc.name))
            return True
    else:
        def permission(doctype, operation, *, doc, user, print_logs):
            assert print_logs is False
            calls.append((doctype, operation, doc.name))
            return True
    engine = Mock(side_effect=permission)
    engine.__signature__ = signature(permission)
    monkeypatch.setattr(source_access, "has_permission", engine)
    assert scenario.persist().state == "RECEIPT_CAPTURED_OBSERVATION"
    assert calls and {operation for _, operation, _ in calls} == {"read", "write"}


@pytest.mark.parametrize("phase", [0, 1])
@pytest.mark.parametrize("guard_value", [False, None, 1, "true"])
def test_low_level_guard_requires_literal_true_without_partial_commit(materials, cipher, archive_cipher, phase, guard_value):
    from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_receipt_recovery import uncertain
    from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_capture import Scenario

    scenario = Scenario(materials[0], cipher, archive_cipher)
    result = uncertain(scenario)
    guard = Mock(side_effect=[True, guard_value] if phase else [guard_value])
    recovery = ComplianceReceiptRecovery(result.observation.requirements.storage_namespace, cipher, archive_cipher,
                                         connection_factory=scenario.factory, source_guard=guard)
    assert recovery.persist_receipt(result) is result
    assert guard.call_count == phase + 1 and (scenario.identity, 2) not in scenario.rows
    scenario.connections[-1].rollback.assert_called_once()
    assert scenario.transport.call_count == 1


def test_protected_resources_translation_and_no_public_endpoint(recovery_operator, materials, cipher, archive_cipher, monkeypatch):
    scenario = scenario_for_recovery(recovery_operator, materials[0], cipher, archive_cipher)
    public = repr(scenario.recovery_service) + repr(scenario.recovery_resources)
    recovered = scenario.persist()
    public += json.dumps(recovered.diagnostic_projection())
    for private in (SELLER, materials[0].pem, materials[0].text, "gw-fatoora", scenario.body.decode()):
        assert private not in public
    for value in (scenario.recovery_resources, scenario.recovery_service):
        with pytest.raises(source_access.ComplianceSourceError, match="not_pickleable"):
            pickle.dumps(value)
    assert not hasattr(scenario.recovery_service, "capture")
    assert not getattr(access.StagedComplianceReceiptRecoveryService.persist_receipt, "is_whitelisted", False)
    catalog = Path(__file__).resolve().parents[2] / "translations/ar.csv"
    with catalog.open() as stream:
        translations = {row[0]: row[1] for row in csv.reader(stream) if len(row) >= 2}
    for message in (access.DENIED_MESSAGE, access.FAILED_MESSAGE):
        assert translations[message] != message
    monkeypatch.setattr(source_access, "_", lambda text: translations.get(text, text))
    monkeypatch.setattr(access, "_", lambda text: translations.get(text, text))
    recovery_operator.denied.add(("Company", "SOURCE"))
    with pytest.raises(PermissionDenied) as error:
        scenario.persist()
    assert str(error.value) == translations[access.DENIED_MESSAGE]


def test_bad_guard_and_provider_dependencies_do_not_acquire_resources(recovery_operator, materials, cipher, archive_cipher):
    scenario = scenario_for_recovery(recovery_operator, materials[0], cipher, archive_cipher)
    with pytest.raises(ComplianceReceiptRecoveryError, match="recovery_dependencies"):
        ComplianceReceiptRecovery(scenario.resources.scope.storage_namespace, cipher, archive_cipher,
                                  connection_factory=scenario.factory, source_guard=False)
    with pytest.raises(source_access.ComplianceSourceError, match="source_dependencies"):
        access.StagedComplianceReceiptRecoveryService(scenario.resources.scope, None)
    with pytest.raises(source_access.ComplianceSourceError, match="source_resources"):
        replace(scenario.recovery_resources, scope=object())
    assert scenario.factory.call_count == 3
