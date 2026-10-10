"""Real isolated SQL + Requests/urllib3 pipeline, fake HTTP pool, NO TLS/socket."""

import json
import os

import pytest
import requests
import urllib3.util.connection

from zatca_erpgulf.zatca_erpgulf.compliance_https import ComplianceHttpsPolicy, ComplianceHttpsTransport
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_capture_mariadb import coordinator, collect
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_archive_mariadb import (
    isolated_server, connections, install_private_bundle_schema, install_private_archive_schema,
    context, materials, audit, read,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_evidence import response
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_https import synthetic_pool


pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
                               reason="Owned private MariaDB plus synthetic HTTP pool only")


@pytest.mark.parametrize("case", ["success", "redirect", "tls_failure", "oversize"])
def test_adapter_composes_with_committed_reservation_and_no_replay(connections, audit, monkeypatch, case):
    def forbidden(*args, **kwargs):
        raise AssertionError("Only fixture-owned Unix SQL sockets are permitted")
    # Do not forbid socket.connect globally: the private MariaDB Unix socket is
    # required. Block the actual urllib3 TCP connection path instead.
    monkeypatch.setattr(urllib3.util.connection, "create_connection", forbidden)
    start = audit[4]
    body = json.dumps(response()).encode()
    headers = {"Content-Length": "8388609"} if case == "oversize" else {}
    fake = synthetic_pool(monkeypatch, body=body, status=302 if case == "redirect" else 200, headers=headers)
    if case == "tls_failure":
        fake.pool.urlopen.side_effect = requests.exceptions.SSLError("PRIVATE-SECRET TLS failure")
    transport = ComplianceHttpsTransport(ComplianceHttpsPolicy((start.route,)), timer=lambda: 100)
    owned = []
    def factory():
        database = connections()
        owned.append(database)
        return database
    original = fake.pool.urlopen.side_effect
    if callable(original):
        def urlopen(**kwargs):
            assert len(owned) == 1 and owned[0].open is False
            assert read(connections(), audit[8], audit[3], start.exchange_id).receipt is None
            return original(**kwargs)
        fake.pool.urlopen.side_effect = urlopen
    collector = coordinator(audit, factory, transport)
    result = collect(collector, audit)
    observed = read(connections(), audit[8], audit[3], start.exchange_id)
    assert all(database.open is False for database in owned)
    assert fake.pool.urlopen.call_count == 1
    assert result.diagnostic_projection()["remote_receipt_verified"] is False
    if case in ("success", "redirect"):
        assert result.state == "RECEIPT_CAPTURED_OBSERVATION"
        assert observed.receipt.response_bytes == body
        assert observed.receipt.http_status == (302 if case == "redirect" else 200)
        if case == "redirect":
            assert observed.receipt.outcome != "PASS_MATCHED_OBSERVATION"
    else:
        assert result.state == "TRANSPORT_UNKNOWN_NO_REPLAY" and observed.receipt is None
    blocked = collect(coordinator(audit, factory, transport), audit)
    assert blocked.state == "PREPARATION_UNCONFIRMED_NO_SEND"
    assert fake.pool.urlopen.call_count == 1
