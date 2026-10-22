"""Owned synthetic source/archive locks; no tenant, ORM, files or authority."""

from dataclasses import replace
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import qr_source_access as access
from zatca_erpgulf.zatca_erpgulf.archive_source_access import SavedSourceRow
from zatca_erpgulf.zatca_erpgulf.journal_repository import MariaDBJournalRepository
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_dispatch_journal import start
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections, namespace, save
from zatca_erpgulf.zatca_erpgulf.tests.test_advance_source_selection_mariadb import store
from zatca_erpgulf.zatca_erpgulf.tests.test_qr_source_access import (
    operator, qr_operator, scenario, inspect, NOW, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf import primary_receipt_access as receipt_access
from zatca_erpgulf.zatca_erpgulf import primary_receipt_persistence as receipt_persistence
from zatca_erpgulf.zatca_erpgulf import primary_receipt_provider as receipt_provider
from zatca_erpgulf.zatca_erpgulf import primary_receipt_custody_access as custody_access
from zatca_erpgulf.zatca_erpgulf.primary_receipt_custody import MariaDBPrimaryReceiptCustodyRepository, PrimaryReceiptCustodyError
from zatca_erpgulf.zatca_erpgulf.tests.test_primary_receipt_custody_access import (
    custody_operator, configure as configure_custody, invoke as invoke_custody,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_primary_receipt_access import (
    receipt_operator, scenario as receipt_scenario, persist as persist_receipt, PermissionDenied,
)
from zatca_erpgulf.zatca_erpgulf import primary_capture_access as capture_access
from zatca_erpgulf.zatca_erpgulf import primary_capture
from zatca_erpgulf.zatca_erpgulf.primary_receipt_custody import PrimaryReceiptCustodyCipher
from zatca_erpgulf.zatca_erpgulf.tests.test_primary_capture import observed as primary_observed
from zatca_erpgulf.zatca_erpgulf.tests.test_primary_capture_access import (
    capture_operator, configure as configure_capture, invoke as invoke_capture,
)
from zatca_erpgulf.zatca_erpgulf import primary_reconciliation_access as pair_access
from zatca_erpgulf.zatca_erpgulf.tests.test_primary_reconciliation_access import (
    pair_operator, configure as configure_pair_access, invoke as invoke_pair_access,
)
from zatca_erpgulf.zatca_erpgulf import event_log
from zatca_erpgulf.zatca_erpgulf.tests.test_retained_event_access import diagnostic_operator
from zatca_erpgulf.zatca_erpgulf.tests.test_event_log_contract import writer


pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="Owned guarded private SQL only; no tenant or authority request")


@pytest.fixture(scope="module")
def qr_source_schema(isolated_server):
    import pymysql
    connection = pymysql.connect(unix_socket=isolated_server[0], user="root",
        database="zatca_journal_rehearsal", autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE diagnostic_access_test (namespace VARCHAR(36) PRIMARY KEY,payload LONGTEXT) ENGINE=InnoDB")
            for dt, fields in access.FIELDS.items():
                numeric = ("docstatus", "custom_zatca_icv", "custom__use_company_certificate__keys")
                columns = ["`name` VARCHAR(140) PRIMARY KEY", "`modified` DATETIME(6) NOT NULL"]
                columns += ["`" + name + "` " + ("BIGINT" if name in numeric else "LONGTEXT") for name in fields]
                cursor.execute("CREATE TABLE `tab" + dt + "` (" + ",".join(columns) + ") ENGINE=InnoDB")
    finally:
        connection.close()


def native_case(qr_operator, der, monkeypatch, connections, namespace, **options):
    repository_type = MariaDBJournalRepository
    case = scenario(qr_operator, der, monkeypatch, **options)
    case.scope = access.CredentialStorageScope("private.test", namespace)
    case.binding = replace(case.binding, scope=case.scope)
    case.lookup.return_value = case.binding
    opened = []
    def factory(scope):
        assert scope == case.scope
        connection = connections()
        opened.append(connection)
        return connection
    case.factory = Mock(side_effect=factory)
    case.service = access.ArchivedQRInspectionService(case.scope, case.lookup, case.factory)
    monkeypatch.setattr(access, "MariaDBJournalRepository", repository_type)
    case.opened = opened
    writer = connections()
    try:
        with writer.cursor() as cursor:
            for doc in qr_operator.documents.values():
                row = SavedSourceRow.from_document(doc)
                fields = ("name", "modified", *row.fields)
                cursor.execute("INSERT INTO `tab" + row.doctype + "` ("
                    + ",".join("`" + name + "`" for name in fields) + ") VALUES ("
                    + ",".join("%s" for _ in fields) + ") ON DUPLICATE KEY UPDATE "
                    + ",".join("`" + name + "`=VALUES(`" + name + "`)" for name in fields),
                    (row.name, NOW, *row.values))
        writer.commit()
    finally:
        writer.close()
    return case


def native_receipt_case(receipt_operator, der, monkeypatch, connections, namespace, **options):
    case = receipt_scenario(receipt_operator, der, monkeypatch, **options)
    case.scope = access.CredentialStorageScope("private.test", namespace)
    case.retained = replace(case.retained, storage_namespace=namespace)
    case.binding = replace(case.binding, scope=case.scope)
    case.lookup.return_value = case.binding
    case.invoice.custom_zatca_status = "Not Submitted"  # Storage must not require a false accepted label.
    case.opened = []
    def factory(scope):
        assert scope == case.scope
        connection = connections()
        case.opened.append(connection)
        return connection
    case.factory = Mock(side_effect=factory)
    case.service = receipt_access.SavedPrimaryReceiptService(case.scope, case.lookup, case.factory)
    monkeypatch.setattr(receipt_persistence, "MariaDBJournalRepository", MariaDBJournalRepository)
    writer = connections()
    try:
        with writer.cursor() as cursor:
            for doc in receipt_operator.documents.values():
                row = SavedSourceRow.from_document(doc)
                fields = ("name", "modified", *row.fields)
                cursor.execute("INSERT INTO `tab" + row.doctype + "` ("
                    + ",".join("`" + name + "`" for name in fields) + ") VALUES ("
                    + ",".join("%s" for _ in fields) + ") ON DUPLICATE KEY UPDATE "
                    + ",".join("`" + name + "`=VALUES(`" + name + "`)" for name in fields),
                    (row.name, NOW, *row.values))
        writer.commit()
        store(writer, namespace, case.before)
    finally:
        writer.close()
    return case


def read_primary_receipt_case(case, connections):
    reader = connections()
    try:
        return MariaDBJournalRepository(reader, case.scope.storage_namespace).load(case.original.key_sha256)
    finally:
        reader.rollback()
        reader.close()


def native_capture_case(capture_operator, der, monkeypatch, connections, namespace, isolated_server, **options):
    # Unlike native_receipt_case, capture MUST begin with an EMPTY journal.
    case = native_case(capture_operator, der, monkeypatch, connections, namespace, **options)
    pinned_receipt_provider(case, isolated_server, connections)
    writer = connections()
    try:
        case.empty = save(writer, namespace, case.original)
    finally:
        writer.close()
    def observe(request):
        assert case.pinned_opened and all(owned.closed for owned in case.pinned_opened)
        return primary_observed(request)  # Synthetic response only, no transport.
    case.observer = Mock(side_effect=observe)
    case.cipher = PrimaryReceiptCustodyCipher({"synthetic-capture-sql": b"S" * 32})
    configure_capture(case, case.cipher, case.observer, key_id="synthetic-capture-sql")
    return case


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("owner", ["company", "device", "linked"])
def test_permissioned_primary_capture_actual_owned_sql_retains_exact_result_and_only_discloses_metadata(
    qr_source_schema, capture_operator, certificates, monkeypatch, connections, namespace, isolated_server,
    doctype, indicator, owner):
    case = native_capture_case(capture_operator, certificates[0], monkeypatch, connections, namespace, isolated_server,
        doctype=doctype, indicator=indicator, owner=owner)
    report = invoke_capture(case)
    assert report["state"] == "RECEIPT_CAPTURED_OBSERVATION_NO_REPLAY"
    assert report["server_custody_acknowledged"] is True and report["server_custody_durable_verified"] is False
    result, = case.retained_results
    assert read_primary_receipt_case(case, connections) == primary_capture._validate_retained(result.receipt)
    assert read_custody_row(case, connections) == result.sealed
    assert case.cipher.open(result.sealed) == result.receipt
    assert not {"request", "response", "receipt", "sealed", "body", "uuid", "invoice_name"} & report.keys()
    assert len(case.pinned_opened) == 3 and all(owned.closed for owned in case.pinned_opened)
    assert case.credentials.call_count == 3
    case.observer.assert_called_once()
    capture_operator.runtime.db.commit.assert_not_called()
    capture_operator.runtime.db.rollback.assert_not_called()


@pytest.mark.parametrize("denied", ["source", "company", "device", "linked"])
def test_permissioned_primary_capture_actual_provider_acl_precedes_resources_and_credentials(qr_source_schema,
    capture_operator, certificates, monkeypatch, connections, namespace, isolated_server, denied):
    case = native_capture_case(capture_operator, certificates[0], monkeypatch, connections, namespace, isolated_server,
        owner="linked")
    capture_operator.denied_operations.add({"source": ("Sales Invoice", "INV-TEST", "write"),
        "company": ("Company", "TEST", "read"), "device": ("ZATCA Multiple Setting", "DEVICE", "read"),
        "linked": ("Company", "LINKED", "read")}[denied])
    with pytest.raises(PermissionDenied):
        invoke_capture(case)
    case.resources.assert_not_called()
    case.credentials.assert_not_called()
    case.observer.assert_not_called()
    case.retainer.assert_not_called()
    assert read_primary_receipt_case(case, connections) == case.empty


@pytest.mark.parametrize("stage", ["pre-observer-close", "observer", "receipt-close"])
def test_permissioned_primary_capture_actual_revocation_never_discards_result_or_undoes_history(qr_source_schema,
    capture_operator, certificates, monkeypatch, connections, namespace, isolated_server, stage):
    case = native_capture_case(capture_operator, certificates[0], monkeypatch, connections, namespace, isolated_server)
    def revoke():
        capture_operator.denied_operations.add(("Sales Invoice", "INV-TEST", "write"))
    if stage == "observer":
        original = case.observer.side_effect
        def observe(request):
            response = original(request)
            revoke()
            return response
        case.observer.side_effect = observe
    else:
        original = case.factory.side_effect
        def connect(scope):
            owned = original(scope)
            index = len(case.pinned_opened)
            def close():
                owned.close()
                if index == (2 if stage == "pre-observer-close" else 3):
                    revoke()
            return SimpleNamespace(cursor=owned.cursor, rollback=owned.rollback, commit=owned.commit, close=close)
        case.factory.side_effect = connect
    with pytest.raises(PermissionDenied) as error:
        invoke_capture(case)
    assert error.value.__context__ is None
    result, = case.retained_results
    assert all(owned.closed for owned in case.pinned_opened)
    if stage == "pre-observer-close":
        case.observer.assert_not_called()
        assert result.response is result.sealed is None
        assert read_primary_receipt_case(case, connections) == case.request.started
    else:
        case.observer.assert_called_once()
        assert result.response is not None and result.sealed is not None
        if stage == "receipt-close":
            assert read_primary_receipt_case(case, connections) == primary_capture._validate_retained(result.receipt)
            assert read_custody_row(case, connections) == result.sealed
        else:
            assert read_primary_receipt_case(case, connections) == case.request.started
            with pytest.raises(PrimaryReceiptCustodyError, match="receipt_custody_missing"):
                read_custody_row(case, connections)


@pytest.mark.parametrize("interrupted", [False, True])
def test_permissioned_primary_capture_actual_handoff_failure_transfers_protected_recovery_not_automatic_replay(
    qr_source_schema, capture_operator, certificates, monkeypatch, connections, namespace, isolated_server, interrupted):
    case = native_capture_case(capture_operator, certificates[0], monkeypatch, connections, namespace, isolated_server)
    case.retainer.side_effect = KeyboardInterrupt("PRIVATE interrupted custody") if interrupted else RuntimeError("PRIVATE custody failure")
    with pytest.raises(capture_access.PrimaryCaptureHandoffRequired) as error:
        invoke_capture(case)
    result = error.value.result
    assert error.value.interrupted is interrupted and error.value.__context__ is None
    assert str(error.value) == capture_access.HANDOFF_MESSAGE
    assert read_primary_receipt_case(case, connections) == primary_capture._validate_retained(result.receipt)
    assert read_custody_row(case, connections) == result.sealed
    case.observer.assert_called_once()
    case.retainer.assert_called_once_with(case.scope, result)
    assert all(owned.closed for owned in case.pinned_opened)


def test_permissioned_primary_capture_actual_saved_sql_drift_blocks_reservation_and_observation(qr_source_schema,
    capture_operator, certificates, monkeypatch, connections, namespace, isolated_server):
    case = native_capture_case(capture_operator, certificates[0], monkeypatch, connections, namespace, isolated_server)
    writer = connections()
    try:
        with writer.cursor() as cursor:
            cursor.execute("UPDATE `tabSales Invoice` SET custom_uuid=%s WHERE name='INV-TEST'", (str(uuid4()),))
        writer.commit()  # Owned synthetic row only; ambient fake Frappe remains stale.
    finally:
        writer.close()
    report = invoke_capture(case)
    assert report["state"] == "RESERVATION_UNCONFIRMED_NO_OBSERVER"
    result, = case.retained_results
    assert result.response is result.sealed is None
    case.observer.assert_not_called()
    assert read_primary_receipt_case(case, connections) == case.empty
    assert all(owned.closed for owned in case.pinned_opened)


@pytest.fixture
def reconciliation_operator(capture_operator, pair_operator):
    # Both saved-source facades share the SAME synthetic permission operator.
    return pair_operator


def native_pair_access_case(reconciliation_operator, der, monkeypatch, connections, namespace, isolated_server, **options):
    case = native_capture_case(reconciliation_operator, der, monkeypatch, connections, namespace, isolated_server, **options)
    original = case.factory.side_effect
    def acquire(scope):
        owned = original(scope)
        if len(case.pinned_opened) == 3:
            def uncommitted():
                raise RuntimeError("PRIVATE synthetic receipt commit unavailable")
            return SimpleNamespace(cursor=owned.cursor, rollback=owned.rollback, close=owned.close, commit=uncommitted)
        return owned
    case.factory.side_effect = acquire
    assert invoke_capture(case)["state"] == "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY"
    case.captured, = case.retained_results
    case.factory.side_effect = original
    case.factory.reset_mock()
    case.credentials.reset_mock()
    configure_pair_access(case, case.captured.request, case.captured.sealed, case.cipher)
    return case


@pytest.mark.parametrize("stage", ["none", "before_insert", "after_insert"])
@pytest.mark.parametrize("target", ["source", "company", "device"])
@pytest.mark.parametrize("parent_commit", [False, True])
def test_diagnostic_fresh_owned_checks_detect_sql_drift_hidden_by_ambient_saved_documents(qr_source_schema,
    reconciliation_operator, diagnostic_operator, certificates, monkeypatch, connections, namespace, isolated_server,
    stage, target, parent_commit):
    op = diagnostic_operator
    assert op.source is reconciliation_operator
    case = native_pair_access_case(reconciliation_operator, certificates[0], monkeypatch, connections, namespace,
        isolated_server, owner="linked")
    assert invoke_pair_access(case, "persist")["state"] == "PAIR_STORED_OBSERVATION_NO_REPLAY"
    before_journal, before_sealed = read_primary_receipt_case(case, connections), read_custody_row(case, connections)
    case.factory.reset_mock()
    parent = connections()
    # Deliberately DO NOT mutate the synthetic ORM document. Fresh locking SQL,
    # rather than an ambient repeatable-read/cached document, must detect drift.
    dt, name, column, value = {
        "source": (case.invoice.doctype, case.invoice.name, "modified", "2026-10-21 12:00:00.000000"),
        "company": ("Company", "TEST", "tax_id", "CHANGED-SYNTHETIC-VAT"),
        "device": ("ZATCA Multiple Setting", "DEVICE", "custom_linked_doctype", "OTHER-COMPANY"),
    }[target]
    def drift():
        changed = connections()
        try:
            with changed.cursor() as cursor:
                # Identifiers come from the fixed map above, never caller text.
                cursor.execute("UPDATE `tab" + dt + "` SET `" + column + "`=%s WHERE name=%s", (value, name))
                assert cursor.rowcount == 1
            changed.commit()
        finally:
            changed.close()
    original_get = op.writer.runtime.get_doc.return_value
    def make_event(payload):
        if stage == "before_insert":
            drift()
        return original_get
    op.writer.runtime.get_doc.side_effect = make_event
    def insert(**options):
        assert options == {"ignore_permissions": False}
        assert all(owned.closed for owned in case.pinned_opened)
        with parent.cursor() as cursor:
            cursor.execute("INSERT INTO diagnostic_access_test VALUES (%s,%s)",
                (namespace, json.dumps(op.writer.runtime.get_doc.call_args.args[0])))
        if stage == "after_insert":
            drift()
    op.writer.doc.insert.side_effect = insert
    def read_event():
        probe = connections()
        try:
            with probe.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM diagnostic_access_test WHERE namespace=%s", (namespace,))
                return cursor.fetchone()[0]
        finally:
            probe.rollback()
            probe.close()
    try:
        if stage == "none":
            report = invoke_pair_access(case, "stage_diagnostic")
            assert report["state"] == "DIAGNOSTIC_INSERT_RETURNED_OBSERVATION_NO_REPLAY"
            assert all(value is False for key, value in report.items() if key != "state")
            assert case.factory.call_count == 3
        else:
            with pytest.raises(pair_access.PrimaryDiagnosticReviewError) as raised:
                invoke_pair_access(case, "stage_diagnostic")
            assert raised.value.__context__ is None and not vars(raised.value)
        assert op.writer.doc.insert.call_count == (stage != "before_insert")
        assert read_event() == 0
        assert read_primary_receipt_case(case, connections) == before_journal
        assert read_custody_row(case, connections) == before_sealed
        (parent.commit if parent_commit else parent.rollback)()
    finally:
        parent.rollback()
        parent.close()
    assert read_event() == (parent_commit and stage != "before_insert")
    assert all(owned.closed for owned in case.pinned_opened)
    op.writer.runtime.db.commit.assert_not_called()
    op.writer.runtime.db.rollback.assert_not_called()
    reconciliation_operator.runtime.db.commit.assert_not_called()
    reconciliation_operator.runtime.db.rollback.assert_not_called()
    case.observer.assert_called_once()  # Fixture's original synthetic response only.


def assert_pair_access_missing(case, connections):
    assert read_primary_receipt_case(case, connections) == case.request.started
    with pytest.raises(PrimaryReceiptCustodyError, match="receipt_custody_missing"):
        read_custody_row(case, connections)


@pytest.mark.parametrize("operation", ["inspect", "persist"])
@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("owner", ["company", "device", "linked"])
def test_permissioned_pair_actual_pinned_provider_source_locks_and_metadata_only(qr_source_schema,
    reconciliation_operator, certificates, monkeypatch, connections, namespace, isolated_server, operation, doctype, indicator, owner):
    case = native_pair_access_case(reconciliation_operator, certificates[0], monkeypatch, connections, namespace, isolated_server,
        doctype=doctype, indicator=indicator, owner=owner)
    report = invoke_pair_access(case, operation)
    assert report["state"] == ("PAIR_MISSING_OBSERVATION_NO_REPLAY" if operation == "inspect" else "PAIR_STORED_OBSERVATION_NO_REPLAY")
    if operation == "inspect":
        assert_pair_access_missing(case, connections)
    else:
        assert read_primary_receipt_case(case, connections) == primary_capture._validate_retained(case.captured.receipt)
        assert read_custody_row(case, connections) == case.sealed
    assert not {"request", "receipt", "response", "sealed", "body", "invoice_name", "uuid", "key_id"} & report.keys()
    assert all(value is False for key, value in report.items() if key.endswith(("_verified", "_authorized")))
    case.keys.assert_called_once_with(case.scope)
    case.credentials.assert_called_once_with(case.scope)
    case.factory.assert_called_once_with(case.scope)
    assert len(case.pinned_opened) == 4 and all(owned.closed for owned in case.pinned_opened)
    case.observer.assert_called_once()  # Initial SYNTHETIC capture only.
    reconciliation_operator.runtime.db.commit.assert_not_called()
    reconciliation_operator.runtime.db.rollback.assert_not_called()


@pytest.mark.parametrize("operation", ["inspect", "persist"])
@pytest.mark.parametrize("identity", ["source", "company", "device", "linked"])
def test_permissioned_pair_actual_acl_precedes_keys_and_concrete_provider_credentials(qr_source_schema,
    reconciliation_operator, certificates, monkeypatch, connections, namespace, isolated_server, operation, identity):
    case = native_pair_access_case(reconciliation_operator, certificates[0], monkeypatch, connections, namespace, isolated_server, owner="linked")
    reconciliation_operator.denied_operations.add({"source": ("Sales Invoice", "INV-TEST", "write"),
        "company": ("Company", "TEST", "read"), "device": ("ZATCA Multiple Setting", "DEVICE", "read"),
        "linked": ("Company", "LINKED", "read")}[identity])
    with pytest.raises(PermissionDenied):
        invoke_pair_access(case, operation)
    case.keys.assert_not_called()
    case.credentials.assert_not_called()
    case.factory.assert_not_called()
    assert_pair_access_missing(case, connections)


@pytest.mark.parametrize("operation", ["inspect", "persist"])
def test_permissioned_pair_actual_sql_drift_never_becomes_safe_absence_or_local_store(qr_source_schema,
    reconciliation_operator, certificates, monkeypatch, connections, namespace, isolated_server, operation):
    case = native_pair_access_case(reconciliation_operator, certificates[0], monkeypatch, connections, namespace, isolated_server)
    writer = connections()
    try:
        with writer.cursor() as cursor:
            cursor.execute("UPDATE `tabSales Invoice` SET custom_uuid=%s WHERE name='INV-TEST'", (str(uuid4()),))
        writer.commit()  # This test's new synthetic row only; fake Frappe remains stale.
    finally:
        writer.close()
    report = invoke_pair_access(case, operation)
    assert report["state"] == ("PAIR_INSPECTION_UNCONFIRMED_NO_REPLAY" if operation == "inspect" else "PAIR_PERSISTENCE_UNCONFIRMED_NO_REPLAY")
    assert_pair_access_missing(case, connections)
    assert all(owned.closed for owned in case.pinned_opened)


@pytest.mark.parametrize("operation", ["inspect", "persist"])
@pytest.mark.parametrize("stage", ["acquire", "last-guard", "close"])
def test_permissioned_pair_actual_late_acl_denial_preserves_originals_and_committed_history(qr_source_schema,
    reconciliation_operator, certificates, monkeypatch, connections, namespace, isolated_server, operation, stage):
    case = native_pair_access_case(reconciliation_operator, certificates[0], monkeypatch, connections, namespace, isolated_server)
    def revoke():
        reconciliation_operator.denied_operations.add(("Sales Invoice", "INV-TEST", "write"))
    if stage == "last-guard":
        original = pair_access._verify_rows
        calls = []
        def verify(connection, rows):
            original(connection, rows)
            calls.append(connection)
            if len(calls) == 2:
                revoke()
        monkeypatch.setattr(pair_access, "_verify_rows", verify)
    else:
        original = case.factory.side_effect
        def acquire(scope):
            owned = original(scope)
            if stage == "acquire":
                revoke()
                return owned
            def close():
                owned.close()
                revoke()
            return SimpleNamespace(cursor=owned.cursor, rollback=owned.rollback, commit=owned.commit, close=close)
        case.factory.side_effect = acquire
    with pytest.raises(PermissionDenied) as error:
        invoke_pair_access(case, operation)
    assert error.value.__context__ is None
    assert case.cipher.open(case.sealed) == case.captured.receipt
    if stage == "close" and operation == "persist":
        assert read_primary_receipt_case(case, connections) == primary_capture._validate_retained(case.captured.receipt)
        assert read_custody_row(case, connections) == case.sealed
    else:
        assert_pair_access_missing(case, connections)
    case.observer.assert_called_once()
    assert all(owned.closed for owned in case.pinned_opened)


@pytest.mark.parametrize("fault", ["commit-before", "commit-after", "close"])
def test_permissioned_pair_actual_uncertain_commit_returns_only_unconfirmed_metadata(qr_source_schema,
    reconciliation_operator, certificates, monkeypatch, connections, namespace, isolated_server, fault):
    case = native_pair_access_case(reconciliation_operator, certificates[0], monkeypatch, connections, namespace, isolated_server)
    original = case.factory.side_effect
    def acquire(scope):
        owned = original(scope)
        def commit():
            if fault == "commit-before":
                raise RuntimeError("PRIVATE before pair commit")
            owned.commit()
            if fault == "commit-after":
                raise RuntimeError("PRIVATE pair commit acknowledgment")
        def close():
            owned.close()
            if fault == "close":
                raise RuntimeError("PRIVATE close acknowledgment")
        return SimpleNamespace(cursor=owned.cursor, rollback=owned.rollback, commit=commit, close=close)
    case.factory.side_effect = acquire
    report = invoke_pair_access(case, "persist")
    assert report["state"] == "PAIR_PERSISTENCE_UNCONFIRMED_NO_REPLAY"
    assert "sealed" not in report and "request" not in report
    if fault == "commit-before":
        assert_pair_access_missing(case, connections)
    else:
        assert read_primary_receipt_case(case, connections) == primary_capture._validate_retained(case.captured.receipt)
        assert read_custody_row(case, connections) == case.sealed
    assert all(owned.closed for owned in case.pinned_opened)
    case.observer.assert_called_once()


@pytest.mark.parametrize("operation", ["inspect", "persist"])
@pytest.mark.parametrize("mode", ["custody-only", "journal-only", "different-seal"])
def test_permissioned_pair_actual_partial_or_changed_envelope_stays_review_only(qr_source_schema,
    reconciliation_operator, certificates, monkeypatch, connections, namespace, isolated_server, operation, mode):
    case = native_pair_access_case(reconciliation_operator, certificates[0], monkeypatch, connections, namespace, isolated_server)
    writer = connections()
    try:
        if mode == "journal-only":
            MariaDBJournalRepository(writer, namespace).append(case.original.key_sha256, case.captured.receipt.response_event,
                expected_journal_sha256=case.request.started.journal_sha256)
        else:
            selected = case.sealed if mode == "custody-only" else case.cipher.seal(case.captured.receipt, key_id=case.sealed.key_id)
            MariaDBPrimaryReceiptCustodyRepository(writer, namespace, case.cipher).stage(selected)
        writer.commit()  # Intentional separate synthetic legacy writer only.
    finally:
        writer.close()
    before = read_primary_receipt_case(case, connections)
    report = invoke_pair_access(case, operation)
    assert report["state"] == {"custody-only": "CUSTODY_ONLY_REVIEW_NO_REPLAY", "journal-only": "JOURNAL_ONLY_REVIEW_NO_REPLAY",
        "different-seal": "PAIR_CONFLICT_REVIEW_NO_REPLAY"}[mode]
    assert read_primary_receipt_case(case, connections) == before
    if mode == "journal-only":
        with pytest.raises(PrimaryReceiptCustodyError, match="receipt_custody_missing"):
            read_custody_row(case, connections)
    else:
        assert read_custody_row(case, connections) == selected
    case.observer.assert_called_once()


def native_custody_case(custody_operator, der, monkeypatch, connections, namespace, isolated_server, **options):
    case = native_receipt_case(custody_operator, der, monkeypatch, connections, namespace, **options)
    pinned_receipt_provider(case, isolated_server, connections)
    configure_custody(case)
    monkeypatch.setattr(custody_access, "MariaDBPrimaryReceiptCustodyRepository", MariaDBPrimaryReceiptCustodyRepository)
    return case


def read_custody_row(case, connections):
    reader = connections()
    try:
        return MariaDBPrimaryReceiptCustodyRepository(reader, case.scope.storage_namespace, case.cipher).load(
            case.original.key_sha256, case.binding.attempt_id)
    finally:
        reader.rollback()
        reader.close()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("owner", ["company", "device", "linked"])
def test_permissioned_custody_uses_actual_pinned_provider_and_two_separate_owned_transactions(qr_source_schema,
    custody_operator, certificates, monkeypatch, connections, namespace, isolated_server, doctype, indicator, owner):
    case = native_custody_case(custody_operator, certificates[0], monkeypatch, connections, namespace, isolated_server,
        doctype=doctype, indicator=indicator, owner=owner, unknown=True)
    stored = invoke_custody(case, "stage")
    recovered = invoke_custody(case, "load")
    assert stored.state == "CUSTODY_STORED_OBSERVATION_NO_REPLAY" and stored.sealed is case.sealed
    assert recovered.state == "CUSTODY_READ_OBSERVATION_NO_REPLAY" and recovered.sealed == case.sealed
    assert case.cipher.open(recovered.sealed) == case.retained
    assert read_primary_receipt_case(case, connections) == case.before  # Custody never appends journal receipts.
    assert len(case.pinned_opened) == 2 and all(owned.closed for owned in case.pinned_opened)
    assert case.pinned_opened[0]._session != case.pinned_opened[1]._session
    assert case.keys.call_count == case.credentials.call_count == 2
    assert all(value is False for key, value in recovered.diagnostic_projection().items() if key.endswith(("_verified", "_authorized")))
    custody_operator.runtime.db.commit.assert_not_called()
    custody_operator.runtime.db.rollback.assert_not_called()


@pytest.mark.parametrize("operation", ["stage", "load"])
@pytest.mark.parametrize("denied", ["source", "company"])
def test_permissioned_custody_actual_provider_denied_before_keys_or_sql(qr_source_schema, custody_operator, certificates,
    monkeypatch, connections, namespace, isolated_server, operation, denied):
    case = native_custody_case(custody_operator, certificates[0], monkeypatch, connections, namespace, isolated_server)
    custody_operator.denied_operations.add(("Sales Invoice", "INV-TEST", "write") if denied == "source" else ("Company", "TEST", "read"))
    with pytest.raises(PermissionDenied):
        invoke_custody(case, operation)
    case.keys.assert_not_called()
    case.factory.assert_not_called()
    case.credentials.assert_not_called()
    assert read_primary_receipt_case(case, connections) == case.before


@pytest.mark.parametrize("operation", ["stage", "load"])
def test_permissioned_custody_actual_saved_sql_drift_blocks_write_or_disclosure(qr_source_schema, custody_operator,
    certificates, monkeypatch, connections, namespace, isolated_server, operation):
    case = native_custody_case(custody_operator, certificates[0], monkeypatch, connections, namespace, isolated_server)
    if operation == "load":
        invoke_custody(case, "stage")
    writer = connections()
    try:
        with writer.cursor() as cursor:
            cursor.execute("UPDATE `tabSales Invoice` SET custom_uuid=%s WHERE name='INV-TEST'", (str(uuid4()),))
        writer.commit()  # Owned synthetic row only; ambient fake Frappe remains stale.
    finally:
        writer.close()
    if operation == "stage":
        result = invoke_custody(case, operation)
        assert result.state == "CUSTODY_COMMIT_UNCONFIRMED_NO_REPLAY" and result.sealed is case.sealed
        with pytest.raises(PrimaryReceiptCustodyError, match="receipt_custody_missing"):
            read_custody_row(case, connections)
    else:
        with pytest.raises(InspectionFailed):
            invoke_custody(case, operation)
        assert read_custody_row(case, connections) == case.sealed  # No cleanup/deletion on access denial.
    assert read_primary_receipt_case(case, connections) == case.before
    assert all(owned.closed for owned in case.pinned_opened)


@pytest.mark.parametrize("committed", [False, True])
def test_permissioned_custody_unknown_actual_commit_preserves_exact_envelope_for_local_redelivery(qr_source_schema,
    custody_operator, certificates, monkeypatch, connections, namespace, isolated_server, committed):
    case = native_custody_case(custody_operator, certificates[0], monkeypatch, connections, namespace, isolated_server)
    original = case.factory.side_effect
    commits = []
    def uncertain(scope):
        owned = original(scope)
        def commit():
            commits.append(owned)
            if committed:
                owned.commit()
            raise RuntimeError("PRIVATE synthetic unknown commit acknowledgment")
        return SimpleNamespace(cursor=owned.cursor, rollback=owned.rollback, close=owned.close, commit=commit)
    case.factory.side_effect = uncertain
    result = invoke_custody(case, "stage")
    assert result.state == "CUSTODY_COMMIT_UNCONFIRMED_NO_REPLAY" and result.sealed is case.sealed
    assert len(commits) == 1 and case.pinned_opened[0].closed
    case.factory.side_effect = original
    recovered = case.service.stage(case.invoice.name, result.sealed)
    assert recovered.state == "CUSTODY_STORED_OBSERVATION_NO_REPLAY" and recovered.sealed is case.sealed
    assert read_custody_row(case, connections) == case.sealed
    assert read_primary_receipt_case(case, connections) == case.before
    assert case.credentials.call_count == 2


@pytest.mark.parametrize("operation", ["stage", "load"])
def test_permissioned_custody_post_close_revocation_refuses_disclosure_without_undoing_history(qr_source_schema,
    custody_operator, certificates, monkeypatch, connections, namespace, isolated_server, operation):
    case = native_custody_case(custody_operator, certificates[0], monkeypatch, connections, namespace, isolated_server)
    if operation == "load":
        invoke_custody(case, "stage")
    original = case.factory.side_effect
    def revoking(scope):
        owned = original(scope)
        def close():
            owned.close()
            custody_operator.denied_operations.add(("Sales Invoice", "INV-TEST", "write"))
        return SimpleNamespace(cursor=owned.cursor, rollback=owned.rollback, close=close, commit=owned.commit)
    case.factory.side_effect = revoking
    with pytest.raises(PermissionDenied) as error:
        invoke_custody(case, operation)
    assert error.value.__context__ is None
    assert read_custody_row(case, connections) == case.sealed
    assert read_primary_receipt_case(case, connections) == case.before
    assert all(owned.closed for owned in case.pinned_opened)


def pinned_receipt_provider(case, isolated_server, connections, *, register=True):
    """Provision ONLY this owned synthetic server; no site/config discovery."""
    writer = connections()
    registration = str(uuid4())
    try:
        with writer.cursor() as cursor:
            cursor.execute("SELECT DATABASE(),@@server_id")
            database, server_id = cursor.fetchone()
            if register:
                cursor.execute("INSERT INTO zatca_receipt_storage_binding_v1 VALUES (%s,%s,%s)",
                    (case.scope.storage_namespace, case.scope.site, registration))
        writer.commit()
    finally:
        writer.close()
    observed = os.lstat(isolated_server[0])
    selected = receipt_provider.ReceiptDatabaseBinding(case.scope, isolated_server[0], observed.st_dev,
        observed.st_ino, observed.st_uid, database, server_id, registration)
    credentials = Mock(return_value=receipt_provider.ReceiptDatabaseCredentials("root", ""))
    concrete = receipt_provider.UnixPrimaryReceiptProvider(selected, credentials)
    opened = []
    def connect(scope):
        owned = concrete(scope)
        opened.append(owned)
        return owned
    factory = Mock(side_effect=connect)
    case.provider, case.provider_binding, case.credentials, case.pinned_opened = concrete, selected, credentials, opened
    case.factory = factory
    case.service = receipt_access.SavedPrimaryReceiptService(case.scope, case.lookup, factory)
    return case


def session_and_global_waits(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT @@session.innodb_lock_wait_timeout,@@session.lock_wait_timeout,"
            "@@global.innodb_lock_wait_timeout,@@global.lock_wait_timeout")
        return cursor.fetchone()


def test_provider_sets_only_owned_waits_and_never_global_or_control_session(qr_source_schema, receipt_operator,
    certificates, monkeypatch, connections, namespace, isolated_server):
    case = native_receipt_case(receipt_operator, certificates[0], monkeypatch, connections, namespace)
    pinned_receipt_provider(case, isolated_server, connections)
    control = connections()
    before = session_and_global_waits(control)
    owned = case.provider(case.scope)
    try:
        assert session_and_global_waits(owned) == (2, 2, *before[2:])
        assert session_and_global_waits(control) == before
    finally:
        owned.rollback()
        owned.close()
        control.rollback()
        control.close()
    assert read_primary_receipt_case(case, connections) == case.before
    case.credentials.assert_called_once()


@pytest.mark.parametrize("variable", ["innodb_lock_wait_timeout", "lock_wait_timeout"])
@pytest.mark.parametrize("operation", ["cursor", "commit"])
def test_actual_wait_drift_is_rejected_without_repair_or_reconnect(qr_source_schema, receipt_operator,
    certificates, monkeypatch, connections, namespace, isolated_server, variable, operation):
    case = native_receipt_case(receipt_operator, certificates[0], monkeypatch, connections, namespace)
    pinned_receipt_provider(case, isolated_server, connections)
    owned = case.provider(case.scope)
    try:
        with owned._raw.cursor() as cursor:  # Trusted fault injection on owned temporary SQL only.
            cursor.execute("SET SESSION " + variable + "=7")
        with pytest.raises(receipt_provider.ReceiptProviderError, match="^receipt_provider_check$"):
            getattr(owned, operation)()
        with pytest.raises(receipt_provider.ReceiptProviderError, match="^receipt_provider_unusable$"):
            owned.cursor()
        with owned._raw.cursor() as cursor:
            cursor.execute("SELECT @@session." + variable)
            assert cursor.fetchone() == (7,)  # Reject, do NOT silently reset/repair.
    finally:
        owned.rollback()
        owned.close()
    case.credentials.assert_called_once()
    assert read_primary_receipt_case(case, connections) == case.before


def test_registration_lock_times_out_during_acquisition_with_owned_cleanup_only(qr_source_schema, receipt_operator,
    certificates, monkeypatch, connections, namespace, isolated_server):
    case = native_receipt_case(receipt_operator, certificates[0], monkeypatch, connections, namespace)
    pinned_receipt_provider(case, isolated_server, connections)
    parent = connections()
    opened = []
    original_connect = receipt_provider.pymysql.connect
    def connect(**kwargs):
        raw = original_connect(**kwargs)
        raw.rollback = Mock(wraps=raw.rollback)
        raw.close = Mock(wraps=raw.close)
        raw.commit = Mock(wraps=raw.commit)
        opened.append(raw)
        return raw
    try:
        before_waits = session_and_global_waits(parent)
        with parent.cursor() as cursor:
            cursor.execute("SELECT site FROM zatca_receipt_storage_binding_v1 WHERE storage_namespace=%s FOR UPDATE", (namespace,))
            assert cursor.fetchone() == (case.scope.site,)
        with monkeypatch.context() as patch:
            patch.setattr(receipt_provider.pymysql, "connect", connect)
            with pytest.raises(receipt_provider.ReceiptProviderError, match="^receipt_provider_acquisition$") as raised:
                case.provider(case.scope)
        assert raised.value.__context__ is None
        assert len(opened) == 1 and not opened[0].open
        opened[0].rollback.assert_called_once()
        opened[0].close.assert_called_once()
        opened[0].commit.assert_not_called()
        assert parent.open and session_and_global_waits(parent) == before_waits
        with parent.cursor() as cursor:
            cursor.execute("SELECT site FROM zatca_receipt_storage_binding_v1 WHERE storage_namespace=%s", (namespace,))
            assert cursor.fetchone() == (case.scope.site,)
    finally:
        parent.rollback()
        parent.close()
    case.credentials.assert_called_once()
    assert read_primary_receipt_case(case, connections) == case.before


@pytest.mark.parametrize("parent_commit", [False, True])
def test_diagnostic_source_contention_times_out_without_parent_or_original_pair_mutation(qr_source_schema,
    reconciliation_operator, diagnostic_operator, certificates, monkeypatch, connections, namespace, isolated_server,
    parent_commit):
    op = diagnostic_operator
    assert op.source is reconciliation_operator
    case = native_pair_access_case(reconciliation_operator, certificates[0], monkeypatch, connections, namespace,
        isolated_server, owner="linked")
    assert invoke_pair_access(case, "persist")["state"] == "PAIR_STORED_OBSERVATION_NO_REPLAY"
    before_journal, before_sealed = read_primary_receipt_case(case, connections), read_custody_row(case, connections)
    case.factory.reset_mock()
    case.credentials.reset_mock()
    parent = connections()
    original_verify = pair_access._verify_rows
    codes = []
    def verify(connection, rows):
        try:
            return original_verify(connection, rows)
        except Exception as error:
            codes.append(error.args[0] if error.args else None)
            raise
    monkeypatch.setattr(pair_access, "_verify_rows", verify)
    try:
        before_waits = session_and_global_waits(parent)
        with parent.cursor() as cursor:
            cursor.execute("SELECT custom_zatca_status FROM `tabSales Invoice` WHERE name=%s FOR UPDATE", (case.invoice.name,))
            original_status, = cursor.fetchone()
            cursor.execute("UPDATE `tabSales Invoice` SET custom_zatca_status=%s WHERE name=%s", ("PARENT-PENDING", case.invoice.name))
        with pytest.raises(pair_access.PrimaryDiagnosticReviewError) as raised:
            invoke_pair_access(case, "stage_diagnostic")
        assert raised.value.__context__ is None and not vars(raised.value)
        assert codes == [1205]  # Server lock timeout, NOT socket-read timeout/reconnect.
        case.factory.assert_called_once_with(case.scope)
        case.credentials.assert_called_once_with(case.scope)
        op.writer.doc.insert.assert_not_called()
        assert all(owned.closed for owned in case.pinned_opened)
        assert read_primary_receipt_case(case, connections) == before_journal
        assert read_custody_row(case, connections) == before_sealed
        assert parent.open and session_and_global_waits(parent) == before_waits
        with parent.cursor() as cursor:
            cursor.execute("SELECT custom_zatca_status FROM `tabSales Invoice` WHERE name=%s", (case.invoice.name,))
            assert cursor.fetchone() == ("PARENT-PENDING",)  # No borrowed rollback/commit.
        (parent.commit if parent_commit else parent.rollback)()
    finally:
        parent.rollback()
        parent.close()
    probe = connections()
    try:
        with probe.cursor() as cursor:
            cursor.execute("SELECT custom_zatca_status FROM `tabSales Invoice` WHERE name=%s", (case.invoice.name,))
            assert cursor.fetchone() == ("PARENT-PENDING" if parent_commit else original_status,)
    finally:
        probe.rollback()
        probe.close()
    case.observer.assert_called_once()  # Initial synthetic setup only; never a new request.
    op.writer.runtime.db.commit.assert_not_called()
    op.writer.runtime.db.rollback.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("owner", ["company", "device", "linked"])
def test_concrete_unix_provider_safely_composes_with_permissioned_local_receipt_storage(qr_source_schema,
    receipt_operator, certificates, monkeypatch, connections, namespace, isolated_server, doctype, indicator, owner):
    case = native_receipt_case(receipt_operator, certificates[0], monkeypatch, connections, namespace,
        doctype=doctype, indicator=indicator, owner=owner, unknown=True)
    pinned_receipt_provider(case, isolated_server, connections)
    result = persist_receipt(case)
    assert result.state == "RECEIPT_STORED_OBSERVATION_NO_REPLAY" and result.receipt is case.retained
    assert read_primary_receipt_case(case, connections) == case.after
    assert len(case.pinned_opened) == 1 and case.pinned_opened[0].closed
    case.factory.assert_called_once_with(case.scope)
    case.credentials.assert_called_once_with(case.scope)
    receipt_operator.runtime.db.commit.assert_not_called()
    receipt_operator.runtime.db.rollback.assert_not_called()
    assert all(value is False for key, value in result.diagnostic_projection().items() if key.endswith(("_verified", "_authorized")))


@pytest.mark.parametrize("wrong", ["missing", "site", "registration", "inode"])
def test_concrete_provider_wrong_registration_or_endpoint_blocks_receipt_append(qr_source_schema,
    receipt_operator, certificates, monkeypatch, connections, namespace, isolated_server, wrong):
    case = native_receipt_case(receipt_operator, certificates[0], monkeypatch, connections, namespace)
    pinned_receipt_provider(case, isolated_server, connections, register=wrong != "missing")
    if wrong == "inode":
        case.provider = receipt_provider.UnixPrimaryReceiptProvider(replace(case.provider_binding,
            socket_inode=case.provider_binding.socket_inode + 1), case.credentials)
        case.service = receipt_access.SavedPrimaryReceiptService(case.scope, case.lookup, case.provider)
    elif wrong != "missing":
        writer = connections()
        try:
            with writer.cursor() as cursor:
                column, value = ("site", "other.test") if wrong == "site" else ("registration_id", str(uuid4()))
                cursor.execute("UPDATE zatca_receipt_storage_binding_v1 SET " + column + "=%s WHERE storage_namespace=%s",
                    (value, namespace))
            writer.commit()
        finally:
            writer.close()
    result = persist_receipt(case)
    assert result.state == "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY" and result.receipt is case.retained
    assert read_primary_receipt_case(case, connections) == case.before
    if wrong == "inode":
        case.credentials.assert_not_called()


@pytest.mark.parametrize("denied", ["source", "company"])
def test_concrete_provider_does_not_acquire_db_credentials_before_acl(qr_source_schema, receipt_operator, certificates,
    monkeypatch, connections, namespace, isolated_server, denied):
    case = native_receipt_case(receipt_operator, certificates[0], monkeypatch, connections, namespace)
    pinned_receipt_provider(case, isolated_server, connections)
    receipt_operator.denied_operations.add(("Sales Invoice", "INV-TEST", "write") if denied == "source" else ("Company", "TEST", "read"))
    with pytest.raises(PermissionDenied):
        persist_receipt(case)
    case.credentials.assert_not_called()
    case.factory.assert_not_called()
    assert read_primary_receipt_case(case, connections) == case.before


def test_concrete_provider_rejects_database_switch_after_handoff_without_reconnect(qr_source_schema, receipt_operator,
    certificates, monkeypatch, connections, namespace, isolated_server):
    case = native_receipt_case(receipt_operator, certificates[0], monkeypatch, connections, namespace)
    pinned_receipt_provider(case, isolated_server, connections)
    original = case.factory.side_effect
    def switch(scope):
        owned = original(scope)
        with owned._raw.cursor() as cursor:  # Deliberate trusted test fault injection, never an operator interface.
            cursor.execute("USE mysql")  # Same owned private server, not another tenant/server.
        return owned
    case.factory.side_effect = switch
    result = persist_receipt(case)
    assert result.state == "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY"
    assert read_primary_receipt_case(case, connections) == case.before
    case.credentials.assert_called_once()
    assert case.pinned_opened[0].closed


def test_concrete_provider_always_creates_new_sessions_and_never_revives_closed_handles(qr_source_schema,
    receipt_operator, certificates, monkeypatch, connections, namespace, isolated_server):
    case = native_receipt_case(receipt_operator, certificates[0], monkeypatch, connections, namespace)
    pinned_receipt_provider(case, isolated_server, connections)
    first = case.provider(case.scope)
    first_session = first._session
    first.rollback()
    first.close()
    second = case.provider(case.scope)
    try:
        assert second is not first and second._session != first_session
        with pytest.raises(receipt_provider.ReceiptProviderError, match="receipt_provider_unusable"):
            first.cursor()
    finally:
        second.rollback()
        second.close()
    assert case.credentials.call_count == 2


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("owner", ["company", "device", "linked"])
def test_permissioned_primary_receipt_source_locks_and_append_share_owned_transaction(qr_source_schema, receipt_operator,
    certificates, monkeypatch, connections, namespace, doctype, indicator, owner):
    case = native_receipt_case(receipt_operator, certificates[0], monkeypatch, connections, namespace,
        doctype=doctype, indicator=indicator, owner=owner)
    result = persist_receipt(case)
    assert result.state == "RECEIPT_STORED_OBSERVATION_NO_REPLAY" and result.receipt is case.retained
    assert read_primary_receipt_case(case, connections) == case.after
    assert len(case.opened) == 1 and not case.opened[0].open
    assert all(value is False for key, value in result.diagnostic_projection().items() if key.endswith(("_verified", "_authorized")))
    receipt_operator.runtime.db.commit.assert_not_called()
    receipt_operator.runtime.db.rollback.assert_not_called()
    assert case.invoice.custom_zatca_status == "Not Submitted"
    for doc in receipt_operator.documents.values():
        doc.save.assert_not_called()
        doc.db_set.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("change", ["revision", "uuid", "tax", "route"])
def test_stale_ambient_primary_source_blocks_sql_receipt_append(qr_source_schema, receipt_operator, certificates,
    monkeypatch, connections, namespace, doctype, change):
    case = native_receipt_case(receipt_operator, certificates[0], monkeypatch, connections, namespace, doctype=doctype)
    writer = connections()
    try:
        with writer.cursor() as cursor:
            if change == "revision":
                cursor.execute("UPDATE `tab" + doctype + "` SET modified=DATE_ADD(modified,INTERVAL 1 SECOND) WHERE name=%s", (case.invoice.name,))
            elif change == "uuid":
                cursor.execute("UPDATE `tab" + doctype + "` SET custom_uuid=%s WHERE name=%s",
                    ("50000000-0000-4000-8000-000000000001", case.invoice.name))
            elif change == "tax":
                cursor.execute("UPDATE `tabCompany` SET tax_id=%s WHERE name=%s", ("OTHER-TAX", "TEST"))
            else:
                cursor.execute("UPDATE `tabCompany` SET custom_production_url=%s WHERE name=%s", ("https://other.invalid/phase2", "TEST"))
        writer.commit()
    finally:
        writer.close()
    constructor = Mock(wraps=MariaDBJournalRepository)
    monkeypatch.setattr(receipt_persistence, "MariaDBJournalRepository", constructor)
    result = persist_receipt(case)
    assert result.state == "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY" and result.receipt is case.retained
    constructor.assert_not_called()
    assert read_primary_receipt_case(case, connections) == case.before
    assert not case.opened[0].open


@pytest.mark.parametrize("identity", [("Sales Invoice", "INV-TEST", "write"), ("Company", "TEST", "read"),
    ("ZATCA Multiple Setting", "DEVICE", "read"), ("Company", "LINKED", "read")])
def test_native_receipt_write_or_related_read_denial_acquires_no_connection(qr_source_schema, receipt_operator,
    certificates, monkeypatch, connections, namespace, identity):
    case = native_receipt_case(receipt_operator, certificates[0], monkeypatch, connections, namespace, owner="linked")
    receipt_operator.denied_operations.add(identity)
    with pytest.raises(PermissionDenied):
        persist_receipt(case)
    case.factory.assert_not_called()
    assert read_primary_receipt_case(case, connections) == case.before


@pytest.mark.parametrize("stage", ["after_append", "after_close"])
def test_native_primary_receipt_revocation_before_commit_or_after_close(qr_source_schema, receipt_operator,
    certificates, monkeypatch, connections, namespace, stage):
    case = native_receipt_case(receipt_operator, certificates[0], monkeypatch, connections, namespace)
    def revoke():
        receipt_operator.denied_operations.add(("Sales Invoice", "INV-TEST", "write"))
    if stage == "after_append":
        original = receipt_access._verify_rows
        calls = []
        def verify(connection, rows):
            original(connection, rows)
            calls.append(connection)
            if len(calls) == 2:
                revoke()
        monkeypatch.setattr(receipt_access, "_verify_rows", verify)
    else:
        original = case.factory.side_effect
        def factory(scope):
            connection = original(scope)
            def close():
                connection.close()
                revoke()
            return SimpleNamespace(cursor=connection.cursor, commit=connection.commit,
                rollback=connection.rollback, close=close)
        case.factory.side_effect = factory
    with pytest.raises(PermissionDenied) as error:
        persist_receipt(case)
    assert error.value.__context__ is None
    assert read_primary_receipt_case(case, connections) == (case.before if stage == "after_append" else case.after)
    assert len(case.opened) == 1 and not case.opened[0].open


def test_native_borrowed_parent_is_not_cleaned_or_committed(qr_source_schema, receipt_operator, certificates,
    monkeypatch, connections, namespace):
    case = native_receipt_case(receipt_operator, certificates[0], monkeypatch, connections, namespace)
    parent = connections()
    receipt_operator.runtime.db._conn = parent
    case.factory.side_effect, case.factory.return_value = None, parent
    try:
        with parent.cursor() as cursor:
            cursor.execute("UPDATE `tabCompany` SET tax_id=%s WHERE name=%s", ("PARENT-PENDING", "TEST"))
        result = persist_receipt(case)
        assert result.state == "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY" and parent.open
        with parent.cursor() as cursor:
            cursor.execute("SELECT tax_id FROM `tabCompany` WHERE name=%s", ("TEST",))
            assert cursor.fetchone() == ("PARENT-PENDING",)
        reader = connections("READ COMMITTED")
        try:
            with reader.cursor() as cursor:
                cursor.execute("SELECT tax_id FROM `tabCompany` WHERE name=%s", ("TEST",))
                assert cursor.fetchone() == (case.company.tax_id,)
        finally:
            reader.rollback()
            reader.close()
        assert read_primary_receipt_case(case, connections) == case.before
    finally:
        parent.rollback()
        parent.close()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("owner", ["company", "device", "linked"])
def test_actual_owned_source_and_archive_locks_metadata_only(qr_source_schema, qr_operator, certificates, monkeypatch, connections, namespace, doctype, indicator, owner):
    case = native_case(qr_operator, certificates[0], monkeypatch, connections, namespace,
        doctype=doctype, indicator=indicator, owner=owner)
    writer = connections()
    try:
        store(writer, namespace, case.journal)
    finally:
        writer.close()
    report = inspect(case)
    assert report["source_kind"] == ("CLEARANCE_RETURNED_XML" if indicator.startswith("01") else "REPORTING_REQUEST_XML")
    assert len(case.opened) == 1 and case.opened[0].open is False
    assert all(value is False for name, value in report.items() if name.endswith(("_verified", "_authorized")))
    qr_operator.runtime.db.commit.assert_not_called()
    qr_operator.runtime.db.rollback.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("change", ["revision", "uuid", "name_case", "tax"])
def test_stale_ambient_source_cannot_hide_actual_sql_edit(qr_source_schema, qr_operator, certificates, monkeypatch, connections, namespace, doctype, change):
    case = native_case(qr_operator, certificates[0], monkeypatch, connections, namespace, doctype=doctype)
    writer = connections()
    try:
        store(writer, namespace, case.journal)
        with writer.cursor() as cursor:
            if change == "tax":
                cursor.execute("UPDATE `tabCompany` SET tax_id=%s WHERE name=%s", ("OTHER-TAX", "TEST"))
            elif change == "revision":
                cursor.execute("UPDATE `tab" + doctype + "` SET modified=DATE_ADD(modified, INTERVAL 1 SECOND) WHERE name=%s", ("INV-TEST",))
            elif change == "uuid":
                cursor.execute("UPDATE `tab" + doctype + "` SET custom_uuid=%s WHERE name=%s", ("01234567-1234-4123-8123-123456789abc", "INV-TEST"))
            else:
                cursor.execute("UPDATE `tab" + doctype + "` SET name=%s WHERE name=%s", ("inv-test", "INV-TEST"))
        writer.commit()
    finally:
        writer.close()
    constructor = Mock(wraps=MariaDBJournalRepository)
    monkeypatch.setattr(access, "MariaDBJournalRepository", constructor)
    with pytest.raises(InspectionFailed, match=access.FAILED_MESSAGE):
        inspect(case)
    constructor.assert_not_called()
    assert case.opened[0].open is False


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("pending", ["receipt", "source"])
def test_owned_initial_rollback_discards_uncommitted_observations(qr_source_schema, qr_operator, certificates, monkeypatch, connections, namespace, doctype, pending):
    case = native_case(qr_operator, certificates[0], monkeypatch, connections, namespace, doctype=doctype)
    writer = connections()
    if pending == "receipt":
        initial = start(case.original)
        store(writer, namespace, initial)
        MariaDBJournalRepository(writer, namespace).append(case.original.key_sha256, case.journal.events[-1],
            expected_journal_sha256=initial.journal_sha256)
    else:
        store(writer, namespace, case.journal)
        with writer.cursor() as cursor:
            cursor.execute("UPDATE `tabCompany` SET tax_id=%s WHERE name=%s", ("PRIVATE-UNCOMMITTED", "TEST"))
    case.factory.side_effect, case.factory.return_value = None, writer
    if pending == "receipt":
        with pytest.raises(InspectionFailed, match=access.FAILED_MESSAGE):
            inspect(case)
    else:
        assert inspect(case)["recovery_authorized"] is False
    assert writer.open is False
    reader = connections()
    try:
        with reader.cursor() as cursor:
            cursor.execute("SELECT tax_id FROM `tabCompany` WHERE name=%s", ("TEST",))
            assert cursor.fetchone() == (case.company.tax_id,)
        loaded = MariaDBJournalRepository(reader, namespace).load(case.original.key_sha256)
        assert loaded.journal_sha256 == (initial.journal_sha256 if pending == "receipt" else case.journal.journal_sha256)
    finally:
        reader.rollback()
        reader.close()
