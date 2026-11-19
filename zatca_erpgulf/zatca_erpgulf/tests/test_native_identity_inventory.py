"""Bounded saved-owner identity discovery; no site or authority interaction."""

import base64
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

from cryptography.hazmat.primitives import serialization
import pytest

from zatca_erpgulf.zatca_erpgulf import native_identity_inventory as inventory
from zatca_erpgulf.zatca_erpgulf.credential_identity import declared_egs_identity_key
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_onboarding_response import material, parse
from zatca_erpgulf.zatca_erpgulf.tests.test_native_onboarding_mariadb import CONFIG


@pytest.fixture
def case(material):
    config = CONFIG.replace('1-TEST|2-TEST|3-SYNTHETIC', material.header['csr_serial'])
    company = Document(doctype='Company', name='OWNER', custom_select=' Production ', custom_csr_config=config)
    other = Document(doctype='Company', name='OTHER', custom_select='Production',
        custom_csr_config=config.replace(material.header['csr_serial'], '1-OTHER|2-OTHER|3-OTHER'))
    device = Document(doctype='ZATCA Multiple Setting', name='DEVICE', custom_linked_doctype='OWNER',
        custom__use_company_certificate__keys=1)
    documents = {(doc.doctype, doc.name): doc for doc in (company, other, device)}
    def sql(statement, values=(), *, as_dict=True):
        if statement.startswith('SELECT @@tx_isolation'):
            return [{'isolation_level': 'REPEATABLE-READ'}]
        if 'information_schema.tables' in statement:
            return [{'table_name': name, 'engine': 'InnoDB'} for name in values]
        assert 'FORCE INDEX (PRIMARY) ORDER BY name LIMIT %s LOCK IN SHARE MODE NOWAIT' in statement
        assert values == (inventory.MAX_OWNERS_PER_TABLE + 1,)
        doctype = 'Company' if '`tabCompany`' in statement else 'ZATCA Multiple Setting'
        return [dict(vars(documents[dt, name])) for dt, name in sorted(documents) if dt == doctype]
    database = SimpleNamespace(sql=Mock(side_effect=sql))
    owner = SimpleNamespace(database=database, actor='operator@example.invalid', owner_current=Mock(return_value=True))
    permission_calls = Mock(return_value=True)
    def permission(dt, operation, *, doc, user, raise_exception=True):
        return permission_calls(dt, operation, doc=doc, user=user, raise_exception=raise_exception)
    runtime = SimpleNamespace(get_doc=Mock(side_effect=lambda dt, name: documents[dt, name]),
        has_permission=permission, permission_calls=permission_calls)
    identity = declared_egs_identity_key('Production', material.header['seller_tax_id'], material.header['csr_serial'])
    return SimpleNamespace(owner=owner, runtime=runtime, company=company, other=other, device=device,
        documents=documents, config=config, identity=identity, material=material)


def test_inventory_records_delegates_separately_and_never_exports_credentials(case):
    c = case
    c.company.custom_private_key = c.material.key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    result = inventory.collect_identity_inventory(c.runtime, c.owner)
    assert len(result.owners) == 3 and len(result.sha256) == 64
    assert result.declaring(c.identity)[0].public_keys == (c.material.header['public_key_sha256'],)
    delegate = next(row for row in result.owners if row.name == 'DEVICE')
    assert delegate.delegates_to_company and delegate.linked_company == 'OWNER'
    assert not delegate.public_keys and not delegate.declared_units
    assert 'PRIVATE KEY' not in str(result) and 'PRIVATE KEY' not in str(vars(result))
    assert c.owner.database.sql.call_count == 4 and c.runtime.permission_calls.call_count == 3
    for call in c.runtime.permission_calls.call_args_list:
        assert call.args[1] == 'read' and call.kwargs['raise_exception'] is False
    with pytest.raises(TypeError, match='not_serializable'):
        pickle.dumps(result)


@pytest.mark.parametrize('field', inventory.MATERIAL_FIELDS[:-1])
def test_each_credential_alias_is_observed_independently_and_claimed_identity_holds_new_key(case, field):
    c = case
    issued = parse(c.material)
    values = {'custom_private_key': c.material.key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode(),
        'custom_public_key': c.material.key.public_key().public_bytes(serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo).decode(),
        'custom_csr_data': base64.b64encode(c.material.raw).decode(),
        'custom_certificate': issued.certificate_text, 'custom_certficate': issued.certificate_text,
        **{name: issued.authorization for name in ('custom_basic_auth_from_csid',
            'custom_basic_auth_from_production', 'custom_final_auth_csid')}}
    c.other.custom_csr_config = c.config
    setattr(c.other, field, values[field])
    result = inventory.collect_identity_inventory(c.runtime, c.owner)
    other = next(row for row in result.owners if row.name == 'OTHER')
    assert other.public_keys == (c.material.header['public_key_sha256'],)
    with pytest.raises(inventory.IdentityInventoryError, match='declaration_conflict'):
        inventory.require_distinct_new_declaration(c.runtime, c.owner, c.company, c.identity)


@pytest.mark.parametrize('environment', ['Sandbox', 'Simulation', 'Production', None, '', 'INVALID'])
def test_device_claims_use_saved_linked_company_environment_without_production_guess(case, environment):
    c = case
    c.other.custom_select = environment
    c.device.custom_linked_doctype = 'OTHER'
    c.device.custom_csr_config = c.config
    c.device.custom_private_key = 'MALFORMED-BUT-NONEMPTY'
    result = inventory.collect_identity_inventory(c.runtime, c.owner)
    device = next(row for row in result.owners if row.doctype == 'ZATCA Multiple Setting')
    known = environment in inventory.ENVIRONMENTS
    assert device.environment == (environment if known else None)
    assert len(device.declared_units) == (1 if known else 3)
    assert device.unparsed_fields == ('custom_private_key',)
    if environment not in ('Sandbox', 'Simulation'):
        with pytest.raises(inventory.IdentityInventoryError, match='declaration_conflict'):
            inventory.require_distinct_new_declaration(c.runtime, c.owner, c.company, c.identity)
    else:
        inventory.require_distinct_new_declaration(c.runtime, c.owner, c.company, c.identity)


@pytest.mark.parametrize('field,value', [('custom_private_key', 'INVALID'), ('custom_pih', 'OLD-HASH'),
    ('custom_zatca_icv_counter', 'OLD-COUNTER'), ('custom_zatca_native_chain', 'OLD-CHAIN')])
def test_same_declaration_with_material_or_history_holds_even_without_parseable_certificate(case, field, value):
    c = case
    c.other.custom_csr_config = c.config
    setattr(c.other, field, value)
    with pytest.raises(inventory.IdentityInventoryError, match='declaration_conflict'):
        inventory.require_distinct_new_declaration(c.runtime, c.owner, c.company, c.identity)


def test_unused_shared_config_is_visible_but_has_no_material_or_history_yet(case):
    c = case
    c.other.custom_csr_config = c.config
    result = inventory.require_distinct_new_declaration(c.runtime, c.owner, c.company, c.identity)
    assert len(result.declaring(c.identity)) == 2
    assert not any(row.has_material_or_history for row in result.declaring(c.identity))
    assert not hasattr(result, 'active') and not hasattr(result, 'genesis_allowed')


@pytest.mark.parametrize('field', ['custom_certificate', 'custom_certficate',
    'custom_basic_auth_from_csid', 'custom_basic_auth_from_production', 'custom_final_auth_csid'])
def test_certificate_claim_without_config_still_finds_legacy_unit(case, field):
    c = case
    issued = parse(c.material)
    c.other.custom_csr_config = None
    setattr(c.other, field, issued.certificate_text if field.startswith('custom_cert') else issued.authorization)
    with pytest.raises(inventory.IdentityInventoryError, match='declaration_conflict'):
        inventory.require_distinct_new_declaration(c.runtime, c.owner, c.company, c.identity)


def test_bad_alias_does_not_conceal_a_valid_certificate_claim(case):
    c = case
    c.other.custom_csr_config = None
    c.other.custom_private_key = 'BAD-ALIAS'
    c.other.custom_certificate = parse(c.material).certificate_text
    row = next(row for row in inventory.collect_identity_inventory(c.runtime, c.owner).owners if row.name == 'OTHER')
    assert row.unparsed_fields == ('custom_private_key',) and c.identity in row.declared_units
    with pytest.raises(inventory.IdentityInventoryError, match='declaration_conflict'):
        inventory.require_distinct_new_declaration(c.runtime, c.owner, c.company, c.identity)


@pytest.mark.parametrize('fault', ['permission', 'source', 'duplicate', 'overflow', 'driver', 'owner',
    'owner_after_acl', 'size', 'shape', 'link_flag', 'missing_target'])
def test_incomplete_inventory_is_static_review_without_secret_exception_context(case, monkeypatch, fault):
    c = case
    if fault == 'permission':
        c.runtime.permission_calls.return_value = False
    elif fault == 'source':
        c.runtime.get_doc.side_effect = lambda dt, name: Document(doctype=dt, name='WRONG')
    elif fault == 'duplicate':
        sql = c.owner.database.sql.side_effect
        c.owner.database.sql.side_effect = lambda statement, values=(), **kw: (
            [vars(c.company), vars(c.company)] if 'FORCE INDEX' in statement else sql(statement, values, **kw))
    elif fault == 'overflow':
        monkeypatch.setattr(inventory, 'MAX_OWNERS_PER_TABLE', 1)
    elif fault == 'driver':
        c.owner.database.sql.side_effect = RuntimeError('PRIVATE-SQL-OR-CREDENTIAL')
    elif fault == 'owner':
        c.owner.owner_current.return_value = False
    elif fault == 'owner_after_acl':
        def acl(dt, operation, *, doc, user, raise_exception=True):
            c.owner.owner_current.return_value = False
            return True
        c.runtime.permission_calls.side_effect = acl
    elif fault == 'size':
        c.other.custom_private_key = 'X' * (inventory.MAX_MATERIAL_BYTES + 1)
    elif fault == 'shape':
        c.other.custom_private_key = 7
    elif fault == 'link_flag':
        c.device.custom__use_company_certificate__keys = 'INVALID'
    else:
        del c.documents['Company', 'OWNER']
    with pytest.raises(inventory.IdentityInventoryError) as failed:
        inventory.require_distinct_new_declaration(c.runtime, c.owner, c.company, c.identity)
    assert failed.value.__context__ is None and 'PRIVATE' not in str(failed.value)


def test_digest_changes_with_identity_and_delegation_not_raw_pem_layout(case):
    c = case
    first = inventory.collect_identity_inventory(c.runtime, c.owner)
    c.device.custom__use_company_certificate__keys = 0
    second = inventory.collect_identity_inventory(c.runtime, c.owner)
    assert first.sha256 != second.sha256
    c.company.custom_csr_config += '\n'
    assert inventory.collect_identity_inventory(c.runtime, c.owner).sha256 == second.sha256


def test_v16_acl_signature_is_quiet_without_a_typeerror_retry(case):
    c = case
    calls = []
    def permission(dt, operation, *, doc, user, print_logs=True):
        calls.append((dt, doc.name, operation, user, print_logs))
        return True
    c.runtime.has_permission = permission
    inventory.collect_identity_inventory(c.runtime, c.owner)
    assert len(calls) == 3 and all(call[-1] is False for call in calls)


@pytest.mark.parametrize('fault', ['READ-COMMITTED', 'READ-UNCOMMITTED', 'missing_isolation',
    'engine', 'missing_table', 'stale_orm'])
def test_range_lock_assumptions_and_current_read_binding_are_required(case, fault):
    c = case
    sql = c.owner.database.sql.side_effect
    def altered(statement, values=(), **kw):
        rows = sql(statement, values, **kw)
        if statement.startswith('SELECT @@tx_isolation'):
            if fault == 'missing_isolation':
                return []
            if fault in ('READ-COMMITTED', 'READ-UNCOMMITTED'):
                return [{'isolation_level': fault}]
        if 'information_schema.tables' in statement:
            if fault == 'engine':
                rows[0]['engine'] = 'MyISAM'
            elif fault == 'missing_table':
                rows.pop()
        if fault == 'stale_orm' and 'FORCE INDEX' in statement and '`tabCompany`' in statement:
            rows[0]['custom_private_key'] = 'NEW-COMMITTED-MATERIAL'
        return rows
    c.owner.database.sql.side_effect = altered
    with pytest.raises(inventory.IdentityInventoryError, match='native_identity_inventory_') as failed:
        inventory.collect_identity_inventory(c.runtime, c.owner)
    assert failed.value.__context__ is None
