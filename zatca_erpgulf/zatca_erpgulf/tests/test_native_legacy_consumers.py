"""Public identity closure and counter contradiction policy; no authority/site."""

import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import native_legacy_consumers as consumers
from zatca_erpgulf.zatca_erpgulf.chain_registration import ChainRegistrationError
from zatca_erpgulf.zatca_erpgulf.native_identity_inventory import OwnerIdentity, IdentityInventory
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document


def identity(name, *, doctype='Company', keys=('a' * 64,), units=(), linked=None, delegate=False, counter=None):
    return OwnerIdentity(doctype, name, 'Production', linked, delegate, keys, units, (), True,
        ('company:' if doctype == 'Company' else 'setting:') + name, counter)


@pytest.fixture
def case(monkeypatch):
    owners = [identity('ROOT', counter='COUNTER'), identity('ALIAS'), identity('INDEPENDENT', keys=('b' * 64,))]
    selected = Document(doctype='Company', name='ROOT')
    counter = Document(doctype='ZATCA ICV Counter', name='COUNTER', company='ROOT', issuing_unit='company:HISTORIC',
        environment='Production', counter_key='COUNTER', active=1, last_issued_icv='27',
        last_invoice_doctype='Sales Invoice', last_invoice='SOURCE')
    records = {'COUNTER': counter}
    owner = SimpleNamespace(owner_current=Mock(return_value=True), actor='operator@example.invalid')
    def sql(statement, values=(), *, as_dict=True):
        if 'information_schema.tables' in statement:
            return [{'table_name': 'tabZATCA ICV Counter', 'engine': 'InnoDB'}]
        assert 'FORCE INDEX (PRIMARY)' in statement and 'LOCK IN SHARE MODE NOWAIT' in statement
        assert values == (consumers.MAX_COUNTERS + 1,)
        return [dict(vars(records[name])) for name in sorted(records)]
    owner.database = SimpleNamespace(sql=Mock(side_effect=sql))
    def permission(dt, operation, *, doc, user, raise_exception=True):
        assert operation == 'read' and raise_exception is False
        return True
    runtime = SimpleNamespace(get_doc=Mock(side_effect=lambda dt, name: records[name]), has_permission=permission)
    monkeypatch.setattr(consumers, 'collect_identity_inventory', lambda runtime, owner: IdentityInventory(tuple(owners), 'd' * 64))
    def inspect():
        return consumers.require_single_legacy_counter(runtime, owner, selected, 'a' * 64, 'company:HISTORIC', 'COUNTER')
    return SimpleNamespace(owners=owners, selected=selected, counter=counter, records=records,
        runtime=runtime, owner=owner, inspect=inspect)


def test_public_key_serial_and_delegate_relations_are_transitive_without_vat_merging():
    rows = (identity('ROOT', units=('e' * 64,)), identity('BRIDGE', keys=('a' * 64, 'b' * 64)),
        identity('NEXT', keys=('b' * 64,)), identity('RENEWED', keys=('c' * 64,), units=('e' * 64,)),
        identity('DELEGATE', doctype='ZATCA Multiple Setting', keys=(), linked='ROOT', delegate=True),
        identity('INDEPENDENT', doctype='ZATCA Multiple Setting', keys=('f' * 64,), linked='ROOT'))
    result = consumers._family(IdentityInventory(rows, 'd' * 64), Document(doctype='Company', name='ROOT'), 'a' * 64)
    assert {row.name for row in result} == {'ROOT', 'BRIDGE', 'NEXT', 'RENEWED', 'DELEGATE'}


def test_large_shared_identity_bucket_yields_each_consumer_once():
    rows = tuple(identity('OWNER-' + str(number)) for number in range(1000))
    report = consumers._family(IdentityInventory(rows, 'd' * 64), Document(doctype='Company', name='OWNER-0'), 'a' * 64)
    assert len(report) == len({(row.doctype, row.name) for row in report}) == 1000


def test_one_known_counter_is_an_inactive_negative_inventory_not_genesis(case):
    report = case.inspect()
    assert report.production_counters == ('COUNTER',) and len(report.consumers) == 2
    assert report.unattributed_counters == 0 and not report.other_purpose_counters
    assert not hasattr(report, 'active') and not hasattr(report, 'genesis_allowed')
    with pytest.raises(TypeError, match='not_serializable'):
        pickle.dumps(report)


@pytest.mark.parametrize('active,icv', [(1, '999'), (0, '999'), (1, '0'), (0, '0')])
def test_another_known_production_counter_is_not_merged_or_declared_unused(case, active, icv):
    c = case
    c.records['EXTRA'] = Document(**(vars(c.counter) | dict(name='EXTRA', issuing_unit='company:ALIAS',
        active=active, last_issued_icv=icv)))
    with pytest.raises(ChainRegistrationError, match='registration_consumer_counter_ambiguous'):
        c.inspect()


@pytest.mark.parametrize('purpose', ['Compliance', 'Debug'])
def test_matching_nonproduction_purpose_is_reported_separately(case, purpose):
    c = case
    c.records['CHECK'] = Document(**(vars(c.counter) | dict(name='CHECK', issuing_unit='company:ALIAS', environment=purpose)))
    report = c.inspect()
    assert report.other_purpose_counters == ('CHECK',) and report.production_counters == ('COUNTER',)


def test_an_unattributed_historical_counter_is_visible_but_not_proof_of_ownership(case):
    c = case
    c.records['UNKNOWN'] = Document(**(vars(c.counter) | dict(name='UNKNOWN', issuing_unit='company:ROTATED-UNKNOWN')))
    report = c.inspect()
    assert report.unattributed_counters == 1 and report.production_counters == ('COUNTER',)


@pytest.mark.parametrize('fault,code', [('missing_ref', 'registration_consumer_counter_missing'),
    ('ref_purpose', 'registration_consumer_counter_purpose'), ('unknown_purpose', 'registration_consumer_counter_purpose'),
    ('counter_identity', 'registration_consumer_counter_identity'), ('old_counter', 'registration_consumer_counter_changed'),
    ('permission', 'registration_consumer_counter_permission'), ('overflow', 'registration_consumer_counter_limit'),
    ('root', 'registration_consumer_owner_review'), ('link', 'registration_consumer_link_review')])
def test_incomplete_or_conflicting_census_holds(case, monkeypatch, fault, code):
    c = case
    if fault == 'missing_ref':
        c.owners.append(identity('MISSING', counter='ABSENT'))
    elif fault == 'ref_purpose':
        c.counter.environment = 'Compliance'
    elif fault == 'unknown_purpose':
        c.records['UNKNOWN'] = Document(**(vars(c.counter) | dict(name='UNKNOWN', issuing_unit='company:ALIAS', environment='Sandbox')))
    elif fault in ('counter_identity', 'old_counter'):
        c.runtime.get_doc.side_effect = lambda dt, name: Document(**(vars(c.counter) |
            (dict(name='WRONG') if fault == 'counter_identity' else dict(last_issued_icv='26'))))
    elif fault == 'permission':
        def denied(dt, operation, *, doc, user, raise_exception=True): return False
        c.runtime.has_permission = denied
    elif fault == 'overflow':
        monkeypatch.setattr(consumers, 'MAX_COUNTERS', 0)
    elif fault == 'root':
        c.selected.name = 'NOT-SAVED'
    else:
        c.owners.append(identity('BROKEN', doctype='ZATCA Multiple Setting', linked='ABSENT', delegate=True))
    with pytest.raises(ChainRegistrationError, match=code):
        c.inspect()
