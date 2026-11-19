"""Exact negative tail policy; fake query rows, no database or authority."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import native_legacy_tail as tail
from zatca_erpgulf.zatca_erpgulf.chain_registration import ChainRegistrationError
from zatca_erpgulf.zatca_erpgulf.native_identity_inventory import IdentityInventoryError
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document


@pytest.fixture
def case(request):
    doctype = getattr(request, 'param', 'Sales Invoice')
    source = Document(doctype=doctype, name='TAIL', company='SYNTHETIC', docstatus=1,
        custom_uuid='10000000-0000-4000-8000-000000000001')
    unit, icv = 'company:reviewed-unit', '9007199254740993'
    row = dict(name=source.name, company=source.company, docstatus=source.docstatus,
        custom_uuid=source.custom_uuid, icv=icv, custom_zatca_issuing_unit=unit)
    results = {doctype: [row], next(kind for kind in tail.SOURCE_TABLES if kind != doctype): []}
    def sql(statement, values=(), *, as_dict=True):
        if statement.startswith('SELECT @@tx_isolation'):
            return [{'isolation_level': 'REPEATABLE-READ'}]
        if 'information_schema.tables' in statement:
            assert set(values) == {'tabSales Invoice', 'tabPOS Invoice', 'tabZATCA ICV Counter'}
            return [{'table_name': name, 'engine': 'InnoDB'} for name in values]
        if 'information_schema.columns' in statement:
            return [dict(table_name=name, column_name='last_issued_icv' if name.endswith('Counter') else 'custom_zatca_icv',
                data_type='varchar', numeric_scale=None) for name in ('tabSales Invoice', 'tabPOS Invoice', 'tabZATCA ICV Counter')]
        assert values == (unit, tail.CANONICAL_ICV, icv, source.company)
        assert 'LIMIT 2 LOCK IN SHARE MODE NOWAIT' in statement
        assert 'DECIMAL(65,0)' in statement and 'MAX(' not in statement
        assert 'custom_zatca_status' not in statement
        return results['Sales Invoice' if '`tabSales Invoice`' in statement else 'POS Invoice']
    owner = SimpleNamespace(database=SimpleNamespace(sql=Mock(side_effect=sql)), owner_current=Mock(return_value=True))
    return SimpleNamespace(owner=owner, source=source, unit=unit, icv=icv, row=row, results=results)


@pytest.mark.parametrize('case', ['Sales Invoice', 'POS Invoice'], indirect=True)
@pytest.mark.parametrize('docstatus', [1, 2])
def test_submitted_or_cancelled_exact_generated_anchor_remains_the_tail(case, docstatus):
    c = case
    c.source.docstatus = c.row['docstatus'] = docstatus
    assert tail.require_unambiguous_saved_tail(c.owner, c.source, c.unit, c.icv) is None
    assert c.owner.database.sql.call_count == 5


@pytest.mark.parametrize('other_doctype', ['Sales Invoice', 'POS Invoice'])
def test_another_candidate_in_either_source_table_is_review_not_a_new_seed(case, other_doctype):
    c = case
    c.results[other_doctype].append(c.row | {'name': 'ANOTHER', 'icv': '9007199254740994'})
    with pytest.raises(ChainRegistrationError, match='registration_saved_tail_conflict'):
        tail.require_unambiguous_saved_tail(c.owner, c.source, c.unit, c.icv)


@pytest.mark.parametrize('field,value', [('company', 'OTHER'), ('docstatus', 0), ('custom_uuid', 'CHANGED'),
    ('icv', '9007199254740992'), ('icv', '09007199254740993'), ('custom_zatca_issuing_unit', 'company:OTHER')])
def test_current_sql_anchor_must_equal_the_already_authorized_source(case, field, value):
    c = case
    c.row[field] = value
    with pytest.raises(ChainRegistrationError, match='registration_saved_tail_conflict'):
        tail.require_unambiguous_saved_tail(c.owner, c.source, c.unit, c.icv)


def test_missing_anchor_does_not_mean_zero_or_fresh_genesis(case):
    c = case
    c.results[c.source.doctype] = []
    with pytest.raises(ChainRegistrationError, match='registration_saved_tail_missing'):
        tail.require_unambiguous_saved_tail(c.owner, c.source, c.unit, c.icv)


@pytest.mark.parametrize('fault', ['isolation', 'engine', 'missing_table', 'owner', 'owner_after_query'])
def test_unproven_range_semantics_never_prove_a_tail(case, fault):
    c = case
    sql = c.owner.database.sql.side_effect
    def changed(statement, values=(), **kw):
        rows = sql(statement, values, **kw)
        if fault == 'isolation' and statement.startswith('SELECT @@tx_isolation'):
            return [{'isolation_level': 'READ-COMMITTED'}]
        if 'information_schema.tables' in statement:
            if fault == 'engine':
                rows[-1]['engine'] = 'MyISAM'
            elif fault == 'missing_table':
                rows.pop()
        if fault == 'owner_after_query' and 'FROM `tabSales Invoice`' in statement:
            c.owner.owner_current.return_value = False
        return rows
    c.owner.database.sql.side_effect = changed
    if fault == 'owner':
        c.owner.owner_current.return_value = False
    with pytest.raises(IdentityInventoryError):
        tail.require_unambiguous_saved_tail(c.owner, c.source, c.unit, c.icv)


@pytest.mark.parametrize('kind,scale,allowed', [('bigint', 0, True), ('varchar', None, True),
    ('decimal', 0, True), ('decimal', 2, False), ('double', None, False), ('float', None, False),
    ('date', None, False)])
def test_only_exact_counter_column_types_can_support_tail_order(case, kind, scale, allowed):
    c = case
    sql = c.owner.database.sql.side_effect
    def columns(statement, values=(), **kw):
        rows = sql(statement, values, **kw)
        if 'information_schema.columns' in statement:
            rows[1].update(data_type=kind, numeric_scale=scale)
        return rows
    c.owner.database.sql.side_effect = columns
    if allowed:
        tail.require_unambiguous_saved_tail(c.owner, c.source, c.unit, c.icv)
    else:
        with pytest.raises(ChainRegistrationError, match='registration_counter_column_review'):
            tail.require_unambiguous_saved_tail(c.owner, c.source, c.unit, c.icv)
