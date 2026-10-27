"""One saved-READ/owned pipeline for native invoice currency and formats."""

import csv
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import pickle
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import calculation_format_access as formats
from zatca_erpgulf.zatca_erpgulf import currency_format_source as source
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access import scenario as financial_case
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_format_source import scenario as format_case, NOW
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, one_failure, untouched, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import project


def bind_formats(case, operator, *, missing_check=False):
    """Add only synthetic saved format documents and trusted explicit providers."""
    case.format_data = format_case()
    if missing_check: case.format_data.records["System Settings"] = []
    case.invoice.currency = "SAR"
    operator.runtime.local.lang = "ar"
    case.related = {}
    for dt, name, value in (("Currency", "SAR", "#.########"), ("Language", "ar", "#,###.##"), ("System Settings", "System Settings", 0 if missing_check else 1)):
        doc = Document(doctype=dt, name=name, modified=NOW, **{source.FLAG if dt == "System Settings" else "number_format": value})
        doc.save, doc.db_set, doc.check_permission = Mock(), Mock(), Mock()
        operator.documents[dt, name] = doc
        case.related[dt] = doc
    raw = case.data.raw_metas[case.invoice.doctype]
    raw.definitions["grand_total"].values["options"] = "currency"
    case.data.metas[case.invoice.doctype] = project(raw)
    case.applied[case.invoice.doctype] = case.data.metas[case.invoice.doctype]
    case.observations[case.invoice.doctype] = observed_metadata(raw)
    case.format_metadata = Mock(side_effect=lambda scope, types: dict(case.format_data.metas))
    def cached(*args):
        return formats.CurrencyFormatContext("ar", case.related["Language"].number_format,
            bool(case.related["System Settings"].get(source.FLAG)), "SAR", case.related["Currency"].number_format)
    case.format_cache = Mock(side_effect=cached)
    case.service = access.SavedCalculationDefaultsService(case.scope, case.factory, case.cache,
        parent_kind=getattr(case, "parent_kind", "site"), applied_metadata_reader=case.metadata_provider,
        format_metadata_reader=case.format_metadata, format_cache_reader=case.format_cache)
    return case


def scenario(operator, monkeypatch, *, doctype="Sales Invoice", missing_check=False, parent_kind="site"):
    case = financial_case(operator, monkeypatch, doctype=doctype, parent_kind=parent_kind)
    bind_formats(case, operator, missing_check=missing_check)
    financial_cursor, format_cursor = case.database.cursor, case.format_data.connection.cursor
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=()):
            selected = any("FROM `tab" + dt + "`" in sql for dt in ("Currency", "Language", "Singles"))
            self.current = format_cursor() if selected else financial_cursor()
            self.current.execute(sql, params)
        def fetchone(self): return self.current.fetchone()
        def fetchall(self): return self.current.fetchall()
        @property
        def description(self): return self.current.description
    case.database.cursor = Mock(side_effect=Cursor)
    provider = Mock()
    provider.load_for_update.side_effect = lambda meta: case.format_data.observations[meta.name]
    provider.require_unchanged.return_value = None
    monkeypatch.setattr(source, "MariaDBMetadataSourceReader", Mock(return_value=provider))
    return case


def capture(case, major=16):
    return case.service.capture_currency_context(case.invoice.name, doctype=case.invoice.doctype, erp_major=major)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("missing_check", [False, True])
def test_shared_owned_read_binds_currency_formats_permissions_and_scope(defaults_operator, monkeypatch, doctype, missing_check):
    case = scenario(defaults_operator, monkeypatch, doctype=doctype, missing_check=missing_check)
    result = capture(case)
    assert type(result) is formats.SavedInvoiceCurrencyRead
    assert result.financial.context.settings.actor == defaults_operator.runtime.session.user
    assert result.formats.context.currency == "SAR" and result.formats.context.language == "ar"
    assert result.related[-1].revision is None
    assert result.resolve_precision("grand_total").precision == 2
    assert case.format_metadata.call_count == case.format_cache.call_count == 2
    case.factory.assert_called_once_with(case.scope)
    assert case.database.rollback.call_count == 2 and case.database.close.call_count == 1
    assert case.invoice.name not in repr(result) and "PARTIAL" in repr(result)
    with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(result)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("denied", ["invoice", "company", "Currency", "Language", "System Settings"])
def test_all_normal_related_reads_precede_format_metadata_cache_or_sql(defaults_operator, monkeypatch, denied):
    case = scenario(defaults_operator, monkeypatch)
    doc = case.invoice if denied == "invoice" else case.company if denied == "company" else case.related[denied]
    doc.flags = type("Flags", (), {"ignore_permissions": True})()
    defaults_operator.denied.add((doc.doctype, doc.name))
    with pytest.raises(PermissionDenied): capture(case)
    case.factory.assert_not_called()
    case.format_metadata.assert_not_called()
    case.format_cache.assert_not_called()
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE)


@pytest.mark.parametrize("boundary", ["metadata_first", "metadata_second", "cache_first", "cache_second", "close"])
@pytest.mark.parametrize("changed", ["permission", "locale", "currency", "related_revision", "related_value"])
def test_late_acl_locale_currency_and_related_source_drift_never_disclose(defaults_operator, monkeypatch, boundary, changed):
    case = scenario(defaults_operator, monkeypatch)
    def mutate():
        if changed == "permission": defaults_operator.denied.add(("Language", "ar"))
        elif changed == "locale": defaults_operator.runtime.local.lang = "en"
        elif changed == "currency": case.invoice.currency = "OTHER"
        elif changed == "related_revision": case.related["Currency"].modified += timedelta(seconds=1)
        else: case.related["Currency"].number_format = "#.###"
    if boundary == "close": case.database.close.side_effect = mutate
    elif boundary.startswith("metadata"):
        def metadata(*args):
            if case.format_metadata.call_count == (1 if boundary.endswith("first") else 2): mutate()
            return dict(case.format_data.metas)
        case.format_metadata.side_effect = metadata
    else:
        original = case.format_cache.side_effect
        def cached(*args):
            result = original(*args)
            if case.format_cache.call_count == (1 if boundary.endswith("first") else 2): mutate()
            return result
        case.format_cache.side_effect = cached
    with pytest.raises(PermissionDenied if changed == "permission" else InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE if changed == "permission" else access.FINANCIAL_FAILED_MESSAGE)
    assert case.database.close.call_count == (0 if boundary == "metadata_first" else 1)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("changed", ["format", "singleton", "financial", "related_revision"])
def test_last_format_cache_callback_is_followed_by_all_native_source_rechecks(defaults_operator, monkeypatch, changed):
    case = scenario(defaults_operator, monkeypatch)
    original = case.format_cache.side_effect
    def cached(*args):
        result = original(*args)
        if case.format_cache.call_count == 2:
            if changed == "format": case.format_data.records["Currency"][0] = ("SAR", NOW, "#.###")
            elif changed == "singleton": case.format_data.records["System Settings"][0] = ("System Settings", source.FLAG, "0")
            elif changed == "financial": case.data.records["items"][0]["amount"] = None
            else: case.format_data.records["Currency"][0] = ("SAR", NOW + timedelta(seconds=1), "#.########")
        return result
    case.format_cache.side_effect = cached
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)


@pytest.mark.parametrize("boundary", ["metadata", "cache", "close"])
@pytest.mark.parametrize("interrupt", [False, True])
def test_producer_failures_are_one_redacted_message_and_owned_cleanup_is_preserved(defaults_operator, monkeypatch, boundary, interrupt):
    case = scenario(defaults_operator, monkeypatch)
    def fail(*args):
        if interrupt: raise KeyboardInterrupt()
        defaults_operator.runtime.throw("PRIVATE-FORMAT-PRODUCER", InspectionFailed)
    if boundary == "metadata": case.format_metadata.side_effect = fail
    elif boundary == "cache": case.format_cache.side_effect = fail
    else: case.database.close.side_effect = fail
    with pytest.raises(KeyboardInterrupt if interrupt else InspectionFailed): capture(case)
    if not interrupt: one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)
    else: assert defaults_operator.runtime.message_log == ["EXISTING-PARENT-MESSAGE"]
    assert case.database.close.call_count == (0 if boundary == "metadata" else 1)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("fault", ["currency", "language", "related_order", "related_revision", "singleton_revision", "financial", "formats"])
def test_result_reconstruction_binds_all_private_parents(defaults_operator, monkeypatch, fault):
    case = scenario(defaults_operator, monkeypatch)
    result = capture(case)
    changes = {}
    if fault == "currency": changes["related"] = (replace(result.related[0], name="OTHER"), *result.related[1:])
    elif fault == "language": changes["related"] = (result.related[0], replace(result.related[1], name="en"), result.related[2])
    elif fault == "related_order": changes["related"] = tuple(reversed(result.related))
    elif fault == "related_revision": changes["related"] = (replace(result.related[0], revision="2026-10-27T19:00:00.000000"), *result.related[1:])
    elif fault == "singleton_revision": changes["related"] = (*result.related[:2], replace(result.related[2], revision="2026-10-27T19:00:00.000000"))
    else: changes[fault] = "PRIVATE"
    with pytest.raises(formats.CalculationFormatAccessError) as caught: replace(result, **changes)
    assert str(caught.value) == "calculation_format_access_result" and caught.value.__context__ is None


def test_precision_is_limited_to_root_fields_explicitly_using_invoice_currency(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    result = capture(case)
    for name in ("currency", "base_grand_total", "not_a_field"):
        with pytest.raises(formats.CalculationFormatAccessError): result.resolve_precision(name)
    assert result.resolve_precision("grand_total").precision == 2


def test_other_capture_modes_do_not_acquire_format_dependencies(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    case.format_metadata.side_effect = AssertionError("Legacy operation must not select format metadata")
    case.format_cache.side_effect = AssertionError("Legacy operation must not select format cache")
    assert type(case.service.capture_financial_context(case.invoice.name, erp_major=15)) is access.SavedCalculationFinancialRead
    case.format_metadata.assert_not_called()
    case.format_cache.assert_not_called()


@pytest.mark.parametrize("fault", ["version", "scope", "language", "provider"])
def test_unsupported_profiles_fail_before_owned_acquisition(defaults_operator, monkeypatch, fault):
    case = scenario(defaults_operator, monkeypatch, parent_kind="global" if fault == "scope" else "site")
    if fault == "language": defaults_operator.runtime.local.lang = None
    elif fault == "provider": case.service._format_metadata = None
    with pytest.raises(InspectionFailed): capture(case, major=15 if fault == "version" else 16)
    case.factory.assert_not_called()


def test_arabic_failure_reuses_one_display_summary_and_english_internal_contract(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    with (Path(__file__).resolve().parents[2] / "translations/ar.csv").open() as stream:
        translations = {row[0]: row[1] for row in csv.reader(stream) if len(row) >= 2}
    monkeypatch.setattr(access, "_", lambda message: translations[message])
    case.format_cache.side_effect = lambda *args: defaults_operator.runtime.throw("PRIVATE-FORMAT", InspectionFailed)
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, translations[access.FINANCIAL_FAILED_MESSAGE])


def test_singleton_saved_access_never_reads_a_fabricated_modified_value(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    doc = case.related["System Settings"]
    original = doc.get
    def get(name, *args):
        if name == "modified": raise AssertionError("Singleton revision must not be fabricated")
        return original(name, *args)
    doc.get = get
    assert capture(case).related[-1].revision is None
