"""Permissioned receipt recovery on OWNED private SQL, fake Frappe only."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import compliance_receipt_recovery_access as access
from zatca_erpgulf.zatca_erpgulf import compliance_capture_access as source_access
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_archive_mariadb import (
    isolated_server, connections, install_private_bundle_schema, install_private_archive_schema,
    context, materials, audit,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_capture_access_mariadb import install_private_source_schema, prepare_sources
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_receipt_recovery_access import (
    operator, capture_operator, recovery_operator, PermissionDenied,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_receipt_recovery_mariadb import uncertain, history


pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
                               reason="Owned guarded private SQL only; no tenant or authority request")


def service(audit, factory):
    scope = access.CredentialStorageScope("private.test", audit[0])
    resources = access.ComplianceReceiptRecoveryResources(scope, audit[1], audit[2], factory)
    provider = Mock(return_value=resources)
    return access.StagedComplianceReceiptRecoveryService(scope, provider), provider


@pytest.mark.parametrize("committed", [False, True])
def test_saved_acl_source_locks_and_exact_ciphertext_recovery_without_sender(connections, audit, recovery_operator, committed):
    prepare_sources(connections, recovery_operator)
    result, transport = uncertain(connections, audit, committed=committed)
    owned = []
    def factory():
        database = connections()
        owned.append(database)
        return database
    operator_service, provider = service(audit, factory)
    recovered = operator_service.persist_receipt("TC", None, result)
    assert recovered.state == "RECEIPT_CAPTURED_OBSERVATION"
    assert recovered.receipt_envelope is result.receipt_envelope
    assert len(owned) == 1 and owned[0].open is False
    assert history(connections, audit).receipt == result.observation
    provider.assert_called_once()
    transport.assert_called_once()


@pytest.mark.parametrize("change", ["route", "revision"])
def test_stale_ambient_document_cannot_ignore_actual_sql_edit(connections, audit, recovery_operator, change):
    prepare_sources(connections, recovery_operator)
    result, transport = uncertain(connections, audit)
    mutation = connections()
    try:
        with mutation.cursor() as cursor:
            if change == "route":
                cursor.execute("UPDATE `tabCompany` SET `custom_production_url`=%s WHERE `name`=%s",
                               ("https://other.invalid/core", "SOURCE"))
            else:
                cursor.execute("UPDATE `tabCompany` SET `modified`=DATE_ADD(`modified`, INTERVAL 1 SECOND) WHERE `name`=%s", ("SOURCE",))
        mutation.commit()  # OWNED synthetic tables only.
    finally:
        mutation.close()
    operator_service, _ = service(audit, connections)
    assert operator_service.persist_receipt("TC", None, result) is result
    assert history(connections, audit).receipt is None
    transport.assert_called_once()


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
def test_competing_permissioned_recoveries_confirm_one_exact_observation(connections, audit, recovery_operator, isolation):
    prepare_sources(connections, recovery_operator)
    result, transport = uncertain(connections, audit)
    services = [service(audit, lambda: connections(isolation))[0] for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(operator_service.persist_receipt, "TC", None, result) for operator_service in services]
        recovered = [future.result(timeout=10) for future in futures]
    assert all(item.state == "RECEIPT_CAPTURED_OBSERVATION" for item in recovered)
    assert history(connections, audit).receipt == result.observation
    transport.assert_called_once()


@pytest.mark.parametrize("committed", [False, True])
def test_guarded_recovery_unknown_commit_keeps_original_without_another_request(connections, audit, recovery_operator, committed):
    prepare_sources(connections, recovery_operator)
    result, transport = uncertain(connections, audit)
    owned = []
    def factory():
        database = connections()
        owned.append(database)
        commit = database.commit
        def unknown():
            if committed:
                commit()
            raise RuntimeError("PRIVATE-SECRET guarded recovery commit unknown")
        database.commit = unknown
        return database
    operator_service, _ = service(audit, factory)
    assert operator_service.persist_receipt("TC", None, result) is result
    assert len(owned) == 1 and owned[0].open is False
    assert (history(connections, audit).receipt is not None) is committed
    reviewed, _ = service(audit, connections)
    assert reviewed.persist_receipt("TC", None, result).state == "RECEIPT_CAPTURED_OBSERVATION"
    transport.assert_called_once()


def test_revoked_permission_blocks_provider_before_any_database_acquisition(connections, audit, recovery_operator):
    prepare_sources(connections, recovery_operator)
    result, transport = uncertain(connections, audit)
    factory = Mock(side_effect=AssertionError("No SQL after denied ACL"))
    operator_service, provider = service(audit, factory)
    recovery_operator.denied_operations.add(("Company", "SOURCE", "write"))
    with pytest.raises(PermissionDenied, match=access.DENIED_MESSAGE):
        operator_service.persist_receipt("TC", None, result)
    provider.assert_not_called()
    factory.assert_not_called()
    assert history(connections, audit).receipt is None
    transport.assert_called_once()


def test_revocation_after_append_rolls_back_the_owned_transaction(connections, audit, recovery_operator):
    prepare_sources(connections, recovery_operator)
    result, transport = uncertain(connections, audit)
    def factory():
        database = connections()
        original_cursor = database.cursor
        def cursor(*args, **kwargs):
            sql_cursor = original_cursor(*args, **kwargs)
            execute = sql_cursor.execute
            def query(statement, values=None):
                returned = execute(statement, values)
                if statement.startswith("INSERT INTO zatca_compliance_archive_v1"):
                    recovery_operator.denied_operations.add(("Company", "SOURCE", "write"))
                return returned
            sql_cursor.execute = query
            return sql_cursor
        database.cursor = cursor
        return database
    operator_service, _ = service(audit, factory)
    with pytest.raises(PermissionDenied, match=access.DENIED_MESSAGE):
        operator_service.persist_receipt("TC", None, result)
    assert history(connections, audit).receipt is None
    transport.assert_called_once()


def test_revocation_on_close_does_not_undo_commit_or_disclose_protected_result(connections, audit, recovery_operator):
    prepare_sources(connections, recovery_operator)
    result, transport = uncertain(connections, audit)
    def factory():
        database = connections()
        close = database.close
        def release():
            close()
            recovery_operator.denied_operations.add(("Company", "SOURCE", "write"))
        database.close = release
        return database
    operator_service, _ = service(audit, factory)
    with pytest.raises(PermissionDenied, match=access.DENIED_MESSAGE):
        operator_service.persist_receipt("TC", None, result)
    assert history(connections, audit).receipt == result.observation
    transport.assert_called_once()


def test_saved_row_writer_waits_for_recovery_commit_then_is_released(connections, audit, recovery_operator, monkeypatch):
    prepare_sources(connections, recovery_operator)
    result, transport = uncertain(connections, audit)
    ready, done = Event(), Event()
    original_verify = source_access.verify_saved_source_rows
    futures = []
    def writer():
        database = connections()
        try:
            with database.cursor() as cursor:
                ready.set()
                cursor.execute("UPDATE `tabCompany` SET `modified`=DATE_ADD(`modified`, INTERVAL 1 SECOND) WHERE `name`=%s", ("SOURCE",))
            database.commit()
            done.set()
        finally:
            database.close()
    with ThreadPoolExecutor(max_workers=1) as workers:
        def verify(connection, rows):
            answer = original_verify(connection, rows)
            if not futures:
                futures.append(workers.submit(writer))
                assert ready.wait(timeout=2) and not done.wait(timeout=0.1)
            return answer
        monkeypatch.setattr(source_access, "verify_saved_source_rows", verify)
        operator_service, _ = service(audit, connections)
        recovered = operator_service.persist_receipt("TC", None, result)
        assert recovered.state == "RECEIPT_CAPTURED_OBSERVATION"
        futures[0].result(timeout=5)
    assert done.is_set() and history(connections, audit).receipt == result.observation
    transport.assert_called_once()
