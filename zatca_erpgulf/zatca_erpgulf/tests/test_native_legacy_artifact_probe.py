"""Bounded local XML declarations; synthetic unsigned signature, no authority."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import native_legacy_artifact_probe as probe, certificate_evidence
from zatca_erpgulf.zatca_erpgulf.chain_registration import ChainRegistrationError
from zatca_erpgulf.zatca_erpgulf.native_identity_inventory import IdentityInventoryError
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates, certificate_root
from zatca_erpgulf.zatca_erpgulf.tests.test_artifact_evidence import UUID, SELLER, xml_bytes
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_onboarding_response import material as issued_material
from zatca_erpgulf.zatca_erpgulf.credential_identity import declared_egs_identity_key


@pytest.fixture
def case(certificates, tmp_path):
    content = xml_bytes(certificate_root(certificates[0]))
    evidence = certificate_evidence.inspect_embedded_certificate(content)
    source = Document(doctype='Sales Invoice', name='INV-TEST', company='TEST', docstatus=1,
        custom_uuid=UUID, custom_zatca_icv='77', custom_zatca_issuing_unit='company:RETIRED')
    company = Document(doctype='Company', name='TEST', tax_id=SELLER)
    file = Document(doctype='File', name='FILE', file_name='archive.xml', file_url='/private/files/archive.xml',
        attached_to_doctype=source.doctype, attached_to_name=source.name, is_private=1)
    folder = tmp_path/'private'/'files';folder.mkdir(parents=True)
    path = folder/'archive.xml';path.write_bytes(content)
    counter = Document(name='OLD', environment='Production', last_invoice_doctype=source.doctype,
        last_invoice=source.name, company=source.company, issuing_unit=source.custom_zatca_issuing_unit, last_issued_icv='77')
    documents = {(doc.doctype,doc.name):doc for doc in (source,company,file)}
    def sql(statement, values=(), *, as_dict=True):
        if 'information_schema.tables' in statement:
            return [{'table_name': name, 'engine': 'InnoDB'} for name in values]
        assert 'LOCK IN SHARE MODE NOWAIT' in statement
        if 'LOWER(file_name)' in statement:
            return [{'name':doc.name} for (dt,name),doc in documents.items() if dt == 'File']
        dt = next(kind for kind,table in probe.TABLES.items() if 'FROM '+table+' WHERE' in statement)
        return [{'name':values[0]}] if (dt,values[0]) in documents else []
    owner = SimpleNamespace(owner_current=Mock(return_value=True),actor='reader@example.invalid',
        database=SimpleNamespace(sql=Mock(side_effect=sql)))
    def permission(dt, operation, *, doc, user, raise_exception=True):
        assert operation == 'read' and raise_exception is False
        return True
    def get_doc(dt,name,**kwargs):
        assert kwargs == {'for_update':True}
        return documents[dt,name]
    runtime = SimpleNamespace(get_doc=Mock(side_effect=get_doc),has_permission=permission,
        get_site_path=lambda *parts:str(tmp_path.joinpath(*parts)))
    family = [SimpleNamespace(public_keys=('a'*64,),declared_units=())]
    def inspect(counters=None):
        return probe.probe_unattributed_counter_artifacts(runtime,owner,(counter,) if counters is None else counters,family)
    return SimpleNamespace(runtime=runtime,owner=owner,source=source,company=company,file=file,path=path,
        content=content,counter=counter,documents=documents,family=family,evidence=evidence,inspect=inspect)


def test_an_inspectable_different_declaration_is_not_authority_or_ownership_proof(case):
    c = case;report = c.inspect()
    assert (report.probed,report.unresolved,report.unprobed,report.xml_bytes) == (1,0,0,len(c.content))
    assert not hasattr(report,'active') and not hasattr(report,'history_complete')
    assert 'PRIVATE-DN' not in repr(report)


def test_embedded_same_key_requires_review_even_for_a_deliberately_invalid_signature(case):
    c = case;c.family[0].public_keys = (c.evidence.public_key_sha256,)
    with pytest.raises(ChainRegistrationError,match='registration_history_counter_related'):
        c.inspect()


def test_declared_unit_projection_preserves_the_original_fingerprint_api_and_hides_raw_claims(issued_material):
    import base64
    import json
    body = json.loads(issued_material.body)
    der = base64.b64decode(base64.b64decode(body['binarySecurityToken'],validate=True),validate=True)
    content = xml_bytes(certificate_root(der))
    evidence, units = certificate_evidence.inspect_embedded_certificate_declarations(content)
    assert evidence == certificate_evidence.inspect_embedded_certificate(content)
    assert set(units) == {declared_egs_identity_key(environment,issued_material.header['seller_tax_id'],
        issued_material.header['csr_serial']) for environment in ('Sandbox','Simulation','Production')}
    assert issued_material.header['csr_serial'] not in repr((evidence,units))


def test_missing_or_malformed_unit_claims_cannot_hide_an_observed_public_key(case, monkeypatch):
    from zatca_erpgulf.zatca_erpgulf import credential_identity
    def invalid(*args):raise ValueError('PRIVATE-CLAIM-DIAGNOSTIC')
    monkeypatch.setattr(credential_identity,'claimed_egs_identity_key',invalid)
    evidence, units = certificate_evidence.inspect_embedded_certificate_declarations(case.content)
    assert evidence == case.evidence and units == ()


def test_v16_quiet_acl_signature_is_used_for_historical_source_company_and_file(case):
    c = case;calls = []
    def permission(dt, operation, *, doc, user, print_logs=True):
        calls.append((dt,operation,print_logs));return True
    c.runtime.has_permission=permission
    assert c.inspect().unresolved == 0
    assert {dt for dt,operation,flag in calls} == {'Sales Invoice','Company','File'}
    assert all(operation == 'read' and flag is False for dt,operation,flag in calls)


def test_context_change_during_a_local_read_is_fatal_before_a_parent_review_can_commit(case):
    c = case;get_path=c.runtime.get_site_path
    def changed(*parts):
        c.owner.owner_current.return_value=False
        return get_path(*parts)
    c.runtime.get_site_path=changed
    with pytest.raises(IdentityInventoryError,match='native_identity_inventory_owner_changed'):
        c.inspect()


@pytest.mark.parametrize('fault', ['source_missing','source_denied','file_denied','bad_icv','wrong_source',
    'wrong_seller','public','debug','remote','missing_file','bad_xml','symlink','many_files'])
def test_missing_or_unsafe_evidence_remains_unresolved_without_a_zero_seed(case, monkeypatch, fault):
    c = case
    if fault == 'source_missing':
        del c.documents[c.source.doctype,c.source.name]
    elif fault in ('source_denied','file_denied'):
        denied = 'File' if fault == 'file_denied' else 'Sales Invoice'
        def permission(dt, operation, *, doc, user, raise_exception=True):return dt != denied
        c.runtime.has_permission = permission
    elif fault == 'bad_icv':c.counter.last_issued_icv = '077'
    elif fault == 'wrong_source':c.source.custom_zatca_issuing_unit = 'company:OTHER'
    elif fault == 'wrong_seller':c.company.tax_id = 'OTHER'
    elif fault == 'public':c.file.is_private = 0
    elif fault == 'debug':c.file.file_name = 'DEBUG_archive.xml'
    elif fault == 'remote':c.file.file_url = 'https://example.invalid/archive.xml'
    elif fault == 'missing_file':c.path.unlink()
    elif fault == 'bad_xml':c.path.write_bytes(b'INVALID-XML')
    elif fault == 'symlink':
        target=c.path.with_name('target.xml');c.path.rename(target);c.path.symlink_to(target)
    else:monkeypatch.setattr(probe,'MAX_FILES_PER_SOURCE',0)
    report = c.inspect()
    assert report.probed == report.unresolved == 1 and report.unprobed == 0


def test_bad_xml_bytes_are_charged_and_cannot_reset_the_global_budget(case, monkeypatch):
    c = case;c.path.write_bytes(b'BAD')
    monkeypatch.setattr(probe,'MAX_TOTAL_XML_BYTES',5)
    report = c.inspect((c.counter,c.counter,c.counter))
    assert (report.probed,report.unresolved,report.unprobed,report.xml_bytes) == (2,2,1,3)


def test_exact_byte_boundary_is_inspectable_but_later_counters_stay_unprobed(case, monkeypatch):
    c = case;monkeypatch.setattr(probe,'MAX_TOTAL_XML_BYTES',len(c.content))
    report = c.inspect((c.counter,c.counter))
    assert (report.probed,report.unresolved,report.unprobed,report.xml_bytes) == (1,0,1,len(c.content))


def test_counter_probe_limit_is_explicit_and_not_a_truncated_complete_result(case, monkeypatch):
    c = case;monkeypatch.setattr(probe,'MAX_COUNTER_PROBES',1)
    report = c.inspect((c.counter,c.counter))
    assert report.probed == report.unprobed == 1


@pytest.mark.parametrize('fault', ['sql','orm','engine','owner'])
def test_infrastructure_or_ownership_failure_aborts_instead_of_swallowing_a_lost_transaction(case, fault):
    c = case
    if fault == 'sql':c.owner.database.sql.side_effect = RuntimeError('PRIVATE-DRIVER-FAILURE')
    elif fault == 'orm':c.runtime.get_doc.side_effect = RuntimeError('PRIVATE-ORM-FAILURE')
    elif fault == 'owner':c.owner.owner_current.return_value = False
    else:
        sql=c.owner.database.sql.side_effect
        def engine(statement,values=(),**kwargs):
            rows=sql(statement,values,**kwargs)
            if 'information_schema.tables' in statement:rows[-1]['engine']='MyISAM'
            return rows
        c.owner.database.sql.side_effect=engine
    with pytest.raises((RuntimeError,IdentityInventoryError)):
        c.inspect()
