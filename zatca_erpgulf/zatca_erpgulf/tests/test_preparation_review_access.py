"""Saved-source READ review, synthetic metadata only, no tenant or transport."""

import csv
import json
import pickle
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import preparation_review_access as access
from zatca_erpgulf.zatca_erpgulf import advance_source_access as advance_access
from zatca_erpgulf.zatca_erpgulf.issuance_preparation import PreparationTicket
from zatca_erpgulf.zatca_erpgulf.issuing_chain import DeclaredChainRegistration, initialize_declared_chain
from zatca_erpgulf.zatca_erpgulf.preparation_hold import PreparationHold
from zatca_erpgulf.zatca_erpgulf import preparation_hold as holds
from zatca_erpgulf.zatca_erpgulf.tests.test_preparation_hold import sample
from zatca_erpgulf.zatca_erpgulf.tests.test_issuing_chain import assert_code
from zatca_erpgulf.zatca_erpgulf.tests.test_advance_source_access import (
    operator, scenario as owner_scenario, NOW, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates


@pytest.fixture(params=[15, 16])
def reviewer(operator, monkeypatch, request):
    monkeypatch.setattr(access, "frappe", operator.runtime)
    monkeypatch.setattr(access, "_", lambda text: text)
    def v16(dt, operation, *, doc, user, print_logs=True):
        return operator.acl(dt, operation, doc=doc, user=user, raise_exception=print_logs)
    monkeypatch.setattr(access, "has_permission", advance_access.has_permission if request.param == 15 else v16)
    return operator


def scenario(reviewer, der, monkeypatch, *, doctype="Sales Invoice", owner="company",
             environment="Production", indicator="0200000", state="pending", docstatus=0):
    case = owner_scenario(reviewer, der, monkeypatch, owner=owner, environment=environment, indicator=indicator)
    source = replace(case.original.context.scope, doctype=doctype)
    ctx = replace(case.original.context, scope=source)
    registered = DeclaredChainRegistration(source.chain_id, str(uuid4()), source.company_name,
        source.seller_tax_id, source.environment, ctx.credential_epoch, "a"*64)
    # A pending ticket precedes saved UUID/counter/status fields on the source.
    ticket = PreparationTicket(initialize_declared_chain(registered), ctx, case.original.artifact.uuid)
    case.hold = PreparationHold(str(uuid4()), ticket,
        case.original.manifest_sha256 if state == "recorded" else None) if state != "missing" else None
    reviewer.documents.pop(("Sales Invoice", case.invoice.name))
    case.invoice.doctype = doctype
    reviewer.documents[doctype, case.invoice.name] = case.invoice
    case.invoice.docstatus = docstatus
    case.invoice.custom_uuid, case.invoice.custom_zatca_icv = "", 0
    case.invoice.custom_zatca_status = "Not Submitted"
    case.repository.load_for_source.return_value = case.hold
    def cursor():
        instance = SimpleNamespace(result=None)
        def execute(sql, params=()):
            reviewer.sql.append((sql, params))
            if sql == "SELECT @@session.autocommit": instance.result = (0,)
            else:
                assert "FOR UPDATE" in sql
                dt = sql.split("FROM `tab", 1)[1].split("`", 1)[0]
                doc = reviewer.documents[dt, params[-1]]
                row = access.SavedPreparationReviewRow.from_document(doc)
                instance.result = (row.name, doc.modified, *row.values)
        handle = Mock()
        handle.__enter__ = Mock(return_value=handle)
        handle.__exit__ = Mock(return_value=False)
        handle.execute.side_effect = execute
        handle.fetchone.side_effect = lambda: instance.result
        return handle
    case.database.cursor.side_effect = cursor
    monkeypatch.setattr(access, "MariaDBPreparationHoldRepository", case.repository_factory)
    case.service = access.SavedPreparationReviewService(case.scope, case.factory)
    return case


def inspect(case):
    return case.service.inspect(case.invoice.name, doctype=case.invoice.doctype)


def untouched(reviewer, case):
    for method in (reviewer.runtime.db.commit, reviewer.runtime.db.rollback, case.database.commit,
                   case.repository.reserve, case.repository.complete): method.assert_not_called()
    for doc in reviewer.documents.values():
        doc.save.assert_not_called()
        doc.db_set.assert_not_called()
        doc.check_permission.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("owner", ["company", "device", "linked"])
@pytest.mark.parametrize("state", ["pending", "recorded", "missing"])
@pytest.mark.parametrize("docstatus", [0, 1, 2])
def test_saved_read_review_without_uuid_counter_or_accepted_status(reviewer, certificates, monkeypatch,
    doctype, owner, state, docstatus):
    case = scenario(reviewer, certificates[0], monkeypatch, doctype=doctype, owner=owner, state=state, docstatus=docstatus)
    report = inspect(case)
    assert report["original_recorded_observed"] is ({"pending":False, "recorded":True, "missing":None}[state])
    assert all(report[name] is False for name in access.FALSE_FLAGS)
    assert not {"uuid", "hold_id", "xml_bytes", "ticket", "invoice_name", "icv", "previous_hash"} & report.keys()
    assert "INV-TEST" not in json.dumps(report) and "PRIVATE" not in json.dumps(report)
    case.repository.load_for_source.assert_called_once_with(doctype, "TEST", "INV-TEST")
    case.factory.assert_called_once_with(case.scope)
    assert case.database.rollback.call_count == 2 and case.database.close.call_count == 1
    untouched(reviewer, case)


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
def test_current_explicit_route_and_environment_do_not_trigger_any_authority_call(reviewer, certificates, monkeypatch, environment, indicator):
    case = scenario(reviewer, certificates[0], monkeypatch, environment=environment, indicator=indicator)
    assert inspect(case)["state"] == "PENDING_ORIGINAL_UNCONFIRMED_REVIEW"
    untouched(reviewer, case)


@pytest.mark.parametrize("identity", [("Sales Invoice","INV-TEST"), ("Company","TEST"),
    ("ZATCA Multiple Setting","DEVICE"), ("Company","LINKED")])
def test_every_saved_read_acl_precedes_archive_access_even_with_ignore_permissions(reviewer, certificates, monkeypatch, identity):
    case = scenario(reviewer, certificates[0], monkeypatch, owner="linked")
    reviewer.denied.add(identity)
    reviewer.documents[identity].flags = SimpleNamespace(ignore_permissions=True)
    with pytest.raises(PermissionDenied) as error: inspect(case)
    assert str(error.value) == access.DENIED_MESSAGE and error.value.__context__ is None
    case.factory.assert_not_called()
    case.repository_factory.assert_not_called()
    untouched(reviewer, case)


@pytest.mark.parametrize("change", ["guest", "role", "site"])
def test_actor_site_and_role_precede_all_saved_reads(reviewer, certificates, monkeypatch, change):
    case = scenario(reviewer, certificates[0], monkeypatch)
    if change == "guest": reviewer.runtime.session.user = "Guest"
    if change == "role": reviewer.runtime.get_roles.return_value = []
    if change == "site": reviewer.runtime.local.site = "OTHER.test"
    with pytest.raises(PermissionDenied): inspect(case)
    reviewer.runtime.get_doc.assert_not_called()
    case.factory.assert_not_called()


@pytest.mark.parametrize("stage", ["factory", "load", "close"])
@pytest.mark.parametrize("change", ["permission", "actor", "revision"])
def test_late_drift_denies_even_metadata_after_owned_cleanup(reviewer, certificates, monkeypatch, stage, change):
    case = scenario(reviewer, certificates[0], monkeypatch)
    def mutate(*args):
        if change == "permission": reviewer.denied.add((case.invoice.doctype, case.invoice.name))
        if change == "actor": reviewer.runtime.session.user = "OTHER@example.test"
        if change == "revision": case.invoice.modified += timedelta(seconds=1)
        return {"factory":case.database, "load":case.hold, "close":None}[stage]
    target = {"factory":case.factory, "load":case.repository.load_for_source, "close":case.database.close}[stage]
    target.side_effect = mutate
    with pytest.raises(InspectionFailed if change == "revision" else PermissionDenied) as error: inspect(case)
    assert error.value.__context__ is None
    case.database.close.assert_called_once()
    untouched(reviewer, case)


@pytest.mark.parametrize("stage", ["factory", "load", "rollback", "close"])
def test_failures_are_redacted_and_read_only(reviewer, certificates, monkeypatch, stage):
    case = scenario(reviewer, certificates[0], monkeypatch)
    {"factory":case.factory, "load":case.repository.load_for_source,
        "rollback":case.database.rollback, "close":case.database.close}[stage].side_effect = RuntimeError("PRIVATE SQL/XML/keys")
    with pytest.raises(InspectionFailed) as error: inspect(case)
    assert str(error.value) == access.FAILED_MESSAGE and error.value.__context__ is None
    if stage != "factory": case.database.close.assert_called_once()
    untouched(reviewer, case)


@pytest.mark.parametrize("borrowed", ["db", "raw"])
def test_recognizable_ambient_connection_is_not_cleaned_or_closed(reviewer, certificates, monkeypatch, borrowed):
    case = scenario(reviewer, certificates[0], monkeypatch)
    reviewer.runtime.db._conn = case.database
    case.factory.return_value = reviewer.runtime.db if borrowed == "db" else case.database
    with pytest.raises(InspectionFailed): inspect(case)
    case.database.rollback.assert_not_called()
    case.database.close.assert_not_called()
    untouched(reviewer, case)


@pytest.mark.parametrize("stage", ["load", "rollback", "close"])
def test_interruptions_propagate_after_owned_cleanup(reviewer, certificates, monkeypatch, stage):
    case = scenario(reviewer, certificates[0], monkeypatch)
    {"load":case.repository.load_for_source, "rollback":case.database.rollback,
        "close":case.database.close}[stage].side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt): inspect(case)
    case.database.close.assert_called_once()


@pytest.mark.parametrize("change", ["doctype", "source", "company", "seller", "environment", "owner", "route"])
def test_cross_source_or_changed_current_binding_never_discloses_metadata(reviewer, certificates, monkeypatch, change):
    case = scenario(reviewer, certificates[0], monkeypatch)
    if change in ("doctype", "source", "company"):
        scope = case.hold.ticket.context.scope
        fields = {"doctype":dict(doctype="POS Invoice"), "source":dict(invoice_name="OTHER"), "company":dict(company_name="OTHER")}[change]
        ctx = replace(case.hold.ticket.context, scope=replace(scope, **fields))
        reg = replace(case.hold.ticket.predecessor.registration,
            company_name="OTHER" if change == "company" else "TEST")
        case.repository.load_for_source.return_value = replace(case.hold,
            ticket=replace(case.hold.ticket, context=ctx, predecessor=initialize_declared_chain(reg)))
    else:
        if change == "seller": case.company.tax_id = "OTHER"
        if change == "environment": case.company.custom_select = "Simulation"
        if change == "owner": case.company.name = "OTHER"  # Identity drift is rejected before SQL.
        if change == "route": case.company.custom_production_url = "https://other.invalid/phase2"
    with pytest.raises(InspectionFailed): inspect(case)
    untouched(reviewer, case)


@pytest.mark.parametrize("doctype", [None, {}, "Company", "Purchase Invoice"])
def test_unsupported_source_precedes_any_saved_read(reviewer, certificates, monkeypatch, doctype):
    case = scenario(reviewer, certificates[0], monkeypatch)
    with pytest.raises(InspectionFailed): case.service.inspect(case.invoice.name, doctype=doctype)
    reviewer.runtime.get_doc.assert_not_called()
    case.factory.assert_not_called()


def test_display_only_arabic_translation_and_english_metadata_are_separate():
    path = Path(__file__).resolve().parents[2] / "translations/ar.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        translations = {row[0]:row[1] for row in csv.reader(handle) if len(row) >= 2}
    assert all(translations[text] != text for text in (access.TITLE, access.DENIED_MESSAGE, access.FAILED_MESSAGE, *access.MESSAGES.values()))
    for state in access.MESSAGES:
        recorded = {"NO_LOCAL_HOLD_OBSERVED_REVIEW":None, "PENDING_ORIGINAL_UNCONFIRMED_REVIEW":False,
            "ORIGINAL_RECORDED_LOCAL_NO_REPLAY":True}[state]
        report = {"state":state, "original_recorded_observed":recorded,
            "active_chain_hold_observed":None if recorded is None else not recorded,
            **{name:False for name in access.FALSE_FLAGS}}
        before = json.dumps(report, sort_keys=True)
        english = access.present_preparation_review(report, lambda text:text)
        arabic = access.present_preparation_review(report, translations.__getitem__)
        assert english["message"] == access.MESSAGES[state] and arabic["message"] != english["message"]
        assert set(arabic) == {"title","message","indicator"} and json.dumps(report, sort_keys=True) == before


@pytest.mark.parametrize("change", ["extra", "grant", "number", "state"])
def test_presenter_refuses_injected_fields_or_false_grants(change):
    report = access._projection(None)
    if change == "extra": report["xml_bytes"] = "PRIVATE"
    if change == "grant": report["rebuild_authorized"] = True
    if change == "number": report["replay_authorized"] = 0
    if change == "state": report["state"] = "ACCEPTED"
    with pytest.raises(access.PreparationReviewAccessError): access.present_preparation_review(report, lambda text:text)


def test_review_service_cannot_be_pickled_or_mutate_hold(reviewer, certificates, monkeypatch):
    case = scenario(reviewer, certificates[0], monkeypatch)
    with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(case.service)
    assert not any(hasattr(case.service, name) for name in ("prepare", "complete", "reserve", "release", "persist"))


def lookup_case(der):
    hold, _ = sample(der)
    cursor = Mock()
    cursor.__enter__ = Mock(return_value=cursor)
    cursor.__exit__ = Mock(return_value=False)
    connection = Mock()
    connection.cursor.return_value = cursor
    repo = holds.MariaDBPreparationHoldRepository(connection, str(uuid4()))
    repo.load = Mock(return_value=hold)
    return hold, repo, connection, cursor


@pytest.mark.parametrize("invalid", [(None,"TEST","NAME"), ([],"TEST","NAME"),
    ("Company","TEST","NAME"), ("Sales Invoice",None,"NAME"), ("Sales Invoice"," TEST","NAME"),
    ("Sales Invoice","TEST",""), ("Sales Invoice","TEST",{}), ("Sales Invoice","TEST","PRIVATE\n")])
def test_invalid_source_lookup_precedes_sql_and_poisons_handle(certificates, invalid):
    _, repo, connection, _ = lookup_case(certificates[0])
    assert_code(lambda: repo.load_for_source(*invalid), "preparation_source")
    connection.cursor.assert_not_called()
    assert repo._chain._failed


@pytest.mark.parametrize("change", ["missing", "wrong-source", "digest", "payload", "shape"])
def test_source_lookup_is_bounded_and_missing_never_authorizes_build(certificates, change):
    hold, repo, connection, cursor = lookup_case(certificates[0])
    row = (hold.hold_id, holds.encode_preparation_ticket(hold.ticket), hold.ticket_sha256)
    name = hold.ticket.context.scope.invoice_name
    if change == "missing": row = None
    if change == "wrong-source": name = "OTHER"
    if change == "digest": row = (*row[:2], "f"*64)
    if change == "payload": row = (row[0], b"PRIVATE INVALID", row[2])
    if change == "shape": row = (row[0],)
    cursor.fetchone.side_effect = [(0,), row]
    if change == "missing": assert repo.load_for_source("Sales Invoice", "TEST", name) is None
    else:
        expected = {"wrong-source":"preparation_hold_conflict", "digest":"preparation_hold_conflict",
            "payload":"preparation_ticket_invalid", "shape":"preparation_hold_missing_or_invalid"}[change]
        assert_code(lambda: repo.load_for_source("Sales Invoice", "TEST", name), expected)
    repo.load.assert_not_called()
    sql, values = cursor.execute.call_args.args
    assert "LIMIT 1" in sql and "FOR UPDATE" not in sql and values[0] == holds.MAX_TICKET_BYTES + 1
    connection.commit.assert_not_called()


def test_source_lookup_reuses_strict_exact_loader_instead_of_adopting_first_read(certificates):
    hold, repo, connection, cursor = lookup_case(certificates[0])
    cursor.fetchone.side_effect = [(0,), (hold.hold_id, holds.encode_preparation_ticket(hold.ticket), hold.ticket_sha256)]
    source = hold.ticket.context.scope
    assert repo.load_for_source(source.doctype, source.company_name, source.invoice_name) == hold
    repo.load.assert_called_once_with(hold)
    for method in (connection.commit, connection.rollback, connection.close): method.assert_not_called()


def test_permission_error_is_translated_only_at_display_boundary(reviewer, certificates, monkeypatch):
    case = scenario(reviewer, certificates[0], monkeypatch)
    reviewer.denied.add(("Sales Invoice", "INV-TEST"))
    monkeypatch.setattr(access, "_", lambda message: "AR: " + message)
    with pytest.raises(PermissionDenied) as error: inspect(case)
    assert str(error.value) == "AR: " + access.DENIED_MESSAGE
    assert access.DENIED_MESSAGE.startswith("You do not")
    case.factory.assert_not_called()
