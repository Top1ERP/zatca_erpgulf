"""SQL-boundary fault tests; real InnoDB coverage lives in the opt-in rehearsal."""

import ast
import inspect
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import journal_repository as repository
from zatca_erpgulf.zatca_erpgulf.dispatch_journal import DispatchJournal
from zatca_erpgulf.zatca_erpgulf.journal_storage import JournalStorageError, encode_candidate_context
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_dispatch_journal import event
from zatca_erpgulf.zatca_erpgulf.tests.test_issuance_candidate import candidate


NAMESPACE = "bfd1667a-c553-4917-af9a-6b19c3d88f39"


@pytest.fixture(scope="module")
def prepared(certificates):
    return candidate(certificates[0])


def mock_connection(prepared, *, row=None, autocommit=0, rows=()):
    empty = DispatchJournal(prepared)
    values = (prepared.manifest_sha256, encode_candidate_context(prepared), prepared.xml_bytes,
              prepared.artifact.file_sha256, prepared.context.scope.environment,
              prepared.context.scope.chain_id, prepared.artifact.uuid, str(prepared.artifact.icv),
              empty.journal_sha256, 0, None)
    cursor = Mock()
    cursor.__enter__ = Mock(return_value=cursor)
    cursor.__exit__ = Mock(return_value=False)
    cursor.fetchone.side_effect = [(autocommit,), values if row is None else row]
    cursor.fetchall.return_value = rows
    cursor.rowcount = 1
    connection = SimpleNamespace(cursor=Mock(return_value=cursor))
    return connection, cursor, values


@pytest.mark.parametrize("invalid", [None, [], "PRIVATE", NAMESPACE.upper(), "00000000-0000-0000-0000-000000000000"])
def test_namespace_must_be_explicit_and_canonical(invalid):
    connection = Mock()
    with pytest.raises(JournalStorageError, match="^repository_namespace$"):
        repository.MariaDBJournalRepository(connection, invalid)
    connection.cursor.assert_not_called()


@pytest.mark.parametrize("invalid", [None, [], "PRIVATE", "A" * 64, True])
def test_invalid_keys_fail_before_sql(prepared, invalid):
    connection = Mock()
    repo = repository.MariaDBJournalRepository(connection, NAMESPACE)
    with pytest.raises(JournalStorageError, match="^repository_key$"):
        repo.load(invalid)
    with pytest.raises(JournalStorageError, match="^repository_transaction_unusable$"):
        repo.put(prepared)
    connection.cursor.assert_not_called()


def test_autocommit_is_rejected_without_changing_session_settings(prepared):
    connection, cursor, _ = mock_connection(prepared, autocommit=1)
    repo = repository.MariaDBJournalRepository(connection, NAMESPACE)
    with pytest.raises(JournalStorageError, match="^repository_autocommit$"):
        repo.put(prepared)
    assert [call.args[0] for call in cursor.execute.call_args_list] == ["SELECT @@session.autocommit"]
    with pytest.raises(JournalStorageError, match="^repository_transaction_unusable$"):
        repo.load(prepared.key_sha256)


def test_bound_candidate_and_snapshot_reconstruct_without_live_lookup(prepared):
    connection, cursor, _ = mock_connection(prepared)
    loaded = repository.MariaDBJournalRepository(connection, NAMESPACE).put(prepared)
    assert loaded.candidate == prepared
    assert loaded.events == ()
    assert loaded.diagnostic_projection()["persistence_verified"] is False
    insert = cursor.execute.call_args_list[1]
    assert "PRIVATE" not in insert.args[0]
    assert prepared.xml_bytes in insert.args[1]
    assert NAMESPACE in insert.args[1]
    assert "FOR UPDATE" in cursor.execute.call_args_list[2].args[0]


@pytest.mark.parametrize("position,value,code", [
    (0, "0" * 64, "repository_candidate_fingerprint"),
    (3, "0" * 64, "repository_candidate_fingerprint"),
    (4, "Sandbox", "repository_candidate_fingerprint"),
    (5, NAMESPACE, "repository_candidate_fingerprint"),
    (6, NAMESPACE, "repository_candidate_fingerprint"),
    (7, "78", "repository_candidate_fingerprint"),
    (8, "0" * 64, "repository_journal_fingerprint"),
    (9, 1, "repository_journal_fingerprint"),
    (9, True, "repository_journal_fingerprint"),
    (10, NAMESPACE, "repository_journal_fingerprint"),
])
def test_denormalized_header_corruption_is_detected(prepared, position, value, code):
    _, _, values = mock_connection(prepared)
    values = list(values)
    values[position] = value
    connection, _, _ = mock_connection(prepared, row=tuple(values))
    with pytest.raises(JournalStorageError, match=f"^{code}$"):
        repository.MariaDBJournalRepository(connection, NAMESPACE).load(prepared.key_sha256)


@pytest.mark.parametrize("number,code", [
    (1062, "repository_unique_conflict"), (1205, "repository_lock_timeout"),
    (1213, "repository_deadlock"), (2006, "repository_database_error"),
    ("PRIVATE", "repository_database_error"),
])
def test_driver_errors_are_static_and_poison_transaction_handle(prepared, number, code):
    connection, cursor, _ = mock_connection(prepared)
    cursor.execute.side_effect = RuntimeError(number, "PRIVATE response/SQL/XML")
    repo = repository.MariaDBJournalRepository(connection, NAMESPACE)
    with pytest.raises(JournalStorageError) as error:
        repo.load(prepared.key_sha256)
    assert str(error.value) == code
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__
    with pytest.raises(JournalStorageError, match="^repository_transaction_unusable$"):
        repo.put(prepared)


def test_stale_expected_hash_prevents_new_event_insert(prepared):
    connection, cursor, _ = mock_connection(prepared)
    with pytest.raises(JournalStorageError, match="^repository_stale_journal$"):
        repository.MariaDBJournalRepository(connection, NAMESPACE).append(
            prepared.key_sha256, event(prepared), expected_journal_sha256="0" * 64,
        )
    assert not any("INSERT" in call.args[0] for call in cursor.execute.call_args_list)


def test_cas_failure_requires_full_rollback_not_partial_success(prepared):
    connection, cursor, _ = mock_connection(prepared)
    cursor.rowcount = 0
    repo = repository.MariaDBJournalRepository(connection, NAMESPACE)
    with pytest.raises(JournalStorageError, match="^repository_compare_and_swap$"):
        repo.append(prepared.key_sha256, event(prepared), expected_journal_sha256=DispatchJournal(prepared).journal_sha256)
    with pytest.raises(JournalStorageError, match="^repository_transaction_unusable$"):
        repo.load(prepared.key_sha256)


def test_repository_never_manages_transactions_schema_or_dispatch():
    tree = ast.parse(inspect.getsource(repository))
    calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert not calls.intersection({"commit", "rollback", "begin", "connect", "post", "get_doc", "save"})
    queries = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    assert not any(value.startswith(("CREATE TABLE", "DROP ", "DELETE ", "START TRANSACTION", "SET ")) for value in queries)
    assert not any("tabSales Invoice" in value or "tabPOS Invoice" in value for value in queries)
