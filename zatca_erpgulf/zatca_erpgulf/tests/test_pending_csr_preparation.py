"""Permissioned one-shot preparation/retention/save with synthetic resources."""

import json
from dataclasses import replace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import pending_csr_access as access
from zatca_erpgulf.zatca_erpgulf import pending_csr_transaction as transaction
from zatca_erpgulf.zatca_erpgulf.pending_csr_binding import PendingCSRBindingRecord
from zatca_erpgulf.zatca_erpgulf.tests.test_pending_csr_creation import creation_case
from zatca_erpgulf.zatca_erpgulf.tests.test_pending_csr_transaction import transaction_case, no_parent_or_active_writes
from zatca_erpgulf.zatca_erpgulf.tests.test_pending_csr_access import access_case, Failed, Denied, PrivateFailure
from zatca_erpgulf.zatca_erpgulf.tests.test_csr_draft import crypto, materials


@pytest.fixture
def preparation_case(creation_case, crypto, monkeypatch):
    def build(kind="company", environment="Production", engine="v15", password=False):
        case = creation_case(kind, environment, engine, password)
        case.context = case.draft.context
        case.crypto = crypto
        crypto.generator.reset_mock()  # Discard only fictional fixture construction calls.
        case.seal = Mock(wraps=case.cipher.seal)
        monkeypatch.setattr(case.cipher, "seal", case.seal)
        case.retained = []
        def retain(scope, original):
            assert scope == case.scope
            assert original == case.transaction.prepared_original
            assert original is not case.transaction.prepared_original
            case.retained.append(original)
            case.events.append(("retain",))
            return True
        case.retain = Mock(side_effect=retain)
        sql = case.cursor.execute.side_effect
        def identity_check(statement, parameters=()):
            if statement.startswith("SELECT draft_id FROM "):
                selected = case.envelope_row if "FROM zatca_pending_csr_v1 " in statement else case.history_record
                case.raw = None if selected is None else (parameters[1],)
                case.events.append(("unused-read",))
            else:
                return sql(statement, parameters)
        case.cursor.execute.side_effect = identity_check
        return case
    return build


def prepare(case):
    return case.transaction.prepare_bound("TC", case.identity, case.context, case.retain)


@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("engine", ["v15", "v16"])
@pytest.mark.parametrize("password", [False, True])
def test_authorize_generate_seal_retain_then_commit_new_pair_without_touching_active_fields(preparation_case, kind, environment, engine, password):
    case = preparation_case(kind, environment, engine, password)
    result = prepare(case)
    original = case.transaction.prepared_original
    assert result["state"] == "PENDING_CSR_BOUND_TRANSACTION_COMPLETED_OBSERVATION"
    assert result["server_custody_acknowledged"] is True and result["server_custody_durable_verified"] is False
    assert all(value is False for name, value in result.items() if name.endswith(("_verified", "_authorized", "_confirmed")))
    assert original == case.envelope_row == case.retained[0]
    assert original is not case.retained[0] and case.history_record.matches(original)
    assert case.cipher.open(original).context == case.context
    assert case.cipher.open(original).config_text == case.target.custom_csr_config
    assert "PRIVATE" not in json.dumps(result) and "TEST COMPANY" not in json.dumps(result)
    assert "prepared_original" not in result and "private_key_pem" not in result
    case.crypto.generator.assert_called_once()
    case.seal.assert_called_once()
    case.retain.assert_called_once()
    case.lookup.assert_not_called()
    case.database.commit.assert_called_once()
    case.database.close.assert_called_once()
    case.database.rollback.assert_not_called()
    assert case.events.index(("unused-read",)) < case.events.index(("retain",)) < case.events.index(("envelope-insert",))
    assert case.visible == []
    for identity, document in case.documents.items():
        assert {name: document.get(name) for name in access.FIELD_MAP[document.doctype]} == case.before[identity]
    no_parent_or_active_writes(case)


@pytest.mark.parametrize("permission", ["read", "write"])
@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
def test_preparation_denial_precedes_keys_generation_and_retention_even_with_test_flags(preparation_case, permission, kind):
    case = preparation_case(kind)
    case.denied.add((case.target.doctype, case.target.name, permission))
    with pytest.raises(Denied) as error:
        prepare(case)
    assert error.value.__context__ is None and case.visible == [transaction.PREPARATION_DENIED_MESSAGE]
    case.connect.assert_not_called()
    case.crypto.generator.assert_not_called()
    case.retain.assert_not_called()
    with pytest.raises(transaction.PendingCSRTransactionError):
        case.transaction.prepared_original


@pytest.mark.parametrize("fault", ["context", "revision", "environment", "owner", "linked-device"])
def test_context_must_match_saved_source_before_resource_acquisition(preparation_case, fault):
    case = preparation_case("multiple_setting" if fault == "linked-device" else "company")
    if fault == "context":
        case.context = {}
    elif fault == "revision":
        case.context = replace(case.context, source_revision="2026-10-24 11:00:01")
    elif fault == "environment":
        case.context = replace(case.context, slot=replace(case.context.slot, environment="Simulation"))
    elif fault == "owner":
        case.identity = {"doctype": "ZATCA Multiple Setting", "name": case.device.name}
    else:
        case.device.custom__use_company_certificate__keys = 1
    with pytest.raises(Failed):
        prepare(case)
    case.connect.assert_not_called()
    case.crypto.generator.assert_not_called()
    case.retain.assert_not_called()


@pytest.mark.parametrize("state", ["pair", "envelope", "history"])
def test_any_existing_identity_prevents_generation_without_reading_or_replacing_its_key(preparation_case, state):
    case = preparation_case()
    if state != "history":
        case.envelope_row = case.sealed
    if state != "envelope":
        case.history_record = PendingCSRBindingRecord.capture(case.binding, case.sealed)
    with pytest.raises(Failed):
        prepare(case)
    case.crypto.generator.assert_not_called()
    case.seal.assert_not_called()
    case.retain.assert_not_called()
    case.database.commit.assert_not_called()
    assert ("envelope-insert",) not in case.events


def test_saved_invalid_configuration_fails_before_key_generation_without_a_caller_config_override(preparation_case):
    case = preparation_case()
    case.target.custom_csr_config = case.target.custom_csr_config.replace("csr.country.name=SA", "csr.country.name=TOOLONG")
    case.rows = tuple(access._PendingSourceRow.capture(case.documents[(row.doctype, row.name)]) for row in case.rows)
    with pytest.raises(Failed) as error:
        prepare(case)
    assert error.value.__context__ is None
    case.crypto.generator.assert_not_called()
    case.seal.assert_not_called()
    case.retain.assert_not_called()


@pytest.mark.parametrize("fault", ["generation", "seal"])
def test_private_generation_or_sealing_failure_is_not_retried_or_saved(preparation_case, fault):
    case = preparation_case()
    (case.crypto.generator if fault == "generation" else case.seal).side_effect = PrivateFailure("PRIVATE")
    with pytest.raises(Failed) as error:
        prepare(case)
    assert error.value.__context__ is None and case.visible == [transaction.PREPARATION_FAILED_MESSAGE]
    case.crypto.generator.assert_called_once()
    assert case.seal.call_count == int(fault == "seal")
    case.retain.assert_not_called()
    case.database.commit.assert_not_called()
    assert case.envelope_row is case.history_record is None
    with pytest.raises(transaction.PendingCSRTransactionError):
        case.transaction.prepared_original


@pytest.mark.parametrize("acknowledgment", [None, False, 1, "true", {}])
def test_retention_requires_literal_true_before_any_staging_and_preserves_protected_original(preparation_case, acknowledgment):
    case = preparation_case()
    case.retain.side_effect = lambda scope, original: case.retained.append(original) or acknowledgment
    with pytest.raises(Failed):
        prepare(case)
    assert case.transaction.prepared_original == case.retained[0]
    assert case.envelope_row is case.history_record is None
    case.database.commit.assert_not_called()
    case.database.rollback.assert_called_once()
    case.database.close.assert_called_once()
    with pytest.raises(Failed):
        prepare(case)
    case.crypto.generator.assert_called_once()
    case.seal.assert_called_once()
    case.retain.assert_called_once()


@pytest.mark.parametrize("stop", [None, KeyboardInterrupt, SystemExit, GeneratorExit])
def test_retention_failure_or_interruption_keeps_original_before_cleanup_and_never_stages(preparation_case, stop):
    case = preparation_case()
    original = stop("PRIVATE") if stop else PrivateFailure("PRIVATE")
    case.retain.side_effect = original
    with pytest.raises(stop or Failed) as error:
        prepare(case)
    assert case.transaction.prepared_original is not None
    if stop:
        assert error.value is original and case.visible == []
    else:
        assert error.value.__context__ is None and case.visible == [transaction.PREPARATION_FAILED_MESSAGE]
    case.crypto.generator.assert_called_once()
    case.seal.assert_called_once()
    case.database.commit.assert_not_called()
    case.database.rollback.assert_called_once()
    case.database.close.assert_called_once()
    assert case.envelope_row is case.history_record is None


@pytest.mark.parametrize("fault", ["permission", "revision", "password"])
def test_post_handoff_source_or_backing_drift_refuses_sql_but_preserves_retained_original(preparation_case, fault):
    case = preparation_case(password=True)
    retain = case.retain.side_effect
    def change(scope, original):
        retain(scope, original)
        if fault == "permission":
            case.denied.add((case.target.doctype, case.target.name, "write"))
        elif fault == "revision":
            case.target.modified = "2026-10-24 11:00:01"
        else:
            case.password_records[(case.target.doctype, case.target.name)] = (("custom_basic_auth_from_csid", 1, "ENCRYPTED TEST ROTATED"),)
        return True
    case.retain.side_effect = change
    with pytest.raises(Denied if fault == "permission" else Failed):
        prepare(case)
    assert case.transaction.prepared_original == case.retained[0]
    assert case.envelope_row is case.history_record is None
    case.database.commit.assert_not_called()


@pytest.mark.parametrize("operation", ["commit", "close"])
def test_unknown_completion_retains_exact_generated_envelope_without_regeneration(preparation_case, operation):
    case = preparation_case()
    getattr(case.database, operation).side_effect = PrivateFailure("PRIVATE")
    with pytest.raises(Failed) as error:
        prepare(case)
    assert error.value.__context__ is None and case.transaction.prepared_original == case.retained[0] == case.envelope_row
    with pytest.raises(Failed):
        prepare(case)
    case.crypto.generator.assert_called_once()
    case.seal.assert_called_once()
    case.retain.assert_called_once()
    case.database.commit.assert_called_once()


@pytest.mark.parametrize("where", ["keys", "retainer"])
def test_swallowed_reentry_poisoning_prevents_save_and_does_not_regenerate(preparation_case, where):
    case = preparation_case()
    def reenter():
        try:
            prepare(case)
        except Failed:
            pass
    if where == "keys":
        keys = case.storage_keys.return_value
        case.storage_keys.side_effect = lambda scope: (reenter(), keys)[1]
    else:
        retain = case.retain.side_effect
        case.retain.side_effect = lambda scope, original: (retain(scope, original), reenter(), True)[2]
    with pytest.raises(Failed):
        prepare(case)
    assert case.crypto.generator.call_count == int(where == "retainer")
    case.database.commit.assert_not_called()
    assert case.envelope_row is case.history_record is None
    assert case.visible == [transaction.PREPARATION_FAILED_MESSAGE]


@pytest.mark.parametrize("denied", [False, True])
def test_preparation_arabic_single_message_english_metadata_without_private_diagnostics(preparation_case, denied):
    case = preparation_case()
    case.lang = "ar"
    if denied:
        case.denied.add((case.target.doctype, case.target.name, "write"))
    else:
        case.retain.side_effect = lambda *args: case.runtime.throw("PRIVATE child popup")
        case.database.rollback.side_effect = lambda: case.runtime.throw("PRIVATE cleanup popup")
    with pytest.raises(Denied if denied else Failed) as error:
        prepare(case)
    key = transaction.PREPARATION_DENIED_MESSAGE if denied else transaction.PREPARATION_FAILED_MESSAGE
    assert key.isascii() and case.visible == [case.catalog[key]]
    assert error.value.__context__ is None and "PRIVATE" not in str(error.value)
