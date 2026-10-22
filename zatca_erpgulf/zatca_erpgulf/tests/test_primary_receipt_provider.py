"""Explicit endpoint/peer/SQL target checks; all IO mocked, no live discovery."""

import ast
from dataclasses import FrozenInstanceError
import inspect
import pickle
import socket
import stat
import struct
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import primary_receipt_provider as provider
from zatca_erpgulf.zatca_erpgulf.credential_bundle_access import CredentialStorageScope


SCOPE = CredentialStorageScope("private.test", "31234567-1234-4123-8123-123456789abc")
REGISTRATION = "50000000-0000-4000-8000-000000000001"


def binding(**changes):
    values = dict(scope=SCOPE, unix_socket="/tmp/SYNTHETIC-ONLY/server.sock", socket_device=1,
        socket_inode=2, socket_uid=1000, database="synthetic_receipts", server_id=1, registration_id=REGISTRATION)
    values.update(changes)
    return provider.ReceiptDatabaseBinding(**values)


@pytest.fixture
def scenario(monkeypatch):
    selected = binding()
    cursor = Mock()
    cursor.__enter__ = Mock(return_value=cursor)
    cursor.__exit__ = Mock(return_value=False)
    raw = SimpleNamespace(cursor=Mock(return_value=cursor), commit=Mock(), rollback=Mock(), close=Mock())
    raw._sock = SimpleNamespace(family=socket.AF_UNIX, getpeername=Mock(return_value=selected.unix_socket),
        getsockopt=Mock(return_value=struct.pack("iII", 42, 1000, 1000)))
    case = SimpleNamespace(binding=selected, raw=raw, cursor=cursor, target=(selected.database, 1, 0, 123),
        registration=(SCOPE.site, REGISTRATION), waits=(2, 2))
    def execute(sql, values=None):
        if sql in ("SET SESSION innodb_lock_wait_timeout=2", "SET SESSION lock_wait_timeout=2"):
            pass  # Read-back result is independently supplied for drift/error tests.
        elif sql == "SELECT @@session.innodb_lock_wait_timeout,@@session.lock_wait_timeout":
            cursor.fetchone.return_value = case.waits
        elif sql.startswith("SELECT DATABASE()"):
            cursor.fetchone.return_value = case.target
        elif sql.startswith("SELECT site,registration_id"):
            assert values == (SCOPE.storage_namespace,)
            cursor.fetchone.return_value = case.registration
        else:
            raise AssertionError("No unreviewed SQL")
    cursor.execute.side_effect = execute
    case.socket_check = Mock()
    monkeypatch.setattr(provider, "_check_socket", case.socket_check)
    case.credentials = Mock(return_value=provider.ReceiptDatabaseCredentials("synthetic_user", "PRIVATE-DB-PASSWORD"))
    case.connect = Mock(return_value=raw)
    monkeypatch.setattr(provider.pymysql, "connect", case.connect)
    case.service = provider.UnixPrimaryReceiptProvider(selected, case.credentials)
    return case


def test_direct_fresh_driver_has_fixed_unix_target_and_no_fallback_options(scenario):
    case = scenario
    one, two = case.service(SCOPE), case.service(SCOPE)
    assert one is not two and case.connect.call_count == 2
    assert case.connect.call_args.kwargs == dict(unix_socket=case.binding.unix_socket,
        database="synthetic_receipts", user="synthetic_user", password="PRIVATE-DB-PASSWORD",
        autocommit=False, charset="utf8mb4", connect_timeout=5, read_timeout=5, write_timeout=5,
        local_infile=False, read_default_file=None)
    case.credentials.assert_called_with(SCOPE)
    case.raw.commit.assert_not_called()
    one.rollback()
    one.close()
    two.close()


@pytest.mark.parametrize("stage", ["scope", "socket", "credentials", "driver"])
def test_acquisition_failure_before_handoff_is_static_and_has_no_fallback(scenario, stage):
    case = scenario
    scope = SCOPE
    if stage == "scope":
        scope = CredentialStorageScope("other.test", SCOPE.storage_namespace)
    elif stage == "socket":
        case.socket_check.side_effect = RuntimeError("PRIVATE path")
    elif stage == "credentials":
        case.credentials.side_effect = RuntimeError("PRIVATE secret provider")
    else:
        case.connect.side_effect = RuntimeError("PRIVATE login/target")
    with pytest.raises(provider.ReceiptProviderError, match="^receipt_provider_acquisition$") as error:
        case.service(scope)
    assert error.value.__context__ is None and "PRIVATE" not in str(error.value)
    if stage in ("scope", "socket"):
        case.credentials.assert_not_called()
    if stage != "driver":
        case.connect.assert_not_called()
    else:
        case.connect.assert_called_once()
    case.raw.commit.assert_not_called()


@pytest.mark.parametrize("fault", ["database", "server", "autocommit", "session_type", "registration", "site", "missing",
    "peer_family", "peer_path", "peer_uid", "peer_pid", "peer_parse", "sql"])
def test_bad_target_or_registration_cleans_owned_connection_before_return(scenario, fault):
    case = scenario
    target = list(case.target)
    if fault in ("database", "server", "autocommit", "session_type"):
        index, value = {"database": (0, "FOREIGN"), "server": (1, 9), "autocommit": (2, 1), "session_type": (3, True)}[fault]
        target[index] = value
        case.target = tuple(target)
    elif fault in ("registration", "site", "missing"):
        case.registration = {"registration": (SCOPE.site, "OTHER"), "site": ("other.test", REGISTRATION), "missing": None}[fault]
    elif fault == "peer_family":
        case.raw._sock.family = socket.AF_INET
    elif fault == "peer_path":
        case.raw._sock.getpeername.return_value = "/tmp/FOREIGN.sock"
    elif fault in ("peer_uid", "peer_pid", "peer_parse"):
        case.raw._sock.getsockopt.return_value = {"peer_uid": struct.pack("iII", 42, 99, 1000),
            "peer_pid": struct.pack("iII", 0, 1000, 1000), "peer_parse": b"PRIVATE malformed"}[fault]
    else:
        case.cursor.execute.side_effect = RuntimeError("PRIVATE SQL/DB")
    with pytest.raises(provider.ReceiptProviderError) as error:
        case.service(SCOPE)
    assert error.value.__context__ is None
    case.raw.rollback.assert_called_once()
    case.raw.close.assert_called_once()
    case.raw.commit.assert_not_called()
    case.connect.assert_called_once()


@pytest.mark.parametrize("fault", ["session", "peer_pid", "database", "registration", "socket"])
@pytest.mark.parametrize("operation", ["cursor", "commit"])
def test_recheck_after_handoff_poisoned_handle_never_commits_or_repairs(scenario, fault, operation):
    case = scenario
    owned = case.service(SCOPE)
    if fault == "session":
        case.target = (*case.target[:3], 321)
    elif fault == "peer_pid":
        case.raw._sock.getsockopt.return_value = struct.pack("iII", 43, 1000, 1000)
    elif fault == "database":
        case.target = ("FOREIGN", *case.target[1:])
    elif fault == "registration":
        case.registration = None
    else:
        case.socket_check.side_effect = RuntimeError("PRIVATE changed socket")
    with pytest.raises(provider.ReceiptProviderError) as error:
        getattr(owned, operation)()
    assert error.value.__context__ is None
    case.raw.commit.assert_not_called()
    owned.rollback()
    with pytest.raises(provider.ReceiptProviderError, match="receipt_provider_unusable"):
        owned.cursor()
    owned.close()
    case.connect.assert_called_once()


def test_commit_error_is_not_retried_and_owned_cleanup_is_still_available(scenario):
    owned = scenario.service(SCOPE)
    scenario.raw.commit.side_effect = RuntimeError("PRIVATE unknown commit")
    with pytest.raises(provider.ReceiptProviderError, match="receipt_provider_commit") as error:
        owned.commit()
    assert error.value.__context__ is None
    with pytest.raises(provider.ReceiptProviderError, match="receipt_provider_unusable"):
        owned.commit()
    scenario.raw.commit.assert_called_once()
    owned.rollback()
    owned.close()


@pytest.mark.parametrize("cleanup", ["rollback", "close"])
def test_failed_acquisition_attempts_both_owned_cleanup_operations(scenario, cleanup):
    scenario.registration = None
    getattr(scenario.raw, cleanup).side_effect = RuntimeError("PRIVATE cleanup failure")
    with pytest.raises(provider.ReceiptProviderError, match="receipt_provider_acquisition") as error:
        scenario.service(SCOPE)
    assert error.value.__context__ is None
    scenario.raw.rollback.assert_called_once()
    scenario.raw.close.assert_called_once()
    scenario.raw.commit.assert_not_called()


def test_interruption_after_acquisition_cleans_only_its_new_owned_handle(scenario):
    scenario.cursor.execute.side_effect = KeyboardInterrupt("Synthetic probe interruption")
    with pytest.raises(KeyboardInterrupt):
        scenario.service(SCOPE)
    scenario.raw.rollback.assert_called_once()
    scenario.raw.close.assert_called_once()
    scenario.connect.assert_called_once()


@pytest.mark.parametrize("credentials", [None, {"user": "PRIVATE", "password": "PRIVATE"}])
def test_untyped_credentials_cannot_reach_the_driver(scenario, credentials):
    scenario.credentials.return_value = credentials
    with pytest.raises(provider.ReceiptProviderError):
        scenario.service(SCOPE)
    scenario.connect.assert_not_called()


def test_json_scope_cannot_invoke_credentials_or_connection(scenario):
    with pytest.raises(provider.ReceiptProviderError):
        scenario.service({"site": SCOPE.site, "storage_namespace": SCOPE.storage_namespace})
    scenario.credentials.assert_not_called()
    scenario.connect.assert_not_called()


@pytest.mark.parametrize("changes", [{"unix_socket": "relative.sock"}, {"unix_socket": "/tmp/../foreign.sock"},
    {"unix_socket": "/" + "x" * 100}, {"database": "db;INJECT"}, {"database": ""}, {"server_id": True},
    {"socket_inode": 0}, {"socket_uid": -1}, {"registration_id": "PRIVATE"}, {"scope": {"site": "private.test"}}])
def test_bad_declarations_are_rejected_without_any_io(changes):
    with pytest.raises(provider.ReceiptProviderError, match="receipt_provider_binding") as error:
        binding(**changes)
    assert error.value.__context__ is None


@pytest.mark.parametrize("user,password", [(None, ""), ("x;inject", ""), ("root", None), ("root", "x\x00y"), ("root", "x" * 4097)])
def test_credential_shape_does_not_allow_dsn_or_default_discovery(user, password):
    with pytest.raises(provider.ReceiptProviderError, match="receipt_provider_credentials"):
        provider.ReceiptDatabaseCredentials(user, password)


@pytest.mark.parametrize("change", [None, "regular_file", "symlink", "parent_symlink", "device", "inode", "owner", "missing"])
def test_actual_socket_observation_rejects_changed_or_aliased_paths(monkeypatch, change):
    selected = binding()
    observed = SimpleNamespace(st_mode=stat.S_IFSOCK, st_dev=1, st_ino=2, st_uid=1000)
    realpath = selected.unix_socket
    if change in ("regular_file", "symlink"):
        observed.st_mode = stat.S_IFREG if change == "regular_file" else stat.S_IFLNK
    elif change == "parent_symlink":
        realpath = "/tmp/FOREIGN/server.sock"
    elif change in ("device", "inode", "owner"):
        setattr(observed, {"device": "st_dev", "inode": "st_ino", "owner": "st_uid"}[change], 99)
    lstat = Mock(return_value=observed)
    if change == "missing":
        lstat.side_effect = FileNotFoundError("PRIVATE socket")
    monkeypatch.setattr(provider, "os", SimpleNamespace(lstat=lstat, path=SimpleNamespace(realpath=lambda path: realpath)))
    if change is None:
        provider._check_socket(selected)
    else:
        with pytest.raises((provider.ReceiptProviderError, FileNotFoundError)):
            provider._check_socket(selected)
    lstat.assert_called_once_with(selected.unix_socket)


def test_credentials_and_bindings_and_handles_are_protected_frozen_and_nonpickleable(scenario):
    owned = scenario.service(SCOPE)
    for value in (scenario.binding, scenario.credentials.return_value, scenario.service, owned):
        assert "PRIVATE" not in repr(value) and "synthetic_receipts" not in repr(value)
        with pytest.raises(provider.ReceiptProviderError, match="receipt_provider_not_pickleable"):
            pickle.dumps(value)
    with pytest.raises(FrozenInstanceError):
        scenario.binding.database = "FOREIGN"
    owned.close()
    with pytest.raises(provider.ReceiptProviderError, match="receipt_provider_unusable"):
        owned.cursor()


def test_no_automatic_installation_dispatch_or_framework_config_discovery():
    source = inspect.getsource(provider)
    tree = ast.parse(source)
    calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert not calls.intersection({"post", "get_site_config", "get_doc", "get_password", "ping", "execute_many"})
    assert "CREATE TABLE" not in source and "frappe.db" not in source


def test_session_waits_are_set_before_any_registration_lock_and_never_committed(scenario):
    owned = scenario.service(SCOPE)
    statements = [call.args[0] for call in scenario.cursor.execute.call_args_list]
    assert statements[:3] == ["SET SESSION innodb_lock_wait_timeout=2", "SET SESSION lock_wait_timeout=2",
        "SELECT @@session.innodb_lock_wait_timeout,@@session.lock_wait_timeout"]
    assert all("GLOBAL" not in sql for sql in statements)
    assert statements.index("SELECT @@session.innodb_lock_wait_timeout,@@session.lock_wait_timeout") < next(
        index for index, sql in enumerate(statements) if "FOR UPDATE" in sql)
    scenario.raw.commit.assert_not_called()
    owned.close()


@pytest.mark.parametrize("waits", [None, (), (2,), [2, 2], (True, 2), (2, False), ("2", 2), (2.0, 2), (0, 2), (2, 0), (3, 2), (2, 3)])
def test_incorrect_or_unreadable_lock_wait_policy_fails_acquisition_with_owned_cleanup(scenario, waits):
    scenario.waits = waits
    with pytest.raises(provider.ReceiptProviderError, match="^receipt_provider_acquisition$") as raised:
        scenario.service(SCOPE)
    assert raised.value.__context__ is None
    scenario.raw.rollback.assert_called_once()
    scenario.raw.close.assert_called_once()
    scenario.raw.commit.assert_not_called()
    assert not any("FOR UPDATE" in call.args[0] for call in scenario.cursor.execute.call_args_list)


@pytest.mark.parametrize("operation", ["cursor", "commit"])
@pytest.mark.parametrize("waits", [(0, 2), (2, 0), (5, 2), (2, 5)])
def test_changed_waits_poison_owned_handle_without_reset_reconnect_or_retry(scenario, operation, waits):
    owned = scenario.service(SCOPE)
    before_sets = sum(call.args[0].startswith("SET SESSION") for call in scenario.cursor.execute.call_args_list)
    scenario.waits = waits
    with pytest.raises(provider.ReceiptProviderError, match="^receipt_provider_check$"):
        getattr(owned, operation)()
    scenario.raw.commit.assert_not_called()
    scenario.connect.assert_called_once()
    assert sum(call.args[0].startswith("SET SESSION") for call in scenario.cursor.execute.call_args_list) == before_sets == 2
    with pytest.raises(provider.ReceiptProviderError, match="^receipt_provider_unusable$"):
        owned.cursor()
    owned.rollback()
    owned.close()


@pytest.mark.parametrize("statement", ["SET SESSION innodb_lock_wait_timeout=2", "SET SESSION lock_wait_timeout=2",
    "SELECT @@session.innodb_lock_wait_timeout,@@session.lock_wait_timeout"])
@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt, SystemExit])
def test_wait_configuration_or_probe_error_always_cleans_owned_acquisition(scenario, statement, error_type):
    execute = scenario.cursor.execute.side_effect
    error = error_type("PRIVATE SQL wait error")
    def fail(sql, values=None):
        if sql == statement:
            raise error
        return execute(sql, values)
    scenario.cursor.execute.side_effect = fail
    expected = provider.ReceiptProviderError if error_type is RuntimeError else error_type
    with pytest.raises(expected) as raised:
        scenario.service(SCOPE)
    if error_type is RuntimeError:
        assert str(raised.value) == "receipt_provider_acquisition" and raised.value.__context__ is None
    else:
        assert raised.value is error
    scenario.raw.rollback.assert_called_once()
    scenario.raw.close.assert_called_once()
    scenario.raw.commit.assert_not_called()
