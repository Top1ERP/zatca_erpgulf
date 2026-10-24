"""Read-only stored-pair review with fixed synthetic ACL/SQL/material fixtures."""

import json
from dataclasses import replace

import pytest

from zatca_erpgulf.zatca_erpgulf import pending_csr_access as access
from zatca_erpgulf.zatca_erpgulf import pending_csr_transaction as transaction
from zatca_erpgulf.zatca_erpgulf.pending_csr import PendingCSRStorageError
from zatca_erpgulf.zatca_erpgulf.pending_csr_binding import PendingCSRBindingRecord
from zatca_erpgulf.zatca_erpgulf.pending_csr_repository import MariaDBPendingCSRRepository
from zatca_erpgulf.zatca_erpgulf.tests.test_pending_csr_creation import creation_case
from zatca_erpgulf.zatca_erpgulf.tests.test_pending_csr_transaction import transaction_case, no_parent_or_active_writes
from zatca_erpgulf.zatca_erpgulf.tests.test_pending_csr_access import access_case, Failed, Denied, PrivateFailure
from zatca_erpgulf.zatca_erpgulf.tests.test_pending_csr_binding import binding_case, history_row
from zatca_erpgulf.zatca_erpgulf.tests.test_pending_csr import (
    cipher, sealed, record, database, no_transaction_ownership, NAMESPACE,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_csr_draft import crypto, sample, materials


STATES = {"exact": "PAIR_EXACT_OBSERVED", "absent": "PAIR_ABSENT_OBSERVED",
          "envelope": "ENVELOPE_ONLY_OBSERVED", "history": "BINDING_ONLY_OBSERVED",
          "conflict": "PAIR_CONFLICT_OBSERVED"}


def configure_pair(case, state):
    envelope = (case.cipher.seal(case.draft, storage_namespace=case.scope.storage_namespace,
                                key_id="test-only-key") if state == "conflict" else case.sealed)
    case.envelope_row = envelope if state not in ("absent", "history") else None
    case.history_record = (PendingCSRBindingRecord.capture(case.binding, envelope)
                           if state not in ("absent", "envelope") else None)
    sql = case.cursor.execute.side_effect
    def read_only(statement, parameters=()):
        assert statement.startswith(("SELECT ", "SET SESSION ")), "Pair review must never stage or repair"
        return sql(statement, parameters)
    case.cursor.execute.side_effect = read_only
    case.database.commit.side_effect = AssertionError("Pair review must never commit")
    return case


def review(case):
    return case.transaction.observe_bound("TC", case.identity, case.sealed)


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
@pytest.mark.parametrize("engine", ["v15", "v16"])
@pytest.mark.parametrize("password", [False, True])
def test_owned_pair_review_uses_current_acl_and_only_exact_stored_history_without_external_lookup(creation_case, state, kind, engine, password):
    case = configure_pair(creation_case(kind, engine=engine, password=password), state)
    before = dict(case.runtime.flags)
    result = review(case)
    assert result["state"] == "PENDING_CSR_BOUND_REVIEW_OBSERVATION"
    assert result["pair_observation"] == STATES[state] and result["local_read_transaction_closed"] is True
    assert result["original_source_binding_observed"] is (state == "exact")
    assert result["password_backing_state_match_observed"] is (state == "exact")
    assert result["current_password_backing_stable_observed"] is True
    assert "local_transaction_completed" not in result and "binding" not in result
    assert all(value is False for name, value in result.items() if name.endswith(("_verified", "_authorized", "_confirmed")))
    assert "TEST COMPANY" not in json.dumps(result) and "source_rows_sha256" not in result
    assert "password_state_sha256" not in result and "PRIVATE" not in json.dumps(result)
    case.database.commit.assert_not_called()
    case.database.rollback.assert_called_once()
    case.database.close.assert_called_once()
    case.lookup.assert_not_called()
    assert case.visible == [] and case.runtime.flags == before
    assert ("envelope-insert",) not in case.events and ("history-insert",) not in case.events
    no_parent_or_active_writes(case)
    with pytest.raises(Failed):
        case.transaction.create_bound("TC", case.identity, case.sealed)
    case.connect.assert_called_once()  # A review owner cannot become a writer.


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
def test_pair_review_environment_is_retained_not_rerouted_or_sent(creation_case, environment):
    case = configure_pair(creation_case(environment=environment), "exact")
    assert review(case)["environment"] == environment
    case.database.commit.assert_not_called()


@pytest.mark.parametrize("state", STATES)
def test_repository_pair_classification_is_select_only_and_returns_binding_only_for_exact(binding_case, state):
    case = binding_case
    envelope = (case.cipher.seal(case.cipher.open(case.original), storage_namespace=NAMESPACE,
        key_id=case.original.key_id) if state == "conflict" else case.original)
    bound = PendingCSRBindingRecord.capture(case.binding, envelope)
    rows = [(0,), None if state in ("absent", "history") else record(envelope),
            None if state in ("absent", "envelope") else history_row(bound)]
    connection, cursor = database(rows)
    result = MariaDBPendingCSRRepository(connection, NAMESPACE, case.cipher).observe_bound(case.binding.scope, case.original)
    assert result == (STATES[state], case.binding if state == "exact" else None)
    assert all(call.args[0].startswith("SELECT ") for call in cursor.execute.call_args_list)
    no_transaction_ownership(connection)


@pytest.mark.parametrize("fault", ["input", "ciphertext", "history", "pair-mismatch", "site", "sql"])
def test_corruption_and_sql_faults_never_become_absence_half_or_conflict(binding_case, fault):
    case = binding_case
    original, envelope, bound = case.original, case.original, case.record
    if fault in ("input", "ciphertext"):
        bad = replace(original, ciphertext=original.ciphertext[:-1] + bytes([original.ciphertext[-1] ^ 1]))
        if fault == "input":
            original = bad
        else:
            envelope = bad
    elif fault == "pair-mismatch":
        envelope = case.cipher.seal(case.cipher.open(original), storage_namespace=NAMESPACE, key_id=original.key_id)
    elif fault == "site":
        bound = PendingCSRBindingRecord.capture(replace(case.binding, scope=replace(case.binding.scope, site="other.test")), original)
    row = () if fault == "history" else history_row(bound)
    connection, cursor = database([(0,), record(envelope), row])
    if fault == "sql":
        cursor.execute.side_effect = PrivateFailure("PRIVATE")
    repo = MariaDBPendingCSRRepository(connection, NAMESPACE, case.cipher)
    with pytest.raises(PendingCSRStorageError) as error:
        repo.observe_bound(case.binding.scope, original)
    assert error.value.__context__ is None and "PRIVATE" not in str(error.value)
    count = cursor.execute.call_count
    with pytest.raises(PendingCSRStorageError, match="^pending_csr_transaction_unusable$"):
        repo.observe_bound(case.binding.scope, case.original)
    assert cursor.execute.call_count == count
    no_transaction_ownership(connection)


@pytest.mark.parametrize("field", ["source_rows_sha256", "password_state_sha256"])
def test_exact_historical_binding_must_match_current_source_and_backing_not_recapture(creation_case, field):
    case = configure_pair(creation_case(password=True), "exact")
    changed = replace(case.binding, **{field: "3" * 64})
    case.history_record = PendingCSRBindingRecord.capture(changed, case.sealed)
    with pytest.raises(Failed) as error:
        review(case)
    assert error.value.__context__ is None and case.visible == [transaction.REVIEW_FAILED_MESSAGE]
    case.lookup.assert_not_called()
    case.database.commit.assert_not_called()


@pytest.mark.parametrize("permission", ["read", "write"])
@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
def test_pair_review_normal_permission_precedes_keys_or_stored_source_observation(creation_case, permission, kind):
    case = configure_pair(creation_case(kind), "exact")
    case.denied.add((case.target.doctype, case.target.name, permission))
    with pytest.raises(Denied):
        review(case)
    case.connect.assert_not_called()
    case.lookup.assert_not_called()
    assert case.visible == [transaction.REVIEW_DENIED_MESSAGE]
    no_parent_or_active_writes(case)


@pytest.mark.parametrize("state", ["exact", "absent", "envelope", "history", "conflict"])
@pytest.mark.parametrize("fault", ["password", "classification"])
def test_pair_review_final_guard_rejects_current_backing_or_pair_classification_drift(creation_case, monkeypatch, state, fault):
    case = configure_pair(creation_case(password=True), state)
    original, calls = access._verify_locked_rows, []
    def change(connection, rows):
        original(connection, rows)
        calls.append(True)
        if len(calls) == 2:
            if fault == "password":
                case.password_records[(case.target.doctype, case.target.name)] = (("custom_basic_auth_from_csid", 1, "ENCRYPTED TEST ROTATED"),)
            elif state == "exact":
                case.envelope_row = case.history_record = None
            else:
                case.envelope_row = case.sealed
                case.history_record = PendingCSRBindingRecord.capture(case.binding, case.sealed)
    monkeypatch.setattr(access, "_verify_locked_rows", change)
    with pytest.raises(Failed):
        review(case)
    case.database.commit.assert_not_called()
    case.database.rollback.assert_called_once()
    case.database.close.assert_called_once()
    case.lookup.assert_not_called()


@pytest.mark.parametrize("operation", ["rollback", "close"])
@pytest.mark.parametrize("stop", [None, KeyboardInterrupt, SystemExit, GeneratorExit])
def test_pair_review_unknown_cleanup_or_interruptions_never_disclose_or_retry(creation_case, operation, stop):
    case = configure_pair(creation_case(), "exact")
    original = stop("PRIVATE") if stop else PrivateFailure("PRIVATE")
    getattr(case.database, operation).side_effect = original
    with pytest.raises(stop or Failed) as error:
        review(case)
    if stop:
        assert error.value is original and case.visible == []
    else:
        assert error.value.__context__ is None and case.visible == [transaction.REVIEW_FAILED_MESSAGE]
    case.database.commit.assert_not_called()
    case.database.rollback.assert_called_once()
    case.database.close.assert_called_once()


@pytest.mark.parametrize("fault", ["permission", "revision"])
def test_pair_review_post_close_drift_withholds_observation_without_lookup_or_new_connection(creation_case, fault):
    case = configure_pair(creation_case(), "absent")
    def late():
        if fault == "permission":
            case.denied.add((case.target.doctype, case.target.name, "write"))
        else:
            case.target.modified = "2026-10-24 11:00:01"
    case.database.close.side_effect = late
    with pytest.raises(Denied if fault == "permission" else Failed):
        review(case)
    case.connect.assert_called_once()
    case.lookup.assert_not_called()
    case.database.commit.assert_not_called()


@pytest.mark.parametrize("denied", [False, True])
def test_pair_review_arabic_uses_one_existing_message_and_mutes_private_child_cleanup(creation_case, denied):
    case = configure_pair(creation_case(), "exact")
    case.lang = "ar"
    if denied:
        case.denied.add((case.target.doctype, case.target.name, "write"))
    else:
        case.database.rollback.side_effect = lambda: case.runtime.throw("PRIVATE child popup")
    with pytest.raises(Denied if denied else Failed) as error:
        review(case)
    expected = transaction.REVIEW_DENIED_MESSAGE if denied else transaction.REVIEW_FAILED_MESSAGE
    assert case.visible == [case.catalog[expected]] and error.value.__context__ is None
    assert "PRIVATE" not in str(error.value)


def test_swallowed_pair_review_reentry_poisoning_does_not_cleanup_someone_elses_lease_or_write(creation_case):
    case = configure_pair(creation_case(), "exact")
    keys = case.storage_keys.return_value
    def reenter(scope):
        try:
            review(case)
        except Failed:
            pass
        return keys
    case.storage_keys.side_effect = reenter
    with pytest.raises(Failed):
        review(case)
    assert case.visible == [transaction.REVIEW_FAILED_MESSAGE]
    case.database.commit.assert_not_called()
    case.database.close.assert_called_once()
