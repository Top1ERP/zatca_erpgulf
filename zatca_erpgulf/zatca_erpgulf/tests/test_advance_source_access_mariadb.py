"""Saved-row locks and metadata inspection on OWNED synthetic private SQL."""

from dataclasses import replace
import os
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import advance_source_access as access
from zatca_erpgulf.zatca_erpgulf.journal_repository import MariaDBJournalRepository
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_dispatch_journal import start
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections, namespace
from zatca_erpgulf.zatca_erpgulf.tests.test_advance_source_access import operator, scenario, InspectionFailed, NOW
from zatca_erpgulf.zatca_erpgulf.tests.test_advance_source_selection_mariadb import store


pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="Owned guarded private SQL only; no tenant or authority request")


@pytest.fixture(scope="module")
def source_schema(isolated_server):
    import pymysql
    connection = pymysql.connect(unix_socket=isolated_server[0], user="root",
        database="zatca_journal_rehearsal", autocommit=True)
    try:
        with connection.cursor() as cursor:
            for dt, fields in access.FIELDS.items():
                if dt == "Sales Invoice":
                    fields += access.MARKERS
                numeric = ("docstatus", "custom_zatca_icv", *access.MARKERS, "custom__use_company_certificate__keys")
                columns = ["`name` VARCHAR(140) PRIMARY KEY", "`modified` DATETIME(6) NOT NULL"]
                columns += ["`" + name + "` " + ("BIGINT" if name in numeric else "LONGTEXT") for name in fields]
                # Names/columns are fixed internal test constants, never user input.
                cursor.execute("CREATE TABLE `tab" + dt + "` (" + ",".join(columns) + ") ENGINE=InnoDB")
    finally:
        connection.close()


def prepare_sources(connections, operator):
    connection = connections()
    try:
        with connection.cursor() as cursor:
            for doc in operator.documents.values():
                row = access._SavedRow.from_document(doc)
                fields = ("name", "modified", *row.fields)
                cursor.execute("INSERT INTO `tab" + row.doctype + "` ("
                    + ",".join("`" + name + "`" for name in fields) + ") VALUES ("
                    + ",".join("%s" for _ in fields) + ") ON DUPLICATE KEY UPDATE "
                    + ",".join("`" + name + "`=VALUES(`" + name + "`)" for name in fields),
                    (row.name, NOW, *row.values))
        connection.commit()  # Only synthetic tables on the owned private server.
    finally:
        connection.close()


def native_case(operator, certificates, monkeypatch, connections, namespace, *, indicator="0200000", environment="Production", owner="company"):
    repository_class = MariaDBJournalRepository
    case = scenario(operator, certificates[0], monkeypatch, indicator=indicator, environment=environment, owner=owner)
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
    case.service = access.ArchivedAdvanceInspectionService(case.scope, case.lookup, case.factory)
    monkeypatch.setattr(access, "MariaDBJournalRepository", repository_class)
    case.opened = opened
    prepare_sources(connections, operator)
    return case


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("owner", ["company", "device", "linked"])
def test_owned_committed_selection_with_actual_source_and_archive_locks(source_schema, connections, namespace, operator, certificates, monkeypatch, environment, indicator, owner):
    case = native_case(operator, certificates, monkeypatch, connections, namespace,
                       environment=environment, indicator=indicator, owner=owner)
    writer = connections()
    store(writer, namespace, case.journal)
    writer.close()
    report = case.service.inspect("INV-TEST")
    assert report["source_kind"] == ("CLEARANCE_RETURNED_XML" if indicator.startswith("01") else "REPORTING_REQUEST_XML")
    assert len(case.opened) == 1 and case.opened[0].open is False
    assert all(value is False for name, value in report.items() if name.endswith(("_verified", "_authorized")))
    operator.runtime.db.commit.assert_not_called()
    operator.runtime.db.rollback.assert_not_called()
    verify = connections()
    assert MariaDBJournalRepository(verify, namespace).load(case.original.key_sha256).journal_sha256 == case.journal.journal_sha256
    verify.rollback()
    verify.close()


@pytest.mark.parametrize("change", ["revision", "uuid", "name_case"])
def test_actual_source_edit_cannot_be_hidden_by_stale_ambient_document(source_schema, connections, namespace, operator, certificates, monkeypatch, change):
    case = native_case(operator, certificates, monkeypatch, connections, namespace)
    writer = connections()
    store(writer, namespace, case.journal)
    with writer.cursor() as cursor:
        if change == "revision":
            cursor.execute("UPDATE `tabSales Invoice` SET modified=DATE_ADD(modified, INTERVAL 1 SECOND) WHERE name=%s", ("INV-TEST",))
        elif change == "uuid":
            cursor.execute("UPDATE `tabSales Invoice` SET custom_uuid=%s WHERE name=%s", ("01234567-1234-4123-8123-123456789abc", "INV-TEST"))
        else:
            cursor.execute("UPDATE `tabSales Invoice` SET name=%s WHERE name=%s", ("inv-test", "INV-TEST"))
    writer.commit()
    writer.close()
    constructor = Mock(wraps=MariaDBJournalRepository)
    monkeypatch.setattr(access, "MariaDBJournalRepository", constructor)
    with pytest.raises(InspectionFailed, match=access.FAILED_MESSAGE):
        case.service.inspect("INV-TEST")
    constructor.assert_not_called()  # Source locks/checks precede archive access.
    assert case.opened[0].open is False


def test_initial_owned_rollback_discards_uncommitted_receipt_before_inspection(source_schema, connections, namespace, operator, certificates, monkeypatch):
    case = native_case(operator, certificates, monkeypatch, connections, namespace)
    started = start(case.original)
    writer = connections()
    store(writer, namespace, started)
    repository = MariaDBJournalRepository(writer, namespace)
    repository.append(case.original.key_sha256, case.journal.events[-1], expected_journal_sha256=started.journal_sha256)
    # Deliberately supply an owned handle carrying an uncommitted observation.
    # The service rolls it back BEFORE source/journal reads; no false durability.
    case.factory.side_effect = None
    case.factory.return_value = writer
    with pytest.raises(InspectionFailed, match=access.FAILED_MESSAGE):
        case.service.inspect("INV-TEST")
    assert writer.open is False
    reader = connections()
    assert MariaDBJournalRepository(reader, namespace).load(case.original.key_sha256).journal_sha256 == started.journal_sha256
    reader.rollback()
    reader.close()


def test_uncommitted_source_edit_is_discarded_not_saved_by_read_service(source_schema, connections, namespace, operator, certificates, monkeypatch):
    case = native_case(operator, certificates, monkeypatch, connections, namespace)
    writer = connections()
    store(writer, namespace, case.journal)
    with writer.cursor() as cursor:
        cursor.execute("UPDATE `tabCompany` SET tax_id=%s WHERE name=%s", ("PRIVATE-UNCOMMITTED-TAX", "TEST"))
    case.factory.side_effect = None
    case.factory.return_value = writer
    assert case.service.inspect("INV-TEST")["source_kind"] == "REPORTING_REQUEST_XML"
    assert writer.open is False
    reader = connections()
    with reader.cursor() as cursor:
        cursor.execute("SELECT tax_id FROM `tabCompany` WHERE name=%s", ("TEST",))
        assert cursor.fetchone() == (case.company.tax_id,)
    reader.rollback()
    reader.close()
