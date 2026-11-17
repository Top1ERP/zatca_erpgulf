"""Owned native services together, using private SQL and mocked HTTP only.

The runtime/Company/source loaders are explicit framework doubles. Real signing,
temporary formatting, worker ownership, repository SQL, AES custody and response
assessment run together. No configured site, installed ERP or financial parity
is claimed; those retain their separate acceptance workstreams.
"""

from collections import deque
import base64
import hashlib
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from requests.structures import CaseInsensitiveDict

from zatca_erpgulf.zatca_erpgulf import (
    api_settings, credential_settings, native_dispatch, native_transport,
    sign_invoice, sign_invoice_first, submission_context,
)
from zatca_erpgulf.zatca_erpgulf.invoice_xml_core import INITIAL_PREVIOUS_HASH
from zatca_erpgulf.zatca_erpgulf.artifact_evidence import inspect_invoice_artifact
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_issuing_attempt import boundary, materials, setup
from zatca_erpgulf.zatca_erpgulf.tests.test_native_dispatch import signed_build
from zatca_erpgulf.zatca_erpgulf.tests.test_native_preparation import registration
from zatca_erpgulf.zatca_erpgulf.tests.test_native_dispatch_store_mariadb import (
    isolated_server, connections, tables, chain, Database, NAMESPACE,
)
from zatca_erpgulf.zatca_erpgulf.worker_transaction import CALLBACKS


pytestmark = pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB') != '1',
    reason='Owned private SQL opt-in only')


class OwnedDatabase(Database):
    """Inspected transaction/callback/connection shape; not installed Frappe."""
    def __init__(self, connection):
        super().__init__(connection)
        self._conn = connection
        self.cur_db_name = 'zatca_journal_rehearsal'
        self.db_type = 'mariadb'
        self.transaction_writes = 0
        self.auto_commit_on_many_writes = 0
        self.commits = 0
        for name in CALLBACKS:
            setattr(self, name, SimpleNamespace(_functions=deque()))

    def sql(self, statement, values=(), *, as_dict=True):
        result = super().sql(statement, values, as_dict=as_dict)
        if statement.lstrip().split()[0].upper() in ('INSERT', 'UPDATE', 'DELETE'):
            self.transaction_writes += 1
        return result

    def rollback(self):
        self.connection.rollback()
        self.connection.begin()
        self.transaction_writes = 0

    def commit(self):
        self.connection.commit()
        self.connection.begin()
        self.transaction_writes = 0
        self.commits += 1


class Runtime:
    def __init__(self, original, database):
        self.original = original
        self.local = SimpleNamespace(site='fictional.invalid', db=database)
        self.conf = {'db_name': 'zatca_journal_rehearsal',
            'encryption_key': base64.urlsafe_b64encode(b'T' * 32).decode()}

    @property
    def db(self):
        return self.local.db

    def __getattr__(self, name):
        return getattr(self.original, name)


@pytest.mark.parametrize('kind,index', [('company', 0), ('device', 2), ('linked', 1)])
@pytest.mark.parametrize('mode', ['simplified', 'standard303'])
def test_native_sales_and_pos_keep_one_chain_through_committed_mocked_dispatch(
        boundary, materials, monkeypatch, connections, tables, chain, kind, index, mode):
    b = boundary
    selected_owner = setup(b, monkeypatch, kind)
    suffix = '-' + kind + '-' + mode
    for record in (b.company, b.linked, b.device):
        record.name += suffix
    b.device.custom_linked_doctype = b.linked.name if kind == 'linked' else b.company.name
    for source in (b.sales, b.pos):
        source.name += suffix
        source.company = b.company.name
        source.custom_zatca_pos_name = None if kind == 'company' else b.device.name
    b.company.custom_zatca_invoice_enabled = 1
    b.company.custom_phase_1_or_2 = 'Phase-2'
    b.company.company_name = 'Synthetic issuer'
    connection = connections()
    database = OwnedDatabase(connection)
    runtime = Runtime(b.frappe, database)
    b.frappe = runtime
    for module in (api_settings, credential_settings, sign_invoice, sign_invoice_first, submission_context):
        monkeypatch.setattr(module, 'frappe', runtime)
    runtime.has_permission = lambda doctype, operation, *, doc, user, raise_exception=True: True
    runtime.get_meta = lambda doctype: SimpleNamespace(get_table_fields=lambda: [])
    fingerprint = registration(b, selected_owner, materials[index])
    key = native_dispatch.owner_key(selected_owner.doctype, selected_owner.name, 'Production')
    with connection.cursor() as cursor:
        cursor.execute('CREATE TABLE IF NOT EXISTS `tabSingles` (`doctype` VARCHAR(140), `field` VARCHAR(140),'
            '`value` LONGTEXT, PRIMARY KEY(doctype,field)) ENGINE=InnoDB')
        cursor.executemany('INSERT IGNORE INTO `tabSingles` VALUES (%s,%s,%s)', [
            ('ZATCA Dispatch Control', 'storage_namespace', NAMESPACE),
            ('ZATCA Dispatch Control', 'storage_version', '1')])
        for table in ('tabCompany', 'tabZATCA Multiple Setting'):
            cursor.execute('CREATE TABLE IF NOT EXISTS `' + table + '` (`name` VARCHAR(140) PRIMARY KEY,'
                '`custom_pih` VARCHAR(140)) ENGINE=InnoDB')
        cursor.executemany('INSERT IGNORE INTO `tabCompany` VALUES (%s,%s)',
            [(b.company.name, INITIAL_PREVIOUS_HASH), (b.linked.name, INITIAL_PREVIOUS_HASH)])
        cursor.execute('INSERT IGNORE INTO `tabZATCA Multiple Setting` VALUES (%s,%s)', (b.device.name, INITIAL_PREVIOUS_HASH))
        for table, source in (('tabSales Invoice', b.sales), ('tabPOS Invoice', b.pos)):
            cursor.execute('CREATE TABLE IF NOT EXISTS `' + table + '` (`name` VARCHAR(140) PRIMARY KEY, `docstatus` INT,'
                '`custom_uuid` VARCHAR(140), `custom_zatca_icv` VARCHAR(140), `custom_zatca_issuing_unit` VARCHAR(140)) ENGINE=InnoDB')
            cursor.execute('INSERT INTO `' + table + '` (name,docstatus) VALUES (%s,1)', (source.name,))
        cursor.execute('UPDATE `tabZATCA Issuing Chain` SET owner_key=%s,active_owner_key=%s,owner_doctype=%s,owner_name=%s,'
            'certificate_sha256=%s,public_key_sha256=%s WHERE name=%s',
            (key, key, selected_owner.doctype, selected_owner.name, fingerprint['certificate_sha256'],
             fingerprint['public_key_sha256'], chain['record_id']))
    connection.commit()

    prototypes = {(doc.doctype, doc.name): doc for doc in (b.company, b.linked, b.device, b.sales, b.pos)}
    def get_doc(doctype, name, **kwargs):
        if doctype == 'Company' and type(name) is dict:
            assert name == {'abbr': 'TC'}
            name = b.company.name
        assert doctype in ('Company', 'ZATCA Multiple Setting', 'Sales Invoice', 'POS Invoice')
        suffix = ' FOR UPDATE NOWAIT' if kwargs.get('for_update') else ''
        row = runtime.db.sql('SELECT * FROM `tab' + doctype + '` WHERE name=%s' + suffix, (name,), as_dict=True)[0]
        return Document(**(vars(prototypes[doctype, name]) | dict(row)))
    runtime.get_doc = get_doc
    address = Document(address_line1='Test Street', address_line2='District', city='Riyadh',
        custom_building_number='1234', pincode='12345', state='')
    monkeypatch.setattr(sign_invoice, '_onboarding_address', lambda *args: address)
    sent = []
    def send(prepared, **kwargs):
        # A separate connection sees the committed reservation/source outputs and
        # can lock the chain NOWAIT: no preparation/attempt row lock spans HTTP.
        fresh = connections()
        observed = inspect_invoice_artifact(base64.b64decode(json.loads(prepared.body)['invoice']))
        with fresh.cursor() as cursor:
            cursor.execute('SELECT last_icv FROM `tabZATCA Issuing Chain` WHERE name=%s FOR UPDATE NOWAIT',
                (chain['record_id'],))
            assert cursor.fetchone()[0] == str(observed.icv)
            cursor.execute('SELECT COUNT(*) FROM `tabZATCA Dispatch Attempt` a '
                'JOIN `tabZATCA Issuance` i ON i.name=a.issuance WHERE a.state=%s AND i.chain=%s',
                ('STARTED', chain['record_id']))
            assert cursor.fetchone()[0] == 1
        fresh.rollback()
        sent.append(prepared.body)
        clearing = prepared.url.endswith('/invoices/clearance/single')
        raw = b'Clearance disabled' if clearing else b' {"validationResults":{"status":"PASS","errorMessages":[],"warningMessages":[],"infoMessages":[]},"reportingStatus":"REPORTED"} '
        return SimpleNamespace(request=prepared, url=prepared.url, history=[], status_code=303 if clearing else 200,
            headers=CaseInsensitiveDict({'x-request-id': 'synthetic'}), close=Mock(),
            raw=SimpleNamespace(read1=Mock(side_effect=[raw, b''])))
    adapter = SimpleNamespace(send=Mock(side_effect=send), close=Mock())
    monkeypatch.setattr(native_transport, 'HTTPAdapter', lambda **kwargs: adapter)
    previous = INITIAL_PREVIOUS_HASH
    for index, source in enumerate((b.sales, b.pos), 1):
        validation_type = 'Standard Invoice' if mode == 'standard303' else 'Simplified Invoice'
        endpoint = 'invoices/clearance/single' if mode == 'standard303' else 'invoices/reporting/single'
        outcome = native_dispatch.dispatch_saved_invoice(source.doctype, source.name, runtime=runtime,
            translate=lambda text: text,
            build=lambda locked: signed_build(b, locked, validation_type=validation_type, endpoint=endpoint))
        assert outcome.current and outcome.outcome == 'REPORTING_MATCHED'
        row = database.sql('SELECT state,icv,previous_hash,invoice_hash,artifact_sha256 FROM `tabZATCA Issuance` WHERE name=%s',
            (outcome.issuance_id,), as_dict=True)[0]
        assert row['state'] == 'REPORTED' and row['icv'] == str(index) and row['previous_hash'] == previous
        previous = row['invoice_hash']
        saved = get_doc(source.doctype, source.name)
        assert saved.custom_zatca_icv == str(index) and saved.custom_uuid == json.loads(sent[-1])['uuid']
        assert saved.custom_zatca_issuing_unit == 'egs:' + chain['record_id']
        assert hashlib.sha256(sent[-1]).hexdigest() == row['artifact_sha256']
        if mode == 'standard303':
            assert sent[-2] == sent[-1]  # Same signed original, not a second issuance.
        original_key=selected_owner.custom_private_key
        selected_owner.custom_private_key='INVALID-KEY-MUST-NOT-BE-READ'
        permission=runtime.has_permission
        runtime.has_permission=lambda doctype, operation, *, doc, user, raise_exception=True: operation=='read'
        try:
            view=native_dispatch.read_retained_invoice(source.doctype,source.name,runtime=runtime)
            assert view.accepted and view.issuance_id==outcome.issuance_id
            original=base64.b64decode(json.loads(sent[-1])['invoice'])
            assert view.original_xml==original
            before=adapter.send.call_count
            cached=native_dispatch.dispatch_saved_invoice(source.doctype,source.name,runtime=runtime,
                translate=lambda text:text,build=lambda saved:pytest.fail('Accepted original was rebuilt'))
            assert cached.reused_accepted and cached.issuance_id==outcome.issuance_id
            assert adapter.send.call_count==before
        finally:
            selected_owner.custom_private_key=original_key
            runtime.has_permission=permission
    assert database.commits == (14 if mode == 'standard303' else 8)
    assert adapter.send.call_count == (4 if mode == 'standard303' else 2)
    assert get_doc(selected_owner.doctype, selected_owner.name).custom_pih == previous
    b.request.assert_not_called()
