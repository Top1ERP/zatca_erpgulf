"""Actual owned InnoDB rollback/commit, fake Frappe File/image/notifications.

Not a restored application, filesystem rollback, client invoice or authority test.
"""

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import advance_deduction, create_qr, phase2_artifacts, qr_regeneration, sign_invoice, pos_sign
from zatca_erpgulf.zatca_erpgulf.qr_attachment_policy import FILE_FIELDS, MAX_FILE_OBSERVATIONS
from zatca_erpgulf.zatca_erpgulf.tests.test_issue_timestamp_adapters import local_qr
from zatca_erpgulf.zatca_erpgulf.tests.test_primary_qr_transaction import primary_qr
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections, namespace
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import ValidationError
from zatca_erpgulf.zatca_erpgulf.tests.test_qr_attachment_policy import row as stored_row
from zatca_erpgulf.zatca_erpgulf.tests.test_qr_regeneration_access import access, Denied, Row, invoke, no_writes
from zatca_erpgulf.zatca_erpgulf import response_processing, zatca_response
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import (
    boundary, run_adapter, ValidationError as BoundaryError,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_received_response_steps import fail_step
from zatca_erpgulf.zatca_erpgulf.tests.test_response_processing import snapshot as response_snapshot


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
            cursor.execute("CREATE TABLE response_processing_test (namespace VARCHAR(36),doctype VARCHAR(40),name VARCHAR(140),"
                "receipt TEXT,status VARCHAR(64),uuid VARCHAR(140),business_value TEXT,"
                "PRIMARY KEY(namespace,doctype,name)) ENGINE=InnoDB")
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
    def file_save(**options):
        assert options in ({}, {"ignore_permissions": True})
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


def response_sql_case(b, connections, namespace, module):
    """Bridge legacy persistence to owned SQL, including its existing commits."""
    doc = b.sales if module is sign_invoice else b.pos
    doc.custom_zatca_full_response, doc.custom_zatca_status = "ORIGINAL-RECEIPT", "ORIGINAL-STATUS"
    seed = connections()
    try:
        with seed.cursor() as cursor:
            cursor.execute("INSERT INTO response_processing_test VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (namespace, doc.doctype, doc.name, doc.custom_zatca_full_response,
                 doc.custom_zatca_status, doc.custom_uuid, "ORIGINAL-BUSINESS"))
        seed.commit()
    finally:
        seed.close()
    transaction = connections()
    key = (namespace, doc.doctype, doc.name)
    def write_current():
        with transaction.cursor() as cursor:
            cursor.execute("UPDATE response_processing_test SET receipt=%s,status=%s,uuid=%s "
                "WHERE namespace=%s AND doctype=%s AND name=%s", (doc.custom_zatca_full_response,
                doc.custom_zatca_status, doc.custom_uuid, *key))
    def db_set(field, value, **options):
        setattr(doc, field, value)
        if field in ("custom_zatca_full_response", "custom_zatca_status", "custom_uuid"):
            write_current()
        if options.get("commit"):
            b.frappe.db.commit()
    doc.db_set.side_effect = db_set
    doc.save.side_effect = lambda **options: write_current()
    b.frappe.db.commit.side_effect = transaction.commit
    with transaction.cursor() as cursor:
        cursor.execute("UPDATE response_processing_test SET business_value=%s "
            "WHERE namespace=%s AND doctype=%s AND name=%s", ("PARENT-PENDING", *key))
    return doc, transaction, key


def read_response_sql(connections, key):
    reader = connections("READ COMMITTED")
    try:
        with reader.cursor() as cursor:
            cursor.execute("SELECT receipt,status,uuid,business_value FROM response_processing_test "
                "WHERE namespace=%s AND doctype=%s AND name=%s", key)
            result = cursor.fetchone()
        reader.rollback()
        return result
    finally:
        reader.close()


@pytest.mark.parametrize("module", [sign_invoice, pos_sign])
@pytest.mark.parametrize("operation", ["reporting", "clearance"])
@pytest.mark.parametrize("status", [200, 202])
@pytest.mark.parametrize("commit", [False, True])
def test_early_response_failure_never_commits_or_overwrites_pending_sql(qr_schema, boundary, connections, namespace,
    monkeypatch, module, operation, status, commit):
    b = boundary
    doc, transaction, key = response_sql_case(b, connections, namespace, module)
    b.response.status_code = status
    def fail_log(**options):
        raise BoundaryError("PRIVATE synthetic local log failure")
    monkeypatch.setattr(module, "log_zatca_event", fail_log)
    try:
        with pytest.raises(response_processing.LocalResponseProcessingError) as error:
            run_adapter(b, module, operation)
        assert error.value.__context__ is None
        assert read_response_sql(connections, key) == (
            "ORIGINAL-RECEIPT", "ORIGINAL-STATUS", "test-existing-uuid", "ORIGINAL-BUSINESS")
        b.frappe.db.commit.assert_not_called()
        doc.save.assert_not_called()
        assert all(call.args[0] == "custom_ksa_einvoicing_xml" for call in doc.db_set.call_args_list)
        (transaction.commit if commit else transaction.rollback)()
    finally:
        transaction.close()
    assert read_response_sql(connections, key) == (
        "ORIGINAL-RECEIPT", "ORIGINAL-STATUS", "test-existing-uuid", "PARENT-PENDING" if commit else "ORIGINAL-BUSINESS")
    b.post.assert_called_once()


@pytest.mark.parametrize("module", [sign_invoice, pos_sign])
@pytest.mark.parametrize("status", [200, 202])
@pytest.mark.parametrize("failure", ["json", "image"])
def test_late_clearance_failure_preserves_already_committed_response_columns(qr_schema, boundary, connections, namespace,
    monkeypatch, module, status, failure):
    b = boundary
    doc, transaction, key = response_sql_case(b, connections, namespace, module)
    b.response.status_code = status
    monkeypatch.setattr(module, "set_zatca_full_response", zatca_response.set_zatca_full_response)
    observed = []
    def fail_local(*args, **options):
        observed.append((read_response_sql(connections, key), b.frappe.db.commit.call_count, doc.db_set.call_count))
        raise BoundaryError("PRIVATE synthetic local artifact failure")
    if failure == "json":
        b.response.json = fail_local
    else:
        monkeypatch.setattr(module, "attach_qr_image", fail_local)
    try:
        with pytest.raises(response_processing.LocalResponseProcessingError) as error:
            run_adapter(b, module, "clearance")
        assert error.value.__context__ is None
        # These independent commits are LEGACY behavior, not added/fixed here.
        assert len(observed) == 1 and observed[0][0] == (
            b.response.text, "CLEARED", "test-uuid", "PARENT-PENDING")
        assert b.frappe.db.commit.call_count == observed[0][1] == 3
        assert doc.db_set.call_count == observed[0][2]
        assert read_response_sql(connections, key) == observed[0][0]
        transaction.rollback()  # Parent cleanup, not a helper rollback.
    finally:
        transaction.close()
    assert read_response_sql(connections, key) == (b.response.text, "CLEARED", "test-uuid", "PARENT-PENDING")
    b.post.assert_called_once()


@pytest.mark.parametrize("module", [sign_invoice, pos_sign])
@pytest.mark.parametrize("operation", ["reporting", "clearance"])
@pytest.mark.parametrize("status", [400, 401, 503])
@pytest.mark.parametrize("stage", ["format", "log_zatca_event", "hide"])
@pytest.mark.parametrize("parent_commit", [False, True])
def test_received_error_step_failure_never_commits_pending_parent_sql_or_overwrites_prior_fields(qr_schema,
    boundary, connections, namespace, monkeypatch, module, operation, status, stage, parent_commit):
    b = boundary
    doc, transaction, key = response_sql_case(b, connections, namespace, module)
    b.response.status_code = status
    selected, observed = fail_step(b, module, operation, monkeypatch, stage, BoundaryError)
    assert selected is doc
    try:
        with pytest.raises(response_processing.LocalResponseProcessingError) as error:
            run_adapter(b, module, operation)
        assert len(observed) == 1 and response_snapshot(b, doc) == observed[0]
        assert error.value.__context__ is None and not vars(error.value)
        assert read_response_sql(connections, key) == (
            "ORIGINAL-RECEIPT", "ORIGINAL-STATUS", "test-existing-uuid", "ORIGINAL-BUSINESS")
        b.frappe.db.commit.assert_not_called()
        doc.save.assert_not_called()
        assert all(call.args[0] == "custom_ksa_einvoicing_xml" for call in doc.db_set.call_args_list)
        (transaction.commit if parent_commit else transaction.rollback)()  # Test's transaction owner, never guard.
    finally:
        transaction.close()
    assert read_response_sql(connections, key) == (
        "ORIGINAL-RECEIPT", "ORIGINAL-STATUS", "test-existing-uuid", "PARENT-PENDING" if parent_commit else "ORIGINAL-BUSINESS")
    b.post.assert_called_once()


@pytest.mark.parametrize("module", [sign_invoice, pos_sign])
@pytest.mark.parametrize("operation", ["reporting", "clearance"])
@pytest.mark.parametrize("status", [400, 401])
@pytest.mark.parametrize("parent_commit", [False, True])
def test_late_rejection_format_failure_adds_no_generic_write_commit_or_503_to_real_sql(qr_schema,
    boundary, connections, namespace, monkeypatch, module, operation, status, parent_commit):
    b = boundary
    doc, transaction, key = response_sql_case(b, connections, namespace, module)
    b.response.status_code = status
    monkeypatch.setattr(module, "set_zatca_full_response", zatca_response.set_zatca_full_response)
    observed, calls = [], []
    def formatting(*args):
        calls.append(args)
        if len(calls) == 2:
            observed.append((response_snapshot(b, doc), read_response_sql(connections, key)))
            raise BoundaryError("PRIVATE synthetic late rejection format failure")
        return "TEST RESPONSE"
    monkeypatch.setattr(module, "format_zatca_response", formatting)
    try:
        with pytest.raises(response_processing.LocalResponseProcessingError) as error:
            run_adapter(b, module, operation)
        assert len(calls) == 2 and len(observed) == 1 and error.value.__context__ is None
        assert response_snapshot(b, doc) == observed[0][0]  # No subsequent generic-handler effects.
        assert read_response_sql(connections, key) == observed[0][1]
        if module is sign_invoice:
            # Reporting already committed response; Clearance has only committed
            # status while its raw response remains in the parent's transaction.
            expected_receipt = b.response.text if operation == "reporting" else "ORIGINAL-RECEIPT"
            assert b.frappe.db.commit.call_count == 1
            expected_uuid = "test-existing-uuid"
        else:
            expected_receipt = expected_uuid = "Not Submitted"  # Existing POS rejection placeholder policy.
            assert b.frappe.db.commit.call_count == 3
        assert observed[0][1] == (expected_receipt, "Not Submitted", expected_uuid, "PARENT-PENDING")
        (transaction.commit if parent_commit else transaction.rollback)()
    finally:
        transaction.close()
    if module is sign_invoice and operation == "clearance" and parent_commit:
        expected_receipt = b.response.text  # Pending raw response committed ONLY by explicit test owner.
    assert read_response_sql(connections, key) == (expected_receipt, "Not Submitted", expected_uuid, "PARENT-PENDING")
    b.post.assert_called_once()


def prepare_primary(primary_qr, connections, namespace, doctype, status, *, failure=None):
    """Use actual SQL, but synthetic File save and no invoice/accounting hooks."""
    case = prepare(primary_qr, connections, namespace, doctype, failure=failure)
    case.doc.custom_zatca_status = status
    seed = connections()
    try:
        with seed.cursor() as cursor:
            cursor.execute("UPDATE qr_invoice_test SET status=%s WHERE namespace=%s AND doctype=%s AND name=%s",
                (status, namespace, doctype, case.doc.name))
        seed.commit()
    finally:
        seed.close()
    def set_value(dt, name, fields, *, update_modified):
        assert dt == doctype and name == case.doc.name and update_modified is False
        assert set(fields) == {"ksa_einv_qr"}
        with case.transaction.cursor() as cursor:
            cursor.execute("UPDATE qr_invoice_test SET qr_url=%s WHERE namespace=%s AND doctype=%s AND name=%s",
                (fields["ksa_einv_qr"], namespace, dt, name))
            assert cursor.rowcount == 1
        if failure == "metadata":
            raise RuntimeError("SYNTHETIC metadata failure after update")
    case.runtime.db.set_value.side_effect = set_value
    return case


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("status", ["REPORTED", "CLEARED"])
@pytest.mark.parametrize("commit", [False, True])
def test_primary_qr_visibility_and_status_are_owned_by_parent(qr_schema, primary_qr, connections, namespace, doctype, status, commit):
    case = prepare_primary(primary_qr, connections, namespace, doctype, status)
    try:
        sign_invoice.attach_qr_image("SYNTHETIC", case.doc, allow_phase2=True, phase2_status=status)
        assert read_saved(connections, namespace, doctype, case.doc.name) == (
            (None, status, "ORIGINAL-BUSINESS", "2026-10-01 00:00:00"), 0)
        (case.transaction.commit if commit else case.transaction.rollback)()
    finally:
        case.transaction.close()
    saved, files = read_saved(connections, namespace, doctype, case.doc.name)
    assert saved == (("/files/SYNTHETIC-QR.png" if commit else None), status,
        "ORIGINAL-BUSINESS", "2026-10-01 00:00:00") and files == int(commit)
    assert case.doc.custom_zatca_status == status
    case.doc.db_set.assert_not_called()
    case.doc.save.assert_not_called()
    case.runtime.db.commit.assert_not_called()
    case.runtime.db.rollback.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("status", ["REPORTED", "CLEARED"])
@pytest.mark.parametrize("failure", ["file", "metadata", "notify", "parent"])
def test_primary_qr_failure_rolls_back_with_parent_pending_work(qr_schema, primary_qr, connections, namespace, doctype, status, failure):
    case = prepare_primary(primary_qr, connections, namespace, doctype, status, failure=failure)
    with pytest.raises(RuntimeError, match="SYNTHETIC"):
        try:
            with case.transaction.cursor() as cursor:
                cursor.execute("UPDATE qr_invoice_test SET business_value=%s WHERE namespace=%s AND doctype=%s AND name=%s",
                    ("PARENT-PENDING", namespace, doctype, case.doc.name))
            sign_invoice.attach_qr_image("SYNTHETIC", case.doc, allow_phase2=True, phase2_status=status)
            if failure == "parent":
                raise RuntimeError("SYNTHETIC later parent failure")
        finally:
            case.transaction.rollback()
            case.transaction.close()
    assert read_saved(connections, namespace, doctype, case.doc.name) == (
        (None, status, "ORIGINAL-BUSINESS", "2026-10-01 00:00:00"), 0)
    assert case.doc.custom_zatca_status == status
    case.doc.db_set.assert_not_called()
    case.doc.save.assert_not_called()
    case.runtime.db.commit.assert_not_called()
    case.runtime.db.rollback.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("operation", ["reporting", "clearance"])
@pytest.mark.parametrize("scenario", ["preserve", "dangling", "orphan", "foreign_url"])
@pytest.mark.parametrize("commit", [False, True])
def test_primary_scoped_qr_preflight_preserves_pending_parent_transaction(qr_schema, primary_qr, connections, namespace,
    monkeypatch, doctype, operation, scenario, commit):
    case = prepare_primary(primary_qr, connections, namespace, doctype, "REPORTED")
    current = None if scenario == "orphan" else "/files/OLD.png"
    case.doc.ksa_einv_qr = current
    rows = [] if scenario == "dangling" else [stored_row(doctype=doctype,
        invoice="FOREIGN-INVOICE" if scenario == "foreign_url" else case.doc.name)]
    seed = connections()
    try:
        with seed.cursor() as cursor:
            cursor.execute("UPDATE qr_invoice_test SET qr_url=%s WHERE namespace=%s AND doctype=%s AND name=%s",
                (current, namespace, doctype, case.doc.name))
            for row in rows:
                cursor.execute("INSERT INTO qr_attachment_test VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (namespace, *(row[field] for field in FILE_FIELDS)))
        seed.commit()
    finally:
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
    # A globally existing foreign URL must not be sufficient for preservation.
    case.runtime.db.exists.return_value = True
    module = sign_invoice if doctype == "Sales Invoice" else pos_sign
    forbidden_post = Mock(side_effect=AssertionError("No request in ownership rehearsal"))
    monkeypatch.setattr(module.requests, "post", forbidden_post)
    try:
        with case.transaction.cursor() as cursor:
            cursor.execute("UPDATE qr_invoice_test SET business_value=%s WHERE namespace=%s AND doctype=%s AND name=%s",
                ("PARENT-PENDING", namespace, doctype, case.doc.name))
        if scenario == "preserve":
            sign_invoice.attach_qr_image("SYNTHETIC", case.doc, allow_phase2=True)
        else:
            with pytest.raises(ValidationError, match="attachments require review"):
                getattr(module, operation + "_api")("SYNTHETIC-UUID", "SYNTHETIC-HASH", "UNOPENED.xml",
                    case.doc.name, case.doc)
        assert read_saved(connections, namespace, doctype, case.doc.name) == (
            (current, "REPORTED", "ORIGINAL-BUSINESS", "2026-10-01 00:00:00"), 0)
        (case.transaction.commit if commit else case.transaction.rollback)()
    finally:
        case.transaction.close()
    assert read_saved(connections, namespace, doctype, case.doc.name) == (
        (current, "REPORTED", "PARENT-PENDING" if commit else "ORIGINAL-BUSINESS", "2026-10-01 00:00:00"), 0)
    assert not case.payloads and case.doc.ksa_einv_qr == current and case.doc.custom_zatca_status == "REPORTED"
    case.runtime.get_doc.assert_not_called()
    case.runtime.db.exists.assert_not_called()
    case.runtime.db.set_value.assert_not_called()
    case.runtime.db.commit.assert_not_called()
    case.runtime.db.rollback.assert_not_called()
    case.runtime.delete_doc.assert_not_called()
    case.doc.db_set.assert_not_called()
    case.doc.save.assert_not_called()
    forbidden_post.assert_not_called()
    verify = connections()
    try:
        with verify.cursor() as cursor:
            cursor.execute("SELECT name,file_name,file_url,attached_to_doctype,attached_to_name,attached_to_field "
                "FROM qr_attachment_test WHERE namespace=%s ORDER BY name ASC", (namespace,))
            assert cursor.fetchall() == tuple(tuple(row[field] for field in FILE_FIELDS) for row in rows)
        verify.rollback()
    finally:
        verify.close()


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


@pytest.mark.parametrize("route,doctype", [("ordinary", "Sales Invoice"),
    ("ordinary", "POS Invoice"), ("advance", "Sales Invoice")])
@pytest.mark.parametrize("scenario", ["preserve", "orphan", "dangling", "foreign_url"])
def test_actual_scoped_file_query_preserves_rows_and_reference_without_cleanup(qr_schema, local_qr, connections, namespace, doctype, scenario, route):
    case = prepare(local_qr, connections, namespace, doctype)
    generate = (create_qr.create_qr_code if route == "ordinary" else
        lambda doc: advance_deduction.ensure_final_sales_invoice_qr_for_print(doc, force=True))
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
        generate(case.doc)
        case.transaction.commit()  # Synthetic parent only; helper wrote nothing.
    else:
        with pytest.raises(ValidationError, match="attachments require review"):
            generate(case.doc)
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


@pytest.mark.parametrize("scenario", ["preserve", "orphan", "dangling", "xml"])
@pytest.mark.parametrize("commit", [False, True])
def test_recovery_never_commits_or_discards_the_parents_pending_work(qr_schema, access, connections, namespace, scenario, commit):
    """Real parent visibility, synthetic saved documents/ACL, no ORM/File IO."""
    doc = access.doc
    current = access.file.file_url if scenario == "preserve" else (
        "/files/MISSING.png" if scenario == "dangling" else None)
    doc.ksa_einv_qr, doc.custom_zatca_status = current, "REPORTED"
    if scenario == "xml":
        access.file.file_name = access.row["file_name"] = "DEBUG-NEW.xml"
    rows = [] if scenario == "dangling" else [access.row]
    seed = connections()
    try:
        with seed.cursor() as cursor:
            cursor.execute("INSERT INTO qr_invoice_test VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (namespace, doc.doctype, doc.name, current, doc.custom_zatca_status,
                 "ORIGINAL-BUSINESS", "2026-10-01 00:00:00"))
            for row in rows:
                cursor.execute("INSERT INTO qr_attachment_test VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (namespace, *(row[field] for field in FILE_FIELDS)))
        seed.commit()
    finally:
        seed.close()
    parent = connections()
    access.runtime.db.commit.side_effect = parent.commit
    access.runtime.db.rollback.side_effect = parent.rollback
    access.runtime.db.set_value.side_effect = AssertionError("Recovery must not write invoice metadata")
    def get_all(dt, *, filters, fields, order_by, limit_page_length):
        assert dt == "File" and fields == list(FILE_FIELDS) and order_by == "name asc"
        assert filters == {"attached_to_doctype": doc.doctype, "attached_to_name": doc.name}
        assert limit_page_length == MAX_FILE_OBSERVATIONS + 1
        with parent.cursor() as cursor:
            cursor.execute("SELECT name,file_name,file_url,attached_to_doctype,attached_to_name,attached_to_field "
                "FROM qr_attachment_test WHERE namespace=%s AND attached_to_doctype=%s AND attached_to_name=%s "
                "ORDER BY name ASC LIMIT %s", (namespace, doc.doctype, doc.name, limit_page_length))
            return [Row(zip(FILE_FIELDS, values)) for values in cursor.fetchall()]
    access.runtime.get_all.side_effect = get_all
    try:
        with parent.cursor() as cursor:
            cursor.execute("UPDATE qr_invoice_test SET business_value=%s WHERE namespace=%s AND doctype=%s AND name=%s",
                ("PARENT-PENDING", namespace, doc.doctype, doc.name))
        if scenario == "preserve":
            assert invoke(access, "regenerate_qr")["status"] == "preserved"
        else:
            with pytest.raises(Denied, match=qr_regeneration.REVIEW_MESSAGE):
                invoke(access, "regenerate_qr")
        before, generated = read_saved(connections, namespace, doc.doctype, doc.name)
        assert before == (current, doc.custom_zatca_status, "ORIGINAL-BUSINESS", "2026-10-01 00:00:00")
        assert generated == 0
        no_writes(access)
        access.reader.assert_not_called()
        access.opener.assert_not_called()
        (parent.commit if commit else parent.rollback)()
    finally:
        parent.rollback()
        parent.close()
    saved, generated = read_saved(connections, namespace, doc.doctype, doc.name)
    assert saved[:2] == (current, doc.custom_zatca_status) and generated == 0
    assert saved[2] == ("PARENT-PENDING" if commit else "ORIGINAL-BUSINESS")
    verify = connections()
    try:
        with verify.cursor() as cursor:
            cursor.execute("SELECT name,file_name,file_url,attached_to_doctype,attached_to_name,attached_to_field "
                "FROM qr_attachment_test WHERE namespace=%s ORDER BY name ASC", (namespace,))
            actual = cursor.fetchall()
        assert actual == tuple(tuple(row[field] for field in FILE_FIELDS) for row in rows)
    finally:
        verify.rollback()
        verify.close()


@pytest.mark.parametrize("scenario", ["preserve", "orphan", "dangling", "foreign_url"])
@pytest.mark.parametrize("commit", [False, True])
@pytest.mark.parametrize("status", ["CLEARED", "REPORTED"])
def test_phase2_hook_preserves_source_attachments_and_parent_transaction(qr_schema, local_qr, monkeypatch, connections, namespace, scenario, commit, status):
    case = prepare(local_qr, connections, namespace, "Sales Invoice")
    monkeypatch.setattr(phase2_artifacts, "frappe", case.runtime)
    monkeypatch.setattr(phase2_artifacts, "_", lambda message: message)
    current = "/files/OLD.png" if scenario != "orphan" else None
    case.doc.ksa_einv_qr, case.doc.custom_zatca_status = current, status
    owned, newer = stored_row(), stored_row("FILE-NEW", "/files/NEW.png", "QR-Phase2-CLEARED-NEW.png")
    rows = [owned, newer] if scenario in ("preserve", "orphan") else []
    if scenario == "foreign_url":
        rows = [stored_row("FOREIGN", invoice="OTHER-INVOICE")]
    seed = connections()
    try:
        with seed.cursor() as cursor:
            cursor.execute("UPDATE qr_invoice_test SET qr_url=%s,status=%s WHERE namespace=%s AND doctype=%s AND name=%s",
                (current, status, namespace, case.doc.doctype, case.doc.name))
            for row in rows:
                cursor.execute("INSERT INTO qr_attachment_test VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (namespace, *(row[field] for field in FILE_FIELDS)))
        seed.commit()
    finally:
        seed.close()
    def get_all(dt, *, filters, fields, order_by, limit_page_length):
        assert dt == "File" and fields == list(FILE_FIELDS) and order_by == "name asc"
        assert filters == {"attached_to_doctype": "Sales Invoice", "attached_to_name": case.doc.name}
        assert limit_page_length == MAX_FILE_OBSERVATIONS + 1
        with case.transaction.cursor() as cursor:
            cursor.execute("SELECT name,file_name,file_url,attached_to_doctype,attached_to_name,attached_to_field "
                "FROM qr_attachment_test WHERE namespace=%s AND attached_to_doctype=%s AND attached_to_name=%s "
                "ORDER BY name ASC LIMIT %s", (namespace, case.doc.doctype, case.doc.name, limit_page_length))
            return [dict(zip(FILE_FIELDS, values)) for values in cursor.fetchall()]
    case.runtime.get_all.side_effect = get_all
    try:
        with case.transaction.cursor() as cursor:
            cursor.execute("UPDATE qr_invoice_test SET business_value=%s WHERE namespace=%s AND doctype=%s AND name=%s",
                ("PARENT-PENDING", namespace, case.doc.doctype, case.doc.name))
        report = phase2_artifacts.assess_phase2_qr_reference(case.doc)
        assert report["action"] == ("PRESERVE" if scenario == "preserve" else "REVIEW")
        assert phase2_artifacts.ensure_phase2_sales_invoice_artifacts(case.doc) is None
        before, generated = read_saved(connections, namespace, case.doc.doctype, case.doc.name)
        assert before == (current, status, "ORIGINAL-BUSINESS", "2026-10-01 00:00:00") and generated == 0
        assert case.doc.ksa_einv_qr == current and case.doc.custom_zatca_status == status and not case.payloads
        case.runtime.db.set_value.assert_not_called()
        case.runtime.delete_doc.assert_not_called()
        case.runtime.db.commit.assert_not_called()
        case.runtime.db.rollback.assert_not_called()
        case.runtime.db.exists.assert_not_called()
        case.doc.save.assert_not_called()
        (case.transaction.commit if commit else case.transaction.rollback)()
    finally:
        case.transaction.rollback()
        case.transaction.close()
    saved, generated = read_saved(connections, namespace, case.doc.doctype, case.doc.name)
    assert saved[:2] == (current, status) and generated == 0
    assert saved[2] == ("PARENT-PENDING" if commit else "ORIGINAL-BUSINESS")
    verify = connections()
    try:
        with verify.cursor() as cursor:
            cursor.execute("SELECT name,file_name,file_url,attached_to_doctype,attached_to_name,attached_to_field "
                "FROM qr_attachment_test WHERE namespace=%s ORDER BY name ASC", (namespace,))
            actual = cursor.fetchall()
        assert actual == tuple(tuple(row[field] for field in FILE_FIELDS) for row in sorted(rows, key=lambda row: row["name"]))
    finally:
        verify.rollback()
        verify.close()
