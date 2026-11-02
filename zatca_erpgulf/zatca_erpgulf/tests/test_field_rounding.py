"""Versioned numeric kernel and real document-rounding probes, entirely offline.

Use installed15 and pinned MIT16 method bodies. Only documents, metadata and
setting/precision getters are synthetic; never initialize a site or run hooks.
"""

import __future__
import ast
from decimal import MAX_PREC, ROUND_HALF_UP, Decimal, getcontext, localcontext
import inspect
import json
import math
from pathlib import Path
import textwrap
from types import FunctionType, SimpleNamespace
from unittest.mock import Mock

from frappe.model import document as model_document
from frappe.model.document import Document
from frappe.utils import data as framework_data
import pytest

from zatca_erpgulf.zatca_erpgulf import field_rounding as core
from zatca_erpgulf.zatca_erpgulf.calculation_precision import FieldPrecisionResolution
from zatca_erpgulf.zatca_erpgulf.calculation_rounding import METHODS, LEGACY_METHOD
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16, declarations


class UnknownMethod(Exception):
    pass


@pytest.fixture(params=(15, 16))
def major(request):
    return request.param


def framework(major, upstream16, monkeypatch, setting=LEGACY_METHOD):
    events = []
    def setting_getter(key):
        events.append(("setting", key))
        return setting
    def fail(*args, **kwargs):
        raise UnknownMethod
    runtime = SimpleNamespace(get_system_settings=Mock(side_effect=setting_getter),
        throw=fail, InvalidRoundingMethod=UnknownMethod, _=lambda text: text)
    if major == 15:
        monkeypatch.setattr(framework_data, "frappe", runtime)
        monkeypatch.setattr(model_document, "frappe", runtime)
        return SimpleNamespace(flt=framework_data.flt, method=Document.round_floats_in,
            runtime=runtime, events=events)
    namespace = dict(upstream16)
    namespace.update(frappe=runtime, math=math, Decimal=Decimal, MAX_PREC=MAX_PREC,
        ROUND_HALF_UP=ROUND_HALF_UP, localcontext=localcontext)
    # Rebind every helper so no module-scoped oracle globals leak across probes.
    for name, fn in tuple(namespace.items()):
        if type(fn) is FunctionType and fn.__globals__ is upstream16:
            namespace[name] = FunctionType(fn.__code__, namespace, fn.__name__, fn.__defaults__, fn.__closure__)
    record = json.loads(Path(__file__).with_name("frappe16_precision_oracle.json").read_text())
    excerpt = record["files"]["model/document.py"]["field_rounding"]["excerpts"]["round_floats_in"]
    exec(compile(excerpt, "pinned-frappe16/round_floats_in", "exec",
        flags=__future__.annotations.compiler_flag), namespace)
    return SimpleNamespace(flt=namespace["flt"], method=namespace["round_floats_in"],
        runtime=runtime, events=events)


def exact(actual, expected):
    assert type(actual) is type(expected)
    assert (actual.hex() if type(actual) is float else actual) == (expected.hex() if type(expected) is float else expected)


@pytest.mark.parametrize("method", sorted(METHODS))
@pytest.mark.parametrize("precision", [None, 0, 1, 2, 9, 64])
@pytest.mark.parametrize("value", [None, 0, -0.0, Decimal("-0.000"), Decimal("8.700000000"),
    2.5, -2.5, 1.25, -1.25, 2.675, -2.675, math.nextafter(1.25, 0),
    math.nextafter(1.25, math.inf), 9007199254740991.0, -9007199254740991.0,
    Decimal("9" * 64), 1e64, 1e-64, math.nextafter(0.0, 1.0), -1e64, Decimal("1e64")])
def test_real_numeric_helpers_match_bits_and_type(major, upstream16, monkeypatch, method, precision, value):
    probe = framework(major, upstream16, monkeypatch)
    actual = core.round_field_value(value, precision=precision, method=method, erp_major=major)
    exact(actual, probe.flt(value, precision, rounding_method=method))
    probe.runtime.get_system_settings.assert_not_called()


@pytest.mark.parametrize("precision", [0, 2, 64])
def test_commercial16_ignores_and_restores_ambient_decimal_context(upstream16, monkeypatch, precision):
    probe = framework(16, upstream16, monkeypatch)
    with localcontext() as ctx:
        ctx.prec = 3
        ctx.rounding = "ROUND_DOWN"
        before = ctx.copy()
        result = core.round_field_value(9007199254740991.0, precision=precision,
            method="Commercial Rounding", erp_major=16)
        exact(result, probe.flt(9007199254740991.0, precision, "Commercial Rounding"))
        assert getcontext().prec == before.prec and getcontext().rounding == before.rounding
        assert getcontext().flags == before.flags


@pytest.mark.parametrize("overrides", [dict(value=True), dict(value="8.7"), dict(value=object()),
    dict(value=10**64), dict(value=Decimal("9" * 65)), dict(value=Decimal("1e-65")),
    dict(value=Decimal("NaN")), dict(value=float("inf")), dict(value=math.nextafter(1e64, math.inf)),
    dict(precision=True), dict(precision=-1), dict(precision=65), dict(precision=2.0),
    dict(method=None), dict(method=""), dict(method="PRIVATE-UNKNOWN"), dict(method=[]),
    dict(erp_major=True), dict(erp_major="16"), dict(erp_major=17)])
def test_invalid_supplied_domain_fails_without_values_or_exception_chain(overrides):
    supplied = dict(value=Decimal("8.7"), precision=2, method=LEGACY_METHOD, erp_major=16)
    supplied.update(overrides)
    with pytest.raises(core.FieldRoundingError) as caught:
        core.round_field_value(**supplied)
    assert str(caught.value) == "calculation_field_rounding"
    assert caught.value.__context__ is None


class SyntheticDocument:
    def __init__(self, probe, values, definitions, parentfield=None):
        self.values = dict(values, parentfield=parentfield)
        self.probe = probe
        def fields(*args):
            assert args == ("fields", {"fieldtype": ["in", ["Currency", "Float", "Percent"]]})
            return [SimpleNamespace(fieldname=name) for name, kind in definitions if kind in ("Currency", "Float", "Percent")]
        self.meta = SimpleNamespace(get=Mock(side_effect=fields))
        self.precision = Mock(side_effect=AssertionError("Child precision must not be used"))

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.probe.events.append(("set", key))
        self.values[key] = value


def parent(probe, precision=1):
    def resolve(name, parentfield):
        probe.events.append(("precision", name, parentfield))
        return precision
    return SimpleNamespace(precision=Mock(side_effect=resolve))


@pytest.mark.parametrize("parentfield", [None, "items", "taxes", "payments", "advances", "custom_zatca_advance_deduction_details"])
@pytest.mark.parametrize("method", sorted(METHODS))
def test_real_document_stage_uses_parent_precision_and_converts_null(major, upstream16, monkeypatch, parentfield, method):
    probe = framework(major, upstream16, monkeypatch, method)
    values = dict(amount=Decimal("1.25"), rate=None, percent=Decimal("-1.25"), rating=Decimal("1.25"))
    definitions = (("amount", "Currency"), ("rate", "Float"), ("percent", "Percent"), ("rating", "Rating"))
    doc = SyntheticDocument(probe, values, definitions, parentfield)
    owner = parent(probe)
    probe.method(owner, doc)
    assert probe.events == [("setting", "rounding_method")] + [event
        for name in ("amount", "rate", "percent") for event in (("precision", name, parentfield), ("set", name))]
    for name in ("amount", "rate", "percent"):
        exact(doc.get(name), core.round_field_value(values[name], precision=1, method=method, erp_major=major))
    assert doc.get("rate") == 0.0 and type(doc.get("rate")) is float
    assert doc.get("rating") is values["rating"]
    doc.precision.assert_not_called()


@pytest.mark.parametrize("selection", [None, [], ["rating", "missing"]])
def test_empty_explicit_selection_means_default_numeric_fields(major, upstream16, monkeypatch, selection):
    probe = framework(major, upstream16, monkeypatch)
    doc = SyntheticDocument(probe, dict(amount=Decimal("1.25"), rating=Decimal("1.25")),
        (("amount", "Currency"), ("rating", "Rating")))
    probe.method(parent(probe), doc, selection)
    names = [event[1] for event in probe.events if event[0] == "set"]
    assert names == (["amount"] if not selection else selection)
    assert doc.meta.get.call_count == (1 if not selection else 0)
    if selection:
        assert doc.get("missing") == 0.0


def test_no_numeric_fields_still_reads_system_method(major, upstream16, monkeypatch):
    probe = framework(major, upstream16, monkeypatch)
    doc = SyntheticDocument(probe, {}, ())
    owner = parent(probe)
    probe.method(owner, doc)
    assert probe.events == [("setting", "rounding_method")]
    owner.precision.assert_not_called()


def test_upfront_setting_failure_precedes_all_precision_or_mutation(major, upstream16, monkeypatch):
    probe = framework(major, upstream16, monkeypatch)
    probe.runtime.get_system_settings.side_effect = RuntimeError("synthetic unavailable setting")
    doc = SyntheticDocument(probe, dict(amount=Decimal("1.25")), (("amount", "Currency"),))
    owner = parent(probe)
    with pytest.raises(RuntimeError, match="synthetic unavailable setting"):
        probe.method(owner, doc)
    assert type(doc.get("amount")) is Decimal
    owner.precision.assert_not_called()
    assert not probe.events


def test_resolved_zero_default_preserves_version_difference(major, upstream16, monkeypatch):
    metadata, defaults = declarations(values={"currency_precision": "0", "number_format": "#.########"})
    resolution = FieldPrecisionResolution(metadata, "grand_total", defaults, major)
    value = Decimal("8.7")
    result = core.round_field_value(value, precision=resolution.precision,
        method="Commercial Rounding", erp_major=resolution.erp_major)
    probe = framework(major, upstream16, monkeypatch)
    exact(result, probe.flt(value, resolution.precision, "Commercial Rounding"))
    assert result == (8.7 if major == 15 else 9.0)


@pytest.mark.parametrize("skipped", [("amount",), ("amount", "rate")])
def test_v16_skip_leaves_original_values_but_keeps_upfront_lookup(upstream16, monkeypatch, skipped):
    probe = framework(16, upstream16, monkeypatch)
    doc = SyntheticDocument(probe, dict(amount=Decimal("1.25"), rate=None), (("amount", "Currency"), ("rate", "Float")))
    probe.method(parent(probe), doc, do_not_round_fields=skipped)
    assert probe.events == [("setting", "rounding_method")] + ([] if len(skipped) == 2 else [("precision", "rate", None), ("set", "rate")])
    assert type(doc.get("amount")) is Decimal
    if len(skipped) == 2:
        assert doc.get("rate") is None
    else:
        assert type(doc.get("rate")) is float


def test_v15_has_no_skip_keyword(upstream16, monkeypatch):
    probe = framework(15, upstream16, monkeypatch)
    with pytest.raises(TypeError):
        probe.method(parent(probe), object(), do_not_round_fields=("amount",))
    assert not probe.events


def test_unknown_method_may_be_unexecuted_for_null_but_explicit_core_refuses_it(major, upstream16, monkeypatch):
    probe = framework(major, upstream16, monkeypatch, "UNKNOWN")
    doc = SyntheticDocument(probe, dict(amount=None), (("amount", "Currency"),))
    probe.method(parent(probe), doc)
    assert doc.get("amount") == 0.0
    with pytest.raises(core.FieldRoundingError):
        core.round_field_value(None, precision=1, method="UNKNOWN", erp_major=major)
    with pytest.raises(UnknownMethod):
        probe.flt(1.25, 1, "UNKNOWN")


def test_shared_legacy_kernel_has_same_body_in_both_upstreams():
    actual = ast.parse(textwrap.dedent(inspect.getsource(framework_data._bankers_rounding_legacy)))
    record = json.loads(Path(__file__).with_name("frappe16_precision_oracle.json").read_text())
    pinned = ast.parse(record["files"]["utils/data.py"]["excerpts"]["_bankers_rounding_legacy"])
    assert ast.dump(actual) == ast.dump(pinned)
