"""Initial authorized source capture and new-pair save; synthetic resources only."""

import json
from dataclasses import replace

import pytest

from zatca_erpgulf.zatca_erpgulf import pending_csr_access as access
from zatca_erpgulf.zatca_erpgulf import pending_csr_transaction as transaction
from zatca_erpgulf.zatca_erpgulf.pending_csr import SealedPendingCSR
from zatca_erpgulf.zatca_erpgulf.pending_csr_binding import decode_binding_record, PendingCSRBindingRecord
from zatca_erpgulf.zatca_erpgulf.tests.test_pending_csr_binding import history_row
from zatca_erpgulf.zatca_erpgulf.tests.test_pending_csr import record
from zatca_erpgulf.zatca_erpgulf.tests.test_pending_csr_transaction import (
    transaction_case, no_parent_or_active_writes,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_pending_csr_access import access_case, Failed, Denied, PrivateFailure
from zatca_erpgulf.zatca_erpgulf.tests.test_csr_draft import crypto, materials


@pytest.fixture
def creation_case(transaction_case):
    def build(kind="company", environment="Production", engine="v15", password=False):
        case = transaction_case(kind, environment, engine, password)
        case.envelope_row = case.history_record = None
        case.lookup.side_effect = AssertionError("Initial capture must never use historical lookup")
        sql = case.cursor.execute.side_effect
        def storage(statement, parameters=()):
            if statement.startswith("INSERT INTO zatca_pending_csr_source_binding_v1"):
                assert case.history_record is None and case.envelope_row is not None
                case.history_record = decode_binding_record(parameters[5])
                case.events.append(("history-insert",))
            elif statement.startswith("SELECT slot_sha256,flow_id,site,"):
                case.raw = None if case.history_record is None else history_row(case.history_record)
                case.events.append(("history-read",))
            elif statement.startswith("INSERT INTO zatca_pending_csr_v1"):
                assert "ON DUPLICATE" not in statement and case.envelope_row is None
                case.envelope_row = SealedPendingCSR(parameters[0], parameters[4], parameters[6], parameters[7], parameters[8])
                case.events.append(("envelope-insert",))
            else:
                result = sql(statement, parameters)
                if statement.startswith("SELECT slot_sha256"):
                    case.raw = None if case.envelope_row is None else record(case.envelope_row)
                return result
        case.cursor.execute.side_effect = storage
        return case
    return build


def create(case):
    return case.transaction.create_bound("TC", case.identity, case.sealed)


@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("engine", ["v15", "v16"])
@pytest.mark.parametrize("password", [False, True])
def test_owned_initial_capture_uses_shared_policy_without_history_then_one_commit_close(creation_case, kind, environment, engine, password):
    case = creation_case(kind, environment, engine, password)
    expected, flags = case.binding, dict(case.runtime.flags)
    report = create(case)
    assert report["state"] == "PENDING_CSR_BOUND_TRANSACTION_COMPLETED_OBSERVATION"
    assert report["local_transaction_completed"] is True and report["original_source_binding_observed"] is True
    assert case.history_record.binding == expected and case.history_record.matches(case.sealed)
    assert all(value is False for name, value in report.items() if name.endswith(("_verified", "_authorized", "_confirmed")))
    assert "TEST COMPANY" not in json.dumps(report) and "PRIVATE" not in json.dumps(report)
    assert "source_rows_sha256" not in report and "password_state_sha256" not in report
    case.lookup.assert_not_called()
    case.database.commit.assert_called_once()
    case.database.close.assert_called_once()
    case.database.rollback.assert_not_called()
    assert case.visible == [] and flags == case.runtime.flags
    assert case.events.index(("history-insert",)) > case.events.index(("envelope-insert",))
    no_parent_or_active_writes(case)


@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
def test_caller_owned_initial_stage_does_not_commit_or_close_and_rejects_recapture(creation_case, kind):
    case = creation_case(kind, password=True)
    report = case.service.stage_new_bound("TC", case.identity, case.sealed)
    assert report["state"] == "PENDING_CSR_BOUND_CREATION_UNCOMMITTED"
    assert "local_transaction_completed" not in report and case.history_record.binding == case.binding
    for operation in ("commit", "rollback", "close"):
        getattr(case.database, operation).assert_not_called()
    with pytest.raises(Failed):
        case.service.stage_new_bound("TC", case.identity, case.sealed)
    case.lookup.assert_not_called()


@pytest.mark.parametrize("operation", ["read", "write"])
@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
def test_initial_capture_checks_normal_acl_before_lookup_or_keys_and_keeps_ambient_work(creation_case, operation, kind):
    case = creation_case(kind)
    case.denied.add((case.target.doctype, case.target.name, operation))
    with pytest.raises(Denied) as error:
        create(case)
    assert error.value.__context__ is None and case.visible == [transaction.DENIED_MESSAGE]
    case.lookup.assert_not_called()
    case.login.assert_not_called()
    case.connect.assert_not_called()
    assert case.envelope_row is case.history_record is None
    no_parent_or_active_writes(case)


@pytest.mark.parametrize("fault", ["revision", "configuration", "owner", "environment", "scope", "linked-device"])
def test_initial_manifest_must_match_exact_saved_source_before_resource_acquisition(creation_case, fault):
    case = creation_case("multiple_setting" if fault == "linked-device" else "company")
    if fault == "revision":
        case.target.modified = "2026-10-24 11:00:01"
    elif fault == "configuration":
        case.target.custom_csr_config += "\n"
    elif fault == "owner":
        case.identity = {"doctype": "ZATCA Multiple Setting", "name": case.device.name}
    elif fault == "environment":
        case.company.custom_select = "Simulation"
    elif fault == "scope":
        case.sealed = replace(case.sealed, storage_namespace="9b036c58-d164-4cc8-861f-a40284293e97")
    else:
        case.device.custom__use_company_certificate__keys = 1
    with pytest.raises(Failed):
        create(case)
    case.connect.assert_not_called()
    case.lookup.assert_not_called()
    assert case.envelope_row is case.history_record is None


@pytest.mark.parametrize("existing", ["pair", "envelope", "history"])
def test_initial_capture_never_adopts_existing_draft_or_recreates_history(creation_case, existing):
    case = creation_case()
    if existing != "history":
        case.envelope_row = case.sealed
    if existing != "envelope":
        case.history_record = PendingCSRBindingRecord.capture(case.binding, case.sealed)
    with pytest.raises(Failed) as error:
        create(case)
    assert error.value.__context__ is None and case.visible == [transaction.FAILED_MESSAGE]
    assert ("envelope-insert",) not in case.events and ("history-insert",) not in case.events
    case.database.commit.assert_not_called()
    case.database.rollback.assert_called_once()
    case.database.close.assert_called_once()


@pytest.mark.parametrize("fault", ["source", "password", "history", "envelope", "permission"])
def test_initial_final_guard_rechecks_captured_binding_backing_and_original_without_lookup(creation_case, monkeypatch, fault):
    case = creation_case(password=True)
    original, calls = access._verify_locked_rows, []
    def changed(connection, rows):
        original(connection, rows)
        calls.append(True)
        if len(calls) == 2:  # After pair staging; final commit guard still must run.
            if fault == "source":
                case.target.modified = "2026-10-24 11:00:01"
            elif fault == "password":
                case.password_records[(case.target.doctype, case.target.name)] = (("custom_basic_auth_from_csid", 1, "ENCRYPTED TEST ROTATED"),)
            elif fault == "history":
                changed = replace(case.history_record.binding, source_rows_sha256="3" * 64)
                case.history_record = PendingCSRBindingRecord.capture(changed, case.sealed)
            elif fault == "envelope":
                case.envelope_row = case.cipher.seal(case.draft, storage_namespace=case.scope.storage_namespace, key_id="test-only-key")
            else:
                case.denied.add((case.target.doctype, case.target.name, "write"))
    monkeypatch.setattr(access, "_verify_locked_rows", changed)
    with pytest.raises(Denied if fault == "permission" else Failed) as error:
        create(case)
    assert error.value.__context__ is None and len(case.visible) == 1
    case.lookup.assert_not_called()
    case.database.commit.assert_not_called()
    case.database.rollback.assert_called_once()
    case.database.close.assert_called_once()


@pytest.mark.parametrize("operation", ["commit", "close"])
@pytest.mark.parametrize("stop", [None, KeyboardInterrupt, SystemExit, GeneratorExit])
def test_initial_unknown_completion_or_interruption_preserves_ambiguity_and_never_replays(creation_case, operation, stop):
    case = creation_case()
    original = stop("PRIVATE") if stop else PrivateFailure("PRIVATE")
    getattr(case.database, operation).side_effect = original
    with pytest.raises(stop or Failed) as error:
        create(case)
    if stop:
        assert error.value is original and case.visible == []
    else:
        assert error.value.__context__ is None and case.visible == [transaction.FAILED_MESSAGE]
    case.database.commit.assert_called_once()
    case.database.close.assert_called_once()
    assert case.database.rollback.call_count == int(operation == "commit")
    case.lookup.assert_not_called()


@pytest.mark.parametrize("fault", ["permission", "revision"])
def test_initial_post_commit_denial_or_source_change_does_not_claim_rollback_or_success(creation_case, fault):
    case = creation_case()
    def late():
        if fault == "permission":
            case.denied.add((case.target.doctype, case.target.name, "write"))
        else:
            case.target.modified = "2026-10-24 11:00:01"
    case.database.commit.side_effect = late
    with pytest.raises(Denied if fault == "permission" else Failed):
        create(case)
    case.database.commit.assert_called_once()
    case.database.close.assert_called_once()
    case.database.rollback.assert_not_called()
    case.lookup.assert_not_called()


@pytest.mark.parametrize("denied", [False, True])
def test_initial_failure_uses_one_translated_existing_message_without_raw_diagnostics(creation_case, denied):
    case = creation_case()
    case.lang = "ar"
    if denied:
        case.denied.add((case.target.doctype, case.target.name, "write"))
    else:
        case.database.commit.side_effect = lambda: case.runtime.throw("PRIVATE child failure")
        case.database.rollback.side_effect = lambda: case.runtime.throw("PRIVATE cleanup failure")
    with pytest.raises(Denied if denied else Failed) as error:
        create(case)
    expected = transaction.DENIED_MESSAGE if denied else transaction.FAILED_MESSAGE
    assert case.visible == [case.catalog[expected]] and error.value.__context__ is None
    assert "PRIVATE" not in str(error.value)


def test_swallowed_reentrant_initial_creation_poisons_outer_owner_without_commit(creation_case):
    case = creation_case()
    keys = case.storage_keys.return_value
    def reenter(scope):
        try:
            create(case)
        except Failed:
            pass
        return keys
    case.storage_keys.side_effect = reenter
    with pytest.raises(Failed):
        create(case)
    assert case.visible == [transaction.FAILED_MESSAGE]
    case.database.commit.assert_not_called()
    case.database.close.assert_called_once()
    case.lookup.assert_not_called()
