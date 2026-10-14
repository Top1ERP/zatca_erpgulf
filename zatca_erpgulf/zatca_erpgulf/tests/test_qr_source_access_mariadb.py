"""Owned synthetic source/archive locks; no tenant, ORM, files or authority."""

from dataclasses import replace
import os
from unittest.mock import Mock

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
