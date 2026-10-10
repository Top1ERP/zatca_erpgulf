"""Operator ACL/resource ordering with generated keys; no tenant or HTTP calls."""

import csv
import json
import pickle
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import credential_bundle_access as access
from zatca_erpgulf.zatca_erpgulf.credential_bundle import CredentialBundleError
from zatca_erpgulf.zatca_erpgulf.credential_settings import SECRET_FIELDS
from zatca_erpgulf.zatca_erpgulf.tests.test_api_route_contract import settings as route_settings
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_bundle import cipher, seal, record, connection, NAMESPACE, VERSION
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import materials
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_snapshot import capture, owner, basic


class PermissionDenied(Exception):
    pass


class InspectionFailed(Exception):
    pass


class SavedDocument:
    """Fail if metadata inspection tries to project legacy secret fields."""

    def __init__(self, doctype, name, **values):
        self.doctype, self.name, self.values = doctype, name, values
        self.flags = SimpleNamespace(ignore_permissions=True)
        self.check_permission = Mock()  # Must NOT be used as an ACL shortcut.
        self.save, self.db_set = Mock(), Mock()

    def get(self, name):
        assert name not in SECRET_FIELDS, "Legacy secrets must not be projected"
        return self.values.get(name)


@pytest.fixture
def operator(monkeypatch):
    documents = {
        ("Company", "SOURCE"): SavedDocument("Company", "SOURCE", tax_id="TEST-VAT", **route_settings()),
        ("Company", "OWNER"): SavedDocument("Company", "OWNER", tax_id="TEST-VAT"),
        ("ZATCA Multiple Setting", "OWNER"): SavedDocument(
            "ZATCA Multiple Setting", "OWNER", custom_linked_doctype="SOURCE", custom__use_company_certificate__keys=0),
        ("Sales Invoice", "SI"): SavedDocument("Sales Invoice", "SI", company="SOURCE", custom_zatca_pos_name="OWNER"),
        ("POS Invoice", "PI"): SavedDocument("POS Invoice", "PI", company="SOURCE", custom_zatca_pos_name="OWNER"),
    }
    events = []
    denied = set()

    def get_doc(doctype, name):
        if isinstance(name, dict):
            assert name == {"abbr": "TC"}
            name = "SOURCE"
        events.append(("read", doctype, name))
        return documents[doctype, name]

    def has_permission(doctype, ptype, *, doc, user, raise_exception):
        assert ptype == "read" and user == runtime.session.user and raise_exception is False
        events.append(("permission", doctype, doc.name))
        return (doctype, doc.name) not in denied

    def fail(message, error_type=InspectionFailed):
        raise error_type(message)

    runtime = SimpleNamespace(
        local=SimpleNamespace(site="private.test", flags=SimpleNamespace(in_test=True)),
        session=SimpleNamespace(user="manager@example.test"), get_roles=Mock(return_value=["System Manager"]),
        get_doc=Mock(side_effect=get_doc), throw=fail, PermissionError=PermissionDenied,
        db=SimpleNamespace(commit=Mock(), rollback=Mock()),
    )
    monkeypatch.setattr(access, "frappe", runtime)
    monkeypatch.setattr(access, "has_permission", Mock(side_effect=has_permission))
    monkeypatch.setattr(access, "_", lambda value: value)
    return SimpleNamespace(runtime=runtime, documents=documents, events=events, denied=denied)


def service(operator, database, cipher, *, namespace=NAMESPACE):
    scope = access.CredentialStorageScope("private.test", namespace)

    def acquire(requested):
        assert requested == scope
        operator.events.append(("resources",))
        return access.CredentialStorageResources(scope, database, cipher)

    provider = Mock(side_effect=acquire)
    return access.StagedCredentialInspectionService(scope, provider), provider


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("endpoint", ["compliance/invoices", "production/csids", "invoices/reporting/single", "invoices/clearance/single"])
@pytest.mark.parametrize("kind", ["company", "linked_company", "multiple_setting"])
def test_real_decrypt_only_after_all_acl_checks_returns_metadata(operator, materials, cipher, environment, endpoint, kind):
    operator.documents["Company", "SOURCE"].values.update(route_settings(environment))
    selected = owner(materials[0], doctype="ZATCA Multiple Setting" if kind == "multiple_setting" else "Company", kind=kind)
    device = operator.documents["ZATCA Multiple Setting", "OWNER"]
    source = {"doctype": "Company", "name": "SOURCE"}
    expected = [("Company", "SOURCE")]
    if kind != "company":
        source = {"doctype": "Sales Invoice", "name": "SI"}
        expected += [("Sales Invoice", "SI"), ("ZATCA Multiple Setting", "OWNER")]
    if kind == "linked_company":
        device.values.update(custom_linked_doctype="OWNER", custom__use_company_certificate__keys=1)
        expected += [("Company", "OWNER")]
    snapshot = capture(materials[0], environment=environment,
                       endpoint="compliance/invoices" if endpoint in ("compliance/invoices", "production/csids") else endpoint,
                       selected_owner=selected)
    envelope = seal(cipher, snapshot)
    database, cursor = connection([(0,), record(envelope)])
    inspector, provider = service(operator, database, cipher)
    report = inspector.inspect("TC", source, endpoint, version_id=VERSION)
    assert report == envelope.manifest.diagnostic_projection()
    assert operator.events[-1] == ("resources",)
    assert [(event[1], event[2]) for event in operator.events if event[0] == "permission"] == expected
    provider.assert_called_once_with(inspector._scope)
    assert all(report[name] is False for name in (
        "activation_authorized", "dispatch_authorized", "replay_authorized", "credential_epoch_verified",
        "remote_authorization_verified", "compliance_completion_verified"))
    public = json.dumps(report) + repr(inspector)
    for value in (materials[0].pem, materials[0].text, basic(materials[0]), "PRIVATE-SECRET", "gw-fatoora"):
        assert value not in public
    assert "ciphertext" not in report and "nonce" not in report and "compliance_request_id" not in report
    database.commit.assert_not_called()
    database.rollback.assert_not_called()
    operator.runtime.db.commit.assert_not_called()
    for doc in operator.documents.values():
        doc.check_permission.assert_not_called()
        doc.save.assert_not_called()
        doc.db_set.assert_not_called()
    assert all("INSERT" not in call.args[0] for call in cursor.execute.call_args_list)


@pytest.mark.parametrize("source", [
    {"doctype": "Company", "name": "SOURCE"}, None,
    {"doctype": "Sales Invoice", "name": "SI"}, {"doctype": "POS Invoice", "name": "PI"},
    {"doctype": "ZATCA Multiple Setting", "name": "OWNER"},
])
def test_company_denial_precedes_key_access_despite_ignore_permissions(operator, cipher, source):
    operator.denied.add(("Company", "SOURCE"))
    database = Mock()
    inspector, provider = service(operator, database, cipher)
    with pytest.raises(PermissionDenied, match=access.DENIED_MESSAGE):
        inspector.inspect("TC", source, "compliance/invoices", version_id=VERSION)
    provider.assert_not_called()
    database.cursor.assert_not_called()


@pytest.mark.parametrize("denied_row", [("Sales Invoice", "SI"), ("ZATCA Multiple Setting", "OWNER"), ("Company", "OWNER")])
def test_each_source_device_and_linked_company_permission_precedes_provider(operator, cipher, denied_row):
    operator.documents["ZATCA Multiple Setting", "OWNER"].values.update(
        custom_linked_doctype="OWNER", custom__use_company_certificate__keys=1)
    operator.denied.add(denied_row)
    inspector, provider = service(operator, Mock(), cipher)
    with pytest.raises(PermissionDenied):
        inspector.inspect("TC", {"doctype": "Sales Invoice", "name": "SI"}, "compliance/invoices", version_id=VERSION)
    provider.assert_not_called()


@pytest.mark.parametrize("user,roles,site", [
    ("Guest", ["System Manager"], "private.test"), (None, ["System Manager"], "private.test"),
    ("", ["System Manager"], "private.test"), ("manager@example.test", [], "private.test"),
    ("manager@example.test", ["Accounts Manager"], "private.test"),
    ("manager@example.test", ["System Manager"], "other.test"),
    ("Administrator", [], "other.test"),
])
def test_actor_denial_even_in_test_before_saved_reads(operator, cipher, user, roles, site):
    operator.runtime.session.user, operator.runtime.local.site = user, site
    operator.runtime.get_roles.return_value = roles
    inspector, provider = service(operator, Mock(), cipher)
    with pytest.raises(PermissionDenied):
        inspector.inspect("TC", None, "compliance/invoices", version_id=VERSION)
    provider.assert_not_called()
    operator.runtime.get_doc.assert_not_called()


@pytest.mark.parametrize("endpoint,version", [("compliance", VERSION), ("unknown", VERSION),
    ("/compliance/invoices", VERSION), (None, VERSION), ("compliance/invoices", None),
    ("compliance/invoices", "latest"), ("compliance/invoices", VERSION.upper())])
def test_no_otp_arbitrary_operation_or_implicit_version(operator, cipher, endpoint, version):
    inspector, provider = service(operator, Mock(), cipher)
    with pytest.raises(InspectionFailed, match=access.FAILED_MESSAGE):
        inspector.inspect("TC", None, endpoint, version_id=version)
    provider.assert_not_called()
    operator.runtime.get_doc.assert_not_called()


@pytest.mark.parametrize("change", ["wrong_company", "wrong_taxpayer", "invalid_flag", "missing_link", "unknown_source", "missing_source", "bad_environment", "swapped_url"])
def test_invalid_saved_settings_or_identity_before_key_access(operator, cipher, change):
    source = {"doctype": "Sales Invoice", "name": "SI"}
    if change == "wrong_company":
        operator.documents["Sales Invoice", "SI"].values["company"] = "OTHER"
    elif change == "wrong_taxpayer":
        operator.documents["ZATCA Multiple Setting", "OWNER"].values["custom_linked_doctype"] = "OWNER"
        operator.documents["Company", "OWNER"].values["tax_id"] = "DIFFERENT"
    elif change == "invalid_flag":
        operator.documents["ZATCA Multiple Setting", "OWNER"].values["custom__use_company_certificate__keys"] = "true"
    elif change == "missing_link":
        operator.documents["ZATCA Multiple Setting", "OWNER"].values["custom_linked_doctype"] = None
    elif change == "unknown_source":
        source = {"doctype": "User", "name": "SI"}
    elif change == "missing_source":
        source["name"] = "MISSING"
    elif change == "bad_environment":
        operator.documents["Company", "SOURCE"].values["custom_select"] = ""
    else:
        operator.documents["Company", "SOURCE"].values["custom_production_url"] = route_settings()["custom_sandbox_url"]
    inspector, provider = service(operator, Mock(), cipher)
    with pytest.raises(InspectionFailed):
        inspector.inspect("TC", source, "compliance/invoices", version_id=VERSION)
    provider.assert_not_called()


@pytest.mark.parametrize("change", ["scope", "type", "failure", "session", "site"])
def test_provider_binding_and_actor_drift_before_storage_sql(operator, cipher, change):
    database = Mock()
    inspector, provider = service(operator, database, cipher)
    if change == "scope":
        provider.side_effect = lambda scope: access.CredentialStorageResources(replace(scope, storage_namespace="e8d42e8a-3d28-45e9-ae4d-662814932f66"), database, cipher)
    elif change == "type":
        provider.side_effect = lambda scope: {"cipher": cipher}
    elif change == "failure":
        provider.side_effect = RuntimeError("PRIVATE-SECRET provider failure")
    else:
        original = provider.side_effect
        def acquire(scope):
            result = original(scope)
            if change == "session":
                operator.runtime.session.user = "other@example.test"
            else:
                operator.runtime.local.site = "other.test"
            return result
        provider.side_effect = acquire
    with pytest.raises((InspectionFailed, PermissionDenied)) as error:
        inspector.inspect("TC", None, "compliance/invoices", version_id=VERSION)
    assert "PRIVATE-SECRET" not in str(error.value)
    assert error.value.__context__ is None
    database.cursor.assert_not_called()


@pytest.mark.parametrize("change", ["environment", "purpose", "owner", "company", "kind", "missing", "corrupt", "key_unavailable", "autocommit", "driver"])
def test_repository_and_source_mismatches_are_static_without_authority(operator, materials, cipher, change):
    selected = owner(materials[0])
    if change == "company":
        selected = replace(selected, company_name="OTHER", name="SOURCE", source_kind="linked_company")
    elif change == "kind":
        selected = replace(selected, source_kind="linked_company")
    elif change == "owner":
        selected = owner(materials[0], doctype="ZATCA Multiple Setting", kind="multiple_setting")
    envelope = seal(cipher, capture(materials[0], selected_owner=selected,
        environment="Simulation" if change == "environment" else "Production",
        endpoint="invoices/reporting/single" if change == "purpose" else "compliance/invoices"))
    if change == "corrupt":
        envelope = replace(envelope, ciphertext=envelope.ciphertext[:-1] + bytes([envelope.ciphertext[-1] ^ 1]))
    database, _ = connection([(1,) if change == "autocommit" else (0,), None if change == "missing" else record(envelope)])
    if change == "driver":
        database.cursor.side_effect = RuntimeError("PRIVATE-SECRET driver failure")
    if change == "key_unavailable":
        from zatca_erpgulf.zatca_erpgulf.credential_bundle import CredentialBundleCipher
        cipher = CredentialBundleCipher({"other-key": b"x" * 32})
    inspector, _ = service(operator, database, cipher)
    with pytest.raises(InspectionFailed, match=access.FAILED_MESSAGE) as error:
        inspector.inspect("TC", None, "compliance/invoices", version_id=VERSION)
    assert error.value.__context__ is None
    database.commit.assert_not_called()


def test_payload_credentials_and_link_flags_are_ignored(operator, materials, cipher):
    envelope = seal(cipher, capture(materials[0], endpoint="compliance/invoices"))
    database, _ = connection([(0,), record(envelope)])
    inspector, _ = service(operator, database, cipher)
    report = inspector.inspect("TC", json.dumps({"doctype": "Company", "name": "SOURCE",
        "custom_private_key": "FORGED", "custom_select": "Sandbox", "custom_zatca_pos_name": "OWNER"}),
        "compliance/invoices", version_id=VERSION)
    assert report["slot"] == {"owner_doctype": "Company", "owner_name": "SOURCE", "environment": "Production", "purpose": "compliance"}


@pytest.mark.parametrize("flag", [None, False, 0, "", "0"])
def test_legacy_false_link_flag_remains_compatible(operator, materials, cipher, flag):
    operator.documents["ZATCA Multiple Setting", "OWNER"].values["custom__use_company_certificate__keys"] = flag
    selected = owner(materials[0], doctype="ZATCA Multiple Setting", kind="multiple_setting")
    envelope = seal(cipher, capture(materials[0], endpoint="compliance/invoices", selected_owner=selected))
    database, _ = connection([(0,), record(envelope)])
    inspector, _ = service(operator, database, cipher)
    report = inspector.inspect("TC", {"doctype": "POS Invoice", "name": "PI"}, "compliance/invoices", version_id=VERSION)
    assert report["slot"]["owner_doctype"] == "ZATCA Multiple Setting"


def test_administrator_still_requires_matching_site_and_row_checks(operator, materials, cipher):
    operator.runtime.session.user = "Administrator"
    operator.runtime.get_roles.return_value = []
    envelope = seal(cipher, capture(materials[0], endpoint="compliance/invoices"))
    database, _ = connection([(0,), record(envelope)])
    inspector, _ = service(operator, database, cipher)
    inspector.inspect("TC", None, "compliance/invoices", version_id=VERSION)
    assert ("permission", "Company", "SOURCE") in operator.events


@pytest.mark.parametrize("change", ["session", "site", "roles"])
def test_actor_drift_during_saved_reads_precedes_provider(operator, cipher, change):
    original = access.has_permission.side_effect
    def permission(*args, **kwargs):
        result = original(*args, **kwargs)
        if change == "session":
            operator.runtime.session.user = "other@example.test"
        elif change == "site":
            operator.runtime.local.site = "other.test"
        else:
            operator.runtime.get_roles.return_value = []
        return result
    access.has_permission.side_effect = permission
    inspector, provider = service(operator, Mock(), cipher)
    with pytest.raises(PermissionDenied):
        inspector.inspect("TC", None, "compliance/invoices", version_id=VERSION)
    provider.assert_not_called()


@pytest.mark.parametrize("change", ["session", "site"])
def test_actor_drift_during_repository_read_cannot_return_metadata(operator, materials, cipher, change):
    envelope = seal(cipher, capture(materials[0], endpoint="compliance/invoices"))
    database, cursor = connection([(0,), record(envelope)])
    def execute(*args):
        if args[0].startswith("SELECT slot_sha256"):
            if change == "session":
                operator.runtime.session.user = "other@example.test"
            else:
                operator.runtime.local.site = "other.test"
    cursor.execute.side_effect = execute
    inspector, _ = service(operator, database, cipher)
    with pytest.raises(PermissionDenied):
        inspector.inspect("TC", None, "compliance/invoices", version_id=VERSION)
    database.commit.assert_not_called()


@pytest.mark.parametrize("change", ["missing_scope", "wrong_cipher", "missing_connection", "wrong_namespace", "missing_provider"])
def test_server_resource_contract_has_no_defaults(cipher, change):
    scope = access.CredentialStorageScope("private.test", NAMESPACE)
    with pytest.raises(CredentialBundleError):
        if change == "missing_scope":
            access.CredentialStorageResources(None, Mock(), cipher)
        elif change == "wrong_cipher":
            access.CredentialStorageResources(scope, Mock(), object())
        elif change == "missing_connection":
            access.CredentialStorageResources(scope, None, cipher)
        elif change == "wrong_namespace":
            access.CredentialStorageScope("private.test", "latest")
        else:
            access.StagedCredentialInspectionService(scope, None)


@pytest.mark.parametrize("site", [None, "", "../site", "/site", "site name", "x" * 256])
def test_scope_rejects_non_site_names(site):
    with pytest.raises(CredentialBundleError, match="bundle_site"):
        access.CredentialStorageScope(site, NAMESPACE)


def test_resources_service_not_pickleable_not_whitelisted_and_arabic_catalogued(operator, cipher):
    inspector, _ = service(operator, Mock(), cipher)
    resources = access.CredentialStorageResources(inspector._scope, Mock(), cipher)
    for value in (resources, inspector):
        with pytest.raises(CredentialBundleError, match="bundle_not_pickleable"):
            pickle.dumps(value)
    assert not getattr(inspector.inspect, "is_whitelisted", False)
    catalog = Path(__file__).resolve().parents[2] / "translations/ar.csv"
    with catalog.open() as stream:
        translations = {row[0]: row[1] for row in csv.reader(stream) if len(row) >= 2}
    assert translations[access.DENIED_MESSAGE] != access.DENIED_MESSAGE
    assert translations[access.FAILED_MESSAGE] != access.FAILED_MESSAGE
