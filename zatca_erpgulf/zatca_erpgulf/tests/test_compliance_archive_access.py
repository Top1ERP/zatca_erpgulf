"""ACL-first metadata inspection of synthetic encrypted SQL rows; never a site."""

import json
import pickle
from dataclasses import replace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import credential_bundle_access as access
from zatca_erpgulf.zatca_erpgulf import compliance_archive_repository as storage
from zatca_erpgulf.zatca_erpgulf.compliance_archive import ComplianceArchiveHistory
from zatca_erpgulf.zatca_erpgulf.compliance_evidence import ComplianceRequirements, STEP_CLASSIFICATION
from zatca_erpgulf.zatca_erpgulf.credential_bundle import CredentialBundleError
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_archive import archive_cipher, archive_record, envelopes
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_evidence import csr, exchange, response
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_bundle import cipher, seal, record, connection, NAMESPACE, VERSION
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_bundle_access import (
    operator, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import materials
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_snapshot import capture, owner, basic
from zatca_erpgulf.zatca_erpgulf.tests.test_api_route_contract import settings as route_settings
from zatca_erpgulf.zatca_erpgulf.tests.test_artifact_evidence import SELLER


def inspection(operator, materials, cipher, archive_cipher, *, environment="Production",
               kind="company", steps=("SIMPLIFIED",), statuses=(200,), source_type="Sales Invoice", functionality="1100"):
    """Real codecs/repositories with an explicit fake SQL response sequence."""
    operator.documents["Company", "SOURCE"].values.update(route_settings(environment), tax_id=SELLER)
    operator.documents["Company", "OWNER"].values["tax_id"] = SELLER
    selected = owner(materials[0], doctype="ZATCA Multiple Setting" if kind == "multiple_setting" else "Company", kind=kind)
    source = {"doctype": "Company", "name": "SOURCE"}
    if kind != "company":
        source = {"doctype": source_type, "name": "PI" if source_type == "POS Invoice" else "SI"}
    if kind == "linked_company":
        operator.documents["ZATCA Multiple Setting", "OWNER"].values.update(
            custom_linked_doctype="OWNER", custom__use_company_certificate__keys=1)
    bundle = seal(cipher, capture(materials[0], environment=environment,
        endpoint="compliance/invoices", selected_owner=selected))
    req = ComplianceRequirements(NAMESPACE, bundle.manifest, csr(materials[0], functionality))
    histories, rows = [], [(0,), record(bundle)]
    for step, status in zip(steps, statuses):
        received = exchange(req, materials[0], step=step, status=200 if status is None else status,
                            body=response(step=step, previous=status == 406))
        start = replace(received, http_status=None, response_bytes=None, received_at=None)
        left, right = envelopes(archive_cipher, start, received)
        histories.append(ComplianceArchiveHistory(start, None if status is None else received))
        rows.extend([(0,), record(bundle), archive_record(left), None if status is None else archive_record(right)])
    database, cursor = connection(rows)
    scope = access.CredentialStorageScope("private.test", NAMESPACE)

    def acquire(requested):
        assert requested == scope
        operator.events.append(("resources",))
        return access.CredentialStorageResources(scope, database, cipher, archive_cipher)

    provider = Mock(side_effect=acquire)
    inspector = access.StagedCredentialInspectionService(scope, provider)
    identities = tuple(history.start.exchange_id for history in histories)
    return inspector, provider, database, cursor, bundle, histories, source, identities


def inspect_prepared(prepared):
    inspector, _, _, _, bundle, _, source, identities = prepared
    return inspector.inspect_compliance_archive("TC", source, version_id=bundle.manifest.version_id, exchange_ids=identities)


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("step", list(STEP_CLASSIFICATION))
@pytest.mark.parametrize("status", [None, 200, 202, 406, 401])
def test_real_authenticated_selection_is_metadata_only_and_never_activation(operator, materials, cipher, archive_cipher, environment, step, status):
    prepared = inspection(operator, materials, cipher, archive_cipher, environment=environment, steps=(step,), statuses=(status,))
    report = inspect_prepared(prepared)
    inspector, provider, database, cursor, bundle, histories, _, identities = prepared
    assert report["state"] == "AUTHENTICATED_ARCHIVED_OBSERVATIONS"
    assert report["selection_is_complete_history"] is False
    assert report["histories"] == [histories[0].diagnostic_projection()]
    assert len(report["checks"]["missing_steps"]) == (5 if status in (200, 202, 406) else 6)
    assert report["checks"]["exchanges"][0]["exchange_id"] == identities[0]
    assert report["checks"]["activation_authorized"] is False
    provider.assert_called_once_with(inspector._scope)
    resource_event = operator.events.index(("resources",))
    assert ("permission", "Company", "SOURCE") in operator.events[:resource_event]
    public = json.dumps(report) + repr(inspector)
    for private in (materials[0].pem, materials[0].text, basic(materials[0]), SELLER,
                    "gw-fatoora", "PRIVATE-CSR-SUBJECT", "PRIVATE-RESPONSE-MESSAGE",
                    bundle.manifest.compliance_request_id, histories[0].start.request_bytes.decode()):
        assert private not in public
    database.commit.assert_not_called()
    database.rollback.assert_not_called()
    operator.runtime.db.commit.assert_not_called()
    operator.runtime.db.rollback.assert_not_called()
    assert all(call.args[0].startswith("SELECT") for call in cursor.execute.call_args_list)
    for doc in operator.documents.values():
        doc.save.assert_not_called()
        doc.db_set.assert_not_called()
        doc.check_permission.assert_not_called()


@pytest.mark.parametrize("kind", ["company", "linked_company", "multiple_setting"])
@pytest.mark.parametrize("source_type", ["Sales Invoice", "POS Invoice"])
def test_full_six_type_selection_uses_saved_owner_not_invoice_or_payload_secrets(operator, materials, cipher, archive_cipher, kind, source_type):
    steps = tuple(STEP_CLASSIFICATION)
    prepared = inspection(operator, materials, cipher, archive_cipher, kind=kind, source_type=source_type,
                          steps=steps, statuses=(200, 202, 406, 200, 200, 200))
    report = inspect_prepared(prepared)
    assert report["checks"]["state"] == "COMPLETE_MATCHED_OBSERVATIONS"
    assert report["checks"]["missing_steps"] == [] and len(report["histories"]) == 6
    assert all(value is False for name, value in report["checks"].items() if name.endswith(("_authorized", "_verified")))
    expected = [("Company", "SOURCE")]
    if kind != "company":
        expected += [(source_type, "PI" if source_type == "POS Invoice" else "SI"), ("ZATCA Multiple Setting", "OWNER")]
    if kind == "linked_company":
        expected += [("Company", "OWNER")]
    assert [(e[1], e[2]) for e in operator.events if e[0] == "permission"] == expected


@pytest.mark.parametrize("change", ["guest", "role", "site", "company", "source", "device", "linked_owner"])
def test_all_acl_failures_precede_resource_acquisition(operator, materials, cipher, archive_cipher, change):
    prepared = inspection(operator, materials, cipher, archive_cipher, kind="linked_company")
    if change == "guest":
        operator.runtime.session.user = "Guest"
    elif change == "role":
        operator.runtime.get_roles.return_value = ["Accounts Manager"]
    elif change == "site":
        operator.runtime.local.site = "other.test"
    else:
        denied = {"company": ("Company", "SOURCE"), "source": ("Sales Invoice", "SI"),
                  "device": ("ZATCA Multiple Setting", "OWNER"), "linked_owner": ("Company", "OWNER")}
        operator.denied.add(denied[change])
    with pytest.raises(PermissionDenied, match=access.DENIED_MESSAGE):
        inspect_prepared(prepared)
    prepared[1].assert_not_called()
    prepared[2].cursor.assert_not_called()


@pytest.mark.parametrize("identities", [None, [], (), (VERSION, VERSION), ("latest",), (True,),
    (VERSION.upper(),), tuple(str(uuid4()) for _ in range(65))])
def test_selection_is_bounded_unique_explicit_and_canonical_before_keys(operator, materials, cipher, archive_cipher, identities):
    prepared = inspection(operator, materials, cipher, archive_cipher)
    with pytest.raises(InspectionFailed, match=access.FAILED_MESSAGE) as error:
        prepared[0].inspect_compliance_archive("TC", prepared[6], version_id=VERSION, exchange_ids=identities)
    assert error.value.__context__ is None
    prepared[1].assert_not_called()
    prepared[2].cursor.assert_not_called()


@pytest.mark.parametrize("change", ["missing_archive_key", "wrong_archive_type", "key_domain_reuse", "scope", "driver", "missing_row", "corrupt"])
def test_resource_and_storage_failure_never_returns_partial_or_secret_context(operator, materials, cipher, archive_cipher, monkeypatch, change):
    prepared = inspection(operator, materials, cipher, archive_cipher)
    inspector, provider, database, cursor = prepared[:4]
    if change in ("missing_archive_key", "wrong_archive_type", "key_domain_reuse", "scope"):
        scope = inspector._scope
        archive = None if change == "missing_archive_key" else archive_cipher
        if change == "wrong_archive_type":
            archive = object()
        elif change == "key_domain_reuse":
            archive = access.ComplianceArchiveCipher({"alias": next(iter(cipher._keys.values()))})
        elif change == "scope":
            scope = replace(scope, storage_namespace=str(uuid4()))
        provider.side_effect = lambda requested: access.CredentialStorageResources(scope, database, cipher, archive)
    elif change == "driver":
        cursor.execute.side_effect = RuntimeError("PRIVATE-SECRET SQL")
    else:
        def load(*args):
            if change == "missing_row":
                raise ValueError("PRIVATE-SECRET missing exchange")
            raise ValueError("PRIVATE-SECRET corrupt envelope")
        monkeypatch.setattr(storage.MariaDBComplianceArchiveRepository, "load", load)
    with pytest.raises(InspectionFailed, match=access.FAILED_MESSAGE) as error:
        inspect_prepared(prepared)
    assert error.value.__context__ is None and "PRIVATE-SECRET" not in str(error.value)
    database.commit.assert_not_called()
    database.rollback.assert_not_called()
    if change in ("missing_archive_key", "wrong_archive_type", "scope"):
        database.cursor.assert_not_called()


@pytest.mark.parametrize("change", ["session", "site", "roles"])
@pytest.mark.parametrize("stage", ["provider", "archive_read"])
def test_actor_drift_prevents_metadata_return(operator, materials, cipher, archive_cipher, monkeypatch, change, stage):
    prepared = inspection(operator, materials, cipher, archive_cipher)
    def drift():
        if change == "session":
            operator.runtime.session.user = "other@example.test"
        elif change == "site":
            operator.runtime.local.site = "other.test"
        else:
            operator.runtime.get_roles.return_value = []
    if stage == "provider":
        original = prepared[1].side_effect
        def acquire(scope):
            result = original(scope)
            drift()
            return result
        prepared[1].side_effect = acquire
    else:
        original = storage.MariaDBComplianceArchiveRepository.load
        def load(*args):
            result = original(*args)
            drift()
            return result
        monkeypatch.setattr(storage.MariaDBComplianceArchiveRepository, "load", load)
    with pytest.raises(PermissionDenied):
        inspect_prepared(prepared)
    if stage == "provider":
        prepared[2].cursor.assert_not_called()


@pytest.mark.parametrize("change", ["namespace", "manifest", "taxpayer", "gateway", "csr", "identity", "failure_second", "size"])
def test_rechecks_source_and_shared_csr_and_aborts_entire_selection(operator, materials, cipher, archive_cipher, monkeypatch, change):
    prepared = inspection(operator, materials, cipher, archive_cipher, steps=("SIMPLIFIED", "STANDARD"), statuses=(200, 200))
    histories = prepared[5]
    if change == "taxpayer":
        operator.documents["Company", "SOURCE"].values["tax_id"] = "300000000000013"
    elif change == "size":
        # Exercise the service's aggregate budget with otherwise valid records.
        from zatca_erpgulf.zatca_erpgulf import compliance_evidence
        monkeypatch.setattr(compliance_evidence, "MAX_CHECK_SET_BYTES", 1)
    elif change in ("namespace", "manifest", "gateway", "csr", "identity"):
        current = histories[1].receipt
        req = current.requirements
        if change == "namespace":
            req = replace(req, storage_namespace=str(uuid4()))
        elif change == "manifest":
            req = replace(req, manifest=replace(req.manifest, flow_id=str(uuid4())))
        elif change == "csr":
            req = replace(req, csr_der=csr(materials[0], "1000"))
        route = current.route
        if change == "gateway":
            from zatca_erpgulf.zatca_erpgulf.api_routing import resolve_api_route
            route = resolve_api_route({"custom_select": "Production", "custom_production_url": "https://gateway.invalid/phase2"}, "compliance/invoices")
        current = replace(current, requirements=req, route=route,
                          exchange_id=str(uuid4()) if change == "identity" else current.exchange_id)
        histories[1] = ComplianceArchiveHistory(replace(current, http_status=None, response_bytes=None, received_at=None), current)
    returned = iter(histories)
    def load(*args):
        result = next(returned)
        if change == "failure_second" and result is histories[1]:
            raise RuntimeError("PRIVATE-SECRET second exchange")
        return result
    monkeypatch.setattr(storage.MariaDBComplianceArchiveRepository, "load", load)
    with pytest.raises(InspectionFailed, match=access.FAILED_MESSAGE) as error:
        inspect_prepared(prepared)
    assert error.value.__context__ is None
    prepared[2].commit.assert_not_called()
    prepared[2].rollback.assert_not_called()


def test_protected_resource_cannot_be_pickled_and_missing_archive_dependency_keeps_legacy_inspection(operator, materials, cipher, archive_cipher):
    prepared = inspection(operator, materials, cipher, archive_cipher)
    resources = prepared[1](prepared[0]._scope)
    assert "audit-test" not in repr(resources) and "cipher" not in repr(resources)
    with pytest.raises(CredentialBundleError, match="bundle_not_pickleable"):
        pickle.dumps(resources)
    original = prepared[1].side_effect
    prepared[1].side_effect = lambda scope: replace(original(scope), archive_cipher=None)
    assert prepared[0].inspect("TC", prepared[6], "compliance/invoices", version_id=VERSION) == prepared[4].manifest.diagnostic_projection()


def test_generic_errors_use_existing_arabic_translation(operator, materials, cipher, archive_cipher, monkeypatch):
    prepared = inspection(operator, materials, cipher, archive_cipher)
    monkeypatch.setattr(access, "_", lambda message: "ARABIC: " + message)
    operator.denied.add(("Company", "SOURCE"))
    with pytest.raises(PermissionDenied, match="ARABIC: "):
        inspect_prepared(prepared)
    operator.denied.clear()
    prepared[1].side_effect = RuntimeError("PRIVATE-SECRET")
    with pytest.raises(InspectionFailed, match="ARABIC: "):
        inspect_prepared(prepared)


def test_full_count_bound_is_accepted_without_implicit_listing(operator, materials, cipher, archive_cipher):
    prepared = inspection(operator, materials, cipher, archive_cipher,
                          steps=("SIMPLIFIED",) * 64, statuses=(None,) * 64)
    report = inspect_prepared(prepared)
    assert len(report["histories"]) == 64 and len(report["checks"]["exchanges"]) == 64
    assert report["selection_is_complete_history"] is False
    assert all("WHERE storage_namespace=" in call.args[0] or call.args[0] == "SELECT @@session.autocommit"
               for call in prepared[3].execute.call_args_list)


def test_no_http_or_file_discovery_during_permissioned_read(operator, materials, cipher, archive_cipher, monkeypatch):
    prepared = inspection(operator, materials, cipher, archive_cipher)
    def forbidden(*args, **kwargs):
        raise AssertionError("No HTTP or filesystem access belongs in this service")
    import requests
    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    assert inspect_prepared(prepared)["checks"]["activation_authorized"] is False


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("functionality", ["1000", "0100", "1100"])
def test_required_subset_comes_from_archived_csr_not_blanket_six_types(operator, materials, cipher, archive_cipher, environment, functionality):
    steps = tuple(step for step in STEP_CLASSIFICATION if (
        functionality[0] == "1" if step.startswith("STANDARD") else functionality[1] == "1"))
    prepared = inspection(operator, materials, cipher, archive_cipher, environment=environment,
                          steps=steps, statuses=(200,) * len(steps), functionality=functionality)
    report = inspect_prepared(prepared)
    assert report["checks"]["required_steps"] == list(steps)
    assert report["checks"]["functionality_map"] == functionality
    assert report["checks"]["missing_steps"] == []
    assert len(report["histories"]) == (6 if functionality == "1100" else 3)
    assert report["checks"]["csr_issuance_provenance_verified"] is False
