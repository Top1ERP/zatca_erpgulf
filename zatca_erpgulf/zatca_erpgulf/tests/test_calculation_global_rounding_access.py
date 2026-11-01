"""Global Check READ/metadata/API-cache composition, entirely synthetic."""

from dataclasses import replace
from datetime import timedelta
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import calculation_global_rounding_access as global_access
from zatca_erpgulf.zatca_erpgulf import global_rounding_source as source
from zatca_erpgulf.zatca_erpgulf.source_metadata import GLOBAL_ROUNDING_PROFILE
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_context_access import scenario as context_case
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, one_failure, untouched, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_global_rounding_source import scenario as global_case
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import Document


def bind_global(case, operator, *, raw="0", missing=False, document_value=1):
    case.global_data = global_case(raw=raw, missing=missing)
    case.global_observation = case.global_data.metadata
    case.global_raw = case.global_data.raw
    df = Document(fieldtype="Check", options=None, default="1", permlevel=0)
    doc = Document(doctype=source.DOCTYPE, name=source.DOCTYPE, disable_rounded_total=document_value)
    doc.save, doc.db_set, doc.check_permission = Mock(), Mock(), Mock()
    doc.meta = SimpleNamespace(get_field=lambda name: df if name == source.FIELD else None,
        get_permlevel_access=Mock(return_value=[0]))
    case.global_doc, case.global_df = doc, df
    operator.documents[doc.doctype, doc.name] = doc
    case.global_metadata = Mock(side_effect=lambda *args: {source.DOCTYPE: case.global_observation.applied})
    case.global_api = 1 if raw == "1" and not missing else 0
    case.global_cache = Mock(side_effect=lambda *args: case.global_api)
    case.service = access.SavedCalculationDefaultsService(case.scope, case.factory, case.cache,
        parent_kind=getattr(case, "parent_kind", "site"), applied_metadata_reader=case.metadata_provider,
        global_rounding_metadata_reader=case.global_metadata, global_rounding_cache_reader=case.global_cache)
    return case


def scenario(operator, monkeypatch, **options):
    parent_kind = options.pop("parent_kind", "site")
    case = context_case(operator, doctype=options.pop("doctype", "Sales Invoice"), parent_kind=parent_kind)
    case.parent_kind = parent_kind
    bind_global(case, operator, **options)
    context_cursor, selected_cursor = case.database.cursor, case.global_data.connection.cursor
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, statement, params=()):
            self.current = selected_cursor() if "FROM `tabSingles`" in statement else context_cursor()
            self.current.execute(statement, params)
        def fetchone(self): return self.current.fetchone()
        def fetchall(self): return self.current.fetchall()
        @property
        def description(self): return self.current.description
    case.database.cursor = Mock(side_effect=Cursor)
    provider = Mock()
    provider.load_for_update.side_effect = lambda *args: case.global_observation
    monkeypatch.setattr(source, "MariaDBMetadataSourceReader", Mock(return_value=provider))
    return case


def capture(case, *, major=15):
    return case.service.capture_global_rounding_context(case.invoice.name,
        doctype=case.invoice.doctype, erp_major=major)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("raw,missing", [(None, True), (None, False), ("", False), ("0", False), ("1", False)])
def test_inspection_uses_one_owned_pipeline_and_exact_single_value_projection(defaults_operator, monkeypatch, doctype, major, raw, missing):
    case = scenario(defaults_operator, monkeypatch, doctype=doctype, raw=raw, missing=missing)
    result = capture(case, major=major)
    assert type(result) is global_access.SavedGlobalRoundingContext
    assert result.erp_major == major and result.global_rounding.value == case.global_api
    assert result.global_rounding.stored is not missing
    assert result.global_rounding.metadata.applied.profile == GLOBAL_ROUNDING_PROFILE
    assert result.related[0].fields == result.related[0].values == ()
    assert result.related[0].revision is None
    assert case.factory.call_count == 1 and case.database.rollback.call_count == 2
    assert case.global_metadata.call_count == 2 and case.global_cache.call_count == 3
    assert case.global_doc.disable_rounded_total == 1
    assert not hasattr(result, "disabled") and not hasattr(result, "financial")
    untouched(defaults_operator, case)


def test_normal_read_never_inspects_or_substitutes_document_default_value(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch, missing=True)
    original = case.global_doc.get
    def get(name, *args):
        if name == source.FIELD: raise AssertionError("Document defaults are not the single-value API")
        return original(name, *args)
    case.global_doc.get = Mock(side_effect=get)
    result = capture(case)
    assert result.global_rounding.value == 0 and result.global_rounding.stored is False
    assert result.related[0].values == ()


@pytest.mark.parametrize("denied", ["invoice", "company", "global", "field", "role"])
def test_normal_and_field_read_precede_all_providers(defaults_operator, monkeypatch, denied):
    case = scenario(defaults_operator, monkeypatch)
    if denied == "role": defaults_operator.runtime.get_roles.return_value = []
    elif denied == "field": case.global_df.permlevel = 1
    else:
        doc = {"invoice": case.invoice, "company": case.company, "global": case.global_doc}[denied]
        doc.flags = SimpleNamespace(ignore_permissions=True)
        defaults_operator.denied.add((doc.doctype, doc.name))
    with pytest.raises(PermissionDenied): capture(case)
    for provider in (case.factory, case.cache, case.metadata_provider, case.global_metadata, case.global_cache):
        provider.assert_not_called()
    one_failure(defaults_operator, access.DENIED_MESSAGE)


@pytest.mark.parametrize("boundary", ["metadata_first", "metadata_last", "cache_first", "cache_last", "close", "cache_after_close"])
@pytest.mark.parametrize("changed", ["permission", "field", "cache", "invoice", "actor"])
def test_callbacks_and_cleanup_cannot_disclose_after_drift(defaults_operator, monkeypatch, boundary, changed):
    case = scenario(defaults_operator, monkeypatch)
    def mutate():
        if changed == "permission": defaults_operator.denied.add((source.DOCTYPE, source.DOCTYPE))
        elif changed == "field": case.global_df.permlevel = 1
        elif changed == "cache": case.global_api = 1
        elif changed == "actor": defaults_operator.runtime.session.user = "other@example.invalid"
        else: case.invoice.modified += timedelta(seconds=1)
    if boundary == "close": case.database.close.side_effect = mutate
    else:
        provider = case.global_metadata if boundary.startswith("metadata") else case.global_cache
        original = provider.side_effect
        when = 1 if boundary.endswith("first") else 3 if boundary.endswith("after_close") else 2
        def callback(*args):
            result = original(*args)
            if provider.call_count == when: mutate()
            if changed == "cache" and provider is case.global_cache: return case.global_api
            return result
        provider.side_effect = callback
    denied = changed in ("permission", "field", "actor")
    with pytest.raises(PermissionDenied if denied else InspectionFailed): capture(case)
    one_failure(defaults_operator, access.DENIED_MESSAGE if denied else access.FAILED_MESSAGE)
    if case.factory.called: case.database.close.assert_called_once()


@pytest.mark.parametrize("fault", ["cached_none", "cached_bool", "cached_float", "metadata_default", "metadata_type", "metadata_extra", "metadata_profile", "missing_cache", "missing_metadata"])
def test_bad_dependencies_never_fall_back_to_the_document(defaults_operator, monkeypatch, fault):
    case = scenario(defaults_operator, monkeypatch, document_value=0)
    if fault.startswith("cached_"):
        case.global_cache.side_effect = lambda *args: {"cached_none": None, "cached_bool": False, "cached_float": 0.0}[fault]
    elif fault == "metadata_default": case.global_df.default = "0"
    elif fault == "metadata_type": case.global_df.fieldtype = "Int"
    elif fault == "metadata_extra": case.global_metadata.side_effect = lambda *args: {source.DOCTYPE: case.global_observation.applied, "System Settings": None}
    elif fault == "metadata_profile": case.global_metadata.side_effect = lambda *args: {source.DOCTYPE: observed_metadata(case.global_raw).applied}
    elif fault == "missing_cache": case.service._global_rounding_cache = None
    else: case.service._global_rounding_metadata = None
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FAILED_MESSAGE)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("major,parent_kind", [(True, "site"), ("16", "site"), (17, "site"), (15, "global"), (16, "user")])
def test_unreviewed_scope_is_refused_before_provider_calls(defaults_operator, monkeypatch, major, parent_kind):
    case = scenario(defaults_operator, monkeypatch, parent_kind=parent_kind)
    with pytest.raises(InspectionFailed): capture(case, major=major)
    for provider in (case.factory, case.cache, case.metadata_provider, case.global_metadata, case.global_cache):
        provider.assert_not_called()


@pytest.mark.parametrize("fault", ["drop_native", "drop_access", "bool_version", "wrong_context", "fake_value", "access_fields"])
def test_protected_result_cannot_drop_or_invent_evidence(defaults_operator, monkeypatch, fault):
    result = capture(scenario(defaults_operator, monkeypatch))
    if fault == "drop_native": changes = dict(global_rounding=None)
    elif fault == "drop_access": changes = dict(related=())
    elif fault == "bool_version": changes = dict(erp_major=True)
    elif fault == "wrong_context": changes = dict(context=object())
    elif fault == "fake_value":
        object.__setattr__(result.global_rounding, "value", 1)
        changes = {}
    else: changes = dict(related=(replace(result.related[0], fields=(source.FIELD,), values=(0,)),))
    with pytest.raises(global_access.CalculationFormatAccessError): replace(result, **changes)


def test_existing_context_path_does_not_consult_global_dependencies(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    defaults_operator.denied.add((source.DOCTYPE, source.DOCTYPE))
    result = case.service.capture_context(case.invoice.name, doctype=case.invoice.doctype)
    assert type(result) is access.SavedCalculationContextRead
    case.global_metadata.assert_not_called()
    case.global_cache.assert_not_called()
    assert not case.global_data.connection.queries


@pytest.mark.parametrize("boundary", ["metadata", "cache", "close"])
def test_interrupt_keeps_priority_and_parent_messages(defaults_operator, monkeypatch, boundary):
    case = scenario(defaults_operator, monkeypatch)
    target = case.global_metadata if boundary == "metadata" else case.global_cache if boundary == "cache" else case.database.close
    target.side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt): capture(case)
    if case.factory.called: case.database.close.assert_called_once()
    assert defaults_operator.runtime.message_log == ["EXISTING-PARENT-MESSAGE"]


def test_protected_objects_refuse_serialization(defaults_operator, monkeypatch):
    result = capture(scenario(defaults_operator, monkeypatch))
    assert "SYNTHETIC" not in repr(result) and "NOT invoice policy" in repr(result)
    with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(result)


def test_explicit_method_path_does_not_consult_global_check(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    defaults_operator.denied.add((source.DOCTYPE, source.DOCTYPE))
    result = case.service.capture_rounding_context(case.invoice.name, erp_major=15,
        doctype=case.invoice.doctype, rounding_override="Commercial Rounding")
    assert result.method == "Commercial Rounding" and result.rounding is None
    case.global_metadata.assert_not_called()
    case.global_cache.assert_not_called()


def test_failure_uses_one_translated_summary_without_raw_internal_values(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    translated = "تعذر تأكيد إعدادات الحساب. لم يتم تغيير الفاتورة أو إرسال أي طلب."
    monkeypatch.setattr(access, "_", lambda text: translated if text == access.FAILED_MESSAGE else text)
    case.global_cache.side_effect = RuntimeError("PRIVATE-DRIVER-INTERNAL-CODE")
    with pytest.raises(InspectionFailed, match=translated): capture(case)
    one_failure(defaults_operator, translated)
    assert "PRIVATE" not in repr(defaults_operator.runtime.message_log)
