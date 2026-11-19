"""Owner discovery/collision and range-lock races in private fixture SQL only."""

import os
from unittest.mock import Mock

import pymysql
import pytest

from zatca_erpgulf.zatca_erpgulf import native_identity_inventory as inventory, native_onboarding as onboarding
from zatca_erpgulf.zatca_erpgulf.tests.test_native_onboarding_mariadb import (
    target, boundary, materials, isolated_server, connections, tables,
)
from zatca_erpgulf.zatca_erpgulf.worker_transaction import owned_worker_transaction


pytestmark = pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB') != '1',
    reason='Fixture-owned private SQL only')


@pytest.mark.parametrize('target', ['company', 'device'], indirect=True)
@pytest.mark.parametrize('evidence', ['key', 'pih', 'counter', 'native_marker'])
def test_actual_initial_preparation_rejects_same_declared_legacy_unit_before_keygen(target, monkeypatch, evidence):
    t = target
    other = t.b.device if t.selected.doctype == 'Company' else t.b.company
    field, value = {'key': ('custom_private_key', 'UNKNOWN-LEGACY-KEY'),
        'pih': ('custom_pih', 'LEGACY-GENERATED-HASH'), 'counter': ('custom_zatca_icv_counter', 'LEGACY-COUNTER'),
        'native_marker': (onboarding.MARKER, 'LEGACY-CHAIN')}[evidence]
    with t.connection.cursor() as cursor:
        cursor.execute('UPDATE `tab' + other.doctype + '` SET `' + field + '`=%s WHERE name=%s', (value, other.name))
    t.connection.commit()
    keygen = Mock(side_effect=AssertionError('No key may be generated after a collision'))
    monkeypatch.setattr(onboarding.ec, 'generate_private_key', keygen)
    with pytest.raises(onboarding.NativeOnboardingError, match='native_identity_inventory_declaration_conflict') as failed:
        t.prepare()
    assert failed.value.__context__ is None and t.database.commits == 0
    saved = t.runtime.get_doc(t.selected.doctype, t.selected.name)
    assert saved.custom_private_key is None and saved.get(onboarding.MARKER) is None
    keygen.assert_not_called()
    t.b.request.assert_not_called()


def test_one_unreadable_inventory_owner_prevents_partial_discovery_and_initial_key(target, monkeypatch):
    t = target
    def permission(dt, operation, *, doc, user, raise_exception=True):
        return doc.name != t.b.device.name
    t.runtime.has_permission = permission
    monkeypatch.setattr(onboarding.ec, 'generate_private_key', lambda *a, **kw: pytest.fail('Partial discovery keygen'))
    with pytest.raises(onboarding.NativeOnboardingError, match='native_identity_inventory_permission'):
        t.prepare()
    assert t.database.commits == 0


@pytest.mark.parametrize('operation', ['copy', 'insert_before', 'insert_after', 'rename', 'engine_ddl'])
def test_shared_full_range_holds_concurrent_copy_insert_or_rename_until_transaction_ends(target, operation):
    t = target
    peer = t.connections()
    with peer.cursor() as cursor:
        cursor.execute('SET SESSION innodb_lock_wait_timeout=1')
        cursor.execute('SET SESSION lock_wait_timeout=1')
    with owned_worker_transaction(t.runtime) as owner:
        observed = inventory.collect_identity_inventory(t.runtime, owner)
        assert observed.declaring(onboarding.egs_identity_key('Production', 'TEST-VAT', t.serial))
        with peer.cursor() as cursor:
            with pytest.raises(pymysql.OperationalError) as failed:
                if operation == 'copy':
                    cursor.execute('UPDATE `tabCompany` SET custom_private_key=%s WHERE name=%s', ('COPIED', t.b.company.name))
                elif operation == 'rename':
                    cursor.execute('UPDATE `tabCompany` SET name=%s WHERE name=%s', ('ZZZ-RENAMED', t.b.company.name))
                elif operation == 'engine_ddl':
                    cursor.execute('ALTER TABLE `tabCompany` ENGINE=MyISAM')
                else:
                    name = '000-INSERTED' if operation == 'insert_before' else 'ZZZ-INSERTED'
                    cursor.execute('INSERT INTO `tabCompany` (name) VALUES (%s)', (name,))
            assert failed.value.args[0] == 1205
        peer.rollback()
    # No inventory commit. Once its transaction closes, the same peer can write.
    with peer.cursor() as cursor:
        cursor.execute('UPDATE `tabCompany` SET custom_private_key=%s WHERE name=%s', ('AFTER-ROLLBACK', t.b.company.name))
    peer.rollback()
    assert t.database.commits == 0


def test_nondefault_read_committed_cannot_claim_phantom_protection(target):
    t = target
    with t.connection.cursor() as cursor:
        cursor.execute('SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED')
    with pytest.raises(inventory.IdentityInventoryError, match='native_identity_inventory_isolation'):
        with owned_worker_transaction(t.runtime) as owner:
            inventory.collect_identity_inventory(t.runtime, owner)
    assert t.database.commits == 0


def test_orm_read_view_cannot_hide_material_committed_before_the_locking_scan(target):
    t = target
    peer = t.connections()
    # Establish an older consistent read, then commit a changed scalar on a
    # separate connection. The ORM double intentionally returns that old row.
    with owned_worker_transaction(t.runtime) as owner:
        old = t.runtime.get_doc(t.b.device.doctype, t.b.device.name)
        with peer.cursor() as cursor:
            cursor.execute('UPDATE `tabZATCA Multiple Setting` SET custom_private_key=%s WHERE name=%s',
                ('NEW-COMMITTED-MATERIAL', t.b.device.name))
        peer.commit()
        get_doc = t.runtime.get_doc
        t.runtime.get_doc = lambda dt, name, **kw: (old if (dt, name) == (old.doctype, old.name)
            else get_doc(dt, name, **kw))
        with pytest.raises(inventory.IdentityInventoryError, match='native_identity_inventory_source_changed'):
            inventory.collect_identity_inventory(t.runtime, owner)
    assert t.database.commits == 0


def test_independent_unit_history_does_not_block_another_new_declaration(target):
    t = target
    # The same table may contain an independently declared EGS with history.
    other = t.b.device
    with t.connection.cursor() as cursor:
        cursor.execute('UPDATE `tabZATCA Multiple Setting` SET custom_csr_config=%s,custom_private_key=%s WHERE name=%s',
            (t.configuration.replace(t.serial, t.serial + '-OTHER'), 'LEGACY-KEY', other.name))
    t.connection.commit()
    result = t.prepare()
    assert result.record_id and t.database.commits == 1
    t.b.request.assert_not_called()
