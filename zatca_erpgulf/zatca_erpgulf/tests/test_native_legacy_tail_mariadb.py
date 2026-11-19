"""Actual legacy review rejects hidden source tails in fixture-owned SQL only."""

import os
from uuid import uuid4

import pymysql
import pytest

from zatca_erpgulf.zatca_erpgulf import native_registration as registration, native_legacy_tail as tail
from zatca_erpgulf.zatca_erpgulf.tests.test_native_registration_mariadb import (
    legacy, boundary, materials, isolated_server, connections, tables,
)
from zatca_erpgulf.zatca_erpgulf.worker_transaction import owned_worker_transaction


pytestmark = pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB') != '1',
    reason='Fixture-owned private SQL only')


def insert_source(t, doctype, *, icv, name=None, company=None, unit=None, docstatus=1):
    name = name or 'CANDIDATE-' + str(uuid4())
    with t.connection.cursor() as cursor:
        cursor.execute('INSERT INTO `tab' + doctype + '` (name,company,docstatus,custom_uuid,custom_zatca_icv,'
            'custom_zatca_issuing_unit) VALUES (%s,%s,%s,%s,%s,%s)',
            (name, t.source.company if company is None else company, docstatus, str(uuid4()), icv,
                t.source.custom_zatca_issuing_unit if unit is None else unit))
    t.connection.commit()
    return name


@pytest.mark.parametrize('doctype', ['Sales Invoice', 'POS Invoice'])
@pytest.mark.parametrize('icv', ['28', '27', None, '', '0', '-1', '027', '27.0', '27\n', '٢٧', '1e2', '9' * 65])
def test_another_latest_duplicate_or_partial_source_stops_real_review(legacy, doctype, icv):
    t = legacy
    insert_source(t, doctype, icv=icv)
    with pytest.raises(registration.ChainRegistrationError, match='registration_saved_tail_conflict') as failed:
        t.review()
    assert failed.value.__context__ is None and t.database.commits == 0
    assert t.runtime.get_doc(t.counter.doctype, t.counter.name).last_issued_icv == '27'
    t.b.request.assert_not_called()


@pytest.mark.parametrize('doctype', ['Sales Invoice', 'POS Invoice'])
@pytest.mark.parametrize('fault', ['foreign_company', 'draft', 'unknown_docstatus'])
def test_older_partial_or_shared_company_source_is_not_silently_omitted(legacy, doctype, fault):
    t = legacy
    insert_source(t, doctype, icv='1', company='OTHER' if fault == 'foreign_company' else None,
        docstatus=0 if fault == 'draft' else None if fault == 'unknown_docstatus' else 1)
    with pytest.raises(registration.ChainRegistrationError, match='registration_saved_tail_conflict'):
        t.review()
    assert t.database.commits == 0


@pytest.mark.parametrize('doctype', ['Sales Invoice', 'POS Invoice'])
def test_older_generated_or_cancelled_same_unit_sources_preserve_the_reviewed_tail(legacy, doctype):
    t = legacy
    insert_source(t, doctype, icv='9', docstatus=1)
    insert_source(t, doctype, icv='26', docstatus=2)
    reviewed = t.review()
    assert reviewed.last_icv == '27' and not reviewed.active and t.database.commits == 1
    t.b.request.assert_not_called()


def test_another_units_later_partial_source_does_not_change_this_units_tail(legacy):
    t = legacy
    insert_source(t, 'POS Invoice', icv='9999', unit='setting:INDEPENDENT')
    reviewed = t.review()
    assert reviewed.last_icv == '27' and not reviewed.active


@pytest.mark.parametrize('legacy', [('company', 0, '9007199254740993')], indirect=True)
@pytest.mark.parametrize('other_icv,blocked', [('9007199254740992', False), ('9007199254740993', True),
    ('9007199254740994', True), ('9999999999999999999999999999999999999999999999999999999999999999', True)])
def test_tail_comparison_is_exact_beyond_float_precision(legacy, other_icv, blocked):
    t = legacy
    insert_source(t, 'POS Invoice', icv=other_icv)
    if blocked:
        with pytest.raises(registration.ChainRegistrationError, match='registration_saved_tail_conflict'):
            t.review()
        assert t.database.commits == 0
    else:
        assert t.review().last_icv == '9007199254740993'
        assert t.database.commits == 1


@pytest.mark.parametrize('doctype', ['Sales Invoice', 'POS Invoice'])
@pytest.mark.parametrize('indexed', [False, True])
def test_a_matching_source_cannot_appear_after_the_negative_check_before_commit(legacy, doctype, indexed):
    t = legacy
    if indexed:
        with t.connection.cursor() as cursor:
            for table in tail.SOURCE_TABLES.values():
                cursor.execute('ALTER TABLE ' + table + ' ADD INDEX IF NOT EXISTS review_unit (custom_zatca_issuing_unit)')
    peer = t.connections()
    with peer.cursor() as cursor:
        cursor.execute('SET SESSION innodb_lock_wait_timeout=1')
    with owned_worker_transaction(t.runtime) as owner:
        tail.require_unambiguous_saved_tail(owner, t.source, t.source.custom_zatca_issuing_unit, '27')
        with peer.cursor() as cursor:
            with pytest.raises(pymysql.OperationalError) as failed:
                cursor.execute('INSERT INTO `tab' + doctype + '` (name,company,docstatus,custom_uuid,'
                    'custom_zatca_icv,custom_zatca_issuing_unit) VALUES (%s,%s,1,%s,%s,%s)',
                    ('LATE-' + str(uuid4()), t.source.company, str(uuid4()), '28', t.source.custom_zatca_issuing_unit))
            assert failed.value.args[0] == 1205
        peer.rollback()
    assert t.database.commits == 0


def test_existing_older_source_cannot_be_changed_above_the_tail_during_review(legacy):
    t = legacy
    name = insert_source(t, 'POS Invoice', icv='26')
    with t.connection.cursor() as cursor:
        for table in tail.SOURCE_TABLES.values():
            cursor.execute('ALTER TABLE ' + table + ' ADD INDEX IF NOT EXISTS review_unit (custom_zatca_issuing_unit)')
    peer = t.connections()
    with peer.cursor() as cursor:
        cursor.execute('SET SESSION innodb_lock_wait_timeout=1')
    with owned_worker_transaction(t.runtime) as owner:
        tail.require_unambiguous_saved_tail(owner, t.source, t.source.custom_zatca_issuing_unit, '27')
        with peer.cursor() as cursor:
            with pytest.raises(pymysql.OperationalError) as failed:
                cursor.execute('UPDATE `tabPOS Invoice` SET custom_zatca_icv=%s WHERE name=%s', ('28', name))
            assert failed.value.args[0] == 1205
        peer.rollback()
    assert t.database.commits == 0


def test_read_committed_is_not_sufficient_for_a_reusable_review(legacy):
    t = legacy
    with t.connection.cursor() as cursor:
        cursor.execute('SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED')
    with pytest.raises(registration.ChainRegistrationError, match='native_identity_inventory_isolation') as failed:
        t.review()
    assert failed.value.__context__ is None and t.database.commits == 0


@pytest.mark.parametrize('doctype', ['Sales Invoice', 'POS Invoice', 'ZATCA ICV Counter'])
def test_nontransactional_source_or_counter_engine_is_not_admissible(legacy, doctype):
    t = legacy
    with t.connection.cursor() as cursor:
        cursor.execute('ALTER TABLE `tab' + doctype + '` ENGINE=MyISAM')
    try:
        with pytest.raises(registration.ChainRegistrationError, match='native_identity_inventory_engine') as failed:
            t.review()
        assert failed.value.__context__ is None and t.database.commits == 0
    finally:
        with t.connection.cursor() as cursor:
            cursor.execute('ALTER TABLE `tab' + doctype + '` ENGINE=InnoDB')


def test_unavailable_pos_history_is_a_static_failure_not_a_sales_only_pass(legacy, monkeypatch):
    t = legacy
    sql = t.database.sql
    def unavailable(statement, values=(), **kwargs):
        if statement.startswith('SELECT name,company,docstatus,custom_uuid,') and 'FROM `tabPOS Invoice`' in statement:
            raise RuntimeError('PRIVATE-DRIVER-CONTEXT')
        return sql(statement, values, **kwargs)
    monkeypatch.setattr(t.database, 'sql', unavailable)
    with pytest.raises(registration.ChainRegistrationError, match='registration_review_failed') as failed:
        t.review()
    assert failed.value.__context__ is None and 'PRIVATE' not in str(failed.value) and t.database.commits == 0


@pytest.mark.parametrize('legacy', [('company', 0, '9007199254740993')], indirect=True)
def test_an_actual_floating_pos_column_cannot_hide_a_rounded_duplicate(legacy):
    t = legacy
    name = 'FLOAT-LOSS-' + str(uuid4())
    # Private fixture DDL only. Preserve earlier fixture rows byte-for-byte;
    # invalid historical strings must not be implicitly converted by the test.
    with t.connection.cursor() as cursor:
        cursor.execute('SELECT name,custom_zatca_icv FROM `tabPOS Invoice`')
        originals = cursor.fetchall()
        cursor.execute('UPDATE `tabPOS Invoice` SET custom_zatca_icv=NULL')
    t.connection.commit()
    try:
        with t.connection.cursor() as cursor:
            cursor.execute('ALTER TABLE `tabPOS Invoice` MODIFY custom_zatca_icv DOUBLE')
        with pytest.raises(registration.ChainRegistrationError, match='registration_counter_column_review'):
            t.review()
        insert_source(t, 'POS Invoice', icv='9007199254740993', name=name)
        with t.connection.cursor() as cursor:
            cursor.execute('SELECT CAST(custom_zatca_icv AS DECIMAL(65,0)) FROM `tabPOS Invoice` WHERE name=%s', (name,))
            assert str(cursor.fetchone()[0]) == '9007199254740992'
        # MariaDB serializes this DOUBLE in scientific notation, so the bad
        # source also trips the canonical-string guard before metadata admission.
        with pytest.raises(registration.ChainRegistrationError, match='registration_saved_tail_conflict'):
            t.review()
        assert t.database.commits == 0
    finally:
        with t.connection.cursor() as cursor:
            cursor.execute('DELETE FROM `tabPOS Invoice` WHERE name=%s', (name,))
            cursor.execute('ALTER TABLE `tabPOS Invoice` MODIFY custom_zatca_icv VARCHAR(140)')
            if originals:
                cursor.executemany('UPDATE `tabPOS Invoice` SET custom_zatca_icv=%s WHERE name=%s',
                    [(value, source_name) for source_name, value in originals])
        t.connection.commit()


def test_previously_reviewed_anchor_is_not_reused_after_another_generated_source_appears(legacy):
    t = legacy
    first = t.review()
    insert_source(t, 'POS Invoice', icv='28')
    with pytest.raises(registration.ChainRegistrationError, match='registration_saved_tail_conflict'):
        t.review()
    assert t.database.commits == 1
    row = t.database.sql('SELECT last_icv,active FROM `tabZATCA Issuing Chain` WHERE name=%s',
        (first.record_id,), as_dict=True)[0]
    assert row == {'last_icv': '27', 'active': 0}
