"""Permissioned metadata with synthetic saved rows/owned handles only."""

import csv
from dataclasses import replace
from datetime import datetime, timedelta
import json
from pathlib import Path
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import advance_source_access as access
from zatca_erpgulf.zatca_erpgulf.api_routing import ENVIRONMENT_FIELDS
from zatca_erpgulf.zatca_erpgulf.tests.test_advance_source_selection import advance, receipt
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import Document


class PermissionDenied(Exception):
    pass


class InspectionFailed(Exception):
    pass


NOW = datetime(2026, 10, 11, 12, 0)


@pytest.fixture
def operator(monkeypatch):
    documents, denied, sql = {}, set(), []
    runtime = SimpleNamespace(local=SimpleNamespace(site="private.test"),
        session=SimpleNamespace(user="manager@example.test"), get_roles=Mock(return_value=["System Manager"]),
        db=SimpleNamespace(commit=Mock(), rollback=Mock(), _conn=object()),
        PermissionError=PermissionDenied, ValidationError=InspectionFailed)
    def throw(message, exception=InspectionFailed):
        raise exception(message)
    runtime.throw = throw
    runtime.get_doc = Mock(side_effect=lambda dt, name: documents[dt, name])
    def permission(dt, operation, *, doc, user, raise_exception=False):
        assert operation == "read" and raise_exception is False
        return (dt, doc.name) not in denied
    acl = Mock(wraps=permission)
    # Expose the inspected v15 signature, not a generic Mock (*args, **kwargs).
    def engine(dt, operation, *, doc, user, raise_exception=False):
        return acl(dt, operation, doc=doc, user=user, raise_exception=raise_exception)
    monkeypatch.setattr(access, "frappe", runtime)
    monkeypatch.setattr(access, "_", lambda text: text)
    monkeypatch.setattr(access, "has_permission", engine)
    return SimpleNamespace(runtime=runtime, documents=documents, denied=denied, sql=sql, acl=acl)


def scenario(operator, der, monkeypatch, *, indicator="0200000", environment="Production", owner="company", marker="is_advance_payment"):
    original = advance(der, indicator=indicator, environment=environment)
    if owner != "company":
        credential = replace(original.context.credential_epoch,
            owner_doctype="ZATCA Multiple Setting" if owner == "device" else "Company",
            owner_name="DEVICE" if owner == "device" else "LINKED")
        original = replace(original, context=replace(original.context, credential_epoch=credential))
    journal = receipt(original)
    def document(dt, name, **values):
        doc = Document(doctype=dt, name=name, modified=NOW, **values)
        doc.meta = SimpleNamespace(has_field=lambda field: field in values)
        doc.save = Mock(side_effect=AssertionError("No document save"))
        doc.db_set = Mock(side_effect=AssertionError("No document write"))
        doc.check_permission = Mock(side_effect=AssertionError("No ignore_permissions shortcut"))
        operator.documents[dt, name] = doc
        return doc
    company = document("Company", "TEST", abbr="TEST", tax_id=original.context.scope.seller_tax_id,
        custom_select=environment, **{field: "https://gateway.invalid/phase2" for field in ENVIRONMENT_FIELDS.values()},
        custom_private_key="PRIVATE-NEVER-READ", custom_basic_auth_from_production="PRIVATE-TOKEN")
    invoice = document("Sales Invoice", "INV-TEST", company="TEST", docstatus=1,
        custom_uuid=original.artifact.uuid, custom_zatca_icv=original.artifact.icv,
        custom_zatca_issuing_unit=original.context.scope.legacy_issuing_unit,
        custom_zatca_status="CLEARED" if indicator.startswith("01") else "REPORTED",
        custom_zatca_pos_name="DEVICE" if owner != "company" else None, **{marker: 1})
    if owner != "company":
        document("ZATCA Multiple Setting", "DEVICE", custom_linked_doctype="LINKED" if owner == "linked" else "TEST",
            custom__use_company_certificate__keys=1 if owner == "linked" else 0)
        if owner == "linked":
            document("Company", "LINKED", abbr="LINKED", tax_id=company.tax_id,
                custom_select=environment, **{field: "https://gateway.invalid/phase2" for field in ENVIRONMENT_FIELDS.values()})
    scope = access.CredentialStorageScope("private.test", "31234567-1234-4123-8123-123456789abc")
    binding = access.AdvanceSourceBinding(scope, original.context, original.artifact.uuid,
        original.artifact.icv, journal.journal_sha256)
    class Cursor:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute(self, statement, parameters=()):
            operator.sql.append((statement, parameters))
            if statement == "SELECT @@session.autocommit":
                self.result = (0,)
                return
            assert "FOR UPDATE" in statement
            dt = statement.split("FROM `tab", 1)[1].split("`", 1)[0]
            doc = operator.documents[dt, parameters[-1]]
            row = access._SavedRow.from_document(doc)
            self.result = (row.name, NOW, *row.values)
        def fetchone(self):
            return self.result
    database = SimpleNamespace(cursor=Mock(side_effect=Cursor), rollback=Mock(), close=Mock(), commit=Mock())
    lookup = Mock(return_value=binding)
    factory = Mock(return_value=database)
    repository = Mock()
    repository.load.return_value = journal
    repository_factory = Mock(return_value=repository)
    monkeypatch.setattr(access, "MariaDBJournalRepository", repository_factory)
    service = access.ArchivedAdvanceInspectionService(scope, lookup, factory)
    return SimpleNamespace(service=service, scope=scope, binding=binding, journal=journal, original=original,
        company=company, invoice=invoice, database=database, lookup=lookup, factory=factory,
        repository=repository, repository_factory=repository_factory)


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("owner", ["company", "device", "linked"])
@pytest.mark.parametrize("marker", access.MARKERS)
def test_saved_permissions_source_locks_exact_lookup_and_metadata_only(operator, certificates, monkeypatch, environment, indicator, owner, marker):
    case = scenario(operator, certificates[0], monkeypatch, environment=environment, indicator=indicator, owner=owner, marker=marker)
    report = case.service.inspect("INV-TEST")
    assert report["source_kind"] == ("CLEARANCE_RETURNED_XML" if indicator.startswith("01") else "REPORTING_REQUEST_XML")
    assert all(value is False for key, value in report.items() if key.endswith(("_verified", "_authorized")))
    assert "PRIVATE" not in json.dumps(report) and "INV-TEST" not in json.dumps(report)
    case.lookup.assert_called_once()
    case.factory.assert_called_once_with(case.scope)
    case.repository.load.assert_called_once_with(case.original.key_sha256)
    assert case.database.rollback.call_count == 2 and case.database.close.call_count == 1
    case.database.commit.assert_not_called()
    operator.runtime.db.commit.assert_not_called()
    operator.runtime.db.rollback.assert_not_called()
    for doc in operator.documents.values():
        doc.save.assert_not_called()
        doc.db_set.assert_not_called()
        doc.check_permission.assert_not_called()
    assert all("PRIVATE" not in str(args) for args in operator.sql)


@pytest.mark.parametrize("identity", [("Sales Invoice", "INV-TEST"), ("Company", "TEST"),
    ("ZATCA Multiple Setting", "DEVICE"), ("Company", "LINKED")])
def test_every_saved_acl_before_lookup_or_database_even_with_ignore_permissions(operator, certificates, monkeypatch, identity):
    case = scenario(operator, certificates[0], monkeypatch, owner="linked")
    operator.denied.add(identity)
    operator.documents[identity].flags = SimpleNamespace(ignore_permissions=True)
    with pytest.raises(PermissionDenied) as error:
        case.service.inspect("INV-TEST")
    assert str(error.value) == access.DENIED_MESSAGE and error.value.__context__ is None
    case.lookup.assert_not_called()
    case.factory.assert_not_called()


@pytest.mark.parametrize("user,roles,site", [("Guest", ["System Manager"], "private.test"),
    (None, ["System Manager"], "private.test"), ("manager@example.test", [], "private.test"),
    ("Administrator", [], "other.test")])
def test_actor_site_role_guard_before_any_saved_row(operator, certificates, monkeypatch, user, roles, site):
    case = scenario(operator, certificates[0], monkeypatch)
    operator.runtime.session.user, operator.runtime.local.site = user, site
    operator.runtime.get_roles.return_value = roles
    with pytest.raises(PermissionDenied):
        case.service.inspect("INV-TEST")
    operator.runtime.get_doc.assert_not_called()
    case.lookup.assert_not_called()
    case.factory.assert_not_called()


@pytest.mark.parametrize("field,value", [("docstatus", 0), ("docstatus", 2), ("is_advance_payment", 0),
    ("custom_uuid", "01234567-1234-4123-8123-123456789abc"), ("custom_zatca_icv", 78),
    ("custom_zatca_issuing_unit", "OTHER"), ("custom_zatca_status", "PHASE-1 QR GENERATED"),
    ("custom_zatca_status", "NOT_REPORTED")])
def test_saved_source_drift_or_phase1_missing_archive_policy_never_opens_sql(operator, certificates, monkeypatch, field, value):
    case = scenario(operator, certificates[0], monkeypatch)
    setattr(case.invoice, field, value)
    with pytest.raises(InspectionFailed) as error:
        case.service.inspect("INV-TEST")
    assert str(error.value) == access.FAILED_MESSAGE and error.value.__context__ is None
    case.factory.assert_not_called()


@pytest.mark.parametrize("stage", ["lookup", "factory", "load", "close"])
@pytest.mark.parametrize("change", ["permission", "actor", "revision"])
def test_revocation_or_edits_at_each_boundary_prevent_disclosure(operator, certificates, monkeypatch, stage, change):
    case = scenario(operator, certificates[0], monkeypatch)
    def mutate(*args):
        if change == "permission":
            operator.denied.add(("Sales Invoice", "INV-TEST"))
        elif change == "actor":
            operator.runtime.session.user = "other-manager@example.test"
        else:
            case.invoice.modified += timedelta(seconds=1)
        return {"lookup": case.binding, "factory": case.database, "load": case.journal, "close": None}[stage]
    {"lookup": case.lookup, "factory": case.factory, "load": case.repository.load, "close": case.database.close}[stage].side_effect = mutate
    with pytest.raises(PermissionDenied if change != "revision" else InspectionFailed) as error:
        case.service.inspect("INV-TEST")
    assert error.value.__context__ is None
    if stage != "lookup":
        assert case.database.close.call_count == 1
    else:
        case.factory.assert_not_called()


@pytest.mark.parametrize("stage", ["lookup", "factory", "load", "rollback", "close"])
def test_private_failures_redacted_and_owned_handle_closed(operator, certificates, monkeypatch, stage):
    case = scenario(operator, certificates[0], monkeypatch)
    target = {"lookup": case.lookup, "factory": case.factory, "load": case.repository.load,
              "rollback": case.database.rollback, "close": case.database.close}[stage]
    target.side_effect = RuntimeError("PRIVATE-SECRET underlying failure")
    with pytest.raises(InspectionFailed) as error:
        case.service.inspect("INV-TEST")
    assert str(error.value) == access.FAILED_MESSAGE and error.value.__context__ is None
    if stage not in ("lookup", "factory"):
        assert case.database.close.call_count == 1
    case.database.commit.assert_not_called()


@pytest.mark.parametrize("borrowed", ["db", "raw"])
def test_recognizable_shared_handle_is_not_rolled_back_or_closed(operator, certificates, monkeypatch, borrowed):
    case = scenario(operator, certificates[0], monkeypatch)
    operator.runtime.db._conn = case.database
    case.factory.return_value = operator.runtime.db if borrowed == "db" else case.database
    with pytest.raises(InspectionFailed):
        case.service.inspect("INV-TEST")
    operator.runtime.db.rollback.assert_not_called()
    case.database.rollback.assert_not_called()
    case.database.close.assert_not_called()


@pytest.mark.parametrize("stage", ["load", "rollback", "close"])
def test_interruptions_close_owned_handle_and_propagate(operator, certificates, monkeypatch, stage):
    case = scenario(operator, certificates[0], monkeypatch)
    {"load": case.repository.load, "rollback": case.database.rollback, "close": case.database.close}[stage].side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        case.service.inspect("INV-TEST")
    assert case.database.close.call_count == 1


def test_standard_zero_does_not_fall_back_to_truthy_custom_marker(operator, certificates, monkeypatch):
    case = scenario(operator, certificates[0], monkeypatch)
    case.invoice.is_advance_payment, case.invoice.custom_is_advance_payment = 0, 1
    case.invoice.meta.has_field = lambda name: name in access.MARKERS
    with pytest.raises(InspectionFailed):
        case.service.inspect("INV-TEST")
    case.factory.assert_not_called()


def test_ambient_proxy_failure_precedes_owned_acquisition(operator, certificates, monkeypatch):
    case = scenario(operator, certificates[0], monkeypatch)
    class BrokenAmbient:
        @property
        def _conn(self):
            raise RuntimeError("PRIVATE-SECRET uninitialized ambient proxy")
    operator.runtime.db = BrokenAmbient()
    with pytest.raises(InspectionFailed) as error:
        case.service.inspect("INV-TEST")
    assert str(error.value) == access.FAILED_MESSAGE and error.value.__context__ is None
    case.factory.assert_not_called()
    case.database.rollback.assert_not_called()
    case.database.close.assert_not_called()


def test_binding_and_service_not_pickleable_and_arabic_operator_messages(operator, certificates, monkeypatch):
    case = scenario(operator, certificates[0], monkeypatch)
    for value in (case.binding, case.service):
        assert "PRIVATE" not in repr(value) and "INV-TEST" not in repr(value)
        with pytest.raises(access.AdvanceSourceAccessError):
            pickle.dumps(value)
    catalog = Path(__file__).resolve().parents[2] / "translations/ar.csv"
    with catalog.open() as stream:
        translations = {row[0]: row[1] for row in csv.reader(stream) if len(row) >= 2}
    for message in (access.DENIED_MESSAGE, access.FAILED_MESSAGE):
        assert translations[message] != message
    monkeypatch.setattr(access, "_", lambda message: translations[message])
    operator.denied.add(("Sales Invoice", "INV-TEST"))
    with pytest.raises(PermissionDenied, match=translations[access.DENIED_MESSAGE]):
        case.service.inspect("INV-TEST")
