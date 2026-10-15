"""Owned synthetic source/archive locks; no tenant, ORM, files or authority."""

from dataclasses import replace
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
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections, namespace
from zatca_erpgulf.zatca_erpgulf.tests.test_advance_source_selection_mariadb import store
from zatca_erpgulf.zatca_erpgulf.tests.test_qr_source_access import (
    operator, qr_operator, scenario, inspect, NOW, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf import primary_receipt_access as receipt_access
from zatca_erpgulf.zatca_erpgulf import primary_receipt_persistence as receipt_persistence
from zatca_erpgulf.zatca_erpgulf import primary_receipt_provider as receipt_provider
from zatca_erpgulf.zatca_erpgulf.tests.test_primary_receipt_access import (
    receipt_operator, scenario as receipt_scenario, persist as persist_receipt, PermissionDenied,
)


pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="Owned guarded private SQL only; no tenant or authority request")


@pytest.fixture(scope="module")
def qr_source_schema(isolated_server):
    import pymysql
    connection = pymysql.connect(unix_socket=isolated_server[0], user="root",
        database="zatca_journal_rehearsal", autocommit=True)
    try:
        with connection.cursor() as cursor:
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
