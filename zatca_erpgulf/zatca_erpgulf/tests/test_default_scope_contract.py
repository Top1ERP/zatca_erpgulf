"""Characterize installed Frappe defaults APIs with synthetic sources only.

These are API behavior tests, not a committed defaults reader or a claim about
another installed Frappe version. No site, SQL, Redis or real default is read.
"""

from types import SimpleNamespace

import frappe
import frappe.defaults as defaults
import pytest
from frappe.database.database import Database


USER = "synthetic-defaults@example.invalid"
KEY = "float_precision"


@pytest.mark.parametrize("parent", ["__default", "__global", USER])
@pytest.mark.parametrize("value,expected", [
    (None, None), ("0", "0"), ("", ""), (0, 0),
    (["2", "3"], "2"), (["0", "2"], "0"),
    (["", "2"], ["", "2"]), ([0, "2"], [0, "2"]),
    (("2", "3"), ("2", "3")),
])
def test_database_default_uses_one_explicit_scope_and_its_own_list_rule(parent, value, expected):
    calls = []

    def read(key, scope):
        calls.append((key, scope))
        return value

    database = SimpleNamespace(get_defaults=read)
    assert Database.get_default(database, KEY, parent) == expected
    assert calls == [(KEY, parent)]


def test_database_default_and_global_have_different_implicit_parents():
    calls = []

    def read(key, parent):
        calls.append((key, parent))
        return parent

    database = SimpleNamespace(get_defaults=read)
    database.get_default = lambda key, parent: Database.get_default(database, key, parent)
    assert Database.get_default(database, KEY) == "__default"
    assert Database.get_global(database, KEY) == "__global"
    assert Database.get_global(database, KEY, USER) == USER
    assert calls == [(KEY, "__default"), (KEY, "__global"), (KEY, USER)]


@pytest.mark.parametrize("key", [KEY, "Float Precision", None])
def test_database_defaults_scrubs_only_when_exact_key_is_missing(monkeypatch, key):
    calls = []
    source = {KEY: "2", "Float Precision": "3"}

    def read(parent="__default"):
        calls.append(parent)
        return source

    monkeypatch.setattr(defaults, "get_defaults_for", read)
    assert Database.get_defaults(key, USER) == (source if key is None else source[key])
    source.pop("Float Precision")
    if key == "Float Precision":
        assert Database.get_defaults(key, USER) == "2"
    assert set(calls) == {USER}


@pytest.mark.parametrize("user_value", [None, "", "0", "2", 0, False, ["2", "3"]])
def test_merged_defaults_honor_user_presence_even_for_false_values(monkeypatch, user_value):
    calls = []
    common = {KEY: "3", "currency_precision": "2"}
    personal = {KEY: user_value}

    def read(parent="__default"):
        calls.append(parent)
        return {"__default": common, USER: personal}[parent]

    monkeypatch.setattr(defaults, "get_defaults_for", read)
    result = defaults.get_defaults(USER)
    assert result == {KEY: user_value, "currency_precision": "2", "user": USER, "owner": USER}
    assert calls == ["__default", USER]
    assert common == {KEY: "3", "currency_precision": "2"}
    assert personal == {KEY: user_value}


@pytest.mark.parametrize("denied", [False, True])
@pytest.mark.parametrize("value,expected", [("0", "0"), (["2", "3"], "2"), (("2", "3"), "2")])
def test_named_global_default_uses_merged_user_scope_and_permission_filter(monkeypatch, denied, value, expected):
    calls, permission_checks = [], []

    def read(parent="__default"):
        calls.append(parent)
        return {KEY: "3"} if parent == "__default" else {KEY: value}

    def permission(key, selected):
        permission_checks.append((key, selected))
        return denied

    monkeypatch.setattr(frappe, "session", SimpleNamespace(user=USER))
    monkeypatch.setattr(defaults, "get_defaults_for", read)
    monkeypatch.setattr(defaults, "not_in_user_permission", permission)
    assert defaults.get_global_default(KEY) == (None if denied else expected)
    assert calls == ["__default", USER]
    assert permission_checks == [(KEY, expected)]


@pytest.mark.parametrize("parent", ["__default", "__global", USER])
@pytest.mark.parametrize("cached", [{}, {KEY: "0"}, {KEY: ["2", "3"]}])
def test_cached_defaults_are_returned_without_proving_committed_rows(monkeypatch, parent, cached):
    calls = []

    def cached_value(bucket, scope):
        calls.append((bucket, scope))
        return cached

    class NoQueries:
        def __getattr__(self, name):
            raise AssertionError("A cache hit must not query or repair anything")

    monkeypatch.setattr(frappe, "cache", SimpleNamespace(hget=cached_value))
    monkeypatch.setattr(frappe, "qb", NoQueries())
    assert defaults.get_defaults_for(parent) is cached
    assert calls == [("defaults", parent)]
