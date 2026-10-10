"""Guarded capture on owned private InnoDB tables, fake Frappe ACL/HTTP only."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
import urllib3.util.connection

from zatca_erpgulf.zatca_erpgulf import compliance_capture_access as access
from zatca_erpgulf.zatca_erpgulf.compliance_https import ComplianceHttpsPolicy, ComplianceHttpsTransport
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_archive_mariadb import (
    isolated_server, connections, install_private_bundle_schema, install_private_archive_schema,
    context, materials, audit, read,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_bundle_access import operator
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_capture_access import capture_operator
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_evidence import response
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_https import synthetic_pool


pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
                               reason="Owned private MariaDB only; fake ACL/HTTP, no tenant")


@pytest.fixture(scope="module", autouse=True)
def install_private_source_schema(isolated_server, install_private_archive_schema):
    import pymysql

    # Reduced synthetic row tables ONLY on the fixture-owned TCP-disabled server.
    # This is not Frappe schema installation or an ERPNext compatibility rehearsal.
    with pymysql.connect(unix_socket=isolated_server[0], user="root", database="zatca_journal_rehearsal", autocommit=True) as db:
        with db.cursor() as cursor:
            for doctype, fields in access.SOURCE_FIELDS.items():
                columns = ["`name` VARCHAR(140) PRIMARY KEY", "`modified` DATETIME(6) NOT NULL"]
                columns += ["`" + field + "` " + ("INT" if field == access.FLAG_FIELD else "TEXT") for field in fields]
                cursor.execute("CREATE TABLE `tab" + doctype + "` (" + ",".join(columns) + ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin")


def prepare_sources(connections, operator):
    db = connections()
    try:
        with db.cursor() as cursor:
            for doctype in access.SOURCE_FIELDS:
                cursor.execute("DELETE FROM `tab" + doctype + "`")
            for (doctype, name), doc in operator.documents.items():
                fields = ("name", "modified", *access.SOURCE_FIELDS[doctype])
                cursor.execute("INSERT INTO `tab" + doctype + "` (" + ",".join("`" + field + "`" for field in fields)
                    + ") VALUES (" + ",".join("%s" for _ in fields) + ")", (name, *(doc.get(field) for field in fields[1:])))
        db.commit()
    finally:
        db.close()


def service_for(connections, audit, factory, transport):
    scope = access.CredentialStorageScope("private.test", audit[0])
    resources = access.ComplianceCaptureResources(scope, audit[1], audit[2], "audit-test", factory, transport,
        lambda: audit[4].started_at)
    return access.StagedComplianceCaptureService(scope, lambda requested: resources)


def collect(service, audit):
    start = audit[4]
    return service.capture("TC", None, start.requirements, exchange_id=start.exchange_id, request_bytes=start.request_bytes)


@pytest.mark.parametrize("case", ["success", "initial_route", "initial_revision", "preflight_route", "preflight_revision", "preflight_commit", "duplicate"])
def test_source_guard_with_real_transactions_and_opt_in_adapter(connections, audit, capture_operator, monkeypatch, case):
    prepare_sources(connections, capture_operator)
    def forbidden(*args, **kwargs):
        raise AssertionError("No real HTTP/TCP; only fixture-owned Unix SQL sockets")
    monkeypatch.setattr(urllib3.util.connection, "create_connection", forbidden)
    fake = synthetic_pool(monkeypatch, body=json.dumps(response()).encode())
    transport = ComplianceHttpsTransport(ComplianceHttpsPolicy((audit[4].route,)), timer=lambda: 100)
    owned = []
    def factory():
        db = connections()
        index = len(owned)
        owned.append(db)
        phase = 0 if case.startswith("initial_") else 1
        if index == phase and case.endswith(("route", "revision")):
            mutation = connections()
            try:
                with mutation.cursor() as cursor:
                    if case.endswith("route"):
                        cursor.execute("UPDATE `tabCompany` SET `custom_production_url`=%s WHERE `name`=%s",
                                       ("https://other.invalid/core", "SOURCE"))
                    else:
                        cursor.execute("UPDATE `tabCompany` SET `modified`=DATE_ADD(`modified`, INTERVAL 1 SECOND) WHERE `name`=%s", ("SOURCE",))
                mutation.commit()
            finally:
                mutation.close()
        if index == 1 and case == "preflight_commit":
            def fail_commit():
                raise RuntimeError("PRIVATE-SECRET commit unconfirmed")
            db.commit = fail_commit
        return db
    original = fake.pool.urlopen.side_effect
    def urlopen(**kwargs):
        assert len(owned) == 2 and all(db.open is False for db in owned)
        reader = connections()
        try:
            assert read(reader, audit[8], audit[3], audit[4].exchange_id).receipt is None
        finally:
            reader.close()
        return original(**kwargs)
    fake.pool.urlopen.side_effect = urlopen
    service = service_for(connections, audit, factory, transport)
    result = collect(service, audit)
    if case in ("success", "duplicate"):
        assert result.state == "RECEIPT_CAPTURED_OBSERVATION" and fake.pool.urlopen.call_count == 1
        reader = connections()
        try:
            assert read(reader, audit[8], audit[3], audit[4].exchange_id).receipt is not None
        finally:
            reader.close()
        if case == "duplicate":
            assert collect(service, audit).state == "PREPARATION_UNCONFIRMED_NO_SEND"
            assert fake.pool.urlopen.call_count == 1
    else:
        assert result.state == ("PREPARATION_UNCONFIRMED_NO_SEND" if case.startswith("initial_") else "DISPATCH_PREFLIGHT_FAILED_NO_SEND")
        fake.pool.urlopen.assert_not_called()
    assert all(db.open is False for db in owned)
    assert result.diagnostic_projection()["source_snapshot_verified"] is False


def test_saved_row_locks_block_writers_and_release_before_network(connections, capture_operator):
    prepare_sources(connections, capture_operator)
    expected = access.SavedComplianceSourceRow.from_document(capture_operator.documents["Company", "SOURCE"])
    guarded = connections()
    ready, done = Event(), Event()
    def writer():
        db = connections()
        try:
            with db.cursor() as cursor:
                ready.set()
                cursor.execute("UPDATE `tabCompany` SET `tax_id`=%s WHERE `name`=%s", ("OTHER", "SOURCE"))
            db.commit()
            done.set()
        finally:
            db.close()
    try:
        assert access.verify_saved_source_rows(guarded, (expected,)) is True
        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(writer)
            try:
                assert ready.wait(timeout=2) and not done.wait(timeout=0.1)
            finally:
                guarded.commit()
                guarded.close()
            future.result(timeout=5)
            assert done.is_set()
    finally:
        if guarded.open:
            guarded.close()
    changed = connections()
    try:
        with pytest.raises(access.ComplianceSourceError, match="source_changed"):
            access.verify_saved_source_rows(changed, (expected,))
        changed.rollback()
    finally:
        changed.close()
