"""Selected metadata SQL contracts with explicit synthetic applied definitions."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta
import json
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import metadata_source as source
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta, Definition, project

NOW = datetime(2026, 10, 27, 13, 0, 0)


def scenario(doctype="Sales Invoice"):
    selected = source.SOURCE_FIELDS[doctype]
    available = [name for name in selected if name not in source.BASE_TYPES]
    custom = next((name for name in available if name.startswith("custom")), None) if len(available) > 2 else None
    # An app DocType can declare ordinary DocFields named custom_*. Names alone
    # never establish Custom Field origin; the SQL table does.
    ordinary = [name for name in available if name != custom][:2]
    meta = AppliedMeta(doctype, ordinary)
    records = {group: [] for group in source.SPECS}
    records["doctype"] = [dict(name=doctype, modified=NOW,
        issingle=int(meta.issingle), istable=int(meta.istable), is_virtual=0, custom=0)]
    for index, name in enumerate(ordinary):
        values = {prop: meta.definitions[name].get(prop) for prop in source.EDITABLE}
        records["docfields"].append(dict(name=f"DOC-{index}", modified=NOW,
            parent=doctype, parenttype="DocType", parentfield="fields", idx=index + 1,
            fieldname=name, is_virtual=0, **values))
    if custom:
        values = {prop: None for prop in source.EDITABLE}
        values["fieldtype"] = "Check"
        records["custom_fields"] = [dict(name="CUSTOM-1", modified=NOW, dt=doctype, idx=0,
            fieldname=custom, is_virtual=0, **values)]
        meta.definitions[custom] = Definition(custom, **values, is_custom_field=1)
    records["property_setters"] = [dict(name="SETTER-1", modified=NOW, doctype_or_field="DocField",
        doc_type=doctype, field_name=ordinary[0], property="precision", property_type="Int", value="2")]
    meta.definitions[ordinary[0]].values["precision"] = 2
    connection = SimpleNamespace(records=records, queries=[], autocommit=(0,), error=None, hook=None,
        commit=Mock(), rollback=Mock(), close=Mock())

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, args=()):
            connection.queries.append((sql, args))
            if connection.error: raise connection.error
            if sql == "SELECT @@session.autocommit": return
            table = sql.split("FROM `tab", 1)[1].split("`", 1)[0]
            group = next(key for key, (name, _) in source.SPECS.items() if name == table)
            preflight = group != "doctype" and ("SUBSTRING(`value`" not in sql if group == "property_setters"
                else "CASE WHEN" not in sql)
            fields = source.PREFLIGHT[group] if preflight else source.SPECS[group][1]
            if connection.hook: connection.hook(group, preflight)
            self.rows = tuple((row["name"], row["modified"], *(row.get(name) for name in fields))
                for row in connection.records[group])
        def fetchone(self): return connection.autocommit
        def fetchall(self): return self.rows

    connection.cursor = Mock(side_effect=Cursor)
    return SimpleNamespace(doctype=doctype, ordinary=ordinary, custom=custom, meta=meta,
        applied=project(meta), records=records, connection=connection,
        reader=source.MariaDBMetadataSourceReader(connection))


def load(case):
    return case.reader.load_for_update(case.applied)


def failure(call, code="metadata_source_read"):
    with pytest.raises(source.MetadataSourceError) as caught: call()
    assert str(caught.value) == code and caught.value.__context__ is None


@pytest.mark.parametrize("doctype", source.SOURCE_FIELDS)
def test_all_selected_types_bind_raw_standard_custom_and_setter_rows(doctype):
    case = scenario(doctype)
    observed = load(case)
    assert observed.applied == case.applied and observed.applied is not case.applied
    assert observed.base.get_field(case.ordinary[0]).get("precision") is None
    assert observed.applied.get_field(case.ordinary[0]).get("precision") == 2
    assert observed.match.base == observed.base and observed.match.applied == observed.applied
    case.reader.require_unchanged(observed)
    assert len(case.connection.queries) == 16  # One session + seven fixed projections per read.
    assert "NOT verified" in repr(observed) and "DOC-" not in repr(observed)
    assert all(not getattr(case.connection, name).called for name in ("commit", "rollback", "close"))
    with pytest.raises(FrozenInstanceError): observed.sha256 = "f" * 64
    for protected in (observed, case.reader):
        with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(protected)


@pytest.mark.parametrize("group", ["docfields", "custom_fields", "property_setters"])
def test_unsafe_preflight_refuses_before_sensitive_projection(group):
    case = scenario()
    if group == "property_setters": case.records[group][0]["property_type"] = "Password"
    else: case.records[group][0]["fieldtype"] = "Password"
    failure(lambda: load(case))
    table = source.SPECS[group][0]
    queries = [sql for sql, _ in case.connection.queries if f"FROM `tab{table}`" in sql]
    assert len(queries) == 1
    assert "CASE WHEN" not in queries[0] and "SUBSTRING(`value`" not in queries[0]
    failure(lambda: load(case), "metadata_source_transaction_unusable")


@pytest.mark.parametrize("group", ["docfields", "custom_fields", "property_setters"])
def test_between_preflight_and_full_membership_revision_or_type_drift_is_rejected(group):
    case = scenario()
    def mutate(current, preflight):
        if current == group and not preflight:
            case.records[group][0]["modified"] += timedelta(seconds=1)
    case.connection.hook = mutate
    failure(lambda: load(case))


@pytest.mark.parametrize("fault", ["type_missing", "type_case", "virtual_type", "type_flags", "missing_standard",
    "standard_parent", "parentfield", "standard_duplicate", "standard_password", "custom_password", "virtual_field",
    "custom_shadow", "base_shadow", "duplicate_property", "storage_setter", "unknown_cast", "stale_applied",
    "field_case", "text_bound", "invalid_timestamp", "custom_revision", "invalid_idx"])
def test_inconsistent_scope_storage_rows_and_cached_effects_fail_closed(fault):
    case = scenario()
    standard, custom, setter = (case.records[group][0] for group in ("docfields", "custom_fields", "property_setters"))
    if fault == "type_missing": case.records["doctype"] = []
    elif fault == "type_case": case.records["doctype"][0]["name"] = case.doctype.lower()
    elif fault == "virtual_type": case.records["doctype"][0]["is_virtual"] = 1
    elif fault == "type_flags": case.records["doctype"][0]["istable"] = 1
    elif fault == "missing_standard": case.records["docfields"] = []
    elif fault == "standard_parent": standard["parent"] = "OTHER"
    elif fault == "parentfield": standard["parentfield"] = "other"
    elif fault == "standard_duplicate": case.records["docfields"].append(dict(standard, name="Z-DUPLICATE"))
    elif fault == "standard_password": standard["fieldtype"] = "Password"
    elif fault == "custom_password": custom["fieldtype"] = "Password"
    elif fault == "virtual_field": standard["is_virtual"] = 1
    elif fault == "custom_shadow": custom["fieldname"] = standard["fieldname"]
    elif fault == "base_shadow": custom["fieldname"] = "docstatus"
    elif fault == "duplicate_property": case.records["property_setters"].append(dict(setter, name="Z-DUPLICATE"))
    elif fault == "storage_setter": setter.update(doctype_or_field="DocType", field_name=None, property="istable")
    elif fault == "unknown_cast": setter["property_type"] = "Datetime"
    elif fault == "stale_applied": setter["value"] = "3"
    elif fault == "field_case": standard["fieldname"] = standard["fieldname"].upper()
    elif fault == "text_bound": standard["options"] = "أ" * source.MAX_TEXT_BYTES
    elif fault == "invalid_timestamp": standard["modified"] = "0000-00-00"
    elif fault == "custom_revision": custom["modified"] = None
    else: standard["idx"] = -1
    failure(lambda: load(case))


@pytest.mark.parametrize("group", ["doctype", "docfields", "custom_fields", "property_setters"])
def test_raw_revision_changes_are_bound_even_when_applied_properties_are_equal(group):
    case = scenario()
    observed = load(case)
    case.records[group][0]["modified"] += timedelta(seconds=1)
    failure(lambda: case.reader.require_unchanged(observed), "metadata_source_changed")
    failure(lambda: load(case), "metadata_source_transaction_unusable")


@pytest.mark.parametrize("change", ["profile", "framework", "source_doctype", "extra", "missing", "order", "default", "noncanonical", "trailing"])
def test_direct_reconstruction_validates_raw_rows_and_repeats_reconciliation(change):
    case = scenario()
    observed = load(case)
    body = json.loads(observed._payload)
    if change in ("profile", "framework", "source_doctype"):
        body[{"framework": "framework_version"}.get(change, change)] = "OTHER"
    elif change == "extra": body["secret"] = "PRIVATE"
    elif change == "missing": body["custom_fields"] = []
    elif change == "order": body["docfields"].reverse()
    elif change == "default":
        next(item for item in body["docfields"][0]["header"] if item[0] == "default")[1] = ["str", "CHANGED"]
    payload = source._canonical(body)
    if change == "noncanonical": payload = json.dumps(body).encode()
    if change == "trailing": payload += b"PRIVATE"
    failure(lambda: replace(observed, _payload=payload), "metadata_source_rows")


def test_sql_identity_names_are_parameters_and_only_fixed_identifiers_are_used():
    case = scenario()
    load(case)
    for sql, args in case.connection.queries[1:]:
        assert "FOR UPDATE" in sql and "ORDER BY BINARY `name`" in sql
        assert case.doctype not in sql and args[0] == case.doctype
        assert "SELECT *" not in sql and "LIMIT %s" in sql


def test_reader_copies_applied_metadata_and_rejects_corrupt_derived_state():
    case = scenario()
    observed = load(case)
    object.__setattr__(case.applied, "sha256", "f" * 64)
    assert observed.applied.sha256 != case.applied.sha256
    object.__setattr__(observed.match, "sha256", "f" * 64)
    failure(lambda: case.reader.require_unchanged(observed), "metadata_source_changed")


@pytest.mark.parametrize("interrupt", [False, True])
def test_driver_errors_are_redacted_and_interruptions_poison_without_cleanup(interrupt):
    case = scenario()
    case.connection.error = KeyboardInterrupt() if interrupt else RuntimeError("PRIVATE DRIVER DETAIL")
    if interrupt:
        with pytest.raises(KeyboardInterrupt): load(case)
    else: failure(lambda: load(case))
    failure(lambda: load(case), "metadata_source_transaction_unusable")
    assert all(not getattr(case.connection, name).called for name in ("commit", "rollback", "close"))


@pytest.mark.parametrize("fieldtype", ["password", "Password ", "UNKNOWN"])
def test_invalid_type_aliases_are_refused_before_default_projection(fieldtype):
    case = scenario()
    case.records["docfields"][0]["fieldtype"] = fieldtype
    failure(lambda: load(case))
    assert not any("FROM `tabDocField`" in sql and "CASE WHEN" in sql for sql, _ in case.connection.queries)


def test_standard_legacy_null_revision_is_explicit_and_expressions_are_never_evaluated():
    case = scenario()
    case.records["docfields"][0].update(modified=None, default="eval:DO_NOT_EXECUTE")
    case.meta.definitions[case.ordinary[0]].values["default"] = "eval:DO_NOT_EXECUTE"
    case.applied = project(case.meta)
    observed = load(case)
    assert json.loads(observed._payload)["docfields"][0]["modified"] == ["null"]
    assert observed.base.get_field(case.ordinary[0]).get("default") == "eval:DO_NOT_EXECUTE"
