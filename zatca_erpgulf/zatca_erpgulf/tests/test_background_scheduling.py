"""Company isolation and real worker wrappers with site-free records/callbacks."""

import inspect
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from zatca_erpgulf.zatca_erpgulf import (
    background_worker, pos_sign, schedule_pos, scheduler_event, scheduling, sign_invoice,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import Document, ValidationError


WORKERS = (
    (scheduler_event, "submit_invoices_to_zatca_background", "Sales Invoice", True),
    (schedule_pos, "submit_posinvoices_to_zatca_background_process", "POS Invoice", False),
)


@pytest.mark.parametrize("value, expected", [
    ("9:05:42", time(9, 5, 42)),
    (" 09:05:42 ", time(9, 5, 42)),
    ("09:05:42.123456", time(9, 5, 42, 123456)),
    (time(0), time(0)),
    (time(23, 59, 59), time(23, 59, 59)),
    (timedelta(0), time(0)),
    (timedelta(hours=9, seconds=42), time(9, 0, 42)),
    (timedelta(microseconds=123456), time(0, 0, 0, 123456)),
])
def test_time_representations_and_compatibility_wrappers(value, expected):
    for module in (scheduling, scheduler_event, schedule_pos):
        assert module.convert_to_time(value) == expected


@pytest.mark.parametrize("value", [
    None, "", "9:05", "24:00:00", "bad", 0, False, [],
    timedelta(days=1), timedelta(seconds=-1), time(9, tzinfo=timezone.utc),
])
def test_bad_times_do_not_wrap_or_authorize(value):
    with pytest.raises(ValueError):
        scheduling.convert_to_time(value)


@pytest.mark.parametrize("start, end, current, expected", [
    (9, 10, 8, False), (9, 10, 9, True), (9, 10, 10, True),
    (9, 10, 11, False), (22, 2, 22, True), (22, 2, 0, True),
    (22, 2, 2, True), (22, 2, 3, False), (22, 2, 21, False),
    (0, 0, 0, True), (0, 0, 1, False),
])
def test_inclusive_and_overnight_windows(start, end, current, expected):
    for module in (scheduling, scheduler_event, schedule_pos):
        assert module.is_time_in_range(time(start), time(end), time(current)) is expected


@pytest.fixture
def worker_boundary(monkeypatch):
    docs, rows = {}, []

    def company(name, **values):
        data = dict(
            custom_zatca_invoice_enabled=1, custom_phase_1_or_2="Phase-2",
            custom_send_invoice_to_zatca="Background", custom_submit_or_not=0,
            custom_start_time="09:00:00", custom_end_time="11:00:00",
            custom_start_time_session=None, custom_end_time_session=None,
        )
        data.update(values)
        doc = Document(name=name, **data)
        docs["Company", name] = doc
        return doc

    def invoice(doctype, name, company_name, **values):
        data = dict(company=company_name, customer="B2C", docstatus=1,
                    custom_zatca_status="Not Submitted")
        data.update(values)
        doc = Document(doctype=doctype, name=name, **data)
        doc.submit = Mock(side_effect=lambda: setattr(doc, "docstatus", 1))
        doc.reload = Mock(return_value=doc)
        docs[doctype, name] = doc
        rows.append({"name": name, "company": "DO-NOT-TRUST-DISCOVERY-ROW"})
        return doc

    docs["Customer", "B2C"] = Document(custom_b2c=1)
    docs["Customer", "B2B"] = Document(custom_b2c=0)
    callback = Mock()
    fake_frappe = SimpleNamespace(
        get_all=Mock(return_value=rows),
        get_doc=Mock(side_effect=lambda dt, name: docs[dt, name]),
        db=SimpleNamespace(commit=Mock()),
        log_error=Mock(), get_traceback=Mock(return_value="TEST TRACEBACK"),
    )
    monkeypatch.setattr(background_worker, "frappe", fake_frappe)
    monkeypatch.setattr(background_worker, "now_datetime", lambda: datetime(2026, 10, 9, 10))
    for module, *_ in WORKERS:
        monkeypatch.setattr(module, "zatca_background_on_submit", callback)
    return SimpleNamespace(
        company=company, invoice=invoice, docs=docs, rows=rows,
        frappe=fake_frappe, callback=callback,
    )


def run_worker(worker):
    module, fn, *_ = worker
    getattr(module, fn)()


@pytest.mark.parametrize("worker", WORKERS)
@pytest.mark.parametrize("blocked_settings", [
    {"custom_start_time": "11:00:00", "custom_end_time": "12:00:00"},
    {"custom_start_time": None, "custom_end_time": None},
    {"custom_start_time": "", "custom_end_time": ""},
    {"custom_send_invoice_to_zatca": "Immediate"},
    {"custom_send_invoice_to_zatca": "Batches"},
    {"custom_send_invoice_to_zatca": ""},
    {"custom_phase_1_or_2": "Phase-1"},
    {"custom_phase_1_or_2": ""},
    {"custom_phase_1_or_2": "Unknown"},
    {"custom_zatca_invoice_enabled": 0},
    {"custom_zatca_invoice_enabled": "0"},
])
def test_other_open_company_cannot_authorize_this_invoice(worker_boundary, worker, blocked_settings):
    b = worker_boundary
    b.company("OPEN")
    b.company("BLOCKED", custom_submit_or_not=1, **blocked_settings)
    blocked = b.invoice(worker[2], "blocked", "BLOCKED", docstatus=0)
    allowed = b.invoice(worker[2], "allowed", "OPEN")
    run_worker(worker)
    b.callback.assert_called_once_with(allowed, bypass_background_check=True)
    blocked.submit.assert_not_called()
    assert b.frappe.db.commit.call_count == int(worker[3])
    assert not any(c.args[0] == "Customer" for c in b.frappe.get_doc.call_args_list)


@pytest.mark.parametrize("worker", WORKERS)
@pytest.mark.parametrize("first", [
    ("01:00:00", "02:00:00"), (None, None), ("", ""),
])
def test_second_window_is_effective_even_with_first_present(worker_boundary, worker, first):
    b = worker_boundary
    b.company("SECOND", custom_start_time=first[0], custom_end_time=first[1],
              custom_start_time_session="09:00:00", custom_end_time_session="11:00:00")
    doc = b.invoice(worker[2], "second", "SECOND")
    run_worker(worker)
    b.callback.assert_called_once_with(doc, bypass_background_check=True)


@pytest.mark.parametrize("worker", WORKERS)
@pytest.mark.parametrize("settings, hour", [
    ({"custom_start_time": timedelta(0), "custom_end_time": "11:00:00"}, 0),
    ({"custom_start_time": "22:00:00", "custom_end_time": "02:00:00"}, 0),
    ({"custom_start_time": "22:00:00", "custom_end_time": "02:00:00"}, 22),
    ({"custom_start_time": "22:00:00", "custom_end_time": "02:00:00"}, 2),
])
def test_worker_uses_local_clock_and_midnight(worker_boundary, monkeypatch, worker, settings, hour):
    b = worker_boundary
    monkeypatch.setattr(background_worker, "now_datetime", lambda: datetime(2026, 10, 9, hour))
    b.company("NIGHT", **settings)
    doc = b.invoice(worker[2], "night", "NIGHT")
    run_worker(worker)
    b.callback.assert_called_once_with(doc, bypass_background_check=True)


@pytest.mark.parametrize("worker", WORKERS)
@pytest.mark.parametrize("broken", [
    {"custom_start_time": "bad"},
    {"custom_end_time": None},
    {"custom_start_time_session": "10:00:00"},
    {"custom_start_time_session": "bad", "custom_end_time_session": "11:00:00"},
    {"custom_start_time": timedelta(days=1)},
])
def test_bad_company_blocks_only_its_invoices_and_logs_once(worker_boundary, worker, broken):
    b = worker_boundary
    b.company("BAD", **broken)
    b.company("GOOD")
    b.invoice(worker[2], "bad-1", "BAD")
    b.invoice(worker[2], "bad-2", "BAD")
    good = b.invoice(worker[2], "good", "GOOD")
    run_worker(worker)
    b.callback.assert_called_once_with(good, bypass_background_check=True)
    b.frappe.log_error.assert_called_once()
    assert b.frappe.get_doc.call_args_list.count(call("Company", "BAD")) == 1


@pytest.mark.parametrize("worker", WORKERS)
@pytest.mark.parametrize("status", ["REPORTED", "CLEARED", "", None, "Unknown", "ERROR"])
@pytest.mark.parametrize("docstatus", [0, 1, 2])
def test_stale_discovery_records_do_not_send_or_submit(worker_boundary, worker, status, docstatus):
    b = worker_boundary
    doc = b.invoice(worker[2], "stale", "NO-COMPANY-LOAD", docstatus=docstatus,
                    custom_zatca_status=status)
    run_worker(worker)
    b.callback.assert_not_called()
    doc.submit.assert_not_called()
    b.frappe.log_error.assert_not_called()
    b.frappe.db.commit.assert_not_called()


@pytest.mark.parametrize("worker", WORKERS)
@pytest.mark.parametrize("status", list(scheduling.PENDING_STATUSES))
def test_cancelled_invoice_with_pending_status_is_not_processed(worker_boundary, worker, status):
    b = worker_boundary
    doc = b.invoice(worker[2], "cancelled", "NO-COMPANY-LOAD", docstatus=2,
                    custom_zatca_status=status)
    run_worker(worker)
    b.callback.assert_not_called()
    doc.submit.assert_not_called()
    b.frappe.log_error.assert_not_called()


@pytest.mark.parametrize("worker", WORKERS)
@pytest.mark.parametrize("status", list(scheduling.PENDING_STATUSES))
def test_discovery_contract_and_saved_company_snapshot(worker_boundary, worker, status):
    b = worker_boundary
    b.company("OPEN")
    first = b.invoice(worker[2], "first", "OPEN", custom_zatca_status=status)
    second = b.invoice(worker[2], "second", "OPEN", custom_zatca_status=status)
    run_worker(worker)
    assert b.callback.call_args_list == [
        call(first, bypass_background_check=True), call(second, bypass_background_check=True),
    ]
    b.frappe.get_all.assert_called_once_with(worker[2], filters=[
        ["creation", ">=", datetime(2026, 10, 8, 10)], ["docstatus", "in", [0, 1]],
        ["custom_zatca_status", "in", list(scheduling.PENDING_STATUSES)],
    ], fields=["name"])
    assert b.frappe.get_doc.call_args_list.count(call("Company", "OPEN")) == 1


@pytest.mark.parametrize("worker", WORKERS)
@pytest.mark.parametrize("auto", [0, "0", 1, "1"])
@pytest.mark.parametrize("customer", ["B2B", "B2C"])
def test_draft_submit_requires_own_company_option_and_b2c(worker_boundary, worker, auto, customer):
    b = worker_boundary
    b.company("OPEN", custom_submit_or_not=auto)
    doc = b.invoice(worker[2], "draft", "OPEN", docstatus=0, customer=customer)
    run_worker(worker)
    should_submit = auto in (1, "1") and customer == "B2C"
    assert doc.submit.call_count == int(should_submit)
    assert b.callback.call_count == int(should_submit)
    assert b.frappe.db.commit.call_count == int(should_submit and worker[3])


@pytest.mark.parametrize("worker", WORKERS)
@pytest.mark.parametrize("alias", ["custom_b2c", "b2c", "is_b2c", "zatca_b2c"])
def test_draft_customer_aliases_are_preserved(worker_boundary, worker, alias):
    b = worker_boundary
    b.company("OPEN", custom_submit_or_not=1)
    b.docs["Customer", "ALIAS"] = Document(**{alias: "1"})
    doc = b.invoice(worker[2], "draft", "OPEN", docstatus=0, customer="ALIAS")
    run_worker(worker)
    doc.submit.assert_called_once()
    b.callback.assert_called_once_with(doc, bypass_background_check=True)


@pytest.mark.parametrize("worker", WORKERS)
def test_phase_alias_and_canonical_false_precedence(worker_boundary, worker):
    b = worker_boundary
    company = b.company("ALIAS", phase_1_or_2="Phase-2")
    del company.custom_phase_1_or_2
    doc = b.invoice(worker[2], "alias", "ALIAS")
    run_worker(worker)
    b.callback.assert_called_once_with(doc, bypass_background_check=True)
    company.custom_phase_1_or_2 = ""
    b.callback.reset_mock()
    run_worker(worker)
    b.callback.assert_not_called()


@pytest.mark.parametrize("worker", WORKERS)
@pytest.mark.parametrize("status", ["REPORTED", "CLEARED"])
def test_draft_on_submit_acceptance_is_not_sent_again(worker_boundary, worker, status):
    b = worker_boundary
    b.company("OPEN", custom_submit_or_not=1)
    doc = b.invoice(worker[2], "draft", "OPEN", docstatus=0)

    def submit():
        doc.docstatus = 1

    def reload():
        # A hook can update the database using a different Document instance.
        doc.custom_zatca_status = status
        return doc

    doc.submit.side_effect = submit
    doc.reload.side_effect = reload
    run_worker(worker)
    doc.reload.assert_called_once_with()
    b.callback.assert_not_called()
    assert b.frappe.db.commit.call_count == int(worker[3])


@pytest.mark.parametrize("worker", WORKERS)
def test_one_invoice_failure_does_not_abort_worker(worker_boundary, worker):
    b = worker_boundary
    b.company("OPEN")
    first = b.invoice(worker[2], "failed", "OPEN")
    second = b.invoice(worker[2], "good", "OPEN")
    b.callback.side_effect = [RuntimeError("TEST ERROR"), None]
    run_worker(worker)
    assert b.callback.call_args_list == [
        call(first, bypass_background_check=True), call(second, bypass_background_check=True),
    ]
    b.frappe.log_error.assert_called_once()
    assert b.frappe.db.commit.call_count == int(worker[3])


@pytest.mark.parametrize("worker", WORKERS)
@pytest.mark.parametrize("failure", ["missing-company", "draft-submit"])
def test_loading_or_draft_failure_does_not_block_other_company(worker_boundary, worker, failure):
    b = worker_boundary
    b.company("GOOD")
    bad = b.invoice(worker[2], "bad", "MISSING", docstatus=0)
    if failure == "draft-submit":
        b.company("MISSING", custom_submit_or_not=1)
        bad.submit.side_effect = RuntimeError("TEST SUBMIT ERROR")
    good = b.invoice(worker[2], "good", "GOOD")
    run_worker(worker)
    b.callback.assert_called_once_with(good, bypass_background_check=True)
    b.frappe.log_error.assert_called_once()
    bad.reload.assert_not_called()


@pytest.mark.parametrize("worker", WORKERS)
def test_empty_or_failed_discovery_does_not_call_submission(worker_boundary, worker):
    b = worker_boundary
    run_worker(worker)
    b.callback.assert_not_called()
    b.frappe.get_all.side_effect = RuntimeError("TEST QUERY ERROR")
    run_worker(worker)
    b.callback.assert_not_called()
    b.frappe.log_error.assert_called_once()


def test_cron_dispatches_sales_and_pos_without_extra_queries(monkeypatch):
    sales, pos = Mock(), Mock()
    monkeypatch.setattr(scheduler_event, "submit_invoices_to_zatca_background", sales)
    monkeypatch.setattr(scheduler_event, "submit_posinvoices_to_zatca_background_process", pos)
    scheduler_event.submit_invoices_to_zatca_background_process()
    sales.assert_called_once_with()
    pos.assert_called_once_with()


def test_unsupported_doctype_has_no_io(worker_boundary):
    with pytest.raises(ValueError, match="Unsupported"):
        background_worker.run_pending_background_invoices("Purchase Invoice", Mock())
    worker_boundary.frappe.get_all.assert_not_called()


@pytest.fixture
def parent_boundary(worker_boundary, monkeypatch):
    """Keep actual on_submit branch selection; mock validation data and builders."""
    b = worker_boundary
    company = b.company("OPEN", tax_id="300000000000003")
    b.docs["Customer", "B2C"].tax_id = ""
    b.docs["POS Profile", "TEST-PROFILE"] = Document(taxes_and_charges="TEST-TAX")
    b.docs["Sales Taxes and Charges Template", "TEST-TAX"] = Document(
        taxes=[Document(included_in_print_rate=0)]
    )
    b.frappe.get_doc.side_effect = lambda dt, name: (
        company if dt == "Company" and isinstance(name, dict) else b.docs[dt, name]
    )
    b.frappe.db.get_value = Mock(return_value="TEST")
    b.frappe.db.exists = Mock(return_value=True)
    b.frappe.get_installed_apps = Mock(return_value=[])
    b.frappe.get_meta = Mock(return_value=Document(has_field=lambda _: False))

    def throw(message):
        raise ValidationError(message)

    b.frappe.throw = throw
    b.frappe.ValidationError = ValidationError
    b.address = Document(address_line1="Test", address_line2="Test district",
                         custom_building_number="1234", pincode="12345")
    b.routes = {}
    for module, names in (
        (sign_invoice, ("zatca_call", "zatca_call_scheduler_background",
                        "submit_sales_invoice_simplifeid", "zatca_call_withoutxml")),
        (pos_sign, ("zatca_call", "zatca_call_pos_without_xml_background",
                    "submit_pos_invoice_simplifeid", "zatca_call_pos_without_xml")),
    ):
        monkeypatch.setattr(module, "frappe", b.frappe)
        monkeypatch.setattr(module, "_", lambda text: text)
        monkeypatch.setattr(module, "get_address", Mock(return_value=b.address))
        monkeypatch.setattr(module, "is_qr_and_xml_attached", Mock(return_value=False))
        for name in names:
            mock = Mock()
            b.routes[module.__name__, name] = mock
            monkeypatch.setattr(module, name, mock)
    return b


def parent_invoice(b, doctype, name="parent"):
    return b.invoice(
        doctype, name, "OPEN", items=[], taxes=[], is_return=0,
        custom_zatca_nominal_invoice=0, pos_profile="TEST-PROFILE",
    )


@pytest.mark.parametrize("module, doctype, preparation", [
    (sign_invoice, "Sales Invoice", "zatca_call_scheduler_background"),
    (pos_sign, "POS Invoice", "zatca_call_pos_without_xml_background"),
])
@pytest.mark.parametrize("bypass", [False, True])
def test_actual_parent_preserves_foreground_prepare_and_worker_send(parent_boundary, module, doctype, preparation, bypass):
    b = parent_boundary
    doc = parent_invoice(b, doctype)
    inspect.unwrap(module.zatca_background_on_submit)(doc, bypass_background_check=bypass)
    route = "zatca_call" if bypass else preparation
    b.routes[module.__name__, route].assert_called_once_with(
        doc.name, "0", False, "TEST", doc
    )
    for (module_name, name), mock in b.routes.items():
        if module_name == module.__name__ and name != route:
            mock.assert_not_called()


@pytest.mark.parametrize("worker, module", [(WORKERS[0], sign_invoice), (WORKERS[1], pos_sign)])
def test_worker_reaches_ordinary_generation_through_actual_parent(parent_boundary, monkeypatch, worker, module):
    b = parent_boundary
    doc = parent_invoice(b, worker[2])
    monkeypatch.setattr(worker[0], "zatca_background_on_submit", inspect.unwrap(module.zatca_background_on_submit))
    run_worker(worker)
    b.routes[module.__name__, "zatca_call"].assert_called_once_with(
        doc.name, "0", False, "TEST", doc
    )
    b.frappe.log_error.assert_not_called()


@pytest.mark.parametrize("worker, module, existing", [
    (WORKERS[0], sign_invoice, "submit_sales_invoice_simplifeid"),
    (WORKERS[1], pos_sign, "submit_pos_invoice_simplifeid"),
])
def test_worker_reuses_existing_xml_without_generating_again(parent_boundary, monkeypatch, worker, module, existing):
    b = parent_boundary
    doc = parent_invoice(b, worker[2])
    monkeypatch.setattr(module, "is_qr_and_xml_attached", Mock(return_value=True))
    monkeypatch.setattr(worker[0], "zatca_background_on_submit", inspect.unwrap(module.zatca_background_on_submit))
    run_worker(worker)
    b.routes[module.__name__, existing].assert_called_once_with(doc, "TEST", doc.name)
    b.routes[module.__name__, "zatca_call"].assert_not_called()
    b.frappe.log_error.assert_not_called()
