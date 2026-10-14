"""Metadata-only QR archive access with synthetic saved rows/ACL/SQL bridge."""

import csv
from dataclasses import replace
from datetime import timedelta
from inspect import signature
import json
from pathlib import Path
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import advance_source_access as advance_access
from zatca_erpgulf.zatca_erpgulf import qr_source_access as access
from zatca_erpgulf.zatca_erpgulf.archive_source_access import SavedSourceRow
from zatca_erpgulf.zatca_erpgulf.tests.test_advance_source_access import (
    operator, scenario as advance_scenario, NOW, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_qr_source_selection import prepared_qr, receipt


@pytest.fixture(params=[15, 16])
def qr_operator(operator, monkeypatch, request):
    monkeypatch.setattr(access, "frappe", operator.runtime)
    monkeypatch.setattr(access, "_", lambda text: text)
    def v16(dt, operation, *, doc, user, print_logs=True):
        return operator.acl(dt, operation, doc=doc, user=user, raise_exception=print_logs)
    monkeypatch.setattr(access, "has_permission", advance_access.has_permission if request.param == 15 else v16)
    return operator


def scenario(operator, der, monkeypatch, *, doctype="Sales Invoice", indicator="0200000", environment="Production", owner="company"):
    # Reuse synthetic owner/actor setup, not the advance selector/marker policy.
    case = advance_scenario(operator, der, monkeypatch, indicator=indicator, environment=environment, owner=owner)
    original = prepared_qr(der, doctype=doctype, indicator=indicator, environment=environment)
    original = replace(original, context=replace(original.context, credential_epoch=case.original.context.credential_epoch))
    case.original, case.journal = original, receipt(original)
    operator.documents.pop(("Sales Invoice", case.invoice.name))
    case.invoice.doctype = doctype
    operator.documents[doctype, case.invoice.name] = case.invoice
    for marker in advance_access.MARKERS:
        if hasattr(case.invoice, marker):
            delattr(case.invoice, marker)
    case.invoice.meta.has_field = lambda name: False  # QR inspection needs no advance schema.
    case.binding = access.QRSourceBinding(case.scope, original.context, original.artifact.uuid,
        original.artifact.icv, case.journal.journal_sha256)
    case.lookup.return_value = case.binding
    case.repository.load.return_value = case.journal
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
            row = SavedSourceRow.from_document(operator.documents[dt, parameters[-1]])
            self.result = (row.name, NOW, *row.values)
        def fetchone(self):
            return self.result
    case.database.cursor.side_effect = Cursor
    monkeypatch.setattr(access, "MariaDBJournalRepository", case.repository_factory)
    case.service = access.ArchivedQRInspectionService(case.scope, case.lookup, case.factory)
    return case


def inspect(case):
    return case.service.inspect(case.invoice.name, doctype=case.invoice.doctype)


def untouched(operator, case):
    operator.runtime.db.commit.assert_not_called()
    operator.runtime.db.rollback.assert_not_called()
    case.database.commit.assert_not_called()
    for doc in operator.documents.values():
        doc.save.assert_not_called()
        doc.db_set.assert_not_called()
        doc.check_permission.assert_not_called()


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("owner", ["company", "device", "linked"])
def test_saved_permissions_source_locks_exact_qr_lookup_metadata_only(qr_operator, certificates, monkeypatch, environment, doctype, indicator, owner):
    case = scenario(qr_operator, certificates[0], monkeypatch, environment=environment, doctype=doctype, indicator=indicator, owner=owner)
    report = inspect(case)
    assert report["source_kind"] == ("CLEARANCE_RETURNED_XML" if indicator.startswith("01") else "REPORTING_REQUEST_XML")
    assert all(value is False for key, value in report.items() if key.endswith(("_verified", "_authorized")))
    assert "PRIVATE" not in json.dumps(report) and "INV-TEST" not in json.dumps(report)
    assert not {"xml_bytes", "qr_payload", "uuid", "issue_date", "issue_time"} & report.keys()
    case.lookup.assert_called_once()
    case.factory.assert_called_once_with(case.scope)
    case.repository.load.assert_called_once_with(case.original.key_sha256)
    assert case.database.rollback.call_count == 2 and case.database.close.call_count == 1
    assert all("PRIVATE" not in str(args) for args in qr_operator.sql)
    untouched(qr_operator, case)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("identity", ["source", "company", "device", "linked"])
def test_each_saved_acl_precedes_lookup_and_acquisition_even_with_ignore_permissions(qr_operator, certificates, monkeypatch, doctype, identity):
    case = scenario(qr_operator, certificates[0], monkeypatch, doctype=doctype, owner="linked")
    key = {"source": (doctype, "INV-TEST"), "company": ("Company", "TEST"),
        "device": ("ZATCA Multiple Setting", "DEVICE"), "linked": ("Company", "LINKED")}[identity]
    qr_operator.denied.add(key)
    qr_operator.documents[key].flags = SimpleNamespace(ignore_permissions=True)
    with pytest.raises(PermissionDenied) as error:
        inspect(case)
    assert str(error.value) == access.DENIED_MESSAGE and error.value.__context__ is None
    case.lookup.assert_not_called()
    case.factory.assert_not_called()
    untouched(qr_operator, case)


@pytest.mark.parametrize("user,roles,site", [("Guest", ["System Manager"], "private.test"),
    (None, ["System Manager"], "private.test"), ("manager@example.test", [], "private.test"),
    ("Administrator", [], "other.test")])
def test_actor_role_site_guard_before_saved_source(qr_operator, certificates, monkeypatch, user, roles, site):
    case = scenario(qr_operator, certificates[0], monkeypatch)
    qr_operator.runtime.session.user, qr_operator.runtime.local.site = user, site
    qr_operator.runtime.get_roles.return_value = roles
    with pytest.raises(PermissionDenied):
        inspect(case)
    qr_operator.runtime.get_doc.assert_not_called()
    case.lookup.assert_not_called()
    case.factory.assert_not_called()


@pytest.mark.parametrize("field,value", [("docstatus", 0), ("docstatus", 2), ("custom_zatca_icv", 78),
    ("custom_uuid", "01234567-1234-4123-8123-123456789abc"), ("custom_zatca_issuing_unit", "OTHER"),
    ("custom_zatca_status", "Phase-1 QR Generated"), ("custom_zatca_status", "NOT_REPORTED")])
def test_saved_source_drift_never_acquires_sql(qr_operator, certificates, monkeypatch, field, value):
    case = scenario(qr_operator, certificates[0], monkeypatch)
    setattr(case.invoice, field, value)
    with pytest.raises(InspectionFailed) as error:
        inspect(case)
    assert str(error.value) == access.FAILED_MESSAGE and error.value.__context__ is None
    case.factory.assert_not_called()


@pytest.mark.parametrize("stage", ["lookup", "factory", "load", "close"])
@pytest.mark.parametrize("change", ["permission", "actor", "revision"])
def test_revocation_or_edit_at_boundaries_prevents_disclosure(qr_operator, certificates, monkeypatch, stage, change):
    case = scenario(qr_operator, certificates[0], monkeypatch)
    def mutate(*args):
        if change == "permission":
            qr_operator.denied.add(("Sales Invoice", "INV-TEST"))
        elif change == "actor":
            qr_operator.runtime.session.user = "other-manager@example.test"
        else:
            case.invoice.modified += timedelta(seconds=1)
        return {"lookup": case.binding, "factory": case.database, "load": case.journal, "close": None}[stage]
    {"lookup": case.lookup, "factory": case.factory, "load": case.repository.load, "close": case.database.close}[stage].side_effect = mutate
    with pytest.raises(PermissionDenied if change != "revision" else InspectionFailed) as error:
        inspect(case)
    assert error.value.__context__ is None
    if stage != "lookup":
        case.database.close.assert_called_once()
    else:
        case.factory.assert_not_called()


@pytest.mark.parametrize("stage", ["lookup", "factory", "load", "rollback", "close"])
def test_provider_and_cleanup_failures_are_redacted(qr_operator, certificates, monkeypatch, stage):
    case = scenario(qr_operator, certificates[0], monkeypatch)
    {"lookup": case.lookup, "factory": case.factory, "load": case.repository.load,
        "rollback": case.database.rollback, "close": case.database.close}[stage].side_effect = RuntimeError("PRIVATE provider detail")
    with pytest.raises(InspectionFailed) as error:
        inspect(case)
    assert str(error.value) == access.FAILED_MESSAGE and error.value.__context__ is None
    if stage not in ("lookup", "factory"):
        case.database.close.assert_called_once()
    untouched(qr_operator, case)


@pytest.mark.parametrize("borrowed", ["db", "raw"])
def test_recognizable_parent_handles_are_never_rolled_back_or_closed(qr_operator, certificates, monkeypatch, borrowed):
    case = scenario(qr_operator, certificates[0], monkeypatch)
    qr_operator.runtime.db._conn = case.database
    case.factory.return_value = qr_operator.runtime.db if borrowed == "db" else case.database
    with pytest.raises(InspectionFailed):
        inspect(case)
    case.database.rollback.assert_not_called()
    case.database.close.assert_not_called()
    untouched(qr_operator, case)


@pytest.mark.parametrize("stage", ["load", "rollback", "close"])
def test_interruptions_close_owned_handle_and_propagate(qr_operator, certificates, monkeypatch, stage):
    case = scenario(qr_operator, certificates[0], monkeypatch)
    {"load": case.repository.load, "rollback": case.database.rollback, "close": case.database.close}[stage].side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        inspect(case)
    case.database.close.assert_called_once()


@pytest.mark.parametrize("doctype", ["Company", "Purchase Invoice", None, {}])
def test_unsupported_requested_source_precedes_any_saved_load(qr_operator, certificates, monkeypatch, doctype):
    case = scenario(qr_operator, certificates[0], monkeypatch)
    with pytest.raises(InspectionFailed):
        case.service.inspect("INV-TEST", doctype=doctype)
    qr_operator.runtime.get_doc.assert_not_called()
    case.factory.assert_not_called()


@pytest.mark.parametrize("change", ["advance", "namespace", "doctype", "uuid", "icv", "owner"])
def test_lookup_binding_must_match_domain_scope_source_and_saved_owner(qr_operator, certificates, monkeypatch, change):
    case = scenario(qr_operator, certificates[0], monkeypatch)
    binding = case.binding
    if change == "advance":
        binding = advance_access.AdvanceSourceBinding(binding.scope, binding.context, binding.uuid, binding.icv, binding.journal_sha256)
    elif change == "namespace":
        binding = replace(binding, scope=access.CredentialStorageScope("private.test", "41234567-1234-4123-8123-123456789abc"))
    elif change == "doctype":
        binding = replace(binding, context=replace(binding.context, scope=replace(binding.context.scope, doctype="POS Invoice")))
    elif change == "uuid":
        binding = replace(binding, uuid="01234567-1234-4123-8123-123456789abc")
    elif change == "icv":
        binding = replace(binding, icv=78)
    else:
        binding = replace(binding, context=replace(binding.context,
            credential_epoch=replace(binding.context.credential_epoch, owner_name="OTHER")))
    case.lookup.return_value = binding
    with pytest.raises(InspectionFailed) as error:
        inspect(case)
    assert str(error.value) == access.FAILED_MESSAGE and error.value.__context__ is None
    case.factory.assert_not_called()


def test_ambient_proxy_fault_precedes_owned_handle_acquisition(qr_operator, certificates, monkeypatch):
    case = scenario(qr_operator, certificates[0], monkeypatch)
    class BrokenAmbient:
        @property
        def _conn(self):
            raise RuntimeError("PRIVATE ambient identity")
    qr_operator.runtime.db = BrokenAmbient()
    with pytest.raises(InspectionFailed) as error:
        inspect(case)
    assert str(error.value) == access.FAILED_MESSAGE and error.value.__context__ is None
    case.factory.assert_not_called()
    case.database.rollback.assert_not_called()
    case.database.close.assert_not_called()


@pytest.mark.parametrize("name", [None, "", {}, " padded "])
def test_invalid_source_name_is_not_a_saved_document_or_filter(qr_operator, certificates, monkeypatch, name):
    case = scenario(qr_operator, certificates[0], monkeypatch)
    with pytest.raises(InspectionFailed):
        case.service.inspect(name)
    qr_operator.runtime.get_doc.assert_not_called()
    case.factory.assert_not_called()


@pytest.mark.parametrize("fault", ["signature", "internal_typeerror"])
def test_permission_engine_fault_has_no_retry_or_private_error(qr_operator, certificates, monkeypatch, fault):
    case = scenario(qr_operator, certificates[0], monkeypatch)
    if fault == "signature":
        engine = Mock()
    else:
        def shaped(dt, operation, *, doc, user, raise_exception=False):
            raise TypeError("PRIVATE permission detail")
        engine = Mock(wraps=shaped)
        engine.__signature__ = signature(shaped)
    monkeypatch.setattr(access, "has_permission", engine)
    with pytest.raises(InspectionFailed) as error:
        inspect(case)
    assert str(error.value) == access.FAILED_MESSAGE and error.value.__context__ is None
    assert engine.call_count == (0 if fault == "signature" else 1)
    case.factory.assert_not_called()


@pytest.mark.parametrize("case_name", ["denied", "failed"])
def test_arabic_redacted_nonpickleable_and_uninstalled_boundary(qr_operator, certificates, monkeypatch, case_name):
    case = scenario(qr_operator, certificates[0], monkeypatch)
    for value in (case.binding, case.service):
        assert "INV-TEST" not in repr(value) and "PRIVATE" not in repr(value)
        with pytest.raises(access.QRSourceAccessError):
            pickle.dumps(value)
    with (Path(__file__).resolve().parents[2] / "translations/ar.csv").open() as stream:
        translations = dict(csv.reader(stream))
    for message in (access.DENIED_MESSAGE, access.FAILED_MESSAGE):
        assert translations[message] != message
    monkeypatch.setattr(access, "_", lambda message: translations[message])
    if case_name == "denied":
        qr_operator.denied.add(("Company", "TEST"))
    else:
        case.repository.load.side_effect = RuntimeError("PRIVATE SQL detail")
    with pytest.raises(PermissionDenied if case_name == "denied" else InspectionFailed) as error:
        inspect(case)
    assert str(error.value) == translations[access.DENIED_MESSAGE if case_name == "denied" else access.FAILED_MESSAGE]
    assert error.value.__context__ is None
    untouched(qr_operator, case)
