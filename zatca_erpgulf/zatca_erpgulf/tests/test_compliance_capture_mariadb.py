"""Single-use reservations and fake transport on OWNED private MariaDB only."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

import pytest

from zatca_erpgulf.zatca_erpgulf.compliance_capture import ComplianceCaptureCoordinator, ComplianceTransportResponse
from zatca_erpgulf.zatca_erpgulf.compliance_archive import ComplianceArchiveError
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_archive_mariadb import (
    isolated_server, connections, install_private_bundle_schema, install_private_archive_schema,
    context, materials, audit, prepare, receive, read,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_evidence import response


pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
                               reason="Only the owned private server, no live DB or HTTP")


def coordinator(audit, factory, transport):
    namespace, bundle_cipher, archive_cipher, _, start = audit[:5]
    return ComplianceCaptureCoordinator(namespace, bundle_cipher, archive_cipher, "audit-test",
        connection_factory=factory, transport=transport, clock=lambda: start.started_at)


def collect(collector, audit):
    start = audit[4]
    return collector.capture(start.requirements, exchange_id=start.exchange_id, route=start.route, request_bytes=start.request_bytes)


@pytest.mark.parametrize("status", [200, 202, 406, 401, 400])
def test_committed_start_is_visible_and_all_owned_connections_closed_before_fake_transport(connections, audit, status):
    bundle, start, repository = audit[3], audit[4], audit[8]
    owned, calls = [], []
    def factory():
        database = connections()
        owned.append(database)
        return database
    body = json.dumps(response(step=start.step, previous=status == 406)).encode()
    def fake_transport(request):
        assert len(owned) == 1 and owned[0].open is False
        # A separate locked read proves the reservation COMMITTED and that the
        # prior connection no longer holds the bundle/archive row locks.
        history = read(connections(), repository, bundle, start.exchange_id)
        assert history.start.request_bytes == request.body == start.request_bytes
        calls.append(request)
        return ComplianceTransportResponse(status, body)
    result = collect(coordinator(audit, factory, fake_transport), audit)
    assert result.state == "RECEIPT_CAPTURED_OBSERVATION" and len(calls) == 1
    assert len(owned) == 2 and all(database.open is False for database in owned)
    history = read(connections(), repository, bundle, start.exchange_id)
    assert history.receipt.http_status == status and history.receipt.response_bytes == body
    assert result.diagnostic_projection()["remote_receipt_verified"] is False


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
def test_two_competing_collectors_only_invoke_one_transport(connections, audit, isolation):
    calls, lock = [], Lock()
    def fake_transport(request):
        with lock:
            calls.append(request)
        return ComplianceTransportResponse(200, json.dumps(response()).encode())
    collectors = [coordinator(audit, lambda: connections(isolation), fake_transport) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(collect, collector, audit) for collector in collectors]
        results = [future.result(timeout=10) for future in futures]
    assert sorted(result.state for result in results) == ["PREPARATION_UNCONFIRMED_NO_SEND", "RECEIPT_CAPTURED_OBSERVATION"]
    assert len(calls) == 1
    assert read(connections(), audit[8], audit[3], audit[4].exchange_id).receipt is not None


@pytest.mark.parametrize("existing", ["prepared", "receipt"])
def test_existing_observation_is_not_reused_as_dispatch_permission(connections, audit, existing):
    prepare(connections(), audit[8], audit[6])
    if existing == "receipt":
        receive(connections(), audit[8], audit[7])
    calls = []
    result = collect(coordinator(audit, connections, lambda request: calls.append(request)), audit)
    assert result.state == "PREPARATION_UNCONFIRMED_NO_SEND" and calls == []
    assert read(connections(), audit[8], audit[3], audit[4].exchange_id).start == audit[4]


@pytest.mark.parametrize("phase", [0, 1])
@pytest.mark.parametrize("committed", [False, True])
def test_unknown_commit_never_authorizes_replay_and_exact_receipt_can_be_reconciled(connections, audit, phase, committed):
    opened, calls = [], []
    def factory():
        database = connections()
        index = len(opened)
        opened.append(database)
        if index == phase:
            original_commit = database.commit
            def ambiguous():
                if committed:
                    original_commit()
                raise RuntimeError("PRIVATE-SECRET lost commit acknowledgement")
            database.commit = ambiguous
        return database
    def fake_transport(request):
        calls.append(request)
        return ComplianceTransportResponse(200, json.dumps(response()).encode())
    result = collect(coordinator(audit, factory, fake_transport), audit)
    assert result.state == ("PREPARATION_UNCONFIRMED_NO_SEND" if phase == 0 else "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY")
    assert len(calls) == phase and all(database.open is False for database in opened)
    if phase == 0:
        if committed:
            # Fresh coordinator still cannot send the spent reservation.
            blocked = collect(coordinator(audit, connections, fake_transport), audit)
            assert blocked.state == "PREPARATION_UNCONFIRMED_NO_SEND" and calls == []
        else:
            reader = connections()
            try:
                with pytest.raises(ComplianceArchiveError, match="archive_missing"):
                    audit[8](reader).load(audit[3].manifest.slot, audit[3].manifest.version_id, audit[4].exchange_id)
            finally:
                reader.rollback()
    else:
        # Explicit TEST recovery of the EXACT retained ciphertext, NOT a retry
        # of HTTP and NOT newly resealed response material. Works either way.
        receive(connections(), audit[8], result.receipt_envelope)
        recovered = read(connections(), audit[8], audit[3], audit[4].exchange_id)
        assert recovered.receipt == result.observation and len(calls) == 1


@pytest.mark.parametrize("rollback", [False, True])
def test_strict_reservation_is_not_idempotent_but_uncommitted_work_rolls_back(connections, audit, rollback):
    database = connections()
    audit[8](database).reserve_request(audit[6])
    if rollback:
        database.rollback()
        audit[8](database).reserve_request(audit[6])
    database.commit()
    repository = audit[8](database)
    with pytest.raises(ComplianceArchiveError, match="archive_unique_conflict"):
        repository.reserve_request(audit[6])
    with pytest.raises(ComplianceArchiveError, match="archive_transaction_unusable"):
        repository.load(audit[3].manifest.slot, audit[3].manifest.version_id, audit[4].exchange_id)
    database.rollback()
    assert read(connections(), audit[8], audit[3], audit[4].exchange_id).start == audit[4]


@pytest.mark.parametrize("phase", ["transport", "receipt_commit"])
def test_owned_server_crash_leaves_spent_start_and_never_replays(connections, audit, isolated_server, phase):
    calls, opened = [], []
    def factory():
        database = connections()
        opened.append(database)
        if phase == "receipt_commit" and len(opened) == 2:
            def interrupted_commit():
                isolated_server[2]()  # Only the exact fixture-owned process.
                raise RuntimeError("PRIVATE-SECRET interrupted receipt commit")
            database.commit = interrupted_commit
        return database
    def fake_transport(request):
        calls.append(request)
        if phase == "transport":
            isolated_server[2]()
            raise RuntimeError("PRIVATE-SECRET transport unknown")
        return ComplianceTransportResponse(200, json.dumps(response()).encode())
    result = collect(coordinator(audit, factory, fake_transport), audit)
    assert result.state == ("TRANSPORT_UNKNOWN_NO_REPLAY" if phase == "transport" else "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY")
    history = read(connections(), audit[8], audit[3], audit[4].exchange_id)
    assert history.start.request_bytes == audit[4].request_bytes and history.receipt is None
    blocked = collect(coordinator(audit, connections, fake_transport), audit)
    assert blocked.state == "PREPARATION_UNCONFIRMED_NO_SEND" and len(calls) == 1
