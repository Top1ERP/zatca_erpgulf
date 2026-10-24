"""Synthetic encrypted backing comparisons; never decrypt/read tenant secrets."""

import inspect
import json
import pickle
from dataclasses import replace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import pending_csr_password_state as state
from zatca_erpgulf.zatca_erpgulf import pending_csr_access as access
from zatca_erpgulf.zatca_erpgulf.tests.test_pending_csr_access import (
    access_case, invoke, untouched, Failed, Denied,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_csr_draft import crypto, materials
from zatca_erpgulf.zatca_erpgulf.tests.test_pending_csr import NAMESPACE, OTHER


FIELDS = ("custom_basic_auth_from_csid", "custom_final_auth_csid")


def source(**changes):
    return state.PasswordStateSource(**{"doctype": "Company", "name": "TEST COMPANY",
        "password_fields": FIELDS, **changes})


def database(records=(), autocommit=(0,)):
    connection, cursor = Mock(), Mock()
    connection.cursor.return_value.__enter__ = Mock(return_value=cursor)
    connection.cursor.return_value.__exit__ = Mock(return_value=False)
    cursor.fetchone.return_value = autocommit
    cursor.fetchall.return_value = records
    return connection, cursor


def no_owner_operations(connection):
    for operation in ("commit", "rollback", "close", "ping"):
        getattr(connection, operation).assert_not_called()


def configure_password_case(case, field="custom_basic_auth_from_csid", *, company=False):
    doc = case.company if company else case.target
    doc.password_fieldtypes[field] = "Password"
    setattr(doc, field, "*****")
    case.password_records[(doc.doctype, doc.name)] = ((field, 1, "ENCRYPTED TEST ORIGINAL"),)
    rows = {access._row_key(item): access._PendingSourceRow.capture(item) for item in (case.target, case.company)}
    case.rows = tuple(rows[key] for key in sorted(rows))
    declarations = tuple(state.PasswordStateSource(row.doctype, row.name, row.password_fields) for row in case.rows)
    case.binding = replace(case.binding, source_rows_sha256=access._rows_sha256(case.rows),
        password_state_sha256=state.capture_password_state(case.database, case.scope.storage_namespace, declarations))
    case.events.clear()
    case.cursor.reset_mock()
    case.before = {identity: {name: item.get(name) for name in access.FIELD_MAP[item.doctype]}
                   for identity, item in case.documents.items()}
    return case


def test_bounded_parameterized_locked_read_returns_only_namespace_and_source_bound_digest():
    connection, cursor = database(((FIELDS[0], 1, "ENCRYPTED TEST ORIGINAL"),))
    result = state.capture_password_state(connection, NAMESPACE, (source(),))
    assert type(result) is str and len(result) == 64 and "ENCRYPTED" not in result
    statement, parameters = cursor.execute.call_args.args
    assert "FOR UPDATE" in statement and "LIMIT %s" in statement and "FROM `__Auth`" in statement
    assert "TEST COMPANY" not in statement and "ENCRYPTED" not in repr(parameters)
    assert parameters == (state.MAX_PASSWORD_BYTES + 1, "Company", "TEST COMPANY",
        *state.CREDENTIAL_FIELDS, len(state.CREDENTIAL_FIELDS) + 1)
    no_owner_operations(connection)


@pytest.mark.parametrize("change", ["token", "missing", "additional", "namespace", "owner", "schema"])
def test_changes_are_detected_without_plaintext_or_unchanged_document_modified_marker(change):
    connection, cursor = database(((FIELDS[0], 1, "ENCRYPTED TEST ORIGINAL"),))
    baseline = state.capture_password_state(connection, NAMESPACE, (source(),))
    namespace, selected = NAMESPACE, source()
    if change == "token":
        cursor.fetchall.return_value = ((FIELDS[0], 1, "ENCRYPTED TEST ROTATED"),)
    elif change == "missing":
        cursor.fetchall.return_value = ()
    elif change == "additional":
        cursor.fetchall.return_value = ((FIELDS[0], 1, "ENCRYPTED TEST ORIGINAL"), (FIELDS[1], 1, "ENCRYPTED TEST NEW"))
    elif change == "namespace":
        namespace = OTHER
    elif change == "owner":
        selected = source(name="OTHER TEST COMPANY")
    else:
        selected = source(password_fields=(FIELDS[0],))
    assert state.capture_password_state(connection, namespace, (selected,)) != baseline
    no_owner_operations(connection)


@pytest.mark.parametrize("records", [None, {}, "PRIVATE", ((FIELDS[0], 1),),
    ([FIELDS[0], 1, "PRIVATE"],), (("unknown", 1, "PRIVATE"),),
    ((FIELDS[0], True, "PRIVATE"),), ((FIELDS[0], 0, "PRIVATE"),),
    ((FIELDS[0], "1", "PRIVATE"),), ((FIELDS[0], 1, None),), ((FIELDS[0], 1, b"PRIVATE"),),
    ((FIELDS[0], 1, ""),), ((FIELDS[0], 1, "x" * (state.MAX_PASSWORD_BYTES + 1)),),
    ((FIELDS[0], 1, "ع" * state.MAX_PASSWORD_BYTES),), ((FIELDS[0], 1, "\ud800"),),
    ((FIELDS[0], 1, "PRIVATE"), (FIELDS[0], 1, "PRIVATE")),
    ((FIELDS[0], 1, "PRIVATE"),) * (len(state.CREDENTIAL_FIELDS) + 1)])
def test_malformed_oversized_duplicate_unencrypted_or_unknown_backing_rows_fail_closed(records):
    connection, cursor = database(records)
    with pytest.raises(state.PendingCSRPasswordStateError) as error:
        state.capture_password_state(connection, NAMESPACE, (source(),))
    assert error.value.__context__ is None and error.value.__cause__ is None
    assert str(error.value) == "pending_csr_password_state_unconfirmed"
    no_owner_operations(connection)


@pytest.mark.parametrize("record", ["custom_private_key", "custom_certficate", "custom_csr_config"])
def test_orphan_backing_rows_are_not_ignored_when_current_schema_is_not_password(record):
    connection, cursor = database(((record, 1, "ENCRYPTED TEST ORPHAN"),))
    with pytest.raises(state.PendingCSRPasswordStateError):
        state.capture_password_state(connection, NAMESPACE, (source(password_fields=()),))


@pytest.mark.parametrize("declarations", [None, (), [], (None,), (source(), source()),
    (source(name="Z TEST"), source(name="A TEST")), (source(),) * 3])
def test_invalid_or_unsorted_source_selection_precedes_sql(declarations):
    connection, cursor = database()
    with pytest.raises(state.PendingCSRPasswordStateError):
        state.capture_password_state(connection, NAMESPACE, declarations)
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("changes", [{"doctype": "User"}, {"name": ""}, {"name": " TEST"},
    {"password_fields": None}, {"password_fields": list(FIELDS)}, {"password_fields": tuple(reversed(FIELDS))},
    {"password_fields": (FIELDS[0], FIELDS[0])}, {"password_fields": ("unknown",)},
    {"password_fields": (FIELDS[0],) * (len(state.CREDENTIAL_FIELDS) + 1)}])
def test_bad_source_schema_declarations_have_static_errors(changes):
    with pytest.raises(state.PendingCSRPasswordStateError) as error:
        source(**changes)
    assert error.value.__context__ is None


@pytest.mark.parametrize("setting", [(1,), (False,), ("0",), [0], (), None])
def test_autocommit_unknown_or_enabled_fails_before_auth_query(setting):
    connection, cursor = database(autocommit=setting)
    with pytest.raises(state.PendingCSRPasswordStateError):
        state.capture_password_state(connection, NAMESPACE, (source(),))
    assert cursor.execute.call_count == 1
    cursor.fetchall.assert_not_called()


@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt, SystemExit, GeneratorExit])
def test_driver_failures_are_redacted_and_interruptions_propagate_without_cleanup(error_type):
    connection, cursor = database()
    original = error_type("PRIVATE encrypted storage failure")
    cursor.fetchall.side_effect = original
    with pytest.raises(state.PendingCSRPasswordStateError if error_type is RuntimeError else error_type) as error:
        state.capture_password_state(connection, NAMESPACE, (source(),))
    if error_type is RuntimeError:
        assert error.value.__context__ is None and "PRIVATE" not in str(error.value)
    else:
        assert error.value is original
    no_owner_operations(connection)


@pytest.mark.parametrize("operation", ["stage", "inspect"])
@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
@pytest.mark.parametrize("engine", ["v15", "v16"])
def test_permissioned_password_profiles_compare_backing_before_and_after_repository_work(access_case, operation, kind, engine):
    case = configure_password_case(access_case(kind, engine=engine))
    result = invoke(case, operation)
    assert result["password_backing_state_match_observed"] is True
    assert result["credential_epoch_verified"] is False and result["activation_authorized"] is False
    assert "ENCRYPTED TEST" not in json.dumps(result) and case.binding.password_state_sha256 not in json.dumps(result)
    assert sum("FROM `__Auth`" in call.args[0] for call in case.cursor.execute.call_args_list) == 2 * len(case.rows)
    untouched(case)


@pytest.mark.parametrize("operation", ["stage", "inspect"])
@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
@pytest.mark.parametrize("change", ["rotate", "remove", "orphan", "schema"])
def test_password_rotation_or_schema_drift_never_reuses_old_binding_even_with_same_mask_and_revision(access_case, operation, kind, change):
    case = configure_password_case(access_case(kind))
    before = (case.target.modified, case.target.custom_basic_auth_from_csid)
    key = (case.target.doctype, case.target.name)
    if change == "rotate":
        case.password_records[key] = ((FIELDS[0], 1, "ENCRYPTED TEST ROTATED"),)
    elif change == "remove":
        case.password_records[key] = ()
    elif change == "orphan":
        case.password_records[key] += (("custom_private_key", 1, "ENCRYPTED TEST ORPHAN"),)
    else:
        case.target.password_fieldtypes[FIELDS[0]] = "Long Text"
    with pytest.raises(Failed) as error:
        invoke(case, operation)
    assert error.value.__context__ is None and len(case.visible) == 1
    assert (case.target.modified, case.target.custom_basic_auth_from_csid) == before
    assert not any(call.args[0].startswith("INSERT INTO zatca_pending_csr") for call in case.cursor.execute.call_args_list)
    if change == "schema":
        case.provider.assert_not_called()
    untouched(case)


@pytest.mark.parametrize("operation", ["stage", "inspect"])
def test_post_repository_backing_change_refuses_result_leaves_transaction_with_caller_and_poisons_service(access_case, operation):
    case = configure_password_case(access_case())
    execute = case.cursor.execute.side_effect
    def rotate(statement, parameters=()):
        result = execute(statement, parameters)
        if statement.startswith("SELECT slot_sha256"):
            case.password_records[(case.target.doctype, case.target.name)] = ((FIELDS[0], 1, "ENCRYPTED TEST LATE"),)
        return result
    case.cursor.execute.side_effect = rotate
    with pytest.raises(Failed):
        invoke(case, operation)
    count = case.cursor.execute.call_count
    with pytest.raises(Failed):
        invoke(case, operation)
    assert case.cursor.execute.call_count == count
    untouched(case)


@pytest.mark.parametrize("operation", ["stage", "inspect"])
def test_related_routing_company_password_change_also_invalidates_device_binding(access_case, operation):
    case = configure_password_case(access_case("multiple_setting"), company=True)
    case.password_records[("Company", case.company.name)] = ((FIELDS[0], 1, "ENCRYPTED TEST ROTATED"),)
    with pytest.raises(Failed):
        invoke(case, operation)
    untouched(case)


def test_repr_pickle_and_no_decryption_discovery_or_writes():
    selected = source()
    assert "TEST COMPANY" not in repr(selected)
    with pytest.raises(state.PendingCSRPasswordStateError):
        pickle.dumps(selected)
    text = inspect.getsource(state)
    for forbidden in ("get_decrypted_password(", "get_encryption_key(", "CREATE TABLE", "INSERT INTO", "UPDATE `", "DELETE FROM", ".commit(", ".rollback(", ".close(", "requests."):
        assert forbidden not in text
