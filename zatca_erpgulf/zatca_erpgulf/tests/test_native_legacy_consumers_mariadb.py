"""Actual legacy review discovers credential copies and counter fragments."""

import base64
import os
from uuid import uuid4

import pytest
import pymysql

from zatca_erpgulf.zatca_erpgulf import native_registration as registration, native_identity_inventory as identity, native_legacy_consumers as consumers
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_native_registration_mariadb import (
    legacy, boundary, materials, isolated_server, connections, tables,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_native_onboarding_mariadb import CONFIG
from zatca_erpgulf.zatca_erpgulf.worker_transaction import owned_worker_transaction


pytestmark = pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB') != '1',
    reason='Fixture-owned temporary SQL only')


def alias(t, *, independent=False, delegate=False, counter_reference=None):
    source = t.b.linked if independent else t.selected
    doctype = 'ZATCA Multiple Setting' if delegate else 'Company'
    name = 'ALIAS-' + str(uuid4())
    values = {field: source.get(field) for field in identity.OBSERVED_FIELDS}
    values['custom_zatca_icv_counter'] = counter_reference
    if delegate:
        values.update(custom_linked_doctype=t.b.company.name, custom__use_company_certificate__keys=1)
        for field in identity.MATERIAL_FIELDS:
            values[field] = None
    doc = Document(doctype=doctype, name=name, **values)
    with t.connection.cursor() as cursor:
        fields = ('name', *identity.OBSERVED_FIELDS)
        cursor.execute('INSERT INTO `tab' + doctype + '` (' + ','.join('`' + field + '`' for field in fields) +
            ') VALUES (' + ','.join('%s' for _ in fields) + ')', tuple(doc.get(field) for field in fields))
    t.connection.commit()
    return doc


def add_counter(t, doc, *, purpose='Production', active=1, icv='999', unit=None):
    name = 'EXTRA-' + str(uuid4())
    unit = identity._legacy_unit(doc) if unit is None else unit
    with t.connection.cursor() as cursor:
        cursor.execute('INSERT INTO `tabZATCA ICV Counter` (name,company,issuing_unit,environment,counter_key,'
            'active,last_issued_icv) VALUES (%s,%s,%s,%s,%s,%s,%s)',
            (name, t.source.company, unit, purpose, name, active, icv))
    t.connection.commit()
    return name


@pytest.mark.parametrize('active,icv', [(1, '999'), (0, '999'), (1, '0')])
def test_known_same_key_counter_fragments_block_real_review_without_a_maximum_seed(legacy, active, icv):
    t = legacy
    copied = alias(t)
    add_counter(t, copied, active=active, icv=icv)
    with pytest.raises(registration.ChainRegistrationError, match='registration_consumer_counter_ambiguous') as failed:
        t.review()
    assert failed.value.__context__ is None and t.database.commits == 0
    assert t.runtime.get_doc(t.counter.doctype, t.counter.name).last_issued_icv == '27'
    t.b.request.assert_not_called()


def test_explicit_company_key_delegate_with_no_copied_material_still_exposes_its_counter(legacy):
    t = legacy
    delegated = alias(t, delegate=True)
    add_counter(t, delegated)
    with pytest.raises(registration.ChainRegistrationError, match='registration_consumer_counter_ambiguous'):
        t.review()
    assert t.database.commits == 0


@pytest.mark.parametrize('purpose', ['Compliance', 'Debug'])
def test_matching_test_purpose_counters_do_not_replace_the_production_tail(legacy, purpose):
    t = legacy
    add_counter(t, alias(t), purpose=purpose)
    result = t.review()
    assert result.last_icv == '27' and not result.active and t.database.commits == 1


def test_independently_keyed_unit_is_not_merged_by_a_matching_company_taxpayer(legacy):
    t = legacy
    add_counter(t, alias(t, independent=True))
    result = t.review()
    assert result.last_icv == '27' and not result.active


def test_a_family_pointer_to_a_missing_counter_is_not_ignored(legacy):
    t = legacy
    alias(t, counter_reference='MISSING-COUNTER')
    with pytest.raises(registration.ChainRegistrationError, match='registration_consumer_counter_missing'):
        t.review()
    assert t.database.commits == 0


def test_a_saved_pointer_preserves_discovery_after_the_token_derived_alias_changes(legacy):
    t = legacy
    copied = alias(t)
    extra = add_counter(t, copied, unit='company:RETIRED-TOKEN-ALIAS')
    t.change(copied, 'custom_zatca_icv_counter', extra)
    with pytest.raises(registration.ChainRegistrationError, match='registration_consumer_counter_ambiguous'):
        t.review()
    assert t.database.commits == 0


def test_a_fresh_key_with_the_same_saved_full_serial_is_not_an_independent_counter(legacy):
    t = legacy
    configuration = CONFIG.replace('1-TEST|2-TEST|3-SYNTHETIC', '1-TEST|2-TEST|3-' + str(uuid4()))
    t.change(t.selected, 'custom_csr_config', configuration)
    copied = alias(t, independent=True)
    t.change(copied, 'custom_csr_config', configuration)
    add_counter(t, copied)
    with pytest.raises(registration.ChainRegistrationError, match='registration_consumer_counter_ambiguous'):
        t.review()
    assert t.database.commits == 0


def test_a_copy_without_another_counter_is_observed_without_activating_or_rewriting_it(legacy):
    t = legacy
    copied = alias(t)
    before = t.runtime.get_doc(copied.doctype, copied.name)
    result = t.review()
    after = t.runtime.get_doc(copied.doctype, copied.name)
    assert vars(before) == vars(after) and result.last_icv == '27' and not result.active
    assert t.database.commits == 1


@pytest.mark.parametrize('denied', ['owner', 'counter'])
def test_unreadable_catalog_rows_cannot_be_omitted_from_the_negative_inventory(legacy, denied):
    t = legacy
    doc = alias(t, independent=True)
    extra = add_counter(t, doc)
    def permission(dt, operation, *, doc, user, raise_exception=True):
        return doc.name != (extra if denied == 'counter' else doc_name)
    doc_name = doc.name
    t.runtime.has_permission = permission
    code = 'registration_consumer_counter_permission' if denied == 'counter' else 'native_identity_inventory_permission'
    with pytest.raises(registration.ChainRegistrationError, match=code):
        t.review()
    assert t.database.commits == 0


@pytest.mark.parametrize('fault', ['owner_copy', 'counter_unit'])
def test_a_current_catalog_change_cannot_be_hidden_by_the_initial_orm_view(legacy, monkeypatch, fault):
    t = legacy
    copied = alias(t, independent=True)
    extra = add_counter(t, copied)
    peer = t.connections()
    original = t.runtime.get_doc
    injected = []
    def get_doc(doctype, name, **kwargs):
        result = original(doctype, name, **kwargs)
        if (doctype, name) == (t.source.doctype, t.source.name) and not kwargs.get('for_update') and not injected:
            injected.append(True)
            with peer.cursor() as cursor:
                if fault == 'owner_copy':
                    fields = identity.MATERIAL_FIELDS
                    cursor.execute('UPDATE `tabCompany` SET ' + ','.join('`' + field + '`=%s' for field in fields) +
                        ' WHERE name=%s', (*(t.selected.get(field) for field in fields), copied.name))
                else:
                    cursor.execute('UPDATE `tabZATCA ICV Counter` SET issuing_unit=%s WHERE name=%s',
                        (identity._legacy_unit(t.selected), extra))
            peer.commit()
        return result
    monkeypatch.setattr(t.runtime, 'get_doc', get_doc)
    code = 'native_identity_inventory_source_changed' if fault == 'owner_copy' else 'registration_consumer_counter_changed'
    with pytest.raises(registration.ChainRegistrationError, match=code) as failed:
        t.review()
    assert injected and failed.value.__context__ is None and t.database.commits == 0


@pytest.mark.parametrize('legacy,fault', [
    (('company', 0), 'authorization'), (('linked', 1), 'authorization'),
    (('company', 0), 'environment'), (('linked', 1), 'environment'), (('linked', 1), 'device_flag')], indirect=['legacy'])
def test_current_locked_issuer_records_cannot_use_an_older_captured_projection(legacy, monkeypatch, fault):
    t = legacy
    target = t.b.device if fault == 'device_flag' else t.b.company if fault == 'environment' else t.selected
    if fault == 'authorization':
        field = 'custom_basic_auth_from_production'
        token = base64.b64decode(target.get(field), validate=True).split(b':', 1)[0]
        value = base64.b64encode(token + b':ROTATED-TEST-SECRET').decode()
    else:
        field, value = ('custom_select', 'Simulation') if fault == 'environment' else ('custom__use_company_certificate__keys', '0')
    peer = t.connections()
    original = t.runtime.get_doc
    injected = []
    def get_doc(doctype, name, **kwargs):
        result = original(doctype, name, **kwargs)
        if (doctype, name) == (t.source.doctype, t.source.name) and not kwargs.get('for_update') and not injected:
            injected.append(True)
            with peer.cursor() as cursor:
                cursor.execute('UPDATE `tab' + target.doctype + '` SET `' + field + '`=%s WHERE name=%s', (value, target.name))
            peer.commit()
        return result
    monkeypatch.setattr(t.runtime, 'get_doc', get_doc)
    with pytest.raises(registration.ChainRegistrationError, match='registration_issuer_snapshot_changed') as failed:
        t.review()
    assert injected and failed.value.__context__ is None and t.database.commits == 0
    t.b.request.assert_not_called()


@pytest.mark.parametrize('operation', ['owner_insert', 'owner_update', 'counter_insert'])
def test_current_catalog_locks_hold_new_copy_or_counter_changes_until_review_ends(legacy, operation):
    t = legacy
    peer = t.connections()
    with peer.cursor() as cursor:
        cursor.execute('SET SESSION innodb_lock_wait_timeout=1')
    fingerprint = registration.inspect_embedded_certificate(t.xml).public_key_sha256
    with owned_worker_transaction(t.runtime) as owner:
        report = consumers.require_single_legacy_counter(t.runtime,owner,t.selected,fingerprint,
            t.source.custom_zatca_issuing_unit,t.counter.name)
        assert report.production_counters == (t.counter.name,)
        with peer.cursor() as cursor:
            with pytest.raises(pymysql.OperationalError) as failed:
                if operation == 'owner_insert':
                    cursor.execute('INSERT INTO `tabCompany` (name,custom_certificate,custom_private_key) VALUES (%s,%s,%s)',
                        ('LATE-' + str(uuid4()), t.selected.custom_certificate, t.selected.custom_private_key))
                elif operation == 'owner_update':
                    cursor.execute('UPDATE `tabCompany` SET custom_private_key=%s WHERE name=%s',
                        (t.selected.custom_private_key, t.b.linked.name))
                else:
                    name = 'LATE-' + str(uuid4())
                    cursor.execute('INSERT INTO `tabZATCA ICV Counter` (name,company,issuing_unit,environment,counter_key) '
                        'VALUES (%s,%s,%s,%s,%s)', (name,t.source.company,identity._legacy_unit(t.selected),'Production',name))
            assert failed.value.args[0] == 1205
        peer.rollback()
    with peer.cursor() as cursor:
        cursor.execute('UPDATE `tabCompany` SET custom_private_key=%s WHERE name=%s',
            (t.selected.custom_private_key,t.b.linked.name))
    peer.rollback()
    assert t.database.commits == 0
