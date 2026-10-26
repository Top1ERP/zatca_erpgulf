"""Scoped defaults, cache comparisons and fixed read-only SQL contracts."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from itertools import product
import json
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import frappe
import frappe.defaults as framework_defaults
import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults as defaults


NOW = datetime(2026, 10, 26, 12, 0, 0)
PARENTS = ("__default", "__global", "synthetic@example.invalid")


def row(name="SYNTHETIC-1", *, value="2", key="currency_precision", parent="__default", offset=0):
    return (name, NOW + timedelta(microseconds=offset), NOW, parent, key, value)


class Cursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.connection.cursor_exits += 1

    def execute(self, sql, args=None):
        self.connection.queries.append((sql, args))
        if self.connection.error is not None:
            raise self.connection.error

    def fetchone(self):
        return self.connection.autocommit

    def fetchall(self):
        return self.connection.rows


class Connection:
    def __init__(self, rows=()):
        self.rows, self.queries = rows, []
        self.autocommit, self.error, self.cursor_exits = (0,), None, 0
        self.commit, self.rollback, self.close = Mock(), Mock(), Mock()

    def cursor(self):
        return Cursor(self)


def load(rows, parent="__default"):
    connection = Connection(rows)
    reader = defaults.MariaDBCalculationDefaultsReader(connection)
    return reader.load_for_update(parent), connection, reader


def static_failure(call, code):
    with pytest.raises(defaults.CalculationDefaultsError) as caught:
        call()
    assert str(caught.value) == caught.value.code == code
    assert caught.value.__context__ is None


@pytest.mark.parametrize("parent", PARENTS)
def test_explicit_scope_roundtrip_uses_only_bounded_fixed_selects(parent):
    observed, connection, reader = load([row(parent=parent)], parent)
    observed.require_cache_match(parent, {"currency_precision": "2", "unselected": object()})
    reader.require_unchanged(observed)
    assert connection.queries == [
        ("SELECT @@session.autocommit", None),
        (defaults.READ_SQL, (parent, *defaults.KEYS, defaults.MAX_ROWS + 1)),
    ] * 2
    assert connection.cursor_exits == 2
    assert all(not getattr(connection, name).called for name in ("commit", "rollback", "close"))
    assert "SYNTHETIC" not in repr(observed) and parent not in repr(observed)
    assert "NOT verified" in repr(observed)
    with pytest.raises(FrozenInstanceError):
        observed.sha256 = "f" * 64
    for protected in (observed, reader):
        with pytest.raises(TypeError, match="not_serializable"):
            pickle.dumps(protected)


@pytest.mark.parametrize("values", [values for size in (1, 2, 3)
    for values in product((None, "", "0", "2"), repeat=size)])
def test_row_folding_matches_actual_framework_cache_miss_without_sql_or_redis(monkeypatch, values):
    raw = [row(f"SYNTHETIC-{index}", value=value, offset=index) for index, value in enumerate(values)]
    observed, _, _ = load(raw)
    records = [frappe._dict(defkey="currency_precision", defvalue=value) for value in values]
    saved = []

    class Query:
        def from_(self, table): return self
        def where(self, condition): return self
        def select(self, *fields): return self
        def orderby(self, field):
            assert field == "creation"
            return self
        def run(self, **kwargs):
            assert kwargs == {"as_dict": True}
            return records

    monkeypatch.setattr(framework_defaults, "DocType", lambda name: SimpleNamespace(
        parent="parent", defkey="key", defvalue="value"))
    monkeypatch.setattr(frappe, "qb", Query())
    monkeypatch.setattr(frappe, "cache", SimpleNamespace(
        hget=lambda *args: None, hset=lambda *args: saved.append(args)))
    cached = framework_defaults.get_defaults_for("__default")
    observed.require_cache_match("__default", cached)
    assert saved == [("defaults", "__default", cached)]


@pytest.mark.parametrize("change", ["absent", "null", "blank", "numeric_zero", "boolean", "list",
    "empty_list", "tuple", "wrong_scope", "miss", "nested", "oversize"])
def test_cache_mismatch_is_explicit_and_does_not_repair_anything(change):
    observed, connection, _ = load([row(value="0")])
    cache, parent = {"currency_precision": "0"}, "__default"
    values = {"null": None, "blank": "", "numeric_zero": 0, "boolean": False,
        "list": ["0"], "empty_list": [], "tuple": ("0",), "nested": [["0"]],
        "oversize": "X" * (defaults.MAX_VALUE_BYTES + 1)}
    if change == "absent": cache = {}
    elif change == "wrong_scope": parent = "__global"
    elif change == "miss": cache = None
    else: cache["currency_precision"] = values[change]
    before = list(connection.queries)
    static_failure(lambda: observed.require_cache_match(parent, cache), "calculation_defaults_cache_mismatch")
    assert connection.queries == before


def test_null_only_empty_scope_and_missing_scope_remain_distinct():
    nulls, _, _ = load([row(value=None)])
    empty, _, _ = load([])
    nulls.require_cache_match("__default", {})
    empty.require_cache_match("__default", {})
    assert nulls.sha256 != empty.sha256
    static_failure(lambda: nulls.require_cache_match("__default", {"currency_precision": None}),
        "calculation_defaults_cache_mismatch")
    static_failure(lambda: empty.require_cache_match("__default", None), "calculation_defaults_cache_mismatch")


def test_extra_cache_keys_and_overridden_mapping_methods_are_not_read():
    class Cache(dict):
        def __contains__(self, key): raise AssertionError("Use only builtin selected-key reads")
        def __getitem__(self, key): raise AssertionError("Use only builtin selected-key reads")
        def __iter__(self): raise AssertionError("Never enumerate unrelated defaults")

    observed, _, _ = load([row()])
    observed.require_cache_match("__default", Cache(currency_precision="2", password=object()))


@pytest.mark.parametrize("fault", ["parent_case", "key_case", "unknown_key", "name", "duplicate_name",
    "creation", "modified", "aware", "type", "large_value", "large_utf8", "overflow", "shape",
    "dict_row", "order", "ambiguous_time", "ambiguous_null_time"])
def test_invalid_or_ambiguous_sql_rows_are_redacted_and_poison_reader(fault):
    records = [row()]
    changes = {"parent_case": (3, "__DEFAULT"), "key_case": (4, "Currency_Precision"),
        "unknown_key": (4, "password"), "name": (0, ""), "creation": (1, "0000-00-00"),
        "modified": (2, "2026-10-26"), "aware": (1, NOW.replace(tzinfo=timezone.utc)),
        "type": (5, 0), "large_value": (5, "X" * (defaults.MAX_VALUE_BYTES + 1)),
        "large_utf8": (5, "أ" * defaults.MAX_VALUE_BYTES)}
    if fault in changes:
        index, value = changes[fault]
        changed = list(records[0])
        changed[index] = value
        records = [tuple(changed)]
    elif fault == "duplicate_name": records *= 2
    elif fault == "overflow": records *= defaults.MAX_ROWS + 1
    elif fault == "shape": records = [records[0][:-1]]
    elif fault == "dict_row": records = [{"PRIVATE": "SECRET"}]
    elif fault == "order": records += [row("EARLIER", offset=-1)]
    elif fault == "ambiguous_time": records += [row("SYNTHETIC-2", value="3")]
    else:
        records = [(name, None, modified, parent, key, value) for name, _, modified, parent, key, value
            in (row(value=None), row("SYNTHETIC-2", value="2"))]
    connection = Connection(records)
    reader = defaults.MariaDBCalculationDefaultsReader(connection)
    static_failure(lambda: reader.load_for_update("__default"), "calculation_defaults_read")
    before = len(connection.queries)
    static_failure(lambda: reader.load_for_update("__default"), "calculation_defaults_transaction_unusable")
    assert len(connection.queries) == before
    assert all(not getattr(connection, name).called for name in ("commit", "rollback", "close"))


def test_equal_creation_equal_values_and_null_revision_are_retained_without_invention():
    rows = [row("A"), row("B")]
    rows = [(name, None, None, parent, key, value) for name, _, _, parent, key, value in rows]
    observed, _, _ = load(rows)
    observed.require_cache_match("__default", {"currency_precision": "2"})
    assert all(item["modified"] == item["creation"] == ["null"]
        for item in json.loads(observed._payload)["rows"])


@pytest.mark.parametrize("setting", [(1,), (False,), ("0",), None, (0, 0)])
def test_invalid_autocommit_refuses_before_reading_defaults(setting):
    connection = Connection([row()])
    connection.autocommit = setting
    static_failure(lambda: defaults.MariaDBCalculationDefaultsReader(connection).load_for_update("__default"),
        "calculation_defaults_read")
    assert connection.queries == [("SELECT @@session.autocommit", None)]


@pytest.mark.parametrize("change", ["value", "creation", "modified", "membership", "name"])
def test_require_unchanged_rechecks_all_rows_not_only_effective_value(change):
    observed, connection, reader = load([row()])
    record = list(connection.rows[0])
    if change == "value": record[5] = "3"
    elif change == "creation": record[1] += timedelta(seconds=1)
    elif change == "modified": record[2] += timedelta(seconds=1)
    elif change == "name": record[0] = "REPLACED"
    connection.rows = [tuple(record)]
    if change == "membership": connection.rows += [row("SECOND", offset=1)]
    static_failure(lambda: reader.require_unchanged(observed), "calculation_defaults_changed")
    static_failure(lambda: reader.require_unchanged(observed), "calculation_defaults_transaction_unusable")


@pytest.mark.parametrize("change", ["profile", "parent", "keys", "extra", "rows", "order", "noncanonical", "trailing"])
def test_direct_construction_rechecks_canonical_scope_and_rows(change):
    observed, _, _ = load([row()])
    body = json.loads(observed._payload)
    if change == "profile": body["profile"] = "OTHER"
    elif change == "parent": body["parent"] = "__global"
    elif change == "keys": body["keys"].reverse()
    elif change == "extra": body["secret"] = "PRIVATE"
    elif change == "rows": body["rows"][0]["value"] = ["int", "0"]
    elif change == "order": body["rows"].append(body["rows"][0])
    payload = defaults._canonical(body)
    if change == "noncanonical": payload = json.dumps(body).encode()
    if change == "trailing": payload += b"PRIVATE"
    static_failure(lambda: replace(observed, _payload=payload), "calculation_defaults_rows")


def test_corrupt_derived_parent_is_refused_before_another_sql_read():
    observed, connection, reader = load([row()])
    object.__setattr__(observed, "sha256", "f" * 64)
    before = list(connection.queries)
    static_failure(lambda: reader.require_unchanged(observed), "calculation_defaults_changed")
    assert connection.queries == before


@pytest.mark.parametrize("interrupt", [False, True])
def test_driver_failures_are_redacted_and_interruptions_still_poison_reader(interrupt):
    connection = Connection()
    connection.error = KeyboardInterrupt() if interrupt else RuntimeError("PRIVATE DRIVER DETAILS")
    reader = defaults.MariaDBCalculationDefaultsReader(connection)
    if interrupt:
        with pytest.raises(KeyboardInterrupt): reader.load_for_update("__default")
    else:
        static_failure(lambda: reader.load_for_update("__default"), "calculation_defaults_read")
    static_failure(lambda: reader.load_for_update("__default"), "calculation_defaults_transaction_unusable")
