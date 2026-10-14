"""Actual owned InnoDB rollback/commit, fake Frappe File/image/notifications.

Not a restored application, filesystem rollback, client invoice or authority test.
"""

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import create_qr
from zatca_erpgulf.zatca_erpgulf.qr_attachment_policy import FILE_FIELDS, MAX_FILE_OBSERVATIONS
from zatca_erpgulf.zatca_erpgulf.tests.test_issue_timestamp_adapters import local_qr
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections, namespace
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import ValidationError
from zatca_erpgulf.zatca_erpgulf.tests.test_qr_attachment_policy import row as stored_row


pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="Owned private SQL only, no tenant or authority request")


@pytest.fixture(scope="module")
def qr_schema(isolated_server):
    import pymysql
    connection = pymysql.connect(unix_socket=isolated_server[0], user="root",
        database="zatca_journal_rehearsal", autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE qr_invoice_test (namespace VARCHAR(36),doctype VARCHAR(40),name VARCHAR(140),"
                "qr_url TEXT NULL,status VARCHAR(64),business_value TEXT,modified VARCHAR(30),"
                "PRIMARY KEY(namespace,doctype,name)) ENGINE=InnoDB")
            cursor.execute("CREATE TABLE qr_file_test (namespace VARCHAR(36),doctype VARCHAR(40),name VARCHAR(140),"
                "file_url TEXT, PRIMARY KEY(namespace,doctype,name)) ENGINE=InnoDB")
            cursor.execute("CREATE TABLE qr_attachment_test (namespace VARCHAR(36),name VARCHAR(140),file_name TEXT,"
                "file_url TEXT,attached_to_doctype VARCHAR(40),attached_to_name VARCHAR(140),attached_to_field VARCHAR(140),"
                "PRIMARY KEY(namespace,name)) ENGINE=InnoDB")
    finally:
        connection.close()


def prepare(local_qr, connections, namespace, doctype, *, failure=None):
    doc, runtime, payloads, _ = local_qr
    doc.doctype = doctype
    seed = connections()
    with seed.cursor() as cursor:
        cursor.execute("INSERT INTO qr_invoice_test VALUES (%s,%s,%s,NULL,%s,%s,%s)",
            (namespace, doctype, doc.name, "Not Submitted", "ORIGINAL-BUSINESS", "2026-10-01 00:00:00"))
    seed.commit()
    seed.close()
    transaction = connections()
    runtime.db.commit.side_effect = AssertionError("QR generator must not commit")
    runtime.db.rollback = Mock(side_effect=AssertionError("QR generator must not roll back"))
    file = runtime.get_doc({"doctype": "File"})
    runtime.get_doc.reset_mock()
    def file_save():
        with transaction.cursor() as cursor:
            cursor.execute("INSERT INTO qr_file_test VALUES (%s,%s,%s,%s)",
                (namespace, doctype, doc.name, file.file_url))
        if failure == "file":
            raise RuntimeError("SYNTHETIC file save failure after insert")
    file.save.side_effect = file_save
    def set_value(dt, name, fields, *, update_modified):
        assert dt == doctype and name == doc.name and update_modified is False
        assert set(fields) == {"ksa_einv_qr", "custom_zatca_status"}
        with transaction.cursor() as cursor:
            cursor.execute("UPDATE qr_invoice_test SET qr_url=%s,status=%s WHERE namespace=%s AND doctype=%s AND name=%s",
                (fields["ksa_einv_qr"], fields["custom_zatca_status"], namespace, dt, name))
            assert cursor.rowcount == 1
        if failure == "metadata":
            raise RuntimeError("SYNTHETIC metadata failure after update")
    runtime.db.set_value.side_effect = set_value
    if failure == "notify":
        doc.notify_update.side_effect = RuntimeError("SYNTHETIC notification failure")
    return SimpleNamespace(doc=doc, runtime=runtime, transaction=transaction, payloads=payloads)


def read_saved(connections, namespace, doctype, name):
    reader = connections("READ COMMITTED")
    try:
        with reader.cursor() as cursor:
            cursor.execute("SELECT qr_url,status,business_value,modified FROM qr_invoice_test "
                "WHERE namespace=%s AND doctype=%s AND name=%s", (namespace, doctype, name))
            row = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) FROM qr_file_test WHERE namespace=%s AND doctype=%s AND name=%s",
                (namespace, doctype, name))
            count = cursor.fetchone()[0]
        reader.rollback()
        return row, count
    finally:
        reader.close()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("commit", [False, True])
def test_caller_owns_file_and_metadata_visibility_and_final_transaction(qr_schema, local_qr, connections, namespace, doctype, commit):
    case = prepare(local_qr, connections, namespace, doctype)
    create_qr.create_qr_code(case.doc)
    before, files_before = read_saved(connections, namespace, doctype, case.doc.name)
    assert before == (None, "Not Submitted", "ORIGINAL-BUSINESS", "2026-10-01 00:00:00") and files_before == 0
    (case.transaction.commit if commit else case.transaction.rollback)()
    case.transaction.close()
    saved, files = read_saved(connections, namespace, doctype, case.doc.name)
    assert saved[:2] == (("/files/SYNTHETIC-QR.png", "Phase-1 QR Generated") if commit else (None, "Not Submitted"))
    assert saved[2:] == ("ORIGINAL-BUSINESS", "2026-10-01 00:00:00") and files == int(commit)
    case.runtime.db.commit.assert_not_called()
    case.runtime.db.rollback.assert_not_called()
    case.doc.save.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
def test_later_parent_failure_rolls_back_qr_and_its_other_work_together(qr_schema, local_qr, connections, namespace, doctype):
    case = prepare(local_qr, connections, namespace, doctype)
    with pytest.raises(RuntimeError, match="SYNTHETIC parent"):
        try:
            with case.transaction.cursor() as cursor:
                cursor.execute("UPDATE qr_invoice_test SET business_value=%s WHERE namespace=%s AND doctype=%s AND name=%s",
                    ("PARENT-PENDING", namespace, doctype, case.doc.name))
            create_qr.create_qr_code(case.doc)
            raise RuntimeError("SYNTHETIC parent validation failure AFTER QR")
        finally:
            case.transaction.rollback()  # Parent, not generator.
            case.transaction.close()
    saved, files = read_saved(connections, namespace, doctype, case.doc.name)
    assert saved == (None, "Not Submitted", "ORIGINAL-BUSINESS", "2026-10-01 00:00:00") and files == 0
    # In-memory QR may remain staged after rollback: caller must reload/discard.
    assert case.doc.ksa_einv_qr == "/files/SYNTHETIC-QR.png"


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("failure", ["file", "metadata", "notify"])
def test_propagated_failure_allows_parent_rollback_no_half_saved_qr(qr_schema, local_qr, connections, namespace, doctype, failure):
    case = prepare(local_qr, connections, namespace, doctype, failure=failure)
    with pytest.raises(RuntimeError, match="SYNTHETIC"):
        try:
            create_qr.create_qr_code(case.doc)
        finally:
            case.transaction.rollback()
            case.transaction.close()
    saved, files = read_saved(connections, namespace, doctype, case.doc.name)
    assert saved[:2] == (None, "Not Submitted") and files == 0
    case.runtime.db.commit.assert_not_called()
    case.doc.save.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("scenario", ["preserve", "orphan", "dangling", "foreign_url"])
def test_actual_scoped_file_query_preserves_rows_and_reference_without_cleanup(qr_schema, local_qr, connections, namespace, doctype, scenario):
    case = prepare(local_qr, connections, namespace, doctype)
    owned = stored_row(doctype=doctype)
    newer = stored_row("FILE-NEW", "/files/NEW.png", "QR-Phase1-NEW.png", doctype=doctype)
    rows = [owned, newer] if scenario in ("preserve", "orphan") else []
    if scenario == "foreign_url":
        rows = [stored_row("FOREIGN", doctype=doctype, invoice="OTHER-INVOICE")]
    current = "/files/OLD.png" if scenario in ("preserve", "dangling", "foreign_url") else None
    case.doc.ksa_einv_qr = current
    case.doc.custom_zatca_status = "CLEARED" if scenario != "orphan" else "Phase-1 QR Generated"
    seed = connections()
    with seed.cursor() as cursor:
        cursor.execute("UPDATE qr_invoice_test SET qr_url=%s,status=%s WHERE namespace=%s AND doctype=%s AND name=%s",
            (current, case.doc.custom_zatca_status, namespace, doctype, case.doc.name))
        for row in rows:
            cursor.execute("INSERT INTO qr_attachment_test VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (namespace, *(row[field] for field in FILE_FIELDS)))
    seed.commit()
    seed.close()
    def get_all(dt, *, filters, fields, order_by, limit_page_length):
        assert dt == "File" and fields == list(FILE_FIELDS)
        assert filters == {"attached_to_doctype": doctype, "attached_to_name": case.doc.name}
        assert order_by == "name asc" and limit_page_length == MAX_FILE_OBSERVATIONS + 1
        with case.transaction.cursor() as cursor:
            cursor.execute("SELECT name,file_name,file_url,attached_to_doctype,attached_to_name,attached_to_field "
                "FROM qr_attachment_test WHERE namespace=%s AND attached_to_doctype=%s AND attached_to_name=%s "
                "ORDER BY name ASC LIMIT %s", (namespace, doctype, case.doc.name, limit_page_length))
            return [dict(zip(FILE_FIELDS, values)) for values in cursor.fetchall()]
    case.runtime.get_all.side_effect = get_all
    if scenario == "preserve":
        create_qr.create_qr_code(case.doc)
        case.transaction.commit()  # Synthetic parent only; helper wrote nothing.
    else:
        with pytest.raises(ValidationError, match="attachments require review"):
            create_qr.create_qr_code(case.doc)
        case.transaction.rollback()
    case.transaction.close()
    saved, generated = read_saved(connections, namespace, doctype, case.doc.name)
    assert saved[:2] == (current, case.doc.custom_zatca_status) and generated == 0
    assert case.doc.ksa_einv_qr == current and not case.payloads
    case.runtime.delete_doc.assert_not_called()
    case.runtime.db.set_value.assert_not_called()
    case.runtime.db.exists.assert_not_called()
    case.runtime.db.commit.assert_not_called()
    verify = connections()
    with verify.cursor() as cursor:
        cursor.execute("SELECT name,file_name,file_url,attached_to_doctype,attached_to_name,attached_to_field "
            "FROM qr_attachment_test WHERE namespace=%s ORDER BY name ASC", (namespace,))
        actual = cursor.fetchall()
    assert actual == tuple(tuple(row[field] for field in FILE_FIELDS) for row in sorted(rows, key=lambda row: row["name"]))
    verify.rollback()
    verify.close()
