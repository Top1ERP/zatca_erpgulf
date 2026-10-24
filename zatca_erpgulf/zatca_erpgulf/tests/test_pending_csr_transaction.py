"""Owned local save lifecycle with synthetic SQL/keys/ACLs, no live resources."""

from dataclasses import replace
import inspect
import json
import pickle
import socket
import struct
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import pending_csr_transaction as transaction
from zatca_erpgulf.zatca_erpgulf import pending_csr_provider as pinned
from zatca_erpgulf.zatca_erpgulf import primary_receipt_provider as local_sql
from zatca_erpgulf.zatca_erpgulf.tests.test_pending_csr_access import access_case, Failed, Denied, PrivateFailure
from zatca_erpgulf.zatca_erpgulf.tests.test_pending_csr_password_state import configure_password_case
from zatca_erpgulf.zatca_erpgulf.tests.test_csr_draft import crypto, materials


def configure_transaction(case, monkeypatch):
    """Shared by fixture-owned native SQL composition, never an app provider."""
    monkeypatch.setattr(transaction, "frappe", case.runtime)
    monkeypatch.setattr(transaction, "_", lambda key: case.catalog[key] if case.lang == "ar" else key)
    case.transaction = transaction.PendingCSRStagingTransaction(case.scope, case.lookup, case.lease)
    return case


@pytest.fixture
def transaction_case(access_case, monkeypatch):
    def build(kind="company", environment="Production", engine="v15", password=False):
        case = access_case(kind, environment, engine)
        if password:
            configure_password_case(case)
        case.database_binding = pinned.PendingCSRDatabaseBinding(case.scope, "/tmp/SYNTHETIC-ONLY/pending.sock",
            1, 2, 1000, "synthetic_pending", 1, "50000000-0000-4000-8000-000000000001", "test-only-key")
        case.database._sock = SimpleNamespace(family=socket.AF_UNIX,
            getpeername=lambda: case.database_binding.unix_socket,
            getsockopt=lambda *args: struct.pack("iII", 42, 1000, 1000))
        execute = case.cursor.execute.side_effect
        def sql(statement, parameters=()):
            if statement.startswith("SET SESSION"):
                case.events.append(("provider-sql", statement))
            elif statement.startswith("SELECT @@session.innodb_lock_wait_timeout"):
                case.raw = (1, 1)
            elif statement.startswith("SELECT DATABASE()"):
                case.raw = (case.database_binding.database, 1, 0, 123)
            elif statement.startswith("SELECT site,registration_id"):
                case.raw = (case.scope.site, case.database_binding.registration_id)
            elif statement.startswith("SELECT key_id FROM"):
                case.raw = ("test-only-key",)
            else:
                return execute(statement, parameters)
        case.cursor.execute.side_effect = sql
        case.database.commit.side_effect = lambda: case.events.append(("commit",))
        case.database.rollback.side_effect = lambda: case.events.append(("rollback",))
        case.database.close.side_effect = lambda: case.events.append(("close",))
        monkeypatch.setattr(local_sql, "_check_socket", Mock())
        case.connect = Mock(return_value=case.database)
        monkeypatch.setattr(pinned.pymysql, "connect", case.connect)
        case.login = Mock(return_value=local_sql.ReceiptDatabaseCredentials("synthetic_user", "PRIVATE DB PASSWORD"))
        case.storage_keys = Mock(return_value=pinned.PendingCSRStorageKeys(case.scope, "test-only-key", case.cipher))
        case.lease = pinned.UnixPendingCSRResourceProvider(case.database_binding, case.login, case.storage_keys)
        return configure_transaction(case, monkeypatch)
    return build


def save(case):
    return case.transaction.save("TC", case.identity, case.sealed)


def no_parent_or_active_writes(case):
    for operation in ("commit", "rollback", "close"):
        getattr(case.runtime.db, operation).assert_not_called()
    for doc in case.documents.values():
        doc.save.assert_not_called()
        doc.db_set.assert_not_called()
    assert all("FOR UPDATE" in call.args[0] for call in case.cursor.execute.call_args_list if "FROM `__Auth`" in call.args[0])


@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("engine", ["v15", "v16"])
@pytest.mark.parametrize("password", [False, True])
def test_complete_staging_has_fresh_exact_checks_one_commit_one_close_and_metadata_only(transaction_case, kind, environment, engine, password):
    case = transaction_case(kind, environment, engine, password)
    before = dict(case.runtime.flags)
    result = save(case)
    assert result["state"] == "PENDING_CSR_TRANSACTION_COMPLETED_OBSERVATION"
    assert result["local_transaction_completed"] is True
    assert all(value is False for name, value in result.items() if name.endswith(("_verified", "_authorized", "_confirmed")))
    assert case.lookup.call_count == 4  # Initial, twice before commit, after closure.
    assert sum("SELECT slot_sha256" in call.args[0] for call in case.cursor.execute.call_args_list) == 2
    case.database.commit.assert_called_once()
    case.database.close.assert_called_once()
    case.database.rollback.assert_not_called()
    case.connect.assert_called_once()
    assert case.runtime.flags == before and case.visible == []
    assert "EXISTING TEST" not in json.dumps(result) and "PRIVATE" not in json.dumps(result)
    assert "TEST COMPANY" not in json.dumps(result) and "sealed" not in result
    no_parent_or_active_writes(case)


@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
@pytest.mark.parametrize("operation", ["read", "write"])
def test_early_row_denial_claims_no_connection_and_does_not_reuse_lease(transaction_case, kind, operation):
    case = transaction_case(kind)
    case.denied.add((case.target.doctype, case.target.name, operation))
    with pytest.raises(Denied) as error:
        save(case)
    assert error.value.__context__ is None and case.visible == [transaction.DENIED_MESSAGE]
    case.connect.assert_not_called()
    case.login.assert_not_called()
    case.database.rollback.assert_not_called()
    with pytest.raises(pinned.PendingCSRProviderError):
        case.lease(case.scope)
    no_parent_or_active_writes(case)


@pytest.mark.parametrize("fault", ["permission", "revision", "binding", "password", "envelope"])
@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
def test_precommit_exact_guard_refuses_drift_and_cleans_owned_work_without_commit(transaction_case, fault, kind):
    case = transaction_case(kind, password=True)
    lookup, calls = case.lookup.side_effect, []
    def changed(*args):
        selected = lookup(*args)
        calls.append(True)
        if len(calls) == 2:
            if fault == "permission":
                case.denied.add((case.target.doctype, case.target.name, "write"))
            elif fault == "revision":
                case.target.modified = "2026-10-24 11:00:01"
            elif fault == "binding":
                selected = replace(selected, source_rows_sha256="0" * 64)
            elif fault == "password":
                case.password_records[(case.target.doctype, case.target.name)] = (("custom_basic_auth_from_csid", 1, "ENCRYPTED TEST ROTATED"),)
            else:
                case.sealed = case.cipher.seal(case.draft, storage_namespace=case.scope.storage_namespace, key_id="test-only-key")
        return selected
    case.lookup.side_effect = changed
    with pytest.raises(Denied if fault == "permission" else Failed) as error:
        save(case)
    assert error.value.__context__ is None and len(case.visible) == 1
    case.database.commit.assert_not_called()
    case.database.rollback.assert_called_once()
    case.database.close.assert_called_once()
    no_parent_or_active_writes(case)


@pytest.mark.parametrize("fault", ["permission", "revision", "binding"])
def test_post_commit_drift_withholds_success_without_undoing_or_retrying_commit(transaction_case, fault):
    case = transaction_case()
    def changed():
        if fault == "permission":
            case.denied.add(("Company", case.company.name, "write"))
        elif fault == "revision":
            case.company.modified = "2026-10-24 11:00:01"
        else:
            case.binding = replace(case.binding, password_state_sha256="0" * 64)
    case.database.commit.side_effect = changed
    with pytest.raises(Denied if fault == "permission" else Failed):
        save(case)
    case.database.commit.assert_called_once()
    case.database.close.assert_called_once()
    case.database.rollback.assert_not_called()
    assert len(case.visible) == 1
    no_parent_or_active_writes(case)


@pytest.mark.parametrize("operation", ["commit", "close"])
def test_unknown_commit_or_close_outcome_is_never_converted_to_success_or_retried(transaction_case, operation):
    case = transaction_case()
    getattr(case.database, operation).side_effect = PrivateFailure("PRIVATE uncertain operation")
    with pytest.raises(Failed) as error:
        save(case)
    assert error.value.__context__ is None and case.visible == [transaction.FAILED_MESSAGE]
    case.database.commit.assert_called_once()
    case.database.close.assert_called_once()
    assert case.database.rollback.call_count == int(operation == "commit")
    with pytest.raises(Failed):
        save(case)
    case.connect.assert_called_once()
    case.database.commit.assert_called_once()
    case.database.close.assert_called_once()


@pytest.mark.parametrize("stage", ["precommit", "commit", "close"])
@pytest.mark.parametrize("stop", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_interruption_propagates_after_owned_cleanup_without_retry_or_popup(transaction_case, stage, stop):
    case = transaction_case()
    original = stop("PRIVATE interrupted")
    if stage == "precommit":
        lookup, calls = case.lookup.side_effect, []
        def interrupted(*args):
            calls.append(True)
            if len(calls) == 2:
                raise original
            return lookup(*args)
        case.lookup.side_effect = interrupted
    else:
        getattr(case.database, stage).side_effect = original
    with pytest.raises(stop) as raised:
        save(case)
    assert raised.value is original and case.visible == []
    assert case.database.commit.call_count == int(stage != "precommit")
    assert case.database.rollback.call_count == int(stage != "close")
    case.database.close.assert_called_once()


@pytest.mark.parametrize("operation", ["rollback", "close"])
@pytest.mark.parametrize("interrupt", [False, True])
def test_precommit_cleanup_attempts_both_operations_and_prioritizes_interruptions(transaction_case, operation, interrupt):
    case = transaction_case()
    lookup, calls = case.lookup.side_effect, []
    def fail(*args):
        calls.append(True)
        if len(calls) == 2:
            raise PrivateFailure("PRIVATE guard failure")
        return lookup(*args)
    case.lookup.side_effect = fail
    original = KeyboardInterrupt() if interrupt else PrivateFailure("PRIVATE cleanup")
    getattr(case.database, operation).side_effect = original
    with pytest.raises(KeyboardInterrupt if interrupt else Failed) as error:
        save(case)
    if interrupt:
        assert error.value is original
    else:
        assert error.value.__context__ is None
    case.database.rollback.assert_called_once()
    case.database.close.assert_called_once()
    case.database.commit.assert_not_called()


@pytest.mark.parametrize("stage", ["keys", "guard"])
def test_swallowed_reentrant_save_poisons_outer_operation_and_never_commits(transaction_case, stage):
    case = transaction_case()
    def reenter():
        try:
            save(case)
        except Failed:
            pass
    if stage == "keys":
        keys = case.storage_keys.return_value
        case.storage_keys.side_effect = lambda scope: (reenter(), keys)[1]
    else:
        lookup, calls = case.lookup.side_effect, []
        def changed(*args):
            calls.append(True)
            if len(calls) == 2:
                reenter()
            return lookup(*args)
        case.lookup.side_effect = changed
    with pytest.raises(Failed):
        save(case)
    assert case.visible == [transaction.FAILED_MESSAGE]
    case.database.commit.assert_not_called()
    case.database.close.assert_called_once()
    case.connect.assert_called_once()


def test_preused_or_other_claimed_lease_is_not_cleaned_by_another_coordinator(transaction_case):
    case = transaction_case()
    resources = case.lease(case.scope)
    with pytest.raises(Failed):
        save(case)
    assert not resources.connection.closed
    case.database.rollback.assert_not_called()
    case.database.close.assert_not_called()
    resources.connection.rollback()
    resources.connection.close()


def test_duplicate_coordinator_cannot_clean_or_acquire_the_original_owners_lease(transaction_case):
    case = transaction_case()
    other = transaction.PendingCSRStagingTransaction(case.scope, case.lookup, case.lease)
    token = object()
    case.lease._claim_for_transaction(token)
    with pytest.raises(Failed):
        other.save("TC", case.identity, case.sealed)
    case.connect.assert_not_called()
    case.database.rollback.assert_not_called()
    owned = case.lease._acquire_for_transaction(case.scope, token).connection
    owned.rollback()
    owned.close()


@pytest.mark.parametrize("denied", [False, True])
def test_arabic_display_single_popup_english_contract_and_private_child_cleanup_popups_muted(transaction_case, denied):
    case = transaction_case()
    case.lang = "ar"
    if denied:
        case.denied.add(("Company", case.company.name, "write"))
    else:
        lookup, calls = case.lookup.side_effect, []
        def failure(*args):
            calls.append(True)
            if len(calls) == 2:
                case.runtime.throw("PRIVATE child popup")
            return lookup(*args)
        case.lookup.side_effect = failure
        case.database.rollback.side_effect = lambda: case.runtime.throw("PRIVATE cleanup popup")
    with pytest.raises(Denied if denied else Failed) as error:
        save(case)
    expected = transaction.DENIED_MESSAGE if denied else transaction.FAILED_MESSAGE
    assert case.visible == [case.catalog[expected]] and expected.isascii()
    assert error.value.__context__ is None and "PRIVATE" not in str(error.value)


def test_coordinator_repr_pickle_and_no_whitelist_transport_generation_or_schema_install(transaction_case):
    case = transaction_case()
    assert "TEST COMPANY" not in repr(case.transaction)
    with pytest.raises(transaction.PendingCSRTransactionError):
        pickle.dumps(case.transaction)
    source = inspect.getsource(transaction)
    for forbidden in ("@frappe.whitelist", "requests.", "CREATE TABLE", "generate_private_key", ".seal(", "get_site_config("):
        assert forbidden not in source
