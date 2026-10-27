"""Company currency evidence and actual Frappe field-currency semantics."""

from dataclasses import replace
from datetime import timedelta
import json
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import frappe
from frappe.model.meta import get_field_currency
from frappe.utils import cstr
import pytest

from zatca_erpgulf.zatca_erpgulf import company_currency_source as source
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_format_source import scenario as format_case, NOW
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16


def scenario():
    case = format_case()
    case.name = "SYNTHETIC-CO"
    case.records["Company"] = [(case.name, NOW, "SAR")]
    case.raw_company = AppliedMeta("Company", ("default_currency",))
    case.raw_company.definitions["default_currency"].values.update(fieldtype="Link", options="Currency")
    case.metadata = observed_metadata(case.raw_company)
    return case


def reader(case, monkeypatch):
    case.metadata_reader = Mock()
    monkeypatch.setattr(source, "MariaDBMetadataSourceReader", Mock(return_value=case.metadata_reader))
    return source.MariaDBCompanyCurrencyReader(case.connection)


def load(case, handle): return handle.load_for_update(case.name, metadata=case.metadata)


def failure(call, code="company_currency_source_read"):
    with pytest.raises(source.CompanyCurrencySourceError) as caught: call()
    assert str(caught.value) == code and caught.value.__context__ is None


def test_exact_company_link_metadata_revision_and_native_scalar_are_bound(monkeypatch):
    case = scenario()
    handle = reader(case, monkeypatch)
    result = load(case, handle)
    assert result.currency == "SAR" and result.revision == NOW.isoformat(timespec="microseconds")
    assert result.metadata == case.metadata and result.metadata is not case.metadata
    handle.require_unchanged(result)
    assert case.metadata_reader.require_unchanged.call_count == 4
    assert all(not getattr(case.connection, method).called for method in ("commit", "rollback", "close"))
    assert case.name not in repr(result)
    for protected in (result, handle):
        with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(protected)


@pytest.mark.parametrize("fault", ["currency", "revision", "missing", "case", "null", "blank", "oversized", "metadata_type", "metadata_options"])
def test_unbound_or_changed_company_sources_are_not_guessed(monkeypatch, fault):
    case = scenario()
    handle = reader(case, monkeypatch)
    original = load(case, handle)
    if fault == "currency": case.records["Company"][0] = (case.name, NOW, "USD")
    elif fault == "revision": case.records["Company"][0] = (case.name, NOW + timedelta(seconds=1), "SAR")
    elif fault == "missing": case.records["Company"] = []
    elif fault == "case": case.records["Company"][0] = (case.name.lower(), NOW, "SAR")
    elif fault in ("null", "blank", "oversized"):
        case.records["Company"][0] = (case.name, NOW, None if fault == "null" else "" if fault == "blank" else "X" * 4097)
    else:
        case.raw_company.definitions["default_currency"].values["fieldtype" if fault == "metadata_type" else "options"] = "Data" if fault == "metadata_type" else "Account"
        case.metadata = observed_metadata(case.raw_company)
        failure(lambda: load(case, source.MariaDBCompanyCurrencyReader(case.connection)))
        return
    failure(lambda: handle.require_unchanged(original), "company_currency_source_changed")


@pytest.mark.parametrize("fault", ["name", "metadata", "record", "value", "derived"])
def test_private_result_reconstruction_binds_exact_company_and_metadata(monkeypatch, fault):
    case = scenario()
    result = load(case, reader(case, monkeypatch))
    if fault == "name": failure(lambda: replace(result, name="OTHER"), "company_currency_source_rows")
    elif fault == "derived":
        object.__setattr__(result, "currency", "OTHER")
        with pytest.raises(ValueError): source._pin_read(result)
    else:
        body = json.loads(result._payload)
        if fault == "metadata": body["metadata_sha256"] = "f" * 64
        elif fault == "record": body["record"]["field"] = "unselected_field"
        else: body["record"]["value"] = ["null"]
        from zatca_erpgulf.zatca_erpgulf.financial_source_observation import _canonical
        failure(lambda: replace(result, _payload=_canonical(body)), "company_currency_source_rows")


@pytest.mark.parametrize("interrupt", [False, True])
def test_failures_poison_without_cleanup_and_interruptions_propagate(monkeypatch, interrupt):
    case = scenario()
    handle = reader(case, monkeypatch)
    case.connection.error = KeyboardInterrupt() if interrupt else RuntimeError("PRIVATE-DRIVER")
    if interrupt:
        with pytest.raises(KeyboardInterrupt): load(case, handle)
    else: failure(lambda: load(case, handle))
    failure(lambda: load(case, handle), "company_currency_source_transaction_unusable")
    assert all(not getattr(case.connection, method).called for method in ("commit", "rollback", "close"))


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("child_field", [False, True])
@pytest.mark.parametrize("options,expected", [("currency", "USD"), ("Company:company:default_currency", "SAR")])
def test_parent_document_field_currency_matches_actual15_or_pinned16(upstream16, monkeypatch, major, child_field, options, expected):
    definition = frappe._dict(fieldname="base_amount" if child_field else "base_grand_total", fieldtype="Currency", options=options)
    values = {"currency": "USD", "company": "SYNTHETIC-CO"}
    doc = SimpleNamespace(doctype="Sales Invoice", name="SYNTHETIC-INV", get=values.get)
    cached = Mock(return_value="SAR")
    runtime = SimpleNamespace(local=SimpleNamespace(field_currency={}), _dict=frappe._dict, get_cached_value=cached)
    if major == 15:
        monkeypatch.setattr(frappe, "local", runtime.local)
        monkeypatch.setattr(frappe, "get_cached_value", cached)
        assert get_field_currency(definition, doc) == expected
    else:
        upstream16["frappe"], upstream16["cstr"] = runtime, cstr
        assert upstream16["get_field_currency"](definition, doc) == expected
    assert cached.call_count == (1 if options.startswith("Company:") else 0)


@pytest.mark.parametrize("major", [15, 16])
def test_existing_framework_field_currency_cache_can_hide_a_changed_company_link(upstream16, monkeypatch, major):
    definition = frappe._dict(fieldname="base_grand_total", fieldtype="Currency", options="Company:company:default_currency")
    values = {"currency": "USD", "company": "SYNTHETIC-CO"}
    doc = SimpleNamespace(doctype="Sales Invoice", name="SYNTHETIC-INV", get=values.get)
    stored = {("Sales Invoice", "SYNTHETIC-INV"): {"base_grand_total": "USD"}}
    cached = Mock(return_value="SAR")
    runtime = SimpleNamespace(local=SimpleNamespace(field_currency=stored), _dict=frappe._dict, get_cached_value=cached)
    if major == 15:
        monkeypatch.setattr(frappe, "local", runtime.local)
        monkeypatch.setattr(frappe, "get_cached_value", cached)
        assert get_field_currency(definition, doc) == "USD"
    else:
        upstream16["frappe"], upstream16["cstr"] = runtime, cstr
        assert upstream16["get_field_currency"](definition, doc) == "USD"
    cached.assert_not_called()
    assert stored == {("Sales Invoice", "SYNTHETIC-INV"): {"base_grand_total": "USD"}}
