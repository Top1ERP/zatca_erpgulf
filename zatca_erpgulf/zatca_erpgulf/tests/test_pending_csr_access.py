"""Permissioned pending custody with fictional rows/keys/SQL, never a site."""

import csv
import hashlib
import inspect
import json
import pickle
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import pending_csr_access as access
from zatca_erpgulf.zatca_erpgulf.credential_bundle_access import CredentialStorageScope
from zatca_erpgulf.zatca_erpgulf.csr_draft import prepare_csr_draft
from zatca_erpgulf.zatca_erpgulf.pending_csr import PendingCSRCipher
from zatca_erpgulf.zatca_erpgulf.tests.test_csr_draft import crypto, materials, context, CONFIG, REVISION
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_pending_csr import NAMESPACE, OTHER, record


class Denied(Exception):
    pass


class Failed(Exception):
    pass


class PrivateFailure(Exception):
    def __str__(self):
        raise AssertionError("Never stringify private provider/source diagnostics")


@pytest.fixture
def access_case(crypto, monkeypatch):
    """Factory shared by owned private SQL composition; no runtime discovery."""
    def build(kind="company", environment="Production", engine="v15"):
        case = SimpleNamespace(events=[], visible=[], denied=set(), lang="en", permission_value=True)
        company = Document(doctype="Company", name="TEST COMPANY", abbr="TC", tax_id="TEST-VAT",
            modified=REVISION, custom_select=environment, custom_csr_config=CONFIG,
            custom_sandbox_url="https://example.invalid/developer-portal",
            custom_simulation_url="https://example.invalid/simulation",
            custom_production_url="https://example.invalid/core", save=Mock(), db_set=Mock())
        device = Document(doctype="ZATCA Multiple Setting", name="TEST DEVICE", modified=REVISION,
            custom_linked_doctype=company.name, custom__use_company_certificate__keys=0,
            custom_csr_config=CONFIG, save=Mock(), db_set=Mock())
        case.documents = {(doc.doctype, doc.name): doc for doc in (company, device)}
        for doc in (company, device):
            # Populated existing credentials remain unchanged: separate pending
            # staging is not permission to replace or activate any of them.
            for name in access.COMMON_FIELDS:
                if name != "custom_csr_config":
                    setattr(doc, name, "EXISTING TEST " + name)
            fields = set(access.FIELD_MAP[doc.doctype])
            if doc is company:
                fields.remove("custom_certficate")  # Optional absent physical alias.
            doc.password_fieldtypes = {name: "Long Text" for name in access.COMMON_FIELDS}
            doc.meta = SimpleNamespace(has_field=lambda name, fields=fields: name in fields,
                get_field=lambda name, doc=doc: SimpleNamespace(fieldtype=doc.password_fieldtypes.get(name)))
        case.company, case.device = company, device
        case.target = company if kind == "company" else device
        case.identity = {"doctype": case.target.doctype, "name": case.target.name}
        case.scope = CredentialStorageScope("private.test", NAMESPACE)
        case.draft = prepare_csr_draft(context(environment, kind), CONFIG)
        case.cipher = PendingCSRCipher({"test-only-key": b"P" * 32})
        case.sealed = case.cipher.seal(case.draft, storage_namespace=NAMESPACE, key_id="test-only-key")
        rows = {access._row_key(doc): access._PendingSourceRow.capture(doc) for doc in (case.target, company)}
        case.rows = tuple(rows[key] for key in sorted(rows))
        case.password_records = {}
        case.database, case.cursor = Mock(), Mock()
        case.database.cursor.return_value.__enter__ = Mock(return_value=case.cursor)
        case.database.cursor.return_value.__exit__ = Mock(return_value=False)

        def sql(statement, parameters=()):
            case.events.append(("sql", statement))
            if statement == "SELECT @@session.autocommit":
                case.raw = (0,)
            elif "FROM `tab" in statement:
                row = next(row for row in case.rows if row.name == parameters[-1])
                case.raw = (row.name, row.revision, *row.values)
            elif "FROM `__Auth`" in statement:
                case.raw_password_records = case.password_records.get((parameters[1], parameters[2]), ())
            elif statement.startswith("INSERT INTO zatca_pending_csr_v1"):
                case.raw = None
            elif statement.startswith("SELECT slot_sha256"):
                case.raw = record(case.sealed)
            else:
                raise AssertionError("Unexpected synthetic SQL statement")
        case.cursor.execute.side_effect = sql
        case.cursor.fetchone.side_effect = lambda: case.raw
        case.cursor.fetchall.side_effect = lambda: case.raw_password_records
        password_sources = tuple(access.PasswordStateSource(row.doctype, row.name, row.password_fields) for row in case.rows)
        case.binding = access.PendingCSRSourceBinding(case.scope, case.sealed.manifest,
            access._rows_sha256(case.rows), "test-only-key",
            access.capture_password_state(case.database, case.scope.storage_namespace, password_sources))
        case.events.clear()
        case.cursor.reset_mock()

        def get_doc(kind, name):
            case.events.append(("load", kind, name))
            assert type(name) is str, "No abbreviation/source fallback"
            return case.documents[kind, name]
        def throw(message, exc=Failed, **kwargs):
            if not case.runtime.flags.get("mute_messages"):
                case.visible.append(message)
            raise exc(message)
        case.runtime = SimpleNamespace(local=SimpleNamespace(site="private.test"),
            session=SimpleNamespace(user="operator@example.invalid"), get_roles=Mock(return_value=["System Manager"]),
            get_doc=Mock(side_effect=get_doc), throw=throw, PermissionError=Denied, ValidationError=Failed,
            flags={"in_test": True, "ignore_permissions": True},
            db=SimpleNamespace(_conn=Mock(), commit=Mock(), rollback=Mock(), close=Mock()))
        def allowed(doctype, operation, doc, user, quiet):
            case.events.append(("acl", doctype, operation, doc.name, user))
            assert quiet is False and user == case.runtime.session.user
            return False if (doctype, doc.name, operation) in case.denied else case.permission_value
        if engine == "v15":
            def permission(doctype, operation, *, doc, user, raise_exception=True):
                return allowed(doctype, operation, doc, user, raise_exception)
        else:
            def permission(doctype, operation, *, doc, user, print_logs=True):
                return allowed(doctype, operation, doc, user, print_logs)
        monkeypatch.setattr(access, "frappe", case.runtime)
        monkeypatch.setattr(access, "has_permission", permission)
        with (Path(__file__).parents[2] / "translations/ar.csv").open(encoding="utf-8", newline="") as source:
            case.catalog = dict(csv.reader(source))
        monkeypatch.setattr(access, "_", lambda message: case.catalog[message] if case.lang == "ar" else message)
        def lookup(*args):
            case.events.append(("lookup",))
            return case.binding
        case.lookup = Mock(side_effect=lookup)
        case.resources = access.PendingCSRResources(case.scope, "test-only-key", case.database, case.cipher)
        def resources(*args):
            case.events.append(("resources",))
            return case.resources
        case.provider = Mock(side_effect=resources)
        case.service = access.SavedPendingCSRService(case.scope, case.lookup, case.provider)
        case.before = {identity: {name: doc.get(name) for name in access.FIELD_MAP[doc.doctype]}
                       for identity, doc in case.documents.items()}
        return case
    return build


def invoke(case, operation):
    if operation == "stage":
        return case.service.stage("TC", case.identity, case.sealed)
    return case.service.inspect("TC", case.identity, draft_id=case.draft.context.draft_id)


def untouched(case):
    for identity, doc in case.documents.items():
        doc.save.assert_not_called()
        doc.db_set.assert_not_called()
        assert {name: doc.get(name) for name in access.FIELD_MAP[doc.doctype]} == case.before[identity]
    for database in (case.runtime.db, case.database):
        for name in ("commit", "rollback", "close"):
            getattr(database, name).assert_not_called()


@pytest.mark.parametrize("operation", ["stage", "inspect"])
@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("engine", ["v15", "v16"])
def test_exact_saved_source_access_then_keys_and_locked_staging_without_transaction_ownership(access_case, operation, kind, environment, engine):
    case = access_case(kind, environment, engine)
    case.identity.update(custom_csr_config="FORGED", custom_private_key="FORGED", flags={"ignore_permissions": True})
    report = invoke(case, operation)
    assert report["state"] == ("PENDING_CSR_STAGED_UNCOMMITTED" if operation == "stage" else "PENDING_CSR_INSPECTION_OBSERVATION")
    assert report["current_source_match_observed"] is True and report["current_permissions_observed"] is True
    assert all(value is False for name, value in report.items() if name.endswith(("_verified", "_authorized", "_confirmed")))
    output = json.dumps(report) + repr(case.service) + repr(case.resources) + repr(case.binding)
    assert "TEST COMPANY" not in output and "EXISTING TEST" not in output and CONFIG not in output
    assert case.draft.private_key_pem.decode() not in output and "sealed" not in report
    case.lookup.assert_called_once_with(case.scope, case.target.doctype, case.target.name, case.draft.context.draft_id)
    case.provider.assert_called_once_with(case.scope)
    order = [event[0] for event in case.events]
    assert order.index("acl") < order.index("lookup") < order.index("resources") < order.index("sql")
    assert case.visible == []
    untouched(case)


@pytest.mark.parametrize("operation", ["stage", "inspect"])
@pytest.mark.parametrize("kind,doctype,permission", [("company", "Company", "read"),
    ("company", "Company", "write"), ("multiple_setting", "ZATCA Multiple Setting", "read"),
    ("multiple_setting", "ZATCA Multiple Setting", "write"), ("multiple_setting", "Company", "read")])
@pytest.mark.parametrize("engine", ["v15", "v16"])
def test_every_normal_row_acl_precedes_lookup_keys_and_sql(access_case, operation, kind, doctype, permission, engine):
    case = access_case(kind, engine=engine)
    doc = case.company if doctype == "Company" else case.device
    doc.flags = SimpleNamespace(ignore_permissions=True)
    case.denied.add((doctype, doc.name, permission))
    with pytest.raises(Denied) as error:
        invoke(case, operation)
    assert error.value.__context__ is None and error.value.__cause__ is None
    assert case.visible == [access.DENIED_MESSAGE]
    case.lookup.assert_not_called()
    case.provider.assert_not_called()
    case.cursor.execute.assert_not_called()
    untouched(case)


@pytest.mark.parametrize("operation", ["stage", "inspect"])
@pytest.mark.parametrize("actor", ["guest", "empty", "no-role", "other-site", "actor-drift"])
def test_actor_site_role_and_continuity_precede_protected_resources(access_case, operation, actor):
    case = access_case()
    if actor == "guest":
        case.runtime.session.user = "Guest"
    elif actor == "empty":
        case.runtime.session.user = None
    elif actor == "no-role":
        case.runtime.get_roles.return_value = []
    elif actor == "other-site":
        case.runtime.local.site = "other.test"
    else:
        original = case.runtime.get_doc.side_effect
        def drift(*args):
            result = original(*args)
            case.runtime.session.user = "other-operator@example.invalid"
            return result
        case.runtime.get_doc.side_effect = drift
    with pytest.raises((Denied, Failed)):
        invoke(case, operation)
    case.provider.assert_not_called()
    case.cursor.execute.assert_not_called()


@pytest.mark.parametrize("operation", ["stage", "inspect"])
@pytest.mark.parametrize("allowed", [None, 1, "yes"])
def test_nonliteral_permission_values_are_not_authorization(access_case, operation, allowed):
    case = access_case()
    case.permission_value = allowed
    with pytest.raises(Denied):
        invoke(case, operation)
    case.provider.assert_not_called()


@pytest.mark.parametrize("operation", ["stage", "inspect"])
@pytest.mark.parametrize("field", ["modified", "custom_csr_config", "custom_private_key", "custom_certificate",
    "custom_basic_auth_from_csid", "custom_final_auth_csid", "custom_csr_data", "tax_id", "custom_select", "custom_production_url", "schema"])
def test_saved_revision_config_credentials_routing_or_schema_drift_is_not_rebound(access_case, operation, field):
    case = access_case()
    if field == "schema":
        case.company.meta.has_field = lambda name: True
    elif field == "modified":
        case.company.modified = "2026-10-24 11:00:01"
    else:
        setattr(case.company, field, "CHANGED TEST")
    with pytest.raises(Failed) as error:
        invoke(case, operation)
    assert error.value.__context__ is None
    case.provider.assert_not_called()
    case.cursor.execute.assert_not_called()


@pytest.mark.parametrize("operation", ["stage", "inspect"])
@pytest.mark.parametrize("stage", ["lookup", "provider", "before-repository", "after-repository"])
@pytest.mark.parametrize("fault", ["permission", "revision"])
def test_late_revocation_and_source_changes_refuse_success_without_cleanup_or_retry(access_case, operation, stage, fault):
    case = access_case()
    def mutate():
        if fault == "permission":
            case.denied.add(("Company", case.company.name, "write"))
        else:
            case.company.modified = "2026-10-24 11:00:01"
    if stage in ("lookup", "provider"):
        callback = getattr(case, stage).side_effect
        def changed(*args):
            result = callback(*args)
            mutate()
            return result
        getattr(case, stage).side_effect = changed
    else:
        callback = case.cursor.execute.side_effect
        count = [0]
        def changed(statement, parameters=()):
            result = callback(statement, parameters)
            if "FROM `tab" in statement:
                count[0] += 1
                if count[0] == (1 if stage == "before-repository" else 2):
                    mutate()
            return result
        case.cursor.execute.side_effect = changed
    with pytest.raises(Denied if fault == "permission" else Failed) as error:
        invoke(case, operation)
    assert error.value.__context__ is None and len(case.visible) == 1
    count = case.cursor.execute.call_count
    with pytest.raises(Failed):
        invoke(case, operation)
    assert case.cursor.execute.call_count == count and case.provider.call_count <= 1
    for database in (case.database, case.runtime.db):
        database.commit.assert_not_called()
        database.rollback.assert_not_called()
        database.close.assert_not_called()


@pytest.mark.parametrize("operation", ["stage", "inspect"])
@pytest.mark.parametrize("field", ["scope", "manifest", "source_rows_sha256", "key_id"])
def test_mismatched_exact_server_binding_is_rejected_without_resource_lookup(access_case, operation, field):
    case = access_case()
    values = {"scope": CredentialStorageScope("private.test", OTHER),
        "manifest": replace(case.binding.manifest, context=replace(case.binding.manifest.context, draft_id=OTHER)),
        "source_rows_sha256": "0" * 64, "key_id": "different-key"}
    case.binding = replace(case.binding, **{field: values[field]})
    # Inspect also validates selected storage keys when resources arrive.
    with pytest.raises(Failed):
        invoke(case, operation)
    if operation == "stage" or field != "key_id":
        case.provider.assert_not_called()
    case.cursor.execute.assert_not_called()


@pytest.mark.parametrize("operation", ["stage", "inspect"])
@pytest.mark.parametrize("fault", ["lookup", "provider", "sql", "missing-resource", "scope", "key", "ambient", "ambient-raw", "autocommit", "locked-row"])
def test_resource_sql_and_binding_faults_are_redacted_and_never_owned_by_service(access_case, operation, fault):
    case = access_case()
    if fault in ("lookup", "provider"):
        getattr(case, fault).side_effect = PrivateFailure("PRIVATE")
    elif fault == "sql":
        case.cursor.execute.side_effect = PrivateFailure("PRIVATE")
    elif fault == "missing-resource":
        case.provider.side_effect = None
        case.provider.return_value = None
    elif fault in ("scope", "key", "ambient", "ambient-raw"):
        options = {"scope": {"scope": CredentialStorageScope("private.test", OTHER)}, "key": {"key_id": "other-key"},
            "ambient": {"connection": case.runtime.db}, "ambient-raw": {"connection": case.runtime.db._conn}}
        if fault == "ambient":
            case.runtime.db.cursor = Mock()
        case.resources = replace(case.resources, **options[fault])
    else:
        original = case.cursor.fetchone.side_effect
        def changed():
            raw = original()
            if fault == "autocommit" and raw == (0,):
                return (1,)
            if fault == "locked-row" and type(raw) is tuple and len(raw) > 1:
                return ("OTHER TEST", *raw[1:])
            return raw
        case.cursor.fetchone.side_effect = changed
    with pytest.raises(Failed) as error:
        invoke(case, operation)
    assert case.visible == [access.FAILED_MESSAGE]
    assert error.value.__context__ is None and error.value.__cause__ is None
    untouched(case)


@pytest.mark.parametrize("operation", ["stage", "inspect"])
@pytest.mark.parametrize("stop", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_cancellation_is_not_swallowed_or_retried_and_poisoned_service_does_not_reacquire(access_case, operation, stop):
    case = access_case()
    case.provider.side_effect = stop()
    with pytest.raises(stop):
        invoke(case, operation)
    assert case.visible == []
    with pytest.raises(Failed):
        invoke(case, operation)
    assert case.provider.call_count == 1
    untouched(case)


@pytest.mark.parametrize("operation", ["stage", "inspect"])
@pytest.mark.parametrize("denied", [False, True])
def test_one_translated_display_failure_with_english_contract_constants(access_case, operation, denied):
    case = access_case()
    case.lang = "ar"
    if denied:
        case.denied.add(("Company", case.company.name, "write"))
    else:
        case.provider.side_effect = PrivateFailure("PRIVATE")
    with pytest.raises(Denied if denied else Failed) as error:
        invoke(case, operation)
    message = access.DENIED_MESSAGE if denied else access.FAILED_MESSAGE
    assert case.visible == [case.catalog[message]] and str(error.value) != message
    assert message.isascii() and error.value.__context__ is None


@pytest.mark.parametrize("operation", ["stage", "inspect"])
@pytest.mark.parametrize("flag", [1, True, "1", None, "yes"])
def test_linked_or_unknown_device_owner_is_not_silently_selected(access_case, operation, flag):
    case = access_case("multiple_setting")
    case.device.custom__use_company_certificate__keys = flag
    with pytest.raises(Failed):
        invoke(case, operation)
    case.lookup.assert_not_called()
    case.provider.assert_not_called()


@pytest.mark.parametrize("kind", ["service", "binding", "resources", "row"])
def test_protected_dependencies_are_not_pickle_transport(access_case, kind):
    case = access_case()
    value = case.rows[0] if kind == "row" else getattr(case, kind)
    with pytest.raises(access.PendingCSRAccessError):
        pickle.dumps(value)


def test_no_whitelist_runtime_installer_or_plaintext_return_contract():
    text = inspect.getsource(access)
    assert "@frappe.whitelist" not in text and "requests." not in text
    assert "CREATE TABLE" not in text and ".commit(" not in text and ".rollback(" not in text and ".close(" not in text


@pytest.mark.parametrize("operation", ["stage", "inspect"])
@pytest.mark.parametrize("identity", [None, {}, [], "PRIVATE", {"doctype": "Sales Invoice", "name": "TEST"},
    {"doctype": "Company", "name": ""}, {"doctype": "Company", "name": " TEST COMPANY"}])
def test_invalid_identity_never_acquires_resources(access_case, operation, identity):
    case = access_case()
    case.identity = identity
    with pytest.raises(Failed) as error:
        invoke(case, operation)
    assert error.value.__context__ is None
    case.lookup.assert_not_called()
    case.provider.assert_not_called()
    case.cursor.execute.assert_not_called()


@pytest.mark.parametrize("value", [None, {}, "PRIVATE", True])
@pytest.mark.parametrize("operation", ["stage", "inspect"])
def test_invalid_exact_selection_never_loads_source_or_keys(access_case, operation, value):
    case = access_case()
    with pytest.raises(Failed):
        if operation == "stage":
            case.service.stage("TC", case.identity, value)
        else:
            case.service.inspect("TC", case.identity, draft_id=value)
    case.runtime.get_doc.assert_not_called()
    case.provider.assert_not_called()


@pytest.mark.parametrize("operation", ["stage", "inspect"])
@pytest.mark.parametrize("roles", [None, "System Manager", {"System Manager": True}, 1])
def test_unknown_role_response_is_not_authorization(access_case, operation, roles):
    case = access_case()
    case.runtime.get_roles.return_value = roles
    with pytest.raises(Denied):
        invoke(case, operation)
    case.runtime.get_doc.assert_not_called()
    case.lookup.assert_not_called()


@pytest.mark.parametrize("operation", ["stage", "inspect"])
def test_administrator_still_requires_direct_row_write_acl(access_case, operation):
    case = access_case()
    case.runtime.session.user = "Administrator"
    case.denied.add(("Company", case.company.name, "write"))
    with pytest.raises(Denied):
        invoke(case, operation)
    case.provider.assert_not_called()


@pytest.mark.parametrize("operation", ["stage", "inspect"])
@pytest.mark.parametrize("fault", ["child-popup", "reentrant"])
def test_child_messages_are_muted_and_reentrant_work_poisoned_without_second_resource_call(access_case, operation, fault):
    case = access_case()
    flags = dict(case.runtime.flags)
    def provider(*args):
        if fault == "child-popup":
            case.runtime.throw("PRIVATE provider details")
        else:
            # Even if the provider swallows the inner denial, its outer call
            # cannot return success or proceed to any SQL afterwards.
            try:
                invoke(case, operation)
            except Failed:
                pass
            return case.resources
    case.provider.side_effect = provider
    with pytest.raises(Failed) as error:
        invoke(case, operation)
    assert case.visible == [access.FAILED_MESSAGE] and error.value.__context__ is None
    assert case.runtime.flags == flags
    assert case.provider.call_count == 1
    case.cursor.execute.assert_not_called()


@pytest.mark.parametrize("operation", ["stage", "inspect"])
@pytest.mark.parametrize("field", ["custom_csr_config", "custom_private_key", "custom_certificate"])
@pytest.mark.parametrize("value", [123, "x" * (access.MAX_FIELD_CHARS + 1)])
def test_unknown_or_unbounded_private_source_values_fail_without_coercion_or_keys(access_case, operation, field, value):
    case = access_case()
    setattr(case.company, field, value)
    with pytest.raises(Failed) as error:
        invoke(case, operation)
    assert error.value.__context__ is None
    case.provider.assert_not_called()
