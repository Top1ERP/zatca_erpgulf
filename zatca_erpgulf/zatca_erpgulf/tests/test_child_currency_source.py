"""Selected child links/columns bound to native financial evidence; synthetic SQL."""

from dataclasses import replace
from datetime import timedelta
import json
import pickle
import re
from types import SimpleNamespace
from unittest.mock import Mock

from pymysql.constants import FIELD_TYPE as FT
import pytest

from zatca_erpgulf.zatca_erpgulf import child_currency_source as source
from zatca_erpgulf.zatca_erpgulf import financial_source_sql as native
from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial
from zatca_erpgulf.zatca_erpgulf.source_metadata import CHILD_CURRENCY_PROFILE, CHILD_CURRENCY_FIELDS, SOURCE_FIELDS
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import scenario as financial_case, observed_metadata, NOW
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta, project


def scenario(monkeypatch, *, doctype="Sales Invoice", present=("currency", "company"), major=16,
        parentfield="items", empty=False, options="currency"):
    case = financial_case(doctype)
    case.major = major
    case.parentfield = parentfield
    dt = financial._child_type(doctype, parentfield)
    monetary = next(name for name, definition in case.raw_metas[dt].definitions.items() if definition.get("fieldtype") == "Currency")
    case.money_field = monetary
    case.raw_metas[dt].definitions[monetary].values["options"] = options
    case.metas[dt] = project(case.raw_metas[dt])
    case.observations[dt] = observed_metadata(case.raw_metas[dt])
    case.raw_own = AppliedMeta(dt, present)
    for name in present:
        case.raw_own.definitions[name].values.update(fieldtype="Link", options="Currency" if name == "currency" else "Company")
    for name in set(source.FIELDS) & set(SOURCE_FIELDS[dt]):
        if name in present:
            case.raw_metas[dt].definitions[name] = case.raw_own.definitions[name]
        else:
            case.raw_metas[dt].definitions.pop(name, None)
    case.metas[dt] = project(case.raw_metas[dt])
    case.observations[dt] = observed_metadata(case.raw_metas[dt])
    case.own = observed_metadata(case.raw_own, profile=CHILD_CURRENCY_PROFILE)
    db = case.connection
    db.columns = set(present)
    if not case.records[parentfield]:
        case.records[parentfield] = [dict(name=parentfield + "-1", parent=case.name, parenttype=doctype,
            parentfield=parentfield, idx=1, modified=NOW)]
    case.records[parentfield][0].update({name: "USD" if name == "currency" else "SYNTHETIC-CHILD-CO" for name in present})
    if empty: case.records[parentfield].clear()
    db.own_values = 0
    db.event = None

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, args=()):
            db.queries.append((sql, args))
            if db.error: raise db.error
            if sql == "SELECT @@session.autocommit": return
            if "information_schema.COLUMNS" in sql:
                if db.event: db.event("columns", False)
                self.rows = tuple((name,) for name in sorted(db.columns))
                return
            table = sql.split("FROM `tab", 1)[1].split("`", 1)[0]
            group = "header" if table == doctype else next(key for key in case.records if key != "header" and financial._child_type(doctype, key) == table)
            selected = tuple(dict.fromkeys(re.findall(r"OCTET_LENGTH\(`([^`]+)`\)", sql)))
            full = "CASE WHEN" in sql
            own = group == parentfield and set(selected) <= set(source.FIELDS)
            if db.event: db.event("own" if own else group, full)
            if own and full: db.own_values += 1
            ids = native.ROOT_IDS if group == "header" else native.CHILD_IDS
            self.description = [(name, FT.VAR_STRING, None, None, 140, 0, True) for name in ids]
            for name in selected:
                if full:
                    signature = db.signatures.get((group, name), [FT.VAR_STRING, 140, 0, True])
                    self.description.append((name, signature[0], None, None, *signature[1:]))
                self.description.append(("length", FT.LONG, None, None, 20, 0, True))
            self.rows = []
            for record in case.records[group][:args[-1]]:
                row = [record.get(name) for name in ids]
                for name in selected:
                    value = record.get(name)
                    length = None if value is None else len(str(value).encode())
                    if full: row.append(value if length is None or length <= financial.MAX_TEXT_BYTES else None)
                    row.append(length)
                self.rows.append(tuple(row))
            self.rows = tuple(self.rows)
        def fetchone(self): return db.autocommit
        def fetchall(self): return self.rows

    db.cursor = Mock(side_effect=Cursor)
    case.metadata_reader = Mock()
    case.metadata_reader.load_for_update.side_effect = lambda meta: case.own if meta.profile == CHILD_CURRENCY_PROFILE else case.observations[meta.name]
    for module in (native, source):
        monkeypatch.setattr(module, "MariaDBMetadataSourceReader", Mock(return_value=case.metadata_reader))
    case.financial = native.MariaDBInvoiceFinancialReader(db).load_for_update(doctype,
        case.name, erp_major=major, applied_metadata=case.metas)
    case.reader = source.MariaDBChildCurrencyReader(db)
    return case


def load(case):
    return case.reader.load_for_update(case.financial, case.parentfield, applied_metadata=case.own.applied)


def failure(call, code="child_currency_source_read"):
    with pytest.raises(source.ChildCurrencySourceError) as caught: call()
    assert str(caught.value) == code and caught.value.__context__ is None


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("present", [(), ("currency",), ("company",), ("currency", "company")])
def test_native_side_profile_preserves_presence_and_binds_parent_and_precision(monkeypatch, doctype, major, present):
    case = scenario(monkeypatch, doctype=doctype, major=major, present=present)
    original = case.financial._payload, case.financial.financial._payload, case.financial.sha256
    result = load(case)
    declared = result.inputs_for("items-1")
    assert declared.row_currency == (("str", "USD") if "currency" in present else ("absent",))
    assert declared.row_company == (("str", "SYNTHETIC-CHILD-CO") if "company" in present else ("absent",))
    assert declared.parent_doc_currency == ("absent",) and declared.parent_currency == ("str", "SAR")
    resolved = result.resolve_currency("items-1", "amount")
    assert resolved.currency == ("USD" if "currency" in present else "SAR")
    assert result.financial == case.financial and result.financial is not case.financial
    assert original == (case.financial._payload, case.financial.financial._payload, case.financial.sha256)
    case.reader.require_unchanged(result)
    assert not any(getattr(case.connection, method).called for method in ("commit", "rollback", "close"))


@pytest.mark.parametrize("value", [None, "", "EUR"])
def test_present_null_blank_and_own_currency_are_not_coerced(monkeypatch, value):
    case = scenario(monkeypatch)
    case.records["items"][0]["currency"] = value
    result = load(case)
    assert result.inputs_for("items-1").row_currency == tuple(financial._scalar(value))
    assert result.resolve_currency("items-1", "amount").currency == (value or "SAR")


@pytest.mark.parametrize("fault", ["orphan", "missing", "case", "unrelated"])
def test_column_membership_must_exactly_match_selected_metadata_before_values(monkeypatch, fault):
    case = scenario(monkeypatch, present=() if fault == "orphan" else ("currency",))
    if fault == "orphan": case.connection.columns.add("currency")
    elif fault == "missing": case.connection.columns.clear()
    elif fault == "case": case.connection.columns = {"Currency"}
    else: case.connection.columns.add("secret")  # A malformed selected-column projection.
    failure(lambda: load(case))
    assert not case.connection.own_values
    failure(lambda: load(case), "child_currency_source_transaction_unusable")


@pytest.mark.parametrize("change", ["currency", "company", "null_to_blank", "revision", "insert", "delete", "idx", "header", "metadata"])
def test_recheck_detects_link_and_membership_drift_without_parent_modified(monkeypatch, change):
    case = scenario(monkeypatch)
    if change == "null_to_blank": case.records["items"][0]["currency"] = None
    result = load(case)
    row = case.records["items"][0]
    if change in ("currency", "company"): row[change] = "OTHER"
    elif change == "null_to_blank": row["currency"] = ""
    elif change == "revision": row["modified"] += timedelta(seconds=1)
    elif change == "insert": case.records["items"].append(dict(row, name="items-2", idx=2))
    elif change == "delete": case.records["items"].clear()
    elif change == "idx": row["idx"] = 2
    elif change == "header": case.records["header"][0]["currency"] = "EUR"
    else: case.metadata_reader.require_unchanged.side_effect = ValueError("PRIVATE")
    failure(lambda: case.reader.require_unchanged(result), "child_currency_source_changed")


@pytest.mark.parametrize("change", ["link", "column", "revision"])
def test_preflight_and_final_checks_refuse_changes_during_value_selection(monkeypatch, change):
    case = scenario(monkeypatch)
    def mutate(group, full):
        if group == "own" and full:
            if change == "link": case.records["items"][0]["currency"] = "LONGER"
            elif change == "column": case.connection.columns.remove("company")
            else: case.records["items"][0]["modified"] += timedelta(seconds=1)
    case.connection.event = mutate
    failure(lambda: load(case))


@pytest.mark.parametrize("fault", ["row", "idx_bool", "revision", "financial", "columns", "signature", "field", "absent"])
def test_result_reconstruction_refuses_unbound_native_payload(monkeypatch, fault):
    case = scenario(monkeypatch, present=() if fault == "absent" else ("currency", "company"))
    result = load(case)
    body = json.loads(result._payload)
    if fault == "row": body["rows"][0][0] = "OTHER"
    elif fault == "idx_bool": body["rows"][0][1] = True
    elif fault == "revision": body["rows"][0][2] = ["null"]
    elif fault == "financial": body["financial_sha256"] = "f" * 64
    elif fault == "columns": body["columns"] = []
    elif fault == "signature": body["types"][0][1][0] = FT.LONG
    elif fault == "field": body["rows"][0][3][0][0] = "secret"
    else: body["rows"][0][3][0][1] = ["null"]
    failure(lambda: replace(result, _payload=financial._canonical(body)), "child_currency_source_rows")


@pytest.mark.parametrize("fault", ["metadata_type", "metadata_option", "profile", "table", "row", "derived"])
def test_unreviewed_metadata_table_or_row_is_not_guessed(monkeypatch, fault):
    case = scenario(monkeypatch)
    if fault in ("metadata_type", "metadata_option"):
        case.raw_own.definitions["currency"].values["fieldtype" if fault == "metadata_type" else "options"] = "Data" if fault == "metadata_type" else "Account"
        case.own = observed_metadata(case.raw_own, profile=CHILD_CURRENCY_PROFILE)
        failure(lambda: load(case))
    elif fault == "profile":
        failure(lambda: case.reader.load_for_update(case.financial, "items", applied_metadata=case.metas[case.raw_own.name]))
    elif fault == "table":
        failure(lambda: case.reader.load_for_update(case.financial, "company", applied_metadata=case.own.applied))
    else:
        result = load(case)
        if fault == "derived": object.__setattr__(result, "sha256", "f" * 64)
        failure(lambda: result.inputs_for("other" if fault == "row" else "items-1"), "child_currency_source_inputs")


@pytest.mark.parametrize("interrupt", [False, True])
def test_reader_failure_never_owns_cleanup_and_interruptions_propagate(monkeypatch, interrupt):
    case = scenario(monkeypatch)
    case.connection.error = KeyboardInterrupt() if interrupt else RuntimeError("PRIVATE-SQL")
    if interrupt:
        with pytest.raises(KeyboardInterrupt): load(case)
    else: failure(lambda: load(case))
    failure(lambda: load(case), "child_currency_source_transaction_unusable")
    assert not any(getattr(case.connection, method).called for method in ("commit", "rollback", "close"))


def test_repr_pickle_and_unknown_own_company_do_not_disclose_or_guess(monkeypatch):
    case = scenario(monkeypatch)
    result = load(case)
    assert "SYNTHETIC" not in repr(result) + repr(case.reader)
    for protected in (result, case.reader):
        with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(protected)
    failure(lambda: result.inputs_for("items-1", company_currency=SimpleNamespace(name="SYNTHETIC-CHILD-CO")), "child_currency_source_inputs")


@pytest.mark.parametrize("doctype", CHILD_CURRENCY_FIELDS)
def test_separate_child_profile_is_narrow_without_extending_financial_v1(doctype):
    from zatca_erpgulf.zatca_erpgulf import source_metadata as metadata
    raw = AppliedMeta(doctype, ("currency", "company"))
    projected = metadata.project_source_metadata(raw, base_fields={}, profile=CHILD_CURRENCY_PROFILE)
    assert tuple(CHILD_CURRENCY_FIELDS[doctype]) == source.FIELDS
    assert projected.istable and not projected.issingle
    assert metadata.project_source_metadata(raw, base_fields={}, profile=CHILD_CURRENCY_PROFILE) == projected


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("parentfield", financial.TABLE_FIELDS)
def test_every_declared_table_uses_its_own_row_type_and_parentfield(monkeypatch, doctype, parentfield):
    case = scenario(monkeypatch, doctype=doctype, parentfield=parentfield)
    result = load(case)
    declared = result.inputs_for(parentfield + "-1")
    assert (declared.doctype, declared.parenttype, declared.parentfield) == (
        financial._child_type(doctype, parentfield), doctype, parentfield)
    assert result.resolve_currency(parentfield + "-1", case.money_field).currency == "USD"


def test_empty_optional_table_has_no_invented_row_but_still_validates_signatures(monkeypatch):
    case = scenario(monkeypatch, parentfield="taxes", empty=True)
    result = load(case)
    assert json.loads(result._payload)["rows"] == []
    failure(lambda: result.inputs_for("taxes-1"), "child_currency_source_inputs")
    body = json.loads(result._payload)
    body["types"][0][1][0] = FT.LONG
    failure(lambda: replace(result, _payload=financial._canonical(body)), "child_currency_source_rows")


def test_exact_own_company_proof_is_composed_without_using_invoice_company(monkeypatch):
    from zatca_erpgulf.zatca_erpgulf.tests.test_company_currency_source import (
        scenario as company_case, reader as company_reader, load as load_company,
    )
    company = company_case()
    company.name = "SYNTHETIC-CHILD-CO"
    company.records["Company"] = [(company.name, NOW, "SAR")]
    proof = load_company(company, company_reader(company, monkeypatch))
    case = scenario(monkeypatch, options="Company:company:default_currency")
    case.records["items"][0]["company"] = proof.name
    result = load(case)
    resolved = result.resolve_currency("items-1", "amount", company_currency=proof)
    assert proof.name != case.records["header"][0]["company"]
    assert resolved.currency == proof.currency and resolved.origin == "ROW_COMPANY_CURRENCY"
    case.records["items"][0]["company"] = "OTHER-COMPANY"
    different = load(case)
    failure(lambda: different.inputs_for("items-1", company_currency=proof), "child_currency_source_inputs")


def test_autocommit_is_rejected_before_own_column_or_value_acquisition(monkeypatch):
    case = scenario(monkeypatch)
    case.connection.autocommit = (1,)
    start = len(case.connection.queries)
    failure(lambda: load(case))
    assert not any("information_schema.COLUMNS" in sql for sql, _ in case.connection.queries[start:])


@pytest.mark.parametrize("fault", ["metadata", "value", "presence"])
def test_advance_deduction_currency_must_match_its_existing_financial_projection(monkeypatch, fault):
    case = scenario(monkeypatch, parentfield="custom_zatca_advance_deduction_details")
    result = load(case)
    if fault == "metadata":
        case.raw_own.definitions["currency"].values["read_only"] = 1
        case.own = observed_metadata(case.raw_own, profile=CHILD_CURRENCY_PROFILE)
        failure(lambda: load(case))
    else:
        body = json.loads(result._payload)
        body["rows"][0][3][0][1] = ["str", "EUR"] if fault == "value" else ["absent"]
        failure(lambda: replace(result, _payload=financial._canonical(body)), "child_currency_source_rows")
