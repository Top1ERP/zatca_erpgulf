"""Saved ACL/revision-bound capture with fake owned SQL and transport only."""

import csv
import json
import pickle
from dataclasses import replace
from datetime import timedelta
from inspect import signature
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import compliance_capture_access as access
from zatca_erpgulf.zatca_erpgulf.compliance_capture import ComplianceCaptureCoordinator, ComplianceCaptureError
from zatca_erpgulf.zatca_erpgulf.compliance_evidence import ComplianceRequirements, STEP_CLASSIFICATION
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_capture import Scenario, OwnedFakeTransaction, materials, cipher, archive_cipher
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_evidence import csr
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_bundle import seal, record, NAMESPACE, NOW, connection
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_bundle_access import operator, PermissionDenied, InspectionFailed, SavedDocument
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_snapshot import capture, owner, basic
from zatca_erpgulf.zatca_erpgulf.tests.test_artifact_evidence import SELLER
from zatca_erpgulf.zatca_erpgulf.tests.test_api_route_contract import settings as route_settings


@pytest.fixture
def capture_operator(operator, monkeypatch):
    for doc in operator.documents.values():
        doc.values["modified"] = NOW.replace(tzinfo=None)
    for name in ("SOURCE", "OWNER"):
        operator.documents["Company", name].values.update(tax_id=SELLER, abbr="TC" if name == "SOURCE" else "OWN")
    operator.denied_operations = set()
    def permission(doctype, operation, *, doc, user, raise_exception):
        assert operation in ("read", "write") and user == operator.runtime.session.user and raise_exception is False
        operator.events.append(("permission", doctype, doc.name, operation))
        return (doctype, doc.name) not in operator.denied and (doctype, doc.name, operation) not in operator.denied_operations
    monkeypatch.setattr(access, "frappe", operator.runtime)
    engine = Mock(side_effect=permission)
    engine.__signature__ = signature(permission)
    monkeypatch.setattr(access, "has_permission", engine)
    monkeypatch.setattr(access, "_", lambda value: value)
    return operator


class SourceTransaction(OwnedFakeTransaction):
    def execute(self, sql, values=None):
        self.context.sql.append((self.index, sql, values))
        if sql.startswith("SELECT `modified`"):
            assert sql.endswith("WHERE `name`=%s FOR UPDATE")
            doctype = sql.split(" FROM `tab", 1)[1].split("`", 1)[0]
            doc = self.context.sql_documents.get((doctype, values[-1]))
            self.row = None if doc is None else (doc.get("modified"), *(doc.get(field) for field in access.SOURCE_FIELDS[doctype]))
        else:
            super().execute(sql, values)


def scenario_for(operator, material, cipher, archive_cipher, *, environment="Production", step="SIMPLIFIED", source="company", status=200):
    scenario = Scenario(material, cipher, archive_cipher, environment=environment, step=step, status=status)
    operator.documents["Company", "SOURCE"].values.update(route_settings(environment))
    device = operator.documents["ZATCA Multiple Setting", "OWNER"]
    kind = "company" if source in ("company", "implicit") else "multiple_setting"
    if source == "linked":
        device.values.update(custom_linked_doctype="OWNER", custom__use_company_certificate__keys=1)
        kind = "linked_company"
    selected = owner(material, doctype="ZATCA Multiple Setting" if kind == "multiple_setting" else "Company", kind=kind)
    scenario.bundle = seal(cipher, capture(material, environment=environment, endpoint="compliance/invoices", selected_owner=selected))
    scenario.requirements = ComplianceRequirements(NAMESPACE, scenario.bundle.manifest, csr(material))
    scenario.source = {"doctype": {"company": "Company", "sales": "Sales Invoice", "pos": "POS Invoice",
        "device": "ZATCA Multiple Setting", "linked": "Sales Invoice"}.get(source, "Company"),
        "name": {"company": "SOURCE", "sales": "SI", "pos": "PI", "device": "OWNER", "linked": "SI"}.get(source, "SOURCE")}
    if source == "implicit":
        scenario.source = None
    scenario.sql_documents = {identity: dict(doc.values) for identity, doc in operator.documents.items()}
    scenario.sql = []
    def acquire():
        transaction = SourceTransaction(scenario, len(scenario.connections))
        scenario.connections.append(transaction)
        return transaction
    scenario.factory.side_effect = acquire
    scope = access.CredentialStorageScope("private.test", NAMESPACE)
    scenario.resources = access.ComplianceCaptureResources(scope, cipher, archive_cipher, "audit-test",
        scenario.factory, scenario.transport, scenario.clock)
    scenario.provider = Mock(return_value=scenario.resources)
    scenario.service = access.StagedComplianceCaptureService(scope, scenario.provider)
    def run(**changes):
        values = dict(exchange_id=scenario.identity, request_bytes=scenario.body)
        values.update(changes)
        return scenario.service.capture("TC", scenario.source, scenario.requirements, **values)
    scenario.collect = run
    return scenario


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("step", list(STEP_CLASSIFICATION))
@pytest.mark.parametrize("source", ["implicit", "company", "sales", "pos", "device", "linked"])
def test_saved_owner_acl_and_three_closed_transactions_without_live_adoption(capture_operator, materials, cipher, archive_cipher, environment, step, source):
    scenario = scenario_for(capture_operator, materials[0], cipher, archive_cipher, environment=environment, step=step, source=source)
    result = scenario.collect()
    assert result.state == "RECEIPT_CAPTURED_OBSERVATION"
    assert scenario.events == [("commit", 0), ("close", 0), ("commit", 1), ("close", 1), ("transport",), ("commit", 2), ("close", 2)]
    assert scenario.transport.call_count == 1 and all(db.closed for db in scenario.connections)
    for index in (0, 1):
        sql = [statement for position, statement, _ in scenario.sql if position == index]
        assert any("FROM `tabCompany`" in statement for statement in sql)
        if index == 0:
            assert next(n for n, statement in enumerate(sql) if "FROM `tabCompany`" in statement) < next(
                n for n, statement in enumerate(sql) if statement.startswith("SELECT slot_sha256"))
        assert all(field not in statement for field in ("custom_private_key", "custom_certificate", "custom_basic_auth") for statement in sql)
    public = json.dumps(result.diagnostic_projection()) + repr(scenario.service) + repr(scenario.resources)
    for private in (materials[0].pem, materials[0].text, basic(materials[0]), SELLER, "gw-fatoora", scenario.body.decode()):
        assert private not in public
    assert all(value is False for name, value in result.diagnostic_projection().items() if name.endswith(("_verified", "_authorized")))
    capture_operator.runtime.db.commit.assert_not_called()
    capture_operator.runtime.db.rollback.assert_not_called()
    for doc in capture_operator.documents.values():
        doc.save.assert_not_called()
        doc.db_set.assert_not_called()
        doc.check_permission.assert_not_called()


@pytest.mark.parametrize("identity", [("Company", "SOURCE"), ("Sales Invoice", "SI"),
    ("ZATCA Multiple Setting", "OWNER"), ("Company", "OWNER")])
@pytest.mark.parametrize("operation", ["read", "write"])
def test_every_row_acl_denied_before_provider_even_with_ignore_flags(capture_operator, materials, cipher, archive_cipher, identity, operation):
    scenario = scenario_for(capture_operator, materials[0], cipher, archive_cipher, source="linked")
    capture_operator.denied_operations.add((*identity, operation))
    with pytest.raises(PermissionDenied, match=access.DENIED_MESSAGE):
        scenario.collect()
    scenario.provider.assert_not_called()
    scenario.factory.assert_not_called()
    scenario.transport.assert_not_called()


@pytest.mark.parametrize("user,roles,site", [("Guest", ["System Manager"], "private.test"),
    ("manager@example.test", [], "private.test"), ("Administrator", [], "other.test"),
    (None, ["System Manager"], "private.test"), ("", ["System Manager"], "private.test")])
def test_actor_denial_before_saved_reads_and_provider(capture_operator, materials, cipher, archive_cipher, user, roles, site):
    scenario = scenario_for(capture_operator, materials[0], cipher, archive_cipher)
    capture_operator.runtime.session.user, capture_operator.runtime.local.site = user, site
    capture_operator.runtime.get_roles.return_value = roles
    with pytest.raises(PermissionDenied):
        scenario.collect()
    capture_operator.runtime.get_doc.assert_not_called()
    scenario.provider.assert_not_called()


@pytest.mark.parametrize("change", ["taxpayer", "environment", "owner", "kind", "namespace", "body", "exchange", "revision", "field", "identity"])
def test_saved_or_input_mismatch_before_provider(capture_operator, materials, cipher, archive_cipher, change):
    scenario = scenario_for(capture_operator, materials[0], cipher, archive_cipher)
    values = {}
    if change in ("owner", "kind"):
        manifest = replace(scenario.requirements.manifest, **({"source_kind": "linked_company"} if change == "kind" else {
            "source_kind": "linked_company", "slot": replace(scenario.requirements.manifest.slot, owner_name="OTHER")}))
        scenario.requirements = replace(scenario.requirements, manifest=manifest)
    elif change == "namespace":
        scenario.requirements = replace(scenario.requirements, storage_namespace=str(uuid4()))
    elif change == "body":
        values["request_bytes"] = b"{}"
    elif change == "exchange":
        values["exchange_id"] = "latest"
    else:
        doc = capture_operator.documents["Company", "SOURCE"]
        key, value = {"taxpayer": ("tax_id", "OTHER"), "environment": ("custom_select", "Sandbox"),
            "revision": ("modified", None), "field": ("custom_simulation_url", 10), "identity": ("abbr", "WRONG")}[change]
        doc.values[key] = value
    with pytest.raises(InspectionFailed, match=access.FAILED_MESSAGE):
        scenario.collect(**values)
    scenario.provider.assert_not_called()
    scenario.factory.assert_not_called()


@pytest.mark.parametrize("phase", [0, 1])
@pytest.mark.parametrize("change", ["revision", "route", "taxpayer", "source_link", "owner_link", "flag", "missing", "acl", "actor", "role"])
def test_drift_stops_before_send_and_keeps_reservation_only_after_commit(capture_operator, materials, cipher, archive_cipher, phase, change):
    scenario = scenario_for(capture_operator, materials[0], cipher, archive_cipher, source="sales")
    original = scenario.factory.side_effect
    def acquire():
        db = original()
        if db.index == phase:
            if change == "acl":
                capture_operator.denied_operations.add(("Company", "SOURCE", "write"))
            elif change == "actor":
                capture_operator.runtime.session.user = "other@example.test"
            elif change == "role":
                capture_operator.runtime.get_roles.return_value = []
            elif change == "missing":
                del scenario.sql_documents["Sales Invoice", "SI"]
            else:
                identity, field, value = {
                    "revision": (("Company", "SOURCE"), "modified", NOW.replace(tzinfo=None) + timedelta(seconds=1)),
                    "route": (("Company", "SOURCE"), "custom_production_url", "https://other.invalid/core"),
                    "taxpayer": (("Company", "SOURCE"), "tax_id", "OTHER"),
                    "source_link": (("Sales Invoice", "SI"), "custom_zatca_pos_name", "OTHER"),
                    "owner_link": (("ZATCA Multiple Setting", "OWNER"), "custom_linked_doctype", "OTHER"),
                    "flag": (("ZATCA Multiple Setting", "OWNER"), access.FLAG_FIELD, 1),
                }[change]
                # SQL state differs even if ambient Frappe reads are stale.
                scenario.sql_documents[identity][field] = value
        return db
    scenario.factory.side_effect = acquire
    result = scenario.collect()
    assert result.state == ("PREPARATION_UNCONFIRMED_NO_SEND" if phase == 0 else "DISPATCH_PREFLIGHT_FAILED_NO_SEND")
    assert bool(scenario.rows) is (phase == 1)
    assert all(db.closed for db in scenario.connections)
    scenario.transport.assert_not_called()


@pytest.mark.parametrize("change", ["saved_revision", "saved_link", "provider_error", "scope", "type", "session", "site"])
def test_provider_failure_or_drift_never_releases_material(capture_operator, materials, cipher, archive_cipher, change):
    scenario = scenario_for(capture_operator, materials[0], cipher, archive_cipher)
    def provider(scope):
        if change == "provider_error":
            raise RuntimeError("PRIVATE-SECRET provider failure")
        if change == "scope":
            return replace(scenario.resources, scope=access.CredentialStorageScope(scope.site, str(uuid4())))
        if change == "type":
            return Mock()
        if change == "saved_revision":
            capture_operator.documents["Company", "SOURCE"].values["modified"] += timedelta(seconds=1)
        elif change == "saved_link":
            capture_operator.documents["Company", "SOURCE"].values["tax_id"] = "OTHER"
        elif change == "session":
            capture_operator.runtime.session.user = "other@example.test"
        elif change == "site":
            capture_operator.runtime.local.site = "other.test"
        return scenario.resources
    scenario.provider.side_effect = provider
    if change in ("saved_revision", "saved_link"):
        assert scenario.collect().state == "PREPARATION_UNCONFIRMED_NO_SEND"
    else:
        with pytest.raises(PermissionDenied if change in ("session", "site") else InspectionFailed) as raised:
            scenario.collect()
        assert raised.value.__context__ is None and "PRIVATE-SECRET" not in str(raised.value)
        scenario.factory.assert_not_called()
    scenario.transport.assert_not_called()


def test_duplicate_and_unknown_transport_have_no_automatic_replay(capture_operator, materials, cipher, archive_cipher):
    scenario = scenario_for(capture_operator, materials[0], cipher, archive_cipher)
    scenario.transport.side_effect = RuntimeError("PRIVATE-SECRET unconfirmed")
    assert scenario.collect().state == "TRANSPORT_UNKNOWN_NO_REPLAY"
    scenario.clock.side_effect = None
    scenario.clock.return_value = NOW + timedelta(seconds=1)
    assert scenario.collect().state == "PREPARATION_UNCONFIRMED_NO_SEND"
    assert scenario.transport.call_count == 1 and len(scenario.rows) == 1


@pytest.mark.parametrize("mode", ["capture", "inspection"])
@pytest.mark.parametrize("version", [15, 16])
def test_both_permissioned_services_use_quiet_version_shaped_engine(capture_operator, materials, cipher, archive_cipher, monkeypatch, mode, version):
    from zatca_erpgulf.zatca_erpgulf import credential_bundle_access as inspection

    scenario = scenario_for(capture_operator, materials[0], cipher, archive_cipher, source="linked")
    original = access.has_permission.side_effect
    calls = []
    def v15(doctype, ptype="read", doc=None, user=None, raise_exception=True):
        calls.append(raise_exception)
        return original(doctype, ptype, doc=doc, user=user, raise_exception=raise_exception)
    def v16(doctype, ptype="read", doc=None, user=None, *, print_logs=True):
        calls.append(print_logs)
        return original(doctype, ptype, doc=doc, user=user, raise_exception=print_logs)
    engine = v15 if version == 15 else v16
    monkeypatch.setattr(access, "has_permission", engine)
    monkeypatch.setattr(inspection, "has_permission", engine)
    if mode == "capture":
        assert scenario.collect().state == "RECEIPT_CAPTURED_OBSERVATION"
    else:
        db, _ = connection([(0,), record(scenario.bundle)])
        resources = inspection.CredentialStorageResources(scenario.resources.scope, db, cipher)
        service = inspection.StagedCredentialInspectionService(scenario.resources.scope, lambda scope: resources)
        assert service.inspect("TC", scenario.source, "compliance/invoices",
            version_id=scenario.bundle.manifest.version_id) == scenario.bundle.manifest.diagnostic_projection()
    assert calls and all(value is False for value in calls)


@pytest.mark.parametrize("phase", [0, 1])
def test_permission_revocation_during_owned_sql_stops_after_sql_check(capture_operator, materials, cipher, archive_cipher, phase):
    scenario = scenario_for(capture_operator, materials[0], cipher, archive_cipher)
    original = scenario.factory.side_effect
    def acquire():
        db = original()
        execute = db.cursor.return_value.execute.side_effect
        def run_sql(sql, values=None):
            result = execute(sql, values)
            if db.index == phase and "FROM `tabCompany`" in sql:
                capture_operator.denied_operations.add(("Company", "SOURCE", "write"))
            return result
        db.cursor.return_value.execute.side_effect = run_sql
        return db
    scenario.factory.side_effect = acquire
    assert scenario.collect().state == ("PREPARATION_UNCONFIRMED_NO_SEND" if phase == 0 else "DISPATCH_PREFLIGHT_FAILED_NO_SEND")
    assert all(db.closed for db in scenario.connections)
    scenario.transport.assert_not_called()


@pytest.mark.parametrize("failure", ["factory", "commit_before", "commit_after", "close"])
def test_preflight_connection_uncertainty_leaves_spent_identity_without_send(capture_operator, materials, cipher, archive_cipher, failure):
    scenario = scenario_for(capture_operator, materials[0], cipher, archive_cipher)
    original = scenario.factory.side_effect
    def acquire():
        if len(scenario.connections) == 1 and failure == "factory":
            raise RuntimeError("PRIVATE-SECRET acquisition")
        db = original()
        if db.index == 1:
            if failure == "close":
                close = db.close.side_effect
                def fail_close():
                    close()
                    raise RuntimeError("PRIVATE-SECRET close")
                db.close.side_effect = fail_close
            else:
                commit = db.commit.side_effect
                def fail_commit():
                    if failure == "commit_after":
                        commit()
                    raise RuntimeError("PRIVATE-SECRET commit")
                db.commit.side_effect = fail_commit
        return db
    scenario.factory.side_effect = acquire
    assert scenario.collect().state == "DISPATCH_PREFLIGHT_FAILED_NO_SEND"
    assert len(scenario.rows) == 1 and all(db.closed for db in scenario.connections)
    scenario.transport.assert_not_called()


@pytest.mark.parametrize("change", ["actor", "role", "acl", "saved_row"])
def test_final_actor_acl_check_after_owned_connection_close_precedes_real_sender(capture_operator, materials, cipher, archive_cipher, change):
    scenario = scenario_for(capture_operator, materials[0], cipher, archive_cipher)
    original = scenario.factory.side_effect
    def acquire():
        db = original()
        close = db.close.side_effect
        def release():
            close()
            if db.index == 1:
                if change == "actor":
                    capture_operator.runtime.session.user = "other@example.test"
                elif change == "role":
                    capture_operator.runtime.get_roles.return_value = []
                elif change == "acl":
                    capture_operator.denied_operations.add(("Company", "SOURCE", "write"))
                else:
                    capture_operator.documents["Company", "SOURCE"].values["modified"] += timedelta(seconds=1)
        db.close.side_effect = release
        return db
    scenario.factory.side_effect = acquire
    result = scenario.collect()
    assert result.state == "TRANSPORT_UNKNOWN_NO_REPLAY" and len(scenario.rows) == 1
    scenario.transport.assert_not_called()


@pytest.mark.parametrize("phase", [0, 1])
def test_source_guard_process_interruption_closes_owned_transaction(materials, cipher, archive_cipher, phase):
    scenario = Scenario(materials[0], cipher, archive_cipher)
    guard = Mock(side_effect=([True, KeyboardInterrupt()] if phase else KeyboardInterrupt()))
    collector = ComplianceCaptureCoordinator(NAMESPACE, cipher, archive_cipher, "audit-test", connection_factory=scenario.factory,
        transport=scenario.transport, clock=scenario.clock, source_guard=guard)
    with pytest.raises(KeyboardInterrupt):
        collector.capture(scenario.requirements, exchange_id=scenario.identity, route=scenario.route, request_bytes=scenario.body)
    assert all(db.closed for db in scenario.connections) and bool(scenario.rows) is (phase == 1)
    scenario.transport.assert_not_called()


@pytest.mark.parametrize("phase", [0, 1])
@pytest.mark.parametrize("returned", [False, None, 1, {}, "yes"])
def test_coordinator_guard_requires_literal_true(materials, cipher, archive_cipher, phase, returned):
    scenario = Scenario(materials[0], cipher, archive_cipher)
    guard = Mock(side_effect=[True, returned] if phase else [returned])
    collector = ComplianceCaptureCoordinator(NAMESPACE, cipher, archive_cipher, "audit-test",
        connection_factory=scenario.factory, transport=scenario.transport, clock=scenario.clock, source_guard=guard)
    result = collector.capture(scenario.requirements, exchange_id=scenario.identity, route=scenario.route, request_bytes=scenario.body)
    assert result.state == ("PREPARATION_UNCONFIRMED_NO_SEND" if phase == 0 else "DISPATCH_PREFLIGHT_FAILED_NO_SEND")
    assert guard.call_count == phase + 1 and all(db.closed for db in scenario.connections)
    scenario.transport.assert_not_called()


@pytest.mark.parametrize("value", [None, "2026-10-10", "2026-10-10T12:00:00Z", NOW, "broken", 1])
def test_revision_rejects_missing_aware_and_incomplete_markers(value):
    with pytest.raises(access.ComplianceSourceError, match="source_revision"):
        access._revision(value)


@pytest.mark.parametrize("value", [NOW.replace(tzinfo=None), "2026-10-10 12:00:00", "2026-10-10T12:00:00.000000"])
def test_revision_normalizes_saved_frappe_and_sql_datetime(value):
    assert access._revision(value) == "2026-10-10T12:00:00.000000"


@pytest.mark.parametrize("raw", [None, (1,), (False,), [0], (0, 0)])
def test_sql_revalidation_denies_autocommit_and_untrusted_shape(capture_operator, raw):
    row = access.SavedComplianceSourceRow.from_document(capture_operator.documents["Company", "SOURCE"])
    db, cursor = connection([raw])
    with pytest.raises(access.ComplianceSourceError, match="source_autocommit"):
        access.verify_saved_source_rows(db, (row,))
    assert cursor.execute.call_count == 1
    db.commit.assert_not_called()
    db.close.assert_not_called()


@pytest.mark.parametrize("selection", [None, (), [], "row", (Mock(),)])
def test_sql_selection_is_explicit_bounded_and_typed(selection):
    db = Mock()
    with pytest.raises(access.ComplianceSourceError, match="source_selection"):
        access.verify_saved_source_rows(db, selection)
    db.cursor.assert_not_called()


def test_sql_name_parameterization_bounds_no_secret_fields_or_cleanup(capture_operator):
    doc = SavedDocument("Company", "O'Reilly`; DROP TABLE nope", **capture_operator.documents["Company", "SOURCE"].values)
    row = access.SavedComplianceSourceRow.from_document(doc)
    db, cursor = connection([(0,), (doc.get("modified"), *row.values)])
    assert access.verify_saved_source_rows(db, (row,)) is True
    sql, params = cursor.execute.call_args.args
    assert doc.name not in sql and params[-1] == doc.name
    assert all(limit == access.MAX_FIELD_CHARS + 1 for limit in params[:-1])
    assert sql.endswith("FOR UPDATE") and "SUBSTRING" in sql
    for method in (db.commit, db.rollback, db.close):
        method.assert_not_called()


def test_protected_objects_translation_and_no_public_registration(capture_operator, materials, cipher, archive_cipher):
    scenario = scenario_for(capture_operator, materials[0], cipher, archive_cipher)
    row = access.SavedComplianceSourceRow.from_document(capture_operator.documents["Company", "SOURCE"])
    for obj in (row, scenario.resources, scenario.service):
        with pytest.raises(access.ComplianceSourceError, match="not_pickleable"):
            pickle.dumps(obj)
        assert SELLER not in repr(obj) and "gw-fatoora" not in repr(obj)
    with pytest.raises(ComplianceCaptureError, match="capture_dependencies"):
        ComplianceCaptureCoordinator(NAMESPACE, cipher, archive_cipher, "audit-test", connection_factory=scenario.factory,
            transport=scenario.transport, clock=scenario.clock, source_guard=False)
    catalog = Path(__file__).resolve().parents[2] / "translations/ar.csv"
    with catalog.open() as stream:
        translations = {row[0]: row[1] for row in csv.reader(stream) if len(row) >= 2}
    for message in (access.DENIED_MESSAGE, access.FAILED_MESSAGE):
        assert translations[message] != message
    assert not getattr(access.StagedComplianceCaptureService.capture, "is_whitelisted", False)
