"""Explicit receipt persistence on our owned TCP-disabled private SQL only."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf.compliance_capture import ComplianceTransportResponse
from zatca_erpgulf.zatca_erpgulf.compliance_receipt_recovery import ComplianceReceiptRecovery
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_archive_mariadb import (
    isolated_server, connections, install_private_bundle_schema, install_private_archive_schema,
    context, materials, audit, read,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_capture_mariadb import coordinator, collect
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_evidence import response


pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
                               reason="Only the guarded owned private server; no tenant DB or HTTP")


def uncertain(connections, audit, *, committed=False):
    owned = []
    def factory():
        database = connections()
        owned.append(database)
        if len(owned) == 2:
            commit = database.commit
            def ambiguous():
                if committed:
                    commit()
                raise RuntimeError("PRIVATE-SECRET lost receipt commit acknowledgement")
            database.commit = ambiguous
        return database
    transport = Mock(return_value=ComplianceTransportResponse(200, json.dumps(response()).encode()))
    result = collect(coordinator(audit, factory, transport), audit)
    assert result.state == "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY"
    assert all(database.open is False for database in owned)
    return result, transport


def recovery(audit, factory):
    return ComplianceReceiptRecovery(*audit[:3], connection_factory=factory)


def history(connections, audit):
    database = connections()
    try:
        return read(database, audit[8], audit[3], audit[4].exchange_id)
    finally:
        database.close()


@pytest.mark.parametrize("committed", [False, True])
def test_exact_uncertain_receipt_recovers_and_can_be_explicitly_redelivered_without_http(connections, audit, monkeypatch, committed):
    result, transport = uncertain(connections, audit, committed=committed)
    monkeypatch.setattr(audit[2], "seal", Mock(side_effect=AssertionError("No resealing")))
    owned = []
    def factory():
        database = connections()
        owned.append(database)
        return database
    service = recovery(audit, factory)
    recovered = service.persist_receipt(result)
    assert recovered == replace(result, state="RECEIPT_CAPTURED_OBSERVATION")
    assert recovered.receipt_envelope is result.receipt_envelope
    assert history(connections, audit).receipt == result.observation
    assert service.persist_receipt(result) == recovered
    assert len(owned) == 2 and all(database.open is False for database in owned)
    transport.assert_called_once()
    assert recovered.diagnostic_projection()["activation_authorized"] is False


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
def test_competing_explicit_recoveries_store_only_the_identical_ciphertext(connections, audit, isolation):
    result, transport = uncertain(connections, audit)
    services = [recovery(audit, lambda: connections(isolation)) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(service.persist_receipt, result) for service in services]
        recovered = [future.result(timeout=10) for future in futures]
    assert all(item.state == "RECEIPT_CAPTURED_OBSERVATION" for item in recovered)
    database = connections()
    try:
        with database.cursor() as cursor:
            cursor.execute("SELECT nonce,ciphertext FROM zatca_compliance_archive_v1 WHERE storage_namespace=%s AND exchange_id=%s AND sequence=2",
                           (audit[0], result.exchange_id))
            assert cursor.fetchall() == ((result.receipt_envelope.nonce, result.receipt_envelope.ciphertext),)
    finally:
        database.rollback()
        database.close()
    transport.assert_called_once()


@pytest.mark.parametrize("fault", ["missing_start", "resealed_start", "corrupt_start", "resealed_receipt", "corrupt_bundle"])
def test_existing_missing_or_conflicting_rows_are_not_repaired_overwritten_or_dispatched(connections, audit, fault):
    result, transport = uncertain(connections, audit)
    database = connections()
    try:
        with database.cursor() as cursor:
            if fault == "missing_start":
                cursor.execute("DELETE FROM zatca_compliance_archive_v1 WHERE storage_namespace=%s AND exchange_id=%s AND sequence=1",
                               (audit[0], result.exchange_id))
            elif fault == "resealed_receipt":
                sealed = audit[2].seal(result.observation, sequence=2, key_id="audit-test")
                audit[8](database).append_receipt(sealed)
            else:
                sealed = result.start_envelope if fault != "corrupt_bundle" else audit[3]
                if fault == "resealed_start":
                    sealed = audit[2].seal(audit[2].open(sealed), sequence=1, key_id="audit-test")
                content = sealed.ciphertext
                if fault.startswith("corrupt"):
                    content = content[:-1] + bytes([content[-1] ^ 1])
                if fault == "corrupt_bundle":
                    cursor.execute("UPDATE zatca_credential_bundle_v1 SET ciphertext=%s WHERE storage_namespace=%s AND version_id=%s",
                                   (content, audit[0], result.version_id))
                else:
                    cursor.execute("UPDATE zatca_compliance_archive_v1 SET nonce=%s,ciphertext=%s WHERE storage_namespace=%s AND exchange_id=%s AND sequence=1",
                                   (sealed.nonce, content, audit[0], result.exchange_id))
        database.commit()  # Synthetic corruption/deletion on OWNED scratch SQL.
        with database.cursor() as cursor:
            cursor.execute("SELECT sequence,nonce,ciphertext FROM zatca_compliance_archive_v1 WHERE storage_namespace=%s AND exchange_id=%s ORDER BY sequence",
                           (audit[0], result.exchange_id))
            before = cursor.fetchall()
        database.rollback()
        assert recovery(audit, connections).persist_receipt(result) is result
        with database.cursor() as cursor:
            cursor.execute("SELECT sequence,nonce,ciphertext FROM zatca_compliance_archive_v1 WHERE storage_namespace=%s AND exchange_id=%s ORDER BY sequence",
                           (audit[0], result.exchange_id))
            assert cursor.fetchall() == before
    finally:
        database.rollback()
        database.close()
    transport.assert_called_once()


@pytest.mark.parametrize("committed", [False, True])
def test_recovery_commit_uncertainty_retains_the_original_then_explicitly_reconciles(connections, audit, committed):
    result, transport = uncertain(connections, audit)
    owned = []
    def factory():
        database = connections()
        owned.append(database)
        commit = database.commit
        def ambiguous():
            if committed:
                commit()
            raise RuntimeError("PRIVATE-SECRET recovery commit unknown")
        database.commit = ambiguous
        return database
    assert recovery(audit, factory).persist_receipt(result) is result
    assert len(owned) == 1 and owned[0].open is False
    assert (history(connections, audit).receipt is not None) is committed
    assert recovery(audit, connections).persist_receipt(result).state == "RECEIPT_CAPTURED_OBSERVATION"
    assert history(connections, audit).receipt == result.observation
    transport.assert_called_once()


def test_owned_process_crash_during_recovery_leaves_only_the_spent_start(connections, audit, isolated_server):
    result, transport = uncertain(connections, audit)
    def factory():
        database = connections()
        def interrupted_commit():
            isolated_server[2]()  # Stop/restart ONLY this fixture's owned process.
            raise RuntimeError("PRIVATE-SECRET recovery commit interrupted")
        database.commit = interrupted_commit
        return database
    assert recovery(audit, factory).persist_receipt(result) is result
    assert history(connections, audit).receipt is None
    recovered = recovery(audit, connections).persist_receipt(result)
    assert recovered.state == "RECEIPT_CAPTURED_OBSERVATION"
    assert history(connections, audit).receipt == result.observation
    transport.assert_called_once()


def test_autocommit_handle_is_rejected_and_closed_without_any_receipt(connections, audit):
    result, transport = uncertain(connections, audit)
    owned = []
    def factory():
        database = connections()
        database.autocommit(True)  # Deliberately invalid TEST dependency.
        owned.append(database)
        return database
    assert recovery(audit, factory).persist_receipt(result) is result
    assert len(owned) == 1 and owned[0].open is False
    assert history(connections, audit).receipt is None
    transport.assert_called_once()
