"""Consumed POS master/default custody; synthetic documents and SQL only."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json
import pickle
from unittest.mock import Mock

import pytest
from pymysql.constants import FIELD_TYPE as FT

from zatca_erpgulf.zatca_erpgulf import pos_profile_source as source
from zatca_erpgulf.zatca_erpgulf import financial_source_sql as native
from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial
from zatca_erpgulf.zatca_erpgulf.source_metadata import POS_LIMIT_PROFILE, POS_DEFAULT_PROFILE
from zatca_erpgulf.zatca_erpgulf.calculation_pos_adjustments import (
    PosTailInputs, PosTailCalculation, DefaultMopRedistributionCalculation,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import scenario as financial_case, observed_metadata, NOW
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta, Definition, project


def declarations(*, kind="default", major=16, doctype="Sales Invoice", limit=Decimal("2.500000000")):
    case = financial_case(doctype, optional=False)
    case.kind, case.major = kind, major
    raw = case.raw_metas[doctype]
    raw.definitions["company"].values.update(fieldtype="Link", options="Company")
    raw.definitions["pos_profile"] = Definition("pos_profile", fieldtype="Link", options="POS Profile")
    case.records["header"][0]["pos_profile"] = "SYNTHETIC-POS"
    case.metas[doctype], case.observations[doctype] = project(raw), observed_metadata(raw)
    case.connection.signatures["header", "pos_profile"] = [FT.VAR_STRING, 140, 0, True]
    fields = source.LIMIT_FIELDS if kind == "limit" else ("company", "payments")
    master = AppliedMeta("POS Profile", fields)
    master.definitions["company"].values.update(fieldtype="Link", options="Company")
    if kind == "limit":
        master.definitions["write_off_limit"].values.update(fieldtype="Currency")
    else:
        master.definitions["payments"].values.update(fieldtype="Table", options="POS Payment Method")
    profile = POS_LIMIT_PROFILE if kind == "limit" else POS_DEFAULT_PROFILE
    case.raw_pos = {"POS Profile": master}
    if kind == "default":
        child = AppliedMeta("POS Payment Method", source.PAYMENT_FIELDS)
        child.definitions["mode_of_payment"].values.update(fieldtype="Link", options="Mode of Payment")
        for name in ("default", "allow_in_returns"):
            child.definitions[name].values.update(fieldtype="Check")
        case.raw_pos[child.name] = child
    case.pos_metadata = {name: observed_metadata(raw, profile=profile) for name, raw in case.raw_pos.items()}
    case.applied_pos = {name: row.applied for name, row in case.pos_metadata.items()}
    case.master_rows = [dict(name="SYNTHETIC-POS", modified=NOW, company="SYNTHETIC-CO", write_off_limit=limit)]
    case.payment_rows = [dict(name="PAY-1", parent="SYNTHETIC-POS", parenttype="POS Profile",
        parentfield="payments", idx=1, modified=NOW, mode_of_payment="Cash", default=1, allow_in_returns=0)]
    case.pos_hook = None
    return case


def scenario(monkeypatch, **options):
    case = declarations(**options)
    original = case.connection.cursor
    class PosCursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=()):
            case.connection.queries.append((sql, params))
            if case.connection.error: raise case.connection.error
            if case.pos_hook: case.pos_hook(sql, params)
            if "LIMIT 2 FOR UPDATE" in sql and "CASE WHEN" not in sql and "OCTET_LENGTH" not in sql:
                self.rows = tuple((row["name"],) for row in case.payment_rows
                                  if row["parent"] == params[0] and row["default"] == 1)[:2]
                return
            child = "FROM `tabPOS Payment Method`" in sql
            fields = source.PAYMENT_FIELDS if child else source.LIMIT_FIELDS if case.kind == "limit" else ("company",)
            ids = native.CHILD_IDS if child else native.ROOT_IDS
            full = "CASE WHEN" in sql
            records = case.payment_rows if child else case.master_rows
            if child:
                records = [r for r in records if (r["parent"], r["parenttype"], r["parentfield"])
                           == (params[0], "POS Profile", "payments")]
                records = sorted(records, key=lambda r: (r["idx"], r["name"].encode()))
            self.description = [(name, FT.VAR_STRING, None, None, 140, 0, True) for name in ids]
            for name in fields:
                code = FT.NEWDECIMAL if name == "write_off_limit" else FT.LONG if name in ("default", "allow_in_returns") else FT.VAR_STRING
                if full: self.description.append((name, code, None, None, 23, 9 if code == FT.NEWDECIMAL else 0, True))
                self.description.append(("length", FT.LONG, None, None, 20, 0, True))
            self.rows = []
            for record in records[:params[-1]]:
                values = [record.get(name) for name in ids]
                for name in fields:
                    value = record.get(name)
                    length = None if value is None else len(str(value).encode())
                    if full: values.append(value if length is None or length <= financial.MAX_TEXT_BYTES else None)
                    values.append(length)
                self.rows.append(tuple(values))
        def fetchall(self): return tuple(self.rows)
    def cursor():
        class Router:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def execute(self, sql, params=()):
                self.inner = PosCursor() if "FROM `tabPOS " in sql else original()
                self.inner.execute(sql, params)
            def fetchone(self): return self.inner.fetchone()
            def fetchall(self): return self.inner.fetchall()
            @property
            def description(self): return self.inner.description
        return Router()
    case.connection.cursor = cursor
    provider = Mock()
    provider.load_for_update.side_effect = lambda meta: {**case.observations, **case.pos_metadata}[meta.name]
    monkeypatch.setattr(native, "MariaDBMetadataSourceReader", Mock(return_value=provider))
    monkeypatch.setattr(source, "MariaDBMetadataSourceReader", Mock(return_value=provider))
    case.provider = provider
    case.financial = native.MariaDBInvoiceFinancialReader(case.connection).load_for_update(
        case.doctype, case.name, erp_major=case.major, applied_metadata=case.metas)
    case.reader = source.MariaDBPosProfileReader(case.connection)
    return case


def load(case):
    return case.reader.load_for_update(case.financial, kind=case.kind, applied_metadata=case.applied_pos)


def failure(call, code="pos_profile_read"):
    with pytest.raises(source.PosProfileSourceError) as caught: call()
    assert str(caught.value) == code and caught.value.__context__ is None


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("limit", [None, Decimal("0.000000000"), Decimal("-2.500000000"), Decimal("2.500000000")])
def test_limit_preserves_native_value_and_reads_no_payment_rows(monkeypatch, major, limit):
    case = scenario(monkeypatch, kind="limit", major=major, limit=limit)
    case.payment_rows *= 2  # Unconsumed ambiguity must not affect this branch.
    observed = load(case)
    raw = observed.limit_observation()
    assert financial._scalar(raw.value) == financial._scalar(limit)
    tail = PosTailCalculation(PosTailInputs("Sales Invoice", 1, 0, 1, "SYNTHETIC-POS", None, 2.5), raw)
    assert tail.assigns_automatic is bool(limit is not None and limit > 0)
    assert not any("tabPOS Payment Method" in sql for sql, _ in case.connection.queries)
    case.reader.require_unchanged(observed)
    for method in (case.connection.commit, case.connection.rollback, case.connection.close): method.assert_not_called()


@pytest.mark.parametrize("mode", [None, "", "Cash"])
@pytest.mark.parametrize("default", [None, 0, 1])
def test_default_selection_retains_blank_mode_and_return_flag_without_filtering(monkeypatch, mode, default):
    case = scenario(monkeypatch)
    case.payment_rows[0].update(mode_of_payment=mode, default=default)
    observed = load(case)
    lookup = observed.default_observation()
    assert lookup.queried and lookup.found is (default == 1)
    assert lookup.mode_of_payment == (mode if default == 1 else None)
    plan = DefaultMopRedistributionCalculation("SAR", "SAR", "SYNTHETIC-POS", 5.0, (), lookup)
    assert plan.replaces is (default == 1)
    case.reader.require_unchanged(observed)
    probes = [(sql, params) for sql, params in case.connection.queries if "LIMIT 2 FOR UPDATE" in sql and "OCTET_LENGTH" not in sql]
    assert probes and all(params == ("SYNTHETIC-POS",) for _, params in probes)
    assert all("parenttype" not in sql and "allow_in_returns" not in sql for sql, _ in probes)


@pytest.mark.parametrize("fault", ["master_missing", "master_identity", "company", "ambiguous", "orphan_type", "orphan_field",
    "check", "row_bound", "oversized", "blank_link", "wrong_link_type", "wrong_link_target", "metadata_target", "metadata_profile"])
def test_unverified_sources_never_become_zero_limits_or_arbitrary_defaults(monkeypatch, fault):
    case = scenario(monkeypatch)
    if fault == "master_missing": case.master_rows.clear()
    elif fault == "master_identity": case.master_rows[0]["name"] = "OTHER"
    elif fault == "company": case.master_rows[0]["company"] = "OTHER"
    elif fault == "ambiguous": case.payment_rows.append({**case.payment_rows[0], "name": "PAY-2", "idx": 2})
    elif fault == "orphan_type": case.payment_rows[0]["parenttype"] = "OTHER"
    elif fault == "orphan_field": case.payment_rows[0]["parentfield"] = "OTHER"
    elif fault == "check": case.payment_rows[0]["allow_in_returns"] = 2
    elif fault == "row_bound": case.payment_rows = [{**case.payment_rows[0], "name": f"PAY-{i}", "idx": i + 1, "default": 0} for i in range(129)]
    elif fault == "oversized": case.payment_rows[0]["mode_of_payment"] = "PRIVATE" * 10000
    elif fault == "blank_link": case.records["header"][0]["pos_profile"] = ""
    elif fault in ("wrong_link_type", "wrong_link_target"):
        raw = case.raw_metas[case.doctype]
        raw.definitions["pos_profile"].values["fieldtype" if fault == "wrong_link_type" else "options"] = "Data" if fault == "wrong_link_type" else "Company"
        case.metas[case.doctype], case.observations[case.doctype] = project(raw), observed_metadata(raw)
        case.financial = native.MariaDBInvoiceFinancialReader(case.connection).load_for_update(case.doctype,
            case.name, erp_major=case.major, applied_metadata=case.metas)
    else:
        raw = case.raw_pos["POS Profile"]
        if fault == "metadata_target": raw.definitions["payments"].values["options"] = "OTHER"
        case.applied_pos["POS Profile"] = observed_metadata(raw,
            profile=POS_DEFAULT_PROFILE if fault == "metadata_target" else None).applied
    failure(lambda: load(case))
    failure(lambda: load(case), "pos_profile_transaction_unusable")
    for method in (case.connection.commit, case.connection.rollback, case.connection.close): method.assert_not_called()


@pytest.mark.parametrize("changed", ["mode", "default", "returns", "revision", "financial", "metadata"])
def test_same_handle_changes_poison_recheck_without_caller_cleanup(monkeypatch, changed):
    case = scenario(monkeypatch)
    observed = load(case)
    if changed == "mode": case.payment_rows[0]["mode_of_payment"] = "Bank"
    elif changed == "default": case.payment_rows[0]["default"] = 0
    elif changed == "returns": case.payment_rows[0]["allow_in_returns"] = 1
    elif changed == "revision": case.master_rows[0]["modified"] += timedelta(seconds=1)
    elif changed == "financial": case.records["items"][0]["amount"] = Decimal("2.000000000")
    else: case.provider.require_unchanged.side_effect = ValueError("PRIVATE")
    failure(lambda: case.reader.require_unchanged(observed), "pos_profile_changed")
    failure(lambda: load(case), "pos_profile_transaction_unusable")


@pytest.mark.parametrize("fault", ["financial", "metadata", "kind", "company", "defaults", "row", "types", "derived", "extra"])
def test_reconstruction_rejects_rebinding_and_protects_private_values(monkeypatch, fault):
    case = scenario(monkeypatch)
    observed = load(case)
    body = json.loads(observed._payload)
    if fault == "derived":
        object.__setattr__(observed, "profile_name", "OTHER")
        failure(observed.default_observation, "pos_profile_rows")
        return
    if fault == "financial": body["financial_sha256"] = "f" * 64
    elif fault == "metadata": body["metadata"][0][1] = "f" * 64
    elif fault == "kind": body["kind"] = "limit"
    elif fault == "company": body["record"]["fields"][0][1] = ["str", "OTHER"]
    elif fault == "defaults": body["default_names"] = []
    elif fault == "row": body["payments"][0]["parenttype"] = "OTHER"
    elif fault == "types": body["types"]["payments"][0][1][0] = FT.LONG
    else: body["extra"] = "PRIVATE"
    failure(lambda: replace(observed, _payload=financial._canonical(body)), "pos_profile_rows")
    assert "Cash" not in repr(observed) and "SYNTHETIC" not in repr(observed)
    with pytest.raises(TypeError): pickle.dumps(observed)
    with pytest.raises(TypeError): pickle.dumps(case.reader)


def test_empty_table_and_cross_kind_calls_are_explicit(monkeypatch):
    case = scenario(monkeypatch)
    case.payment_rows.clear()
    observed = load(case)
    assert not observed.default_observation().found
    failure(observed.limit_observation, "pos_profile_lookup_kind")
    limit = load(scenario(monkeypatch, kind="limit"))
    failure(limit.default_observation, "pos_profile_lookup_kind")


@pytest.mark.parametrize("error_type", [ValueError, KeyboardInterrupt, SystemExit])
def test_faults_and_interrupts_poison_reader_without_leaking_or_cleaning_parent(monkeypatch, error_type):
    case = scenario(monkeypatch)
    case.connection.error = error_type("PRIVATE-DRIVER")
    if error_type is ValueError:
        failure(lambda: load(case))
    else:
        with pytest.raises(error_type): load(case)
    case.connection.error = None
    failure(lambda: load(case), "pos_profile_transaction_unusable")
    for method in (case.connection.commit, case.connection.rollback, case.connection.close): method.assert_not_called()


def test_borrowed_autocommit_session_is_refused_before_master_query(monkeypatch):
    case = scenario(monkeypatch)
    case.connection.queries.clear()
    case.connection.autocommit = (1,)
    failure(lambda: load(case))
    assert not any("FROM `tabPOS " in sql for sql, _ in case.connection.queries)
