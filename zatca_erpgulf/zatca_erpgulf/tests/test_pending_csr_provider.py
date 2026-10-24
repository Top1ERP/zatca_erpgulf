"""Pinned pending resources with synthetic sockets/login/SQL; no live IO."""

from dataclasses import FrozenInstanceError, replace
import inspect
import pickle
import socket
import struct
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import pending_csr_provider as provider
from zatca_erpgulf.zatca_erpgulf import primary_receipt_provider as local_sql
from zatca_erpgulf.zatca_erpgulf.credential_bundle_access import CredentialStorageScope
from zatca_erpgulf.zatca_erpgulf.pending_csr import PendingCSRCipher
from zatca_erpgulf.zatca_erpgulf.tests.test_primary_receipt_provider import (
    scenario as local_scenario, binding as receipt_binding, SCOPE, REGISTRATION,
)


class PrivateFailure(Exception):
    def __str__(self):
        raise AssertionError("Never stringify protected acquisition diagnostics")


@pytest.fixture
def scenario(local_scenario):
    case = local_scenario
    case.binding = provider.PendingCSRDatabaseBinding(**{
        **vars(case.binding), "database": "synthetic_pending"}, storage_key_id="pending-test-key")
    case.target = (case.binding.database, 1, 0, 123)
    case.key_registration = (case.binding.storage_key_id,)
    case.cipher = PendingCSRCipher({"pending-test-key": b"Q" * 32})
    case.keys = Mock(return_value=provider.PendingCSRStorageKeys(SCOPE, case.binding.storage_key_id, case.cipher))
    execute = case.cursor.execute.side_effect
    def pending_sql(statement, values=None):
        if statement.startswith("SELECT key_id FROM"):
            assert "FROM zatca_pending_csr_storage_binding_v1 " in statement
            assert values == (SCOPE.storage_namespace,)
            case.cursor.fetchone.return_value = case.key_registration
        else:
            if statement.startswith("SELECT site,registration_id"):
                assert "FROM zatca_pending_csr_storage_binding_v1 " in statement
            execute(statement, values)
    case.cursor.execute.side_effect = pending_sql
    case.service = provider.UnixPendingCSRResourceProvider(case.binding, case.credentials, case.keys)
    return case


def test_single_use_fixed_unix_driver_pending_marker_then_keys_and_protected_caller_handoff(scenario):
    case = scenario
    def keys(scope):
        statements = [call.args[0] for call in case.cursor.execute.call_args_list]
        assert any(sql.startswith("SELECT key_id FROM") for sql in statements)
        assert not any("zatca_receipt_storage_binding_v1" in sql for sql in statements)
        return provider.PendingCSRStorageKeys(scope, case.binding.storage_key_id, case.cipher)
    case.keys.side_effect = keys
    result = case.service(SCOPE)
    assert case.service.resources is result and result.scope == SCOPE and result.cipher is case.cipher
    assert case.connect.call_args.kwargs == dict(unix_socket=case.binding.unix_socket,
        database="synthetic_pending", user="synthetic_user", password="PRIVATE-DB-PASSWORD",
        autocommit=False, charset="utf8mb4", connect_timeout=5, read_timeout=5, write_timeout=5,
        local_infile=False, read_default_file=None)
    case.keys.assert_called_once_with(SCOPE)
    case.raw.commit.assert_not_called()
    case.raw.rollback.assert_not_called()
    with pytest.raises(provider.PendingCSRProviderError, match="^pending_csr_provider_unusable$"):
        case.service(SCOPE)
    assert case.service.resources is result
    case.connect.assert_called_once()
    result.connection.rollback()
    result.connection.close()
    result.connection.close()  # Idempotent local closure, not another driver call.
    case.raw.rollback.assert_called_once()
    case.raw.close.assert_called_once()


@pytest.mark.parametrize("stage", ["scope", "json-scope", "socket", "credentials", "untyped-login", "driver"])
def test_before_handoff_faults_never_fall_back_or_request_storage_keys(scenario, stage):
    case, scope = scenario, SCOPE
    if stage == "scope":
        scope = CredentialStorageScope("other.test", SCOPE.storage_namespace)
    elif stage == "json-scope":
        scope = {"site": SCOPE.site, "storage_namespace": SCOPE.storage_namespace}
    elif stage == "socket":
        case.socket_check.side_effect = PrivateFailure("PRIVATE socket")
    elif stage == "credentials":
        case.credentials.side_effect = PrivateFailure("PRIVATE login")
    elif stage == "untyped-login":
        case.credentials.return_value = {"user": "PRIVATE", "password": "PRIVATE"}
    else:
        case.connect.side_effect = PrivateFailure("PRIVATE driver")
    with pytest.raises(provider.PendingCSRProviderError, match="^pending_csr_provider_acquisition$") as error:
        case.service(scope)
    assert error.value.__context__ is None and error.value.__cause__ is None
    case.keys.assert_not_called()
    case.raw.commit.assert_not_called()
    if stage in ("scope", "json-scope", "socket"):
        case.credentials.assert_not_called()
    if stage != "driver":
        case.connect.assert_not_called()
    with pytest.raises(provider.PendingCSRProviderError):
        case.service.resources
    with pytest.raises(provider.PendingCSRProviderError):
        case.service(SCOPE)
    assert case.connect.call_count <= 1


@pytest.mark.parametrize("fault", ["database", "server", "autocommit", "session", "site", "registration", "missing-marker",
    "key-marker", "key-marker-shape", "waits", "peer-family", "peer-uid", "peer-pid", "peer-path", "sql"])
def test_initial_target_pending_registration_or_peer_fault_cleans_only_new_handle_before_keys(scenario, fault):
    case = scenario
    if fault in ("database", "server", "autocommit", "session"):
        index, value = {"database": (0, "OTHER"), "server": (1, 9), "autocommit": (2, 1), "session": (3, True)}[fault]
        target = list(case.target)
        target[index] = value
        case.target = tuple(target)
    elif fault in ("site", "registration", "missing-marker"):
        case.registration = {"site": ("other.test", REGISTRATION), "registration": (SCOPE.site, "OTHER"), "missing-marker": None}[fault]
    elif fault in ("key-marker", "key-marker-shape"):
        case.key_registration = ("other-key",) if fault == "key-marker" else [case.binding.storage_key_id]
    elif fault == "waits":
        case.waits = (2, 1)
    elif fault == "peer-family":
        case.raw._sock.family = socket.AF_INET
    elif fault in ("peer-uid", "peer-pid"):
        case.raw._sock.getsockopt.return_value = struct.pack("iII", 0 if fault == "peer-pid" else 42,
            99 if fault == "peer-uid" else 1000, 1000)
    elif fault == "peer-path":
        case.raw._sock.getpeername.return_value = "/tmp/OTHER.sock"
    else:
        case.cursor.execute.side_effect = PrivateFailure("PRIVATE SQL")
    with pytest.raises(provider.PendingCSRProviderError) as error:
        case.service(SCOPE)
    assert error.value.__context__ is None
    case.keys.assert_not_called()
    case.raw.rollback.assert_called_once()
    case.raw.close.assert_called_once()
    case.raw.commit.assert_not_called()
    case.connect.assert_called_once()


@pytest.mark.parametrize("fault", ["missing", "json", "scope", "key-id", "private-error", "late-marker", "late-session"])
def test_storage_key_callback_must_match_scope_id_and_rechecked_connection(scenario, fault):
    case = scenario
    if fault == "private-error":
        case.keys.side_effect = PrivateFailure("PRIVATE keys")
    elif fault in ("late-marker", "late-session"):
        def late(scope):
            if fault == "late-marker":
                case.key_registration = ("other-key",)
            else:
                case.target = (*case.target[:3], 999)
            return provider.PendingCSRStorageKeys(scope, case.binding.storage_key_id, case.cipher)
        case.keys.side_effect = late
    else:
        values = {"missing": None, "json": {"key": "PRIVATE"},
            "scope": provider.PendingCSRStorageKeys(CredentialStorageScope("other.test", SCOPE.storage_namespace),
                case.binding.storage_key_id, case.cipher),
            "key-id": provider.PendingCSRStorageKeys(SCOPE, "other-key", PendingCSRCipher({"other-key": b"R" * 32}))}
        case.keys.return_value = values[fault]
    with pytest.raises(provider.PendingCSRProviderError) as error:
        case.service(SCOPE)
    assert error.value.__context__ is None
    case.raw.rollback.assert_called_once()
    case.raw.close.assert_called_once()
    case.raw.commit.assert_not_called()


@pytest.mark.parametrize("operation", ["cursor", "commit"])
@pytest.mark.parametrize("fault", ["session", "peer-pid", "database", "registration", "key-id", "waits", "socket"])
def test_changed_binding_after_handoff_poisoned_no_reset_reconnect_or_commit(scenario, operation, fault):
    case = scenario
    owned = case.service(SCOPE).connection
    sets = sum(call.args[0].startswith("SET SESSION") for call in case.cursor.execute.call_args_list)
    if fault == "session":
        case.target = (*case.target[:3], 999)
    elif fault == "peer-pid":
        case.raw._sock.getsockopt.return_value = struct.pack("iII", 43, 1000, 1000)
    elif fault == "database":
        case.target = ("OTHER", *case.target[1:])
    elif fault == "registration":
        case.registration = None
    elif fault == "key-id":
        case.key_registration = ("other-key",)
    elif fault == "waits":
        case.waits = (1, 2)
    else:
        case.socket_check.side_effect = PrivateFailure("PRIVATE replacement socket")
    with pytest.raises(provider.PendingCSRProviderError) as error:
        getattr(owned, operation)()
    assert error.value.__context__ is None
    with pytest.raises(provider.PendingCSRProviderError, match="^pending_csr_provider_unusable$"):
        owned.commit()
    case.raw.commit.assert_not_called()
    case.connect.assert_called_once()
    assert sum(call.args[0].startswith("SET SESSION") for call in case.cursor.execute.call_args_list) == sets == 2
    owned.rollback()
    owned.close()


@pytest.mark.parametrize("operation", ["cursor", "commit", "rollback", "close"])
def test_driver_failure_is_sanitized_without_retry(scenario, operation):
    case = scenario
    owned = case.service(SCOPE).connection
    getattr(case.raw, operation).side_effect = PrivateFailure("PRIVATE driver operation")
    with pytest.raises(provider.PendingCSRProviderError) as error:
        getattr(owned, operation)()
    assert error.value.__context__ is None and error.value.__cause__ is None
    if operation != "close":
        with pytest.raises(provider.PendingCSRProviderError):
            owned.cursor()
        owned.close()
    assert case.connect.call_count == 1


@pytest.mark.parametrize("stop", [KeyboardInterrupt, SystemExit, GeneratorExit])
@pytest.mark.parametrize("stage", ["credentials", "keys", "sql"])
def test_acquisition_interruption_propagates_and_cleans_owned_handle_only(scenario, stop, stage):
    case = scenario
    error = stop("PRIVATE interrupted")
    if stage == "sql":
        case.cursor.execute.side_effect = error
    else:
        getattr(case, stage).side_effect = error
    with pytest.raises(stop) as raised:
        case.service(SCOPE)
    assert raised.value is error
    assert case.raw.rollback.call_count == case.raw.close.call_count == (0 if stage == "credentials" else 1)
    with pytest.raises(provider.PendingCSRProviderError):
        case.service(SCOPE)


@pytest.mark.parametrize("operation", ["cursor", "commit"])
@pytest.mark.parametrize("stop", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_handoff_probe_interruption_permanently_poisons_handle(scenario, operation, stop):
    case = scenario
    owned = case.service(SCOPE).connection
    case.cursor.execute.side_effect = stop()
    with pytest.raises(stop):
        getattr(owned, operation)()
    with pytest.raises(provider.PendingCSRProviderError, match="^pending_csr_provider_unusable$"):
        owned.cursor()
    owned.rollback()
    owned.close()
    case.raw.commit.assert_not_called()


@pytest.mark.parametrize("cleanup", ["rollback", "close"])
@pytest.mark.parametrize("stop", [PrivateFailure, KeyboardInterrupt])
def test_failed_acquisition_attempts_both_cleanup_operations_with_interruption_priority(scenario, cleanup, stop):
    case = scenario
    case.key_registration = None
    getattr(case.raw, cleanup).side_effect = stop("PRIVATE cleanup")
    with pytest.raises(provider.PendingCSRProviderError if stop is PrivateFailure else KeyboardInterrupt) as error:
        case.service(SCOPE)
    if stop is PrivateFailure:
        assert error.value.__context__ is None
    case.raw.rollback.assert_called_once()
    case.raw.close.assert_called_once()


@pytest.mark.parametrize("stage", ["credentials", "keys"])
def test_reentrant_acquisition_even_if_swallowed_never_hands_off(scenario, stage):
    case = scenario
    mock = getattr(case, stage)
    value = mock.return_value
    def reentrant(scope):
        try:
            case.service(scope)
        except provider.PendingCSRProviderError:
            pass
        return value
    mock.side_effect = reentrant
    with pytest.raises(provider.PendingCSRProviderError):
        case.service(SCOPE)
    with pytest.raises(provider.PendingCSRProviderError):
        case.service.resources
    if stage == "credentials":
        case.connect.assert_not_called()
    else:
        case.raw.rollback.assert_called_once()
        case.raw.close.assert_called_once()


@pytest.mark.parametrize("changes", [{"storage_key_id": ""}, {"storage_key_id": "bad key"},
    {"database": "db;INJECT"}, {"unix_socket": "relative.sock"}, {"server_id": True}])
def test_binding_validation_is_static_without_io(changes):
    values = {**vars(receipt_binding()), "storage_key_id": "pending-test-key", **changes}
    with pytest.raises(provider.PendingCSRProviderError, match="^pending_csr_provider_binding$") as error:
        provider.PendingCSRDatabaseBinding(**values)
    assert error.value.__context__ is None


@pytest.mark.parametrize("cipher,key_id", [(None, "pending-test-key"), ({}, "pending-test-key"),
    (PendingCSRCipher({"other": b"T" * 32}), "pending-test-key")])
def test_scoped_keys_require_actual_selected_key_availability(cipher, key_id):
    with pytest.raises(provider.PendingCSRProviderError, match="^pending_csr_provider_keys$") as error:
        provider.PendingCSRStorageKeys(SCOPE, key_id, cipher)
    assert error.value.__context__ is None


def test_private_dependencies_repr_pickle_and_frozen_binding(scenario):
    case = scenario
    with pytest.raises(provider.PendingCSRProviderError):
        case.service.resources
    owned = case.service(SCOPE).connection
    for value in (case.binding, case.keys.return_value, case.service, owned):
        assert "PRIVATE" not in repr(value) and "synthetic_pending" not in repr(value) and "server.sock" not in repr(value)
        with pytest.raises(provider.PendingCSRProviderError, match="^pending_csr_provider_not_pickleable$"):
            pickle.dumps(value)
    with pytest.raises(FrozenInstanceError):
        case.binding.storage_key_id = "OTHER"
    owned.close()


@pytest.mark.parametrize("table", ["tabCompany", "bad;INJECT", "", None, {}])
def test_shared_probe_rejects_unreviewed_registration_tables_before_any_io(scenario, table):
    case = scenario
    with pytest.raises(local_sql.ReceiptProviderError):
        local_sql._check_connection(case.raw, case.binding, registration_table=table)
    case.socket_check.assert_not_called()
    case.cursor.execute.assert_not_called()


def test_no_runtime_installer_discovery_whitelist_connector_override_or_authority_client():
    source = inspect.getsource(provider)
    assert "CREATE TABLE" not in source and "@frappe.whitelist" not in source
    for forbidden in ("requests.", "get_site_config(", "get_password(", "get_doc(", "host=", "read_default_group="):
        assert forbidden not in source
