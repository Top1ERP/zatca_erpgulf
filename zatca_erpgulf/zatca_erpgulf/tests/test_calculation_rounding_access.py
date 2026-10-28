"""Synthetic rounding READ/cache composition on the shared owned transaction."""

from dataclasses import replace
from datetime import timedelta
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import calculation_rounding_access as rounding
from zatca_erpgulf.zatca_erpgulf import rounding_setting_source as sql
from zatca_erpgulf.zatca_erpgulf.calculation_rounding import METHODS, LEGACY_METHOD
from zatca_erpgulf.zatca_erpgulf.source_metadata import ROUNDING_PROFILE
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_context_access import scenario as context_case
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, one_failure, untouched, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_format_source import scenario as text_case
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import Document


def bind_rounding(case, operator, *, value=LEGACY_METHOD, missing=False):
    raw = AppliedMeta("System Settings", ("rounding_method",))
    options = "\n".join(sorted(METHODS))
    raw.definitions["rounding_method"].values.update(fieldtype="Select", options=options)
    case.round_observation = observed_metadata(raw, profile=ROUNDING_PROFILE)
    case.round_raw = raw
    df = Document(fieldtype="Select", options=options, default=None, permlevel=0)
    doc = Document(doctype="System Settings", name="System Settings", rounding_method=None if missing else value)
    doc.save, doc.db_set, doc.check_permission = Mock(), Mock(), Mock()
    doc.meta = SimpleNamespace(get_field=lambda name: df if name == "rounding_method" else None,
        get_permlevel_access=Mock(return_value=[0]))
    case.round_doc, case.round_df = doc, df
    operator.documents[doc.doctype, doc.name] = doc
    case.round_data = text_case(currency=None)
    case.round_data.records["System Settings"] = [] if missing else [(doc.doctype, "rounding_method", value)]
    case.round_metadata = Mock(side_effect=lambda *args: {"System Settings": case.round_observation.applied})
    case.round_cache = Mock(side_effect=lambda *args: case.round_doc.rounding_method)
    case.service = access.SavedCalculationDefaultsService(case.scope, case.factory, case.cache,
        parent_kind=getattr(case, "parent_kind", "site"), applied_metadata_reader=case.metadata_provider,
        rounding_metadata_reader=case.round_metadata, rounding_cache_reader=case.round_cache)
    return case


def scenario(operator, monkeypatch, **options):
    parent_kind = options.pop("parent_kind", "site")
    case = context_case(operator, doctype=options.pop("doctype", "Sales Invoice"),
        parent_kind=parent_kind)
    case.parent_kind = parent_kind
    bind_rounding(case, operator, **options)
    context_cursor, round_cursor = case.database.cursor, case.round_data.connection.cursor
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, statement, params=()):
            self.current = round_cursor() if "FROM `tabSingles`" in statement else context_cursor()
            self.current.execute(statement, params)
        def fetchone(self): return self.current.fetchone()
        def fetchall(self): return self.current.fetchall()
        @property
        def description(self): return self.current.description
    case.database.cursor = Mock(side_effect=Cursor)
    provider = Mock()
    provider.load_for_update.side_effect = lambda meta: case.round_observation
    provider.require_unchanged.return_value = None
    monkeypatch.setattr(sql, "MariaDBMetadataSourceReader", Mock(return_value=provider))
    return case


def capture(case, *, major=15, override=None):
    return case.service.capture_rounding_context(case.invoice.name, doctype=case.invoice.doctype,
        erp_major=major, rounding_override=override)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("value,missing", [(None, False), ("", False), (None, True),
    *[(method, False) for method in sorted(METHODS)]])
def test_exact_rounding_sources_share_one_owned_pipeline(defaults_operator, monkeypatch, doctype, major, value, missing):
    case = scenario(defaults_operator, monkeypatch, doctype=doctype, value=value, missing=missing)
    result = capture(case, major=major)
    assert type(result) is rounding.SavedRoundingContext
    assert result.erp_major == major and result.method == (value or LEGACY_METHOD)
    assert result.origin == ("SYSTEM_SETTING" if value else "LEGACY_DEFAULT")
    assert result.rounding.value == value and result.rounding.stored is not missing
    assert result.rounding.metadata.applied.profile == ROUNDING_PROFILE
    assert result.related[0].revision is None
    assert result.context.settings.sources[1].name == case.invoice.name
    assert case.factory.call_count == 1 and case.database.rollback.call_count == 2
    assert case.round_metadata.call_count == 2 and case.round_cache.call_count == 3
    assert not hasattr(result, "financial")
    untouched(defaults_operator, case)


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("override", sorted(METHODS))
def test_explicit_method_skips_unused_related_dependencies(defaults_operator, monkeypatch, major, override):
    case = scenario(defaults_operator, monkeypatch, value="UNKNOWN-PRIVATE")
    defaults_operator.denied.add(("System Settings", "System Settings"))
    case.round_df.fieldtype = "UNKNOWN"
    result = capture(case, major=major, override=override)
    assert result.method == override and result.origin == "EXPLICIT_OVERRIDE"
    assert result.rounding is None and result.related == ()
    case.round_metadata.assert_not_called()
    case.round_cache.assert_not_called()
    assert not case.round_data.connection.queries
    assert not any(call.args[0] == "System Settings" for call in defaults_operator.runtime.get_doc.call_args_list)


@pytest.mark.parametrize("denied", ["invoice", "company", "system", "field", "role"])
def test_all_read_checks_precede_every_provider(defaults_operator, monkeypatch, denied):
    case = scenario(defaults_operator, monkeypatch)
    if denied == "role": defaults_operator.runtime.get_roles.return_value = []
    elif denied == "field": case.round_df.permlevel = 1
    else:
        doc = {"invoice": case.invoice, "company": case.company, "system": case.round_doc}[denied]
        defaults_operator.denied.add((doc.doctype, doc.name))
    with pytest.raises(PermissionDenied): capture(case)
    for provider in (case.factory, case.cache, case.metadata_provider, case.round_metadata, case.round_cache): provider.assert_not_called()
    one_failure(defaults_operator, access.DENIED_MESSAGE)


@pytest.mark.parametrize("boundary", ["metadata_first", "metadata_last", "cache_first", "cache_last", "close", "cache_after_close"])
@pytest.mark.parametrize("changed", ["value", "permission", "field", "invoice"])
def test_callbacks_and_cleanup_cannot_disclose_after_drift(defaults_operator, monkeypatch, boundary, changed):
    case = scenario(defaults_operator, monkeypatch)
    def mutate():
        if changed == "value": case.round_doc.rounding_method = "Commercial Rounding"
        elif changed == "permission": defaults_operator.denied.add(("System Settings", "System Settings"))
        elif changed == "field": case.round_df.permlevel = 1
        else: case.invoice.modified += timedelta(seconds=1)
    if boundary == "close": case.database.close.side_effect = mutate
    else:
        provider = case.round_metadata if boundary.startswith("metadata") else case.round_cache
        original = provider.side_effect
        when = 1 if boundary.endswith("first") else 3 if boundary.endswith("after_close") else 2
        def callback(*args):
            result = original(*args)
            if provider.call_count == when: mutate()
            return result
        provider.side_effect = callback
    denied = changed in ("permission", "field")
    with pytest.raises(PermissionDenied if denied else InspectionFailed): capture(case)
    one_failure(defaults_operator, access.DENIED_MESSAGE if denied else access.FAILED_MESSAGE)
    if case.factory.called: case.database.close.assert_called_once()


@pytest.mark.parametrize("fault", ["cache", "default", "fieldtype", "profile", "metadata_extra", "empty_singleton"])
def test_inconsistent_values_or_empty_singleton_are_not_defaulted(defaults_operator, monkeypatch, fault):
    case = scenario(defaults_operator, monkeypatch, value="", missing=fault == "empty_singleton")
    if fault == "cache": case.round_cache.side_effect = lambda *args: LEGACY_METHOD
    elif fault == "default": case.round_df.default = "Commercial Rounding"
    elif fault == "fieldtype": case.round_df.fieldtype = "Data"
    elif fault == "profile": case.round_metadata.side_effect = lambda *args: {"System Settings": observed_metadata(case.round_raw).applied}
    elif fault == "metadata_extra": case.round_metadata.side_effect = lambda *args: {"System Settings": case.round_observation.applied, "Currency": None}
    else: case.round_data.connection.singleton_nonempty = False
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FAILED_MESSAGE)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("major,override,parent_kind", [(True, None, "site"), ("16", None, "site"),
    (17, None, "site"), (15, "UNKNOWN-PRIVATE", "site"), (15, None, "user"), (16, None, "global")])
def test_unreviewed_inputs_fail_before_callbacks(defaults_operator, monkeypatch, major, override, parent_kind):
    case = scenario(defaults_operator, monkeypatch, parent_kind=parent_kind)
    with pytest.raises(InspectionFailed): capture(case, major=major, override=override)
    for provider in (case.factory, case.cache, case.metadata_provider, case.round_metadata, case.round_cache): provider.assert_not_called()


@pytest.mark.parametrize("fault", ["rounding", "related", "version", "context", "override"])
def test_protected_result_cannot_drop_or_rebind_evidence(defaults_operator, monkeypatch, fault):
    result = capture(scenario(defaults_operator, monkeypatch))
    changes = {"rounding": None} if fault == "rounding" else {"related": ()} if fault == "related" else {"erp_major": True} if fault == "version" else {"context": object()} if fault == "context" else {"override": "Commercial Rounding"}
    with pytest.raises(rounding.CalculationFormatAccessError): replace(result, **changes)
    assert "SYNTHETIC" not in repr(result)
    with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(result)


def test_old_context_api_does_not_acquire_new_rounding_dependencies(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    defaults_operator.denied.add(("System Settings", "System Settings"))
    result = case.service.capture_context(case.invoice.name, doctype=case.invoice.doctype)
    assert type(result) is access.SavedCalculationContextRead
    case.round_metadata.assert_not_called()
    case.round_cache.assert_not_called()
    assert not case.round_data.connection.queries


def test_rounding_cache_interrupt_preserves_cleanup_and_parent_messages(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    case.round_cache.side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt): capture(case)
    case.database.close.assert_called_once()
    assert defaults_operator.runtime.message_log == ["EXISTING-PARENT-MESSAGE"]
    untouched(defaults_operator, case)
