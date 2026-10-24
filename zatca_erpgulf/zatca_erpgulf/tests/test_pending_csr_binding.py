"""Restricted immutable source-history codec/repository, synthetic inputs only."""

import hashlib
import inspect
import json
import pickle
from dataclasses import replace
from types import SimpleNamespace

import pytest

from zatca_erpgulf.zatca_erpgulf import pending_csr_binding as history
from zatca_erpgulf.zatca_erpgulf import pending_csr_access as access
from zatca_erpgulf.zatca_erpgulf.pending_csr import PendingCSRStorageError
from zatca_erpgulf.zatca_erpgulf.pending_csr_repository import MariaDBPendingCSRRepository
from zatca_erpgulf.zatca_erpgulf.tests.test_pending_csr import (
    cipher, sealed, record, database, no_transaction_ownership, NAMESPACE, OTHER,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_csr_draft import crypto, sample, materials


def declaration(original, site="private.test"):
    return history.PendingCSRSourceBinding(history.CredentialStorageScope(site, original.storage_namespace),
        original.manifest, "1" * 64, original.key_id, "2" * 64)


def history_row(bound):
    context, encoded = bound.binding.manifest.context, bound.encode()
    return (context.slot.sha256, context.flow_id, bound.binding.scope.site, encoded,
            hashlib.sha256(encoded).hexdigest(), bound.envelope_sha256)


@pytest.fixture
def binding_case(sealed, cipher):
    binding = declaration(sealed)
    return SimpleNamespace(original=sealed, cipher=cipher, binding=binding,
                           record=history.PendingCSRBindingRecord.capture(binding, sealed))


def test_binding_type_is_reexported_without_second_policy_and_canonical_bytes_roundtrip(binding_case):
    case = binding_case
    assert access.PendingCSRSourceBinding is history.PendingCSRSourceBinding
    assert access.PendingCSRAccessError is history.PendingCSRAccessError
    assert history.decode_binding_record(case.record.encode()) == case.record
    assert case.record.matches(case.original)
    text = case.record.encode().decode()
    assert "BEGIN EC PRIVATE KEY" not in text and "ciphertext" not in text
    assert case.record.binding is not case.binding and case.record.binding.scope is not case.binding.scope


@pytest.mark.parametrize("kind", ["schema-bool", "schema-float", "schema-old", "source-old", "source-bool",
    "extra", "missing", "scope-extra", "bad-hash", "bad-envelope-hash", "manifest", "base64-space",
    "key", "site", "duplicate", "whitespace", "trailing", "unicode", "not-bytes", "oversize"])
def test_binding_decoder_is_bounded_strict_canonical_and_never_repairs(binding_case, kind):
    body = json.loads(binding_case.record.encode())
    if kind.startswith("schema-"):
        body["schema_version"] = {"schema-bool": True, "schema-float": 1.0, "schema-old": 0}[kind]
    elif kind == "source-old":
        body["source_schema"] = 1
    elif kind == "source-bool":
        body["source_schema"] = True
    elif kind == "extra":
        body["unexpected"] = "PRIVATE"
    elif kind == "missing":
        del body["key_id"]
    elif kind == "scope-extra":
        body["scope"]["unexpected"] = "PRIVATE"
    elif kind == "bad-hash":
        body["source_rows_sha256"] = "PRIVATE"
    elif kind == "bad-envelope-hash":
        body["envelope_sha256"] = "A" * 64
    elif kind == "manifest":
        body["manifest_b64"] = "e30="
    elif kind == "base64-space":
        body["manifest_b64"] += " "
    elif kind == "key":
        body["key_id"] = "../PRIVATE"
    elif kind == "site":
        body["scope"]["site"] = "https://PRIVATE"
    encoded = history._encode(body, history.MAX_BINDING_BYTES)
    encoded = {"duplicate": encoded[:-1] + b',"schema_version":1}', "whitespace": b" " + encoded,
        "trailing": encoded + b"{}", "unicode": b"\xff", "not-bytes": encoded.decode(),
        "oversize": b"x" * (history.MAX_BINDING_BYTES + 1)}.get(kind, encoded)
    with pytest.raises(PendingCSRStorageError, match="^pending_csr_binding$") as error:
        history.decode_binding_record(encoded)
    assert error.value.__context__ is None and "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("field", ["scope", "manifest", "key_id"])
def test_capture_rejects_mismatched_envelope_binding_before_sql(binding_case, field):
    case = binding_case
    changed = {"scope": replace(case.binding.scope, storage_namespace=OTHER), "key_id": "another-key",
        "manifest": replace(case.binding.manifest, context=replace(case.original.manifest.context, flow_id=OTHER))}[field]
    with pytest.raises(PendingCSRStorageError, match="^pending_csr_binding$"):
        history.PendingCSRBindingRecord.capture(replace(case.binding, **{field: changed}), case.original)


def test_resealing_same_material_is_not_the_same_historical_record(binding_case):
    case = binding_case
    resealed = case.cipher.seal(case.cipher.open(case.original), storage_namespace=NAMESPACE, key_id=case.original.key_id)
    assert case.record.matches(resealed) is False
    assert history.envelope_sha256(resealed) != case.record.envelope_sha256


@pytest.mark.parametrize("operation", ["new", "redelivery", "load"])
def test_repository_pair_operations_share_immutable_envelope_path_and_caller_transaction(binding_case, operation):
    case = binding_case
    rows = [(0,), record(case.original), history_row(case.record)]
    if operation == "new":
        rows = [(0,), None, None, record(case.original), history_row(case.record)]
    connection, cursor = database(rows)
    repo = MariaDBPendingCSRRepository(connection, NAMESPACE, case.cipher)
    result = repo.load_binding(case.binding.scope, case.original.manifest.context) if operation == "load" else repo.stage_bound(case.binding, case.original)
    assert result == case.binding
    inserts = [call.args[0] for call in cursor.execute.call_args_list if call.args[0].startswith("INSERT")]
    assert len(inserts) == (2 if operation == "new" else 0)
    assert not any("UPDATE" in sql for sql in inserts)  # No backfill after absent-read race.
    no_transaction_ownership(connection)


@pytest.mark.parametrize("half", ["envelope", "history"])
def test_repository_never_adopts_unbound_envelope_or_orphan_history(binding_case, half):
    case = binding_case
    connection, cursor = database([(0,), record(case.original) if half == "envelope" else None,
                                   history_row(case.record) if half == "history" else None])
    repo = MariaDBPendingCSRRepository(connection, NAMESPACE, case.cipher)
    with pytest.raises(PendingCSRStorageError, match="^pending_csr_binding_unpaired$"):
        repo.stage_bound(case.binding, case.original)
    assert all(call.args[0].startswith("SELECT") for call in cursor.execute.call_args_list)
    with pytest.raises(PendingCSRStorageError, match="^pending_csr_transaction_unusable$"):
        repo.stage_bound(case.binding, case.original)
    no_transaction_ownership(connection)


@pytest.mark.parametrize("field", ["source_rows_sha256", "password_state_sha256", "scope"])
def test_existing_pair_cannot_be_rebound_to_new_settings_or_site(binding_case, field):
    case = binding_case
    changed = replace(case.binding, **{field: replace(case.binding.scope, site="another.test") if field == "scope" else "3" * 64})
    connection, cursor = database([(0,), record(case.original), history_row(case.record)])
    repo = MariaDBPendingCSRRepository(connection, NAMESPACE, case.cipher)
    with pytest.raises(PendingCSRStorageError, match="^pending_csr_binding_conflict$"):
        repo.stage_bound(changed, case.original)
    assert all(call.args[0].startswith("SELECT") for call in cursor.execute.call_args_list)
    no_transaction_ownership(connection)


@pytest.mark.parametrize("column", range(6))
def test_restricted_history_columns_are_rechecked_not_reconstructed(binding_case, column):
    case = binding_case
    row = list(history_row(case.record))
    row[column] = b"PRIVATE" if column == 3 else "PRIVATE"
    connection, cursor = database([(0,), record(case.original), tuple(row)])
    with pytest.raises(PendingCSRStorageError) as error:
        MariaDBPendingCSRRepository(connection, NAMESPACE, case.cipher).load_binding(case.binding.scope, case.original.manifest.context)
    assert error.value.__context__ is None and "PRIVATE" not in str(error.value)
    no_transaction_ownership(connection)


@pytest.mark.parametrize("fault", ["site", "namespace", "revision", "flow", "missing", "row-shape"])
def test_load_requires_exact_context_scope_and_paired_history(binding_case, fault):
    case = binding_case
    scope, context = case.binding.scope, case.original.manifest.context
    if fault == "site":
        scope = replace(scope, site="another.test")
    elif fault == "namespace":
        scope = replace(scope, storage_namespace=OTHER)
    elif fault == "revision":
        context = replace(context, source_revision="2026-10-24 11:00:01")
    elif fault == "flow":
        context = replace(context, flow_id=OTHER)
    row = None if fault == "missing" else () if fault == "row-shape" else history_row(case.record)
    connection, cursor = database([(0,), record(case.original), row])
    with pytest.raises(PendingCSRStorageError):
        MariaDBPendingCSRRepository(connection, NAMESPACE, case.cipher).load_binding(scope, context)
    no_transaction_ownership(connection)


def test_private_repr_pickle_and_no_runtime_source_schema_http_or_transaction_ownership(binding_case):
    case = binding_case
    assert "private.test" not in repr(case.record) + repr(case.record.binding)
    with pytest.raises(PendingCSRStorageError, match="not_pickleable"):
        pickle.dumps(case.record)
    text = inspect.getsource(history)
    for forbidden in ("@frappe.whitelist", "requests.", "CREATE TABLE", ".commit(", ".rollback(", ".close(", "frappe.db", ".seal("):
        assert forbidden not in text
