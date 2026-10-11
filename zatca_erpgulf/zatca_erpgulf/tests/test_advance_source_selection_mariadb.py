"""Exact journal reconstruction on OWNED private SQL; no site or authority."""

import os
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import advance_source_selection as selection
from zatca_erpgulf.zatca_erpgulf.dispatch_journal import append_dispatch_event
from zatca_erpgulf.zatca_erpgulf.journal_repository import MariaDBJournalRepository
from zatca_erpgulf.zatca_erpgulf.journal_storage import JournalStorageError
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_dispatch_journal import event, start
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import (
    isolated_server, connections, namespace,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_advance_source_selection import (
    advance, changed_return, receipt, response_with_xml, select,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="Owned guarded private SQL only; no tenant or authority request",
)


def store(connection, namespace, journal, *, commit=True):
    repository = MariaDBJournalRepository(connection, namespace)
    current = repository.put(journal.candidate)
    for item in journal.events:
        current = repository.append(journal.candidate.key_sha256, item,
            expected_journal_sha256=current.journal_sha256)
    if commit:
        connection.commit()  # Synthetic test caller only, never a runtime hook.
    return current


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
def test_committed_exact_request_receipt_reconstruction_selects_endpoint_artifact(connections, namespace, certificates, environment, indicator):
    prepared = advance(certificates[0], environment=environment, indicator=indicator)
    returned = changed_return(prepared)
    observed = receipt(prepared, response=response_with_xml(prepared, returned))
    writer = connections()
    store(writer, namespace, observed)
    writer.close()
    reader = connections()
    loaded = MariaDBJournalRepository(reader, namespace).load(prepared.key_sha256)
    result = select(loaded, expected_context=prepared.context,
                    expected_journal_sha256=observed.journal_sha256)
    assert result.xml_bytes == (returned if indicator.startswith("01") else prepared.xml_bytes)
    assert result.reference.issue_time == "00:05:42+03:00"
    assert loaded.journal_sha256 == observed.journal_sha256
    assert result.diagnostic_projection()["persistence_verified"] is False
    reader.rollback()  # Release read locks; the selector never commits SQL.
    reader.close()
    reopened = connections()
    assert MariaDBJournalRepository(reopened, namespace).load(prepared.key_sha256).journal_sha256 == observed.journal_sha256
    reopened.rollback()
    reopened.close()


def test_wrong_storage_namespace_cannot_fall_back_to_another_archive(connections, namespace, certificates):
    prepared = advance(certificates[0])
    writer = connections()
    store(writer, namespace, receipt(prepared))
    writer.close()
    reader = connections()
    with pytest.raises(JournalStorageError, match="repository_missing"):
        MariaDBJournalRepository(reader, str(uuid4())).load(prepared.key_sha256)
    reader.rollback()
    reader.close()


def test_late_committed_receipt_requires_new_explicit_revision_not_latest_guess(connections, namespace, certificates):
    prepared = advance(certificates[0])
    unknown = append_dispatch_event(start(prepared), event(prepared, "TRANSPORT_UNKNOWN", 2))
    late = receipt(prepared, late=True)
    writer = connections()
    store(writer, namespace, unknown)
    repository = MariaDBJournalRepository(writer, namespace)
    repository.append(prepared.key_sha256, late.events[-1], expected_journal_sha256=unknown.journal_sha256)
    writer.commit()
    writer.close()
    reader = connections()
    loaded = MariaDBJournalRepository(reader, namespace).load(prepared.key_sha256)
    with pytest.raises(selection.AdvanceSourceSelectionError, match="advance_source_revision_mismatch"):
        select(loaded, expected_journal_sha256=unknown.journal_sha256)
    assert select(loaded, expected_journal_sha256=late.journal_sha256).source_kind == "REPORTING_REQUEST_XML"
    reader.rollback()
    reader.close()


def test_uncommitted_same_connection_observation_does_not_prove_persistence(connections, namespace, certificates):
    prepared = advance(certificates[0])
    started = start(prepared)
    writer = connections()
    store(writer, namespace, started)
    completed = receipt(prepared)
    repository = MariaDBJournalRepository(writer, namespace)
    repository.append(prepared.key_sha256, completed.events[-1], expected_journal_sha256=started.journal_sha256)
    visible = repository.load(prepared.key_sha256)
    # This local contract intentionally cannot attest commit. Runtime adoption
    # MUST provide an audited committed-record source and owned transaction.
    assert select(visible).diagnostic_projection()["persistence_verified"] is False
    writer.rollback()
    writer.close()
    reader = connections()
    actual = MariaDBJournalRepository(reader, namespace).load(prepared.key_sha256)
    assert actual.journal_sha256 == started.journal_sha256
    with pytest.raises(selection.AdvanceSourceSelectionError, match="advance_source_response_unconfirmed"):
        select(actual)
    reader.rollback()
    reader.close()


def test_committed_rejected_receipt_is_not_an_original_accepted_artifact(connections, namespace, certificates):
    prepared = advance(certificates[0])
    observed = receipt(prepared, status=400)
    writer = connections()
    store(writer, namespace, observed)
    writer.close()
    reader = connections()
    loaded = MariaDBJournalRepository(reader, namespace).load(prepared.key_sha256)
    with pytest.raises(selection.AdvanceSourceSelectionError, match="advance_source_response_unconfirmed"):
        select(loaded)
    reader.rollback()
    reader.close()
