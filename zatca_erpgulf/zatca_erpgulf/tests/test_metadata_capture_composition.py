"""SQL projection parity with the former document bridge; no site or I/O."""

from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from frappe.utils.data import cast

from zatca_erpgulf.zatca_erpgulf import metadata_source as source
from zatca_erpgulf.zatca_erpgulf import metadata_reconciliation as matching
from zatca_erpgulf.zatca_erpgulf.tests.test_metadata_source import scenario, load
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta, project
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
from zatca_erpgulf.zatca_erpgulf.source_metadata import PROFILE, PROFILE_FIELDS, BASE_TYPES, project_source_metadata


def legacy_match(observed):
    """Independent former bridge through the public document capture boundary."""
    body = json.loads(observed._payload)
    def documents(group):
        result = []
        for row in body[group]:
            values = {name: source._validate_scalar(tag) for name, tag in row["header"]}
            modified = source._validate_scalar(row["modified"])
            result.append(SimpleNamespace(doctype=source.SPECS[group][0], name=row["name"],
                get=lambda name, values=values, modified=modified: modified if name == "modified" else values.get(name)))
        return result
    return matching.reconcile_field_customizations(observed.base, observed.applied,
        custom_fields=documents("custom_fields"), property_setters=documents("property_setters"))


@pytest.mark.parametrize("doctype", source.SOURCE_FIELDS)
@pytest.mark.parametrize("kind", ["ordinary", "zero", "null", "unicode", "empty"])
def test_captured_sql_tags_preserve_legacy_match_bytes_and_digests(doctype, kind):
    case = scenario(doctype)
    if kind in ("zero", "null"):
        setter = case.records["property_setters"][0]
        setter["value"] = "0" if kind == "zero" else None
        case.meta.definitions[case.ordinary[0]].values["precision"] = cast("Int", setter["value"])
    elif kind == "unicode":
        case.records["docfields"][0]["default"] = "قيمة افتراضية — eval:DO_NOT_EXECUTE"
        case.meta.definitions[case.ordinary[0]].values["default"] = case.records["docfields"][0]["default"]
    elif kind == "empty":
        case.records["custom_fields"].clear()
        case.records["property_setters"].clear()
        case.meta.definitions[case.ordinary[0]].values["precision"] = None
        if case.custom: case.meta.definitions.pop(case.custom)
    case.applied = project(case.meta)
    observed = load(case)
    expected = legacy_match(observed)
    assert observed.match._payload == expected._payload
    assert observed.match.sha256 == expected.sha256
    assert observed.match.base._payload == expected.base._payload
    assert observed.match.applied._payload == expected.applied._payload
    assert len(case.connection.queries) == 8
    for name in ("commit", "rollback", "close"): getattr(case.connection, name).assert_not_called()


@pytest.mark.parametrize("field,value", [("idx", -1), ("idx", True), ("is_virtual", 1), ("dt", "OTHER")])
def test_source_only_custom_columns_are_checked_before_narrower_projection(field, value):
    observed = load(scenario())
    body = json.loads(observed._payload)
    row = body["custom_fields"][0]
    row["header"] = [[name, source._scalar(value) if name == field else tag] for name, tag in row["header"]]
    with pytest.raises(source.MetadataSourceError) as caught:
        replace(observed, _payload=source._canonical(body))
    assert str(caught.value) == "metadata_source_rows" and caught.value.__context__ is None


def test_public_document_capture_still_rejects_corrupt_declarations_before_getters():
    observed = load(scenario())
    object.__setattr__(observed.applied, "sha256", "CORRUPT")
    protected = SimpleNamespace(get=Mock(side_effect=AssertionError("Protected getter must not run")))
    with pytest.raises(matching.MetadataReconciliationError) as caught:
        matching.reconcile_field_customizations(observed.base, observed.applied,
            custom_fields=[protected], property_setters=[])
    assert str(caught.value) == "metadata_customization_reconciliation" and caught.value.__context__ is None
    protected.get.assert_not_called()


@pytest.mark.parametrize("profile,doctype", [(profile, doctype)
    for profile, types in PROFILE_FIELDS.items() for doctype in types])
def test_each_metadata_profile_keeps_the_same_raw_setter_match(profile, doctype):
    name = next(name for name in PROFILE_FIELDS[profile][doctype] if name not in BASE_TYPES)
    raw = AppliedMeta(doctype, (name,))
    original = observed_metadata(raw, profile=None if profile == PROFILE else profile)
    body = json.loads(original._payload)
    raw.definitions[name].values["precision"] = 2
    applied = project(raw) if profile == PROFILE else project_source_metadata(raw, base_fields={}, profile=profile)
    values = dict(doctype_or_field="DocField", doc_type=doctype, field_name=name,
        property="precision", property_type="Int", value="2")
    body["property_setters"] = [dict(name="SETTER-1", modified=body["doctype"]["modified"],
        header=[[field, source._scalar(values[field])] for field in matching.SETTER_FIELDS])]
    observed = source.SelectedMetadataRows(applied, source._canonical(body))
    expected = legacy_match(observed)
    assert observed.match._payload == expected._payload and observed.match.sha256 == expected.sha256
