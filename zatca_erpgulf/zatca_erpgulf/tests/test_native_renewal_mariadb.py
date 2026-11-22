"""Actual pending-renewal service on private fixture SQL, never a live issuer."""

from datetime import datetime, timezone
import os
from unittest.mock import Mock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from zatca_erpgulf.zatca_erpgulf import native_renewal as renewal
from zatca_erpgulf.zatca_erpgulf.credential_snapshot import CredentialSnapshot, CredentialSnapshotError
from zatca_erpgulf.zatca_erpgulf.api_routing import resolve_api_route
from zatca_erpgulf.zatca_erpgulf.credential_material import CredentialOwner
from zatca_erpgulf.zatca_erpgulf.renewal_custody import OLD_FIELDS, RenewalStore
from zatca_erpgulf.zatca_erpgulf.worker_transaction import owned_worker_transaction
from zatca_erpgulf.zatca_erpgulf.tests.test_native_enrollment_mariadb import flow
from zatca_erpgulf.zatca_erpgulf.tests.test_native_onboarding_mariadb import target, boundary, materials, connections, isolated_server, tables


pytestmark = pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB') != '1', reason='Fixture-owned private Unix SQL only')
REASON = 'Prepare reviewed renewal while preserving the active issuer.'


@pytest.fixture
def active(flow):
    f = flow; f.request(); f.request('production/csids'); t = f.t
    # Explicit synthetic activation input; no real activation/drain or authority
    # enrollment is invoked or qualified by this fixture.
    with t.connection.cursor() as cursor:
        cursor.execute('UPDATE `tabZATCA Issuing Chain` SET active=1,active_owner_key=owner_key,last_icv=%s '
            'WHERE name=%s', ('27', f.prepared.record_id))
    t.connection.commit()
    saved = t.runtime.get_doc(t.selected.doctype, t.selected.name)
    t.old_values = {name: saved.get(name) for name in OLD_FIELDS}
    t.chain_id = f.prepared.record_id; t.initial_calls = len(f.calls); t.flow = f
    t.prepare_renewal = lambda reason=REASON: renewal.prepare_renewal(t.chain_id, reason, runtime=t.runtime)
    t.renewals = lambda: t.database.sql('SELECT * FROM `tabZATCA CSID Renewal` WHERE old_chain=%s', (t.chain_id,), as_dict=True)
    return t


@pytest.mark.parametrize('target', ['company', 'device'], indirect=True)
def test_pending_key_csr_and_exact_old_material_commit_without_changing_active_settings(active):
    t = active; commits = t.database.commits; prepared = t.prepare_renewal()
    assert not prepared.reused and prepared.old_chain == t.chain_id and not prepared.old_certificate_expired
    current = t.runtime.get_doc(t.selected.doctype, t.selected.name)
    assert {name: current.get(name) for name in OLD_FIELDS} == t.old_values
    assert t.flow.state()['last_icv'] == '27' and t.flow.state()['active'] == 1
    rows = t.renewals(); assert len(rows) == 1 and rows[0]['state'] == 'CSR_READY'
    assert 'PRIVATE KEY' not in rows[0]['preparation_ciphertext'] and 'PRIVATE KEY' not in rows[0]['preparation_header']
    with owned_worker_transaction(t.runtime) as owner:
        header, material = RenewalStore(owner).pending(rows[0]['owner_key'])
        assert dict(material.old) == t.old_values
        key = serialization.load_pem_private_key(material.private_key.encode(), password=None)
        csr = x509.load_pem_x509_csr(material.csr)
        assert csr.is_signature_valid and csr.public_key().public_numbers() == key.public_key().public_numbers()
        assert header['new_public_key_sha256'] != header['old_public_key_sha256']
    again = t.prepare_renewal()
    assert again.reused and again.record_id == prepared.record_id and again.csr_data == prepared.csr_data
    assert t.database.commits == commits+1 and len(t.flow.calls) == t.initial_calls
    t.selected.save.assert_not_called(); t.b.request.assert_not_called()


def test_lost_commit_ack_recovers_exact_pending_key_without_generating_another(active, monkeypatch):
    t = active; commit = t.database.commit
    def lost(): commit(); raise RuntimeError('PRIVATE LOST ACK')
    monkeypatch.setattr(t.database, 'commit', lost)
    with pytest.raises(renewal.NativeRenewalError) as caught: t.prepare_renewal()
    assert caught.value.commit_uncertain and 'PRIVATE' not in str(caught.value)
    row = t.renewals()[0]
    monkeypatch.setattr(t.database, 'commit', commit)
    monkeypatch.setattr(renewal.ec, 'generate_private_key', Mock(side_effect=AssertionError('No replacement key')))
    again = t.prepare_renewal()
    assert again.reused and again.record_id == row['record_id'] and len(t.renewals()) == 1


@pytest.mark.parametrize('fault', ['manager', 'owner-read', 'owner-write', 'chain-read', 'rollout', 'marker', 'certificate', 'identity'])
def test_invalid_current_owner_and_permissions_cannot_stage_or_replace_material(active, fault):
    t = active; commits = t.database.commits
    if fault == 'manager': t.runtime.get_roles = lambda actor: []
    elif fault in ('owner-read', 'owner-write', 'chain-read'):
        def permitted(dt, operation, *, doc, user, raise_exception=True):
            return not ((dt == t.selected.doctype and doc.name == t.selected.name and operation == fault.removeprefix('owner-'))
                or (fault == 'chain-read' and dt == 'ZATCA Issuing Chain'))
        t.runtime.has_permission = permitted
    elif fault == 'rollout': t.runtime.conf['zatca_native_dispatch'] = 0
    else:
        field = {'marker': 'custom_zatca_native_chain', 'certificate': 'custom_private_key', 'identity': 'custom_csr_config'}[fault]
        with t.connection.cursor() as cursor:
            cursor.execute('UPDATE `tab'+t.selected.doctype+'` SET `'+field+'`=%s WHERE name=%s', ('INVALID', t.selected.name))
        t.connection.commit()
    with pytest.raises(renewal.NativeRenewalError): t.prepare_renewal()
    assert t.database.commits == commits and not t.renewals() and len(t.flow.calls) == t.initial_calls


@pytest.mark.parametrize('fault', ['reason', 'ciphertext', 'header', 'index', 'route'])
def test_changed_or_corrupt_pending_custody_is_held_instead_of_reset(active, fault):
    t = active; t.prepare_renewal(); row = t.renewals()[0]; commits = t.database.commits
    if fault == 'route': t.b.company.custom_production_url = 'https://other.invalid/core'
    elif fault != 'reason':
        field = {'ciphertext': 'preparation_ciphertext', 'header': 'preparation_header', 'index': 'old_chain'}[fault]
        with t.connection.cursor() as cursor:
            cursor.execute('UPDATE `tabZATCA CSID Renewal` SET `'+field+'`=%s WHERE name=%s', ('INVALID', row['name']))
        t.connection.commit()
    with pytest.raises(renewal.NativeRenewalError): t.prepare_renewal('Different reason' if fault == 'reason' else REASON)
    assert t.database.commits == commits


def test_expired_certificate_can_be_retained_for_local_preparation_but_not_invoice_signing(active, monkeypatch):
    t = active; sql = t.database.sql
    def clock(statement, values=(), **kwargs):
        return [{'utc_now': datetime(2036, 1, 1)}] if statement == 'SELECT UTC_TIMESTAMP(6) AS utc_now' else sql(statement, values, **kwargs)
    monkeypatch.setattr(t.database, 'sql', clock)
    assert t.prepare_renewal().old_certificate_expired
    current = t.runtime.get_doc(t.selected.doctype, t.selected.name)
    owner = CredentialOwner(current.name, current.doctype, current.name, 'company', t.old_values)
    with pytest.raises(CredentialSnapshotError, match='snapshot_certificate_time'):
        CredentialSnapshot(owner, resolve_api_route(vars(t.b.company), 'invoices/reporting/single'),
            current.custom_certificate, datetime(2036, 1, 1, tzinfo=timezone.utc))


def test_pending_preparation_does_not_freeze_or_rewind_a_later_old_epoch_counter(active):
    t = active; first = t.prepare_renewal()
    with t.connection.cursor() as cursor:
        cursor.execute('UPDATE `tabZATCA Issuing Chain` SET last_icv=%s,state_version=state_version+1 WHERE name=%s', ('28', t.chain_id))
    t.connection.commit()
    again = t.prepare_renewal()
    assert again.reused and again.record_id == first.record_id and t.flow.state()['last_icv'] == '28'


@pytest.mark.parametrize('parent', ['write', 'callback'])
def test_renewal_preparation_preserves_foreign_parent_work(active, parent):
    t = active; commits = t.database.commits
    if parent == 'write':
        t.database.sql('UPDATE `tabZATCA Issuing Chain` SET last_icv=%s WHERE name=%s', ('29', t.chain_id))
    else: t.database.before_commit._functions.append(lambda: None)
    with pytest.raises(renewal.NativeRenewalError) as caught: t.prepare_renewal()
    assert caught.value.code == 'worker_transaction_parent_state' and t.database.commits == commits
    if parent == 'write': assert t.flow.state()['last_icv'] == '29' and t.database.transaction_writes == 1
    else: assert len(t.database.before_commit._functions) == 1


def test_changed_material_during_key_generation_rolls_back_without_partial_custody(active, monkeypatch):
    t = active; generate = renewal.ec.generate_private_key; commits = t.database.commits
    def changed(*args, **kwargs):
        t.database.sql('UPDATE `tab'+t.selected.doctype+'` SET custom_public_key=%s WHERE name=%s', ('CHANGED', t.selected.name))
        return generate(*args, **kwargs)
    monkeypatch.setattr(renewal.ec, 'generate_private_key', changed)
    with pytest.raises(renewal.NativeRenewalError) as caught: t.prepare_renewal()
    assert caught.value.code == 'native_renewal_source_changed'
    assert t.database.commits == commits and not t.renewals()
    assert t.runtime.get_doc(t.selected.doctype, t.selected.name).get('custom_public_key') == t.old_values['custom_public_key']
