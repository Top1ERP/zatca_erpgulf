"""Invoice-currency native config and precision-free flt projection only."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json
import math
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pymysql.constants import FIELD_TYPE as FT
from frappe.utils import data as framework_data

from zatca_erpgulf.zatca_erpgulf import currency_fraction_source as source
from zatca_erpgulf.zatca_erpgulf import financial_source_sql as native
from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial
from zatca_erpgulf.zatca_erpgulf.source_metadata import CURRENCY_FRACTION_PROFILE
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import scenario as financial_case, observed_metadata, NOW
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta, project
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16


def declarations(*, doctype="Sales Invoice", major=16, value=Decimal("0.050000000")):
    case = financial_case(doctype, optional=False)
    root = case.raw_metas[doctype]
    root.definitions["currency"].values.update(fieldtype="Link", options="Currency")
    case.metas[doctype], case.observations[doctype] = project(root), observed_metadata(root)
    case.major = major
    case.raw_fraction = AppliedMeta("Currency", (source.FIELD,))
    case.raw_fraction.definitions[source.FIELD].values.update(fieldtype="Currency", non_negative=1)
    case.fraction = observed_metadata(case.raw_fraction, profile=CURRENCY_FRACTION_PROFILE)
    case.currency_rows = [dict(name="SAR", modified=NOW, value=value)]
    scale = -value.as_tuple().exponent if type(value) is Decimal else 9
    case.fraction_signature = [FT.DOUBLE, 22, None, True] if type(value) is float else [FT.NEWDECIMAL, 66, scale, True]
    case.fraction_hook = None
    return case


def scenario(monkeypatch, **options):
    case = declarations(**options)
    original = case.connection.cursor
    class CurrencyCursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=()):
            case.connection.queries.append((sql, params))
            if case.connection.error: raise case.connection.error
            full = "CASE WHEN" in sql
            if case.fraction_hook: case.fraction_hook(full)
            self.description = [("name", FT.VAR_STRING, None, None, 140, 0, True),
                ("modified", FT.DATETIME, None, None, 26, 6, True)]
            if full:
                code, precision, scale, nullable = case.fraction_signature
                self.description.append((source.FIELD, code, None, None, precision, scale, nullable))
            self.description.append(("length", FT.LONG, None, None, 20, 0, True))
            self.rows = []
            for record in case.currency_rows:
                value = record["value"]
                size = None if value is None else len(str(value).encode())
                bounded = value if size is None or size <= financial.MAX_TEXT_BYTES else None
                row = (record["name"], record["modified"], bounded, size) if full else (record["name"], record["modified"], size)
                self.rows.append(row)
            self.rows = tuple(self.rows)
        def fetchall(self): return self.rows
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=()):
            self.current = CurrencyCursor() if "FROM `tabCurrency`" in sql else original()
            self.current.execute(sql, params)
        def fetchone(self): return self.current.fetchone()
        def fetchall(self): return self.current.fetchall()
        @property
        def description(self): return self.current.description
    case.connection.cursor = Mock(side_effect=Cursor)
    case.metadata_reader = Mock()
    case.metadata_reader.load_for_update.side_effect = lambda meta: case.fraction if meta.profile == CURRENCY_FRACTION_PROFILE else case.observations[meta.name]
    for module in (native, source):
        monkeypatch.setattr(module, "MariaDBMetadataSourceReader", Mock(return_value=case.metadata_reader))
    case.financial = native.MariaDBInvoiceFinancialReader(case.connection).load_for_update(case.doctype,
        case.name, erp_major=case.major, applied_metadata=case.metas)
    case.reader = source.MariaDBCurrencyFractionReader(case.connection)
    return case


def load(case):
    return case.reader.load_for_update(case.financial, applied_metadata=case.fraction.applied)


def failure(call, code="currency_fraction_read"):
    with pytest.raises(source.CurrencyFractionSourceError) as caught: call()
    assert str(caught.value) == code and caught.value.__context__ is None


VALUES = (None, Decimal("0.000000000"), Decimal("0.050000000"), Decimal("1"),
    Decimal("9" * 64), 0.0, -0.0, 0.05, 5e-324)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("value", VALUES)
def test_exact_invoice_currency_config_raw_and_effective_views(monkeypatch, doctype, major, value):
    case = scenario(monkeypatch, doctype=doctype, major=major, value=value)
    before = case.financial._payload, case.financial.financial._payload, case.financial.sha256
    result = load(case)
    assert result.currency == "SAR" and result.financial is not case.financial
    expected = 0.0 if value is None else float(value)
    assert result.effective_fraction.hex() == expected.hex()
    assert result.branch == ("CURRENCY_FRACTION_THEN_FIELD_PRECISION" if expected else "WHOLE_UNIT_THEN_FIELD_PRECISION")
    assert json.loads(result._payload)["record"]["value"] == financial._scalar(value)
    result.require_effective_cache_match(expected)
    case.reader.require_unchanged(result)
    assert before == (case.financial._payload, case.financial.financial._payload, case.financial.sha256)
    for name in ("commit", "rollback", "close"): getattr(case.connection, name).assert_not_called()
    selected = [params for sql, params in case.connection.queries if "FROM `tabCurrency`" in sql]
    assert selected and all(params == ("SAR", 2) for params in selected)


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("value", VALUES)
def test_configuration_normalization_matches_actual15_and_pinned16_flt(monkeypatch, upstream16, major, value):
    case = scenario(monkeypatch, major=major, value=value)
    result = load(case)
    runtime = SimpleNamespace(get_system_settings=Mock(side_effect=AssertionError("No precision/method dependency")),
        InvalidRoundingMethod=RuntimeError)
    namespace = vars(framework_data) if major == 15 else upstream16
    monkeypatch.setitem(namespace, "frappe", runtime)
    expected = namespace["flt"](value)
    assert type(expected) is float
    result.require_effective_cache_match(expected)
    runtime.get_system_settings.assert_not_called()


@pytest.mark.parametrize("supplied", [None, False, True, 0, 1, Decimal("0.05"), "0.05", math.inf, math.nan, 0.01])
def test_effective_cache_requires_finite_exact_float_not_a_raw_lookup(monkeypatch, supplied):
    result = load(scenario(monkeypatch))
    failure(lambda: result.require_effective_cache_match(supplied), "currency_fraction_cache_mismatch")


def test_signed_zero_is_not_hidden_by_numeric_equality_or_derived_tampering(monkeypatch):
    result = load(scenario(monkeypatch, value=-0.0))
    failure(lambda: result.require_effective_cache_match(0.0), "currency_fraction_cache_mismatch")
    object.__setattr__(result, "effective_fraction", 0.0)
    failure(lambda: result.require_effective_cache_match(0.0), "currency_fraction_cache_mismatch")


@pytest.mark.parametrize("fault", ["missing", "duplicate", "identity", "negative", "text", "schema_type", "precision",
    "metadata_absent", "metadata_type", "metadata_profile", "metadata_currency_link"])
def test_missing_or_conflicting_config_is_not_replaced_by_a_default(monkeypatch, fault):
    case = scenario(monkeypatch)
    if fault == "missing": case.currency_rows.clear()
    elif fault == "duplicate": case.currency_rows *= 2
    elif fault == "identity": case.currency_rows[0]["name"] = "USD"
    elif fault == "negative": case.currency_rows[0]["value"] = Decimal("-0.050000000")
    elif fault == "text": case.currency_rows[0]["value"] = "0.05"
    elif fault == "schema_type": case.fraction_signature[0] = FT.LONG
    elif fault == "precision": case.currency_rows[0]["value"] = Decimal("0.05")
    elif fault in ("metadata_absent", "metadata_type", "metadata_profile"):
        if fault == "metadata_absent": case.raw_fraction.definitions.clear()
        elif fault == "metadata_type": case.raw_fraction.definitions[source.FIELD].values["fieldtype"] = "Float"
        case.fraction = observed_metadata(case.raw_fraction, profile=None if fault == "metadata_profile" else CURRENCY_FRACTION_PROFILE)
    else:
        # The immutable financial snapshot cannot be rebound by a new declaration.
        root = case.raw_metas[case.doctype]
        root.definitions["currency"].values["options"] = "Company"
        case.metas[case.doctype] = project(root)
        case.observations[case.doctype] = observed_metadata(root)
    failure(lambda: load(case))
    failure(lambda: load(case), "currency_fraction_transaction_unusable")


@pytest.mark.parametrize("changed", ["value", "null_to_zero", "revision", "invoice_currency", "child", "metadata"])
def test_rechecks_detect_same_route_and_financial_changes(monkeypatch, changed):
    case = scenario(monkeypatch, value=None)
    observed = load(case)
    if changed == "value": case.currency_rows[0]["value"] = Decimal("0.010000000")
    elif changed == "null_to_zero": case.currency_rows[0]["value"] = Decimal("0.000000000")
    elif changed == "revision": case.currency_rows[0]["modified"] += timedelta(seconds=1)
    elif changed == "invoice_currency": case.records["header"][0]["currency"] = "USD"
    elif changed == "child": case.records["items"][0]["amount"] = Decimal("2.000000000")
    else: case.metadata_reader.require_unchanged.side_effect = ValueError("PRIVATE-META")
    failure(lambda: case.reader.require_unchanged(observed), "currency_fraction_changed")


@pytest.mark.parametrize("fault", ["profile", "metadata", "financial", "revision", "currency", "value", "sql_type", "extra", "derived"])
def test_private_reconstruction_and_comparison_revalidate_bindings(monkeypatch, fault):
    result = load(scenario(monkeypatch))
    body = json.loads(result._payload)
    if fault == "derived":
        object.__setattr__(result, "currency", "USD")
        failure(lambda: result.require_effective_cache_match(0.05), "currency_fraction_cache_mismatch")
        return
    if fault == "profile": body["profile"] = "OTHER"
    elif fault == "metadata": body["metadata_sha256"] = "f" * 64
    elif fault == "financial": body["financial_sha256"] = "f" * 64
    elif fault == "revision": body["record"]["modified"] = ["null"]
    elif fault == "currency": body["record"]["name"] = "USD"
    elif fault == "value": body["record"]["value"] = ["str", "0.05"]
    elif fault == "sql_type": body["record"]["sql_type"][0] = FT.LONG
    else: body["extra"] = "PRIVATE"
    failure(lambda: replace(result, _payload=financial._canonical(body)), "currency_fraction_rows")


@pytest.mark.parametrize("interrupt", [False, True])
def test_driver_failure_poisoning_does_not_clean_borrowed_work(monkeypatch, interrupt):
    case = scenario(monkeypatch)
    case.connection.error = KeyboardInterrupt() if interrupt else RuntimeError("PRIVATE-DRIVER")
    if interrupt:
        with pytest.raises(KeyboardInterrupt): load(case)
    else: failure(lambda: load(case))
    failure(lambda: load(case), "currency_fraction_transaction_unusable")
    for name in ("commit", "rollback", "close"): getattr(case.connection, name).assert_not_called()


def test_protected_results_and_reader_refuse_serialization(monkeypatch):
    case = scenario(monkeypatch)
    for value in (load(case), case.reader):
        assert "SAR" not in repr(value)
        with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(value)
