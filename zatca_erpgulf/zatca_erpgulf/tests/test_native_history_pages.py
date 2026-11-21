"""Partial-page arithmetic and numeric keyset contract, not durable capture."""

from types import SimpleNamespace
from unittest.mock import Mock
from dataclasses import FrozenInstanceError
import pickle

import pytest

from zatca_erpgulf.zatca_erpgulf import native_legacy_history as history
from zatca_erpgulf.zatca_erpgulf.chain_registration import ChainRegistrationError
from zatca_erpgulf.zatca_erpgulf.dispatch_store import DispatchStoreError
from zatca_erpgulf.zatca_erpgulf.tests.test_native_legacy_history import records


ID = '10000000-0000-4000-8000-000000000001'


@pytest.fixture
def page_case(monkeypatch):
    rows, evidence = records()
    for row in rows:
        row.update(company='COMPANY', docstatus=1, unit='UNIT', custom_uuid=ID)
    source = SimpleNamespace(doctype='Sales Invoice', name='SYNTHETIC-3', company='COMPANY')
    owner = SimpleNamespace(owner_current=Mock(return_value=True), database=SimpleNamespace(sql=Mock()), actor='OPERATOR')
    monkeypatch.setattr(history, 'require_range_isolation', lambda owner: None)
    monkeypatch.setattr(history, 'require_range_engines', lambda owner, tables: None)
    monkeypatch.setattr(history, 'MAX_PAGE_SOURCES', 2)
    monkeypatch.setattr(history, '_count_slots', lambda owner, unit, after_icv=None:
        sum(int(row['icv']) > int(after_icv or '0') for row in rows))
    monkeypatch.setattr(history, '_page_rows', lambda owner, unit, after_icv, boundary=False:
        [row for row in rows if (int(row['icv']) == int(after_icv) if boundary else int(row['icv']) > int(after_icv))])
    older = Mock(side_effect=lambda runtime, owner, row, seller, budget: evidence[row['doctype'], row['name']])
    monkeypatch.setattr(history, '_older_xml', older)
    anchor = evidence[source.doctype, source.name][0]
    def run(after='0'):
        return history.inspect_known_legacy_page(SimpleNamespace(), owner, source, 'UNIT', anchor, 'KEY',
            review_id=ID, after_icv=after)
    return SimpleNamespace(rows=rows, evidence=evidence, older=older, run=run, owner=owner)


def test_each_page_reports_its_own_coverage_and_rereads_boundary_before_linking(page_case):
    c = page_case; first = c.run()
    assert first.review_id == ID and first.after_icv == '0' and first.through_icv == first.next_after_icv == '2'
    assert first.remaining_sources == 1 and first.inventory.matched_links == 1 and not first.inventory.source_scan_complete
    second = c.run(first.next_after_icv)
    assert second.after_icv == '2' and second.through_icv == '3' and second.next_after_icv is None
    assert second.remaining_sources == 0 and second.inventory.matched_links == 1 and second.inventory.tail_match is True
    assert c.older.call_count == 3  #1,2 then fresh2; the anchor is reused.
    with pytest.raises(FrozenInstanceError): second.through_icv = '999'
    with pytest.raises(TypeError): pickle.dumps(second)


@pytest.mark.parametrize('cursor', ['01', '-1', '', '1.0', 1, True])
def test_untrusted_cursor_shapes_are_not_normalized_or_rounded(page_case, cursor):
    with pytest.raises(DispatchStoreError): page_case.run(cursor)
    page_case.older.assert_not_called()


def test_after_tail_is_not_an_empty_complete_scan(page_case):
    with pytest.raises(ChainRegistrationError, match='registration_history_cursor_range'): page_case.run('4')


def test_cursor_in_a_gap_is_not_silently_substituted(page_case):
    page_case.rows.pop(1)
    with pytest.raises(ChainRegistrationError, match='registration_history_cursor_missing'): page_case.run('2')


def test_missing_boundary_cannot_supply_a_previous_digest(page_case):
    c = page_case; c.evidence['POS Invoice', 'SYNTHETIC-2'] = None
    result = c.run('2')
    assert result.boundary_unresolved and result.inventory.matched_links == 0
    assert result.inventory.unresolved_sources == 1 and result.remaining_sources == 0


def test_numeric_keyset_merges_both_tables_without_lexical_or_float_order():
    owner = SimpleNamespace(owner_current=Mock(return_value=True))
    def sql(statement, values, *, as_dict):
        assert 'OFFSET' not in statement and 'DECIMAL(65,0)' in statement
        assert 'BINARY custom_zatca_issuing_unit=BINARY %s' in statement
        assert 'LOCK IN SHARE MODE NOWAIT' in statement and values[:3] == ('UNIT', 'UNIT', '0')
        return [{'icv': value} for value in (('1', '10') if '`tabSales Invoice`' in statement else ('2', '9007199254740993'))]
    owner.database = SimpleNamespace(sql=Mock(side_effect=sql))
    rows = history._page_rows(owner, 'UNIT', '0')
    assert [row['icv'] for row in rows] == ['1', '2', '10', '9007199254740993']
    assert len({row['doctype'] for row in rows}) == 2
