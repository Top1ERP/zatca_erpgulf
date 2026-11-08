"""Co-owned settlement stages on NEW guard-owned TCP-disabled SQL only."""

from dataclasses import replace
from decimal import Decimal
import json
import os
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import calculation_settlement_access as settlement
from zatca_erpgulf.zatca_erpgulf import calculation_payments as payment
from zatca_erpgulf.zatca_erpgulf import calculation_receivable as receivable
from zatca_erpgulf.zatca_erpgulf.source_metadata import (
    PROPERTIES, PAYMENT_CONTROLS_PROFILE, OUTSTANDING_GUARDS_PROFILE, OUTSTANDING_GUARDS_FIELDS,
    WRITE_OFF_PROFILE, OWNER_CURRENCY_PROFILE, INVOICE_ROUNDING_PROFILE,
)
from zatca_erpgulf.zatca_erpgulf.metadata_source import SelectedMetadataRows
from zatca_erpgulf.zatca_erpgulf.financial_source_observation import _canonical, _validate_scalar
from zatca_erpgulf.zatca_erpgulf.tests.test_guarded_outstanding_mariadb import native_case as previous
from zatca_erpgulf.zatca_erpgulf.tests.test_pos_profile_source import declarations as pos_declarations
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta, Definition, project
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_numeric_access import bind_numeric
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_format_access_mariadb import seed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_metadata_source_mariadb import insert
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access_mariadb import (
    combined_schema, defaults_schema, financial_schema, metadata_schema, isolated_server, connections, untouched,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_format_source_mariadb import format_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_field_currency_access_mariadb import field_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_format_access_mariadb import empty_sources
from zatca_erpgulf.zatca_erpgulf.tests.test_rounding_stage_mariadb import selected_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_pos_profile_source_mariadb import pos_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, one_failure, InspectionFailed, PermissionDenied,
)

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW guarded temporary SQL only; no tenant or authority access")


@pytest.fixture(autouse=True)
def empty_pos_sources(selected_schema, pos_schema, connections):
    setup = connections()
    with setup.cursor() as cursor:
        for dt in ("POS Profile", "POS Payment Method"): cursor.execute(f"DELETE FROM `tab{dt}`")
    setup.commit();setup.close()  # NEW synthetic fixture setup only.


def field(name, **values):
    result = Definition(name, **values)
    result.fieldtype, result.fieldname = result.get("fieldtype"), name
    return result


def profile_observation(case, raw, profile, suffix):
    result = observed_metadata(raw, profile=profile)
    body = json.loads(result._payload)
    source = json.loads(case.observations[case.invoice.doctype]._payload)
    common = {dict(row["header"])["fieldname"][1]: row for row in source["docfields"]}
    body["doctype"] = source["doctype"]
    for i, row in enumerate(body["docfields"]):
        name = dict(row["header"])["fieldname"][1]
        if name in common: body["docfields"][i] = common[name]
        else: row["name"] += suffix
    body["docfields"].sort(key=lambda row: row["name"])
    return SelectedMetadataRows(result.applied, _canonical(body))


def native_case(operator, connections, *, kind=None, is_return=0, consolidated=0, foreign=False, auto=0, internal=False, is_pos=1):
    scenario = ("combined", is_return, is_pos, None, 0, int(internal), "same" if internal else None)
    case = previous(operator, connections, scenario=scenario)
    service = case.service
    root = case.data.raw_metas[case.invoice.doctype]
    for name in ("grand_total", "base_grand_total", "outstanding_amount", "rounding_adjustment", "total_advance"):
        root.definitions[name] = field(name, fieldtype="Currency", precision="3" if name == "outstanding_amount" else "2", options="currency")
        case.data.records["header"][0].setdefault(name, Decimal("0.000000000"))
    root.definitions["disable_rounded_total"] = field("disable_rounded_total", fieldtype="Check")
    root.definitions["pos_profile"] = field("pos_profile", fieldtype="Link", options="POS Profile")
    case.data.records["header"][0].update(disable_rounded_total=0, pos_profile="SYNTHETIC-POS")
    case.applied[root.name] = case.data.metas[root.name] = project(root)
    case.observations[root.name] = observed_metadata(root)

    def copied(names, source):
        raw = AppliedMeta(root.name, names)
        for name in names:
            definition = source.applied.get_field(name)
            raw.definitions[name] = field(name, **{key: definition.get(key) for key in PROPERTIES})
        return raw
    controls = copied(payment.LockedPaymentControlsRead.FIELDS, case.controls_observation)
    guards = copied(OUTSTANDING_GUARDS_FIELDS[root.name], case.guard_observation)
    case.controls_observation = profile_observation(case, controls, PAYMENT_CONTROLS_PROFILE, "-PAYMENT")
    case.guard_observation = profile_observation(case, guards, OUTSTANDING_GUARDS_PROFILE, "-GUARD")
    owner = AppliedMeta(root.name, ("party_account_currency",))
    owner.definitions["party_account_currency"] = field("party_account_currency", fieldtype="Link", options="Currency")
    write = AppliedMeta(root.name, (*receivable.WRITE_FIELDS, receivable.AUTO))
    for name in write.definitions:
        write.definitions[name] = field(name, fieldtype="Check" if name == receivable.AUTO else "Currency",
            precision=None if name == receivable.AUTO else "2" if name == "write_off_amount" else "3",
            options=None if name == receivable.AUTO else "currency")
    rounding = AppliedMeta(root.name, ("is_consolidated", "rounding_adjustment", "rounded_total", "disable_rounded_total"))
    for name in rounding.definitions:
        rounding.definitions[name] = root.definitions[name] if name in root.definitions else field(name, fieldtype="Check")
    case.owner_observation = profile_observation(case, owner, OWNER_CURRENCY_PROFILE, "-OWNER")
    case.write_observation = profile_observation(case, write, WRITE_OFF_PROFILE, "-WRITE")
    case.rounding_observation = profile_observation(case, rounding, INVOICE_ROUNDING_PROFILE, "-ROUNDING")
    overrides = dict(case.field_overrides)
    bind_numeric(case, operator)
    case.field_overrides.update(overrides)
    for raw in (root, controls, guards, owner, write, rounding):
        for name, definition in raw.definitions.items():
            if definition.get("fieldtype") in ("Table", "Table MultiSelect"):
                continue
            definition.fieldname, definition.fieldtype = name, definition.get("fieldtype")
            definition.options = definition.get("options")
            case.field_overrides[root.name, name] = definition
    case.invoice.meta.istable = case.invoice.meta.issingle = 0
    case.invoice._precision = {}
    case.invoice.party_account_currency = "USD" if foreign else case.invoice.currency
    case.invoice.write_off_amount = Decimal("0.000000000")
    case.invoice.base_write_off_amount = Decimal("0.000000000")
    case.invoice.write_off_outstanding_amount_automatically = auto
    case.invoice.is_consolidated = consolidated
    case.invoice.loyalty_amount = Decimal("1.234500000")
    case.kind = kind
    case.pos_data = pos_declarations(kind=kind or "default")
    for dt, raw in case.pos_data.raw_pos.items():
        definitions = {name: Document(permlevel=0, **df.values) for name, df in raw.definitions.items()}
        case.normal_metas[dt] = Document(name=dt, issingle=0, istable=int(dt == "POS Payment Method"),
            get_field=lambda name, definitions=definitions: definitions.get(name),
            has_field=lambda name, definitions=definitions: name in definitions,
            get_permlevel_access=Mock(return_value=[0]))
    case.master = Document(doctype="POS Profile", name="SYNTHETIC-POS", company=case.company.name,
        modified=case.pos_data.master_rows[0]["modified"], meta=case.normal_metas["POS Profile"],
        save=Mock(), db_set=Mock(), check_permission=Mock(), payments=[])
    operator.documents[case.master.doctype, case.master.name] = case.master
    if kind == "default":
        raw = case.pos_data.payment_rows[0]
        child = Document(doctype="POS Payment Method", **raw, meta=case.normal_metas["POS Payment Method"],
            save=Mock(), db_set=Mock(), check_permission=Mock())
        case.master.payments = [child]
        operator.documents[child.doctype, child.name] = child

    setup = connections()
    with setup.cursor() as cursor:
        for name in ("outstanding_amount", "rounding_adjustment", "write_off_amount", "base_write_off_amount", "total_advance"):
            cursor.execute(f"ALTER TABLE `tab{root.name}` ADD COLUMN IF NOT EXISTS `{name}` DECIMAL(21,9)")
        for name in ("disable_rounded_total", "write_off_outstanding_amount_automatically", "is_consolidated"):
            cursor.execute(f"ALTER TABLE `tab{root.name}` ADD COLUMN IF NOT EXISTS `{name}` INT")
        cursor.execute(f"ALTER TABLE `tab{root.name}` ADD COLUMN IF NOT EXISTS party_account_currency LONGTEXT")
        cursor.execute(f"UPDATE `tab{root.name}` SET outstanding_amount=0,rounding_adjustment=0,total_advance=0,write_off_amount=0,"
            "base_write_off_amount=0,disable_rounded_total=0,write_off_outstanding_amount_automatically=%s,"
            "is_consolidated=%s,pos_profile='SYNTHETIC-POS',party_account_currency=%s", (auto, consolidated, case.invoice.party_account_currency))
        cursor.execute("DELETE FROM `tabDocField` WHERE parent=%s", (root.name,))
    observations = (case.observations[root.name], case.controls_observation, case.guard_observation,
        case.owner_observation, case.write_observation, case.rounding_observation)
    seeded = set()
    for observation in observations:
        body = json.loads(observation._payload)
        for row in body["docfields"]:
            if row["name"] not in seeded:
                # The SQL fixture seeder accepts record groups; don't construct
                # an incomplete metadata envelope solely for fixture insertion.
                insert(setup, "docfields", [dict(name=row["name"], modified=_validate_scalar(row["modified"]),
                    **{name: _validate_scalar(value) for name, value in row["header"]})])
                seeded.add(row["name"])
    for observation in case.pos_data.pos_metadata.values(): seed_metadata(setup, observation)
    with setup.cursor() as cursor:
        cursor.execute("INSERT INTO `tabPOS Profile` VALUES ('SYNTHETIC-POS',%s,%s,2.5,'PRIVATE')",
            (case.master.modified, case.company.name))
        if kind == "default":
            cursor.execute("INSERT INTO `tabPOS Payment Method` VALUES ('PAY-1',%s,'SYNTHETIC-POS','POS Profile',"
                "'payments',1,'Cash',1,0,'PRIVATE')", (case.master.modified,))
    setup.commit();setup.close()  # NEW synthetic fixture setup only.
    case.owner_metadata = Mock(side_effect=lambda *args: {root.name: case.owner_observation.applied})
    case.write_metadata = Mock(side_effect=lambda *args: {root.name: case.write_observation.applied})
    case.invoice_rounding_metadata = Mock(side_effect=lambda *args: {root.name: case.rounding_observation.applied})
    case.pos_metadata = Mock(side_effect=lambda scope, selected, types: {name: case.pos_data.applied_pos[name] for name in types})
    case.service = access.SavedCalculationDefaultsService(case.scope, case.factory, case.cache,
        applied_metadata_reader=case.metadata_provider, rounding_metadata_reader=service._rounding_metadata,
        rounding_cache_reader=service._rounding_cache, payment_controls_metadata_reader=case.controls_metadata,
        outstanding_guard_metadata_reader=case.guard_metadata, owner_currency_metadata_reader=case.owner_metadata,
        write_off_metadata_reader=case.write_metadata, invoice_rounding_metadata_reader=case.invoice_rounding_metadata,
        pos_profile_metadata_reader=case.pos_metadata)
    return case


def capture(case, major=16):
    return case.service.capture_settlement_context(case.invoice.name, erp_major=major, pos_lookup=case.kind)


@pytest.mark.parametrize("kind", [None, "limit", "default"])
@pytest.mark.parametrize("major", [15, 16])
def test_one_owned_union_yields_existing_strict_substage_contexts(defaults_operator, connections, kind, major):
    case = native_case(defaults_operator, connections, kind=kind)
    source = capture(case, major)
    assert type(source) is settlement.SavedSettlementRead
    assert source.guarded.payment.stage.owner_document == source.receivable.stage.owner_document == id(case.invoice)
    assert source.guarded.payment.stage.numeric == source.receivable.stage.numeric
    assert tuple(proof.target[2] for proof in source.guarded.payment.stage.fields) == payment.STAGE_FIELDS
    assert tuple(proof.target[2] for proof in source.receivable.stage.fields) == receivable.STAGE_FIELDS
    assert tuple(proof.target[2] for proof in source.prefix.fields) == settlement.PREFIX_FIELDS
    assert source.prefix.owner_document == id(case.invoice)
    assert source.prefix.numeric == source.receivable.stage.numeric
    assert source.prefix.method == source.receivable.stage.method
    assert (source.pos is None) is (kind is None)
    if source.pos is not None: assert source.pos.owner_document == id(case.invoice)
    else: case.pos_metadata.assert_not_called()
    assert len(case.opened) == 1 and case.opened[0].rollback.call_count == 2
    case.invoice.precision.assert_not_called()
    if kind == "limit" and major == 16:
        from zatca_erpgulf.zatca_erpgulf.tests.test_settlement_sequence_mariadb import sequence
        # Inspection alone is not proof that the current controller consumes
        # this limit: the saved consolidation flag is zero in this fixture.
        with pytest.raises(settlement.SettlementAccessError): sequence(source)
    if kind == "default" and major == 16:
        with pytest.raises(settlement.SettlementAccessError):
            replace(source, pos=replace(source.pos, owner_document=source.pos.owner_document + 1))
    untouched(defaults_operator, case)


@pytest.mark.parametrize("defaults_operator", [15], indirect=True)
@pytest.mark.parametrize("denial", ["profile", "pos_child", "write_off_field", "party_field"])
def test_union_read_denials_precede_metadata_and_sql_callbacks(defaults_operator, connections, denial):
    case = native_case(defaults_operator, connections, kind="default")
    if denial == "profile": defaults_operator.denied.add(("POS Profile", "SYNTHETIC-POS"))
    elif denial == "pos_child": defaults_operator.denied.add(("POS Payment Method", "PAY-1"))
    else:
        name = receivable.AUTO if denial == "write_off_field" else "party_account_currency"
        case.field_overrides[case.invoice.doctype, name].values["permlevel"] = 2
    with pytest.raises(PermissionDenied): capture(case)
    for callback in (case.factory, case.metadata_provider, case.cache, case.controls_metadata,
                     case.guard_metadata, case.write_metadata, case.owner_metadata, case.pos_metadata):
        callback.assert_not_called()
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE)


@pytest.mark.parametrize("defaults_operator", [15], indirect=True)
@pytest.mark.parametrize("changed", ["link", "field", "definition"])
def test_profile_root_is_rechecked_through_close_even_without_a_lookup(defaults_operator, connections, changed):
    case = native_case(defaults_operator, connections)
    def wrap(owned):
        close = owned.close.side_effect
        def finish():
            result = close()
            if changed == "link": case.invoice.pos_profile = "OTHER"
            elif changed == "field": case.field_overrides[case.invoice.doctype, "pos_profile"].values["permlevel"] = 2
            else: case.field_overrides[case.invoice.doctype, "pos_profile"].options = "Company"
            return result
        owned.close.side_effect = finish
    case.before_handoff = wrap
    with pytest.raises(PermissionDenied if changed == "field" else InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE if changed == "field" else access.FINANCIAL_FAILED_MESSAGE)
    case.pos_metadata.assert_not_called()
    untouched(defaults_operator, case)


@pytest.mark.parametrize("defaults_operator", [15], indirect=True)
@pytest.mark.parametrize("changed", ["party", "write_off", "consolidation"])
def test_last_pos_metadata_callback_cannot_invalidate_another_native_side_source(defaults_operator, connections, changed):
    case = native_case(defaults_operator, connections, kind="default")
    original = case.pos_metadata.side_effect
    def supplied(*args):
        result = original(*args)
        if case.pos_metadata.call_count == 2:
            with case.opened[0].cursor() as cursor:
                if changed == "party": cursor.execute("UPDATE `tabSales Invoice` SET party_account_currency='EUR'")
                elif changed == "write_off": cursor.execute("UPDATE `tabSales Invoice` SET write_off_amount=2")
                else: cursor.execute("UPDATE `tabSales Invoice` SET is_consolidated=1")
        return result
    case.pos_metadata.side_effect = supplied
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT party_account_currency,write_off_amount,is_consolidated FROM `tabSales Invoice`")
        assert cursor.fetchone() == (case.invoice.currency, Decimal("0.000000000"), 0)
    untouched(defaults_operator, case)
