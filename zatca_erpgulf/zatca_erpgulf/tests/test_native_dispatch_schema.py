"""Source schema/privacy invariants; not installed Frappe15/16 or SQL proof."""

import importlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import service_owned_record as records

NAMES=('ZATCA Dispatch Control','ZATCA Issuing Chain','ZATCA Issuance','ZATCA Dispatch Attempt')
ROOT=Path(__file__).resolve().parents[1]/'doctype'


def metadata(name):
    folder=name.lower().replace(' ','_')
    return json.loads((ROOT/folder/(folder+'.json')).read_text())


@pytest.mark.parametrize('name',NAMES)
def test_generic_roles_have_only_read_access_and_all_service_fields_are_readonly(name):
    body=metadata(name)
    assert body['permissions']==[{'role':'System Manager','read':1}]
    assert body['allow_import']==body['allow_rename']==0
    assert all(field.get('read_only')==1 for field in body['fields'])
    assert len(body['field_order'])==len(set(body['field_order']))==len(body['fields'])
    assert not {'xml','response_body','private_key','authorization','otp','secret'} & {field['fieldname'] for field in body['fields']}
    for field in body['fields']:
        if field['fieldname'].endswith('_ciphertext'):
            assert field['fieldtype']=='Long Text' and field['hidden']==field['no_copy']==field['print_hide']==1


@pytest.mark.parametrize('name',NAMES)
@pytest.mark.parametrize('method',['before_insert','validate','before_save','before_update_after_submit','before_rename','on_trash'])
def test_native_controllers_deny_generic_edits_without_reading_fields(name,method,monkeypatch):
    folder=name.lower().replace(' ','_')
    module=importlib.import_module('zatca_erpgulf.zatca_erpgulf.doctype.'+folder+'.'+folder)
    controller=getattr(module,''.join(name.split()))
    model=object.__new__(controller)
    class Denied(RuntimeError):pass
    failure=Denied('static')
    throw=Mock(side_effect=failure)
    monkeypatch.setattr(records.frappe,'throw',throw)
    monkeypatch.setattr(records,'_',lambda text:text)
    with pytest.raises(Denied) as caught:getattr(model,method)()
    assert caught.value is failure and throw.call_count==1
    assert throw.call_args.args[0] in (records.EDIT_REVIEW,records.DELETE_REVIEW)


def test_artifact_and_chain_slots_are_unique_independent_of_human_invoice_numbers():
    artifact={f['fieldname']:f for f in metadata('ZATCA Issuance')['fields']}
    assert all(artifact[name]['unique']==1 for name in ('record_id','issuance_key','icv_key','invoice_uuid'))
    assert artifact['artifact_ciphertext']['reqd']==1
    assert artifact['icv']['fieldtype']=='Data'  # No float or signed-64 conversion of an existing ICV.
    chain={f['fieldname']:f for f in metadata('ZATCA Issuing Chain')['fields']}
    assert chain['active_owner_key']['unique']==1 and not chain['active_owner_key'].get('reqd')
    assert not chain['owner_key'].get('unique')  # Retain older registrations without a new active slot.


def test_authenticated_identities_cannot_be_rewritten_by_generic_link_renames():
    from zatca_erpgulf.zatca_erpgulf.dispatch_store import ARTIFACT_FIELDS, ATTEMPT_FIELDS
    for name, fields in (('ZATCA Issuance', ARTIFACT_FIELDS), ('ZATCA Dispatch Attempt', ATTEMPT_FIELDS)):
        declared = {field['fieldname']: field for field in metadata(name)['fields']}
        assert all(declared[field]['fieldtype'] not in ('Link', 'Dynamic Link') for field in fields)
    chain = {field['fieldname']: field for field in metadata('ZATCA Issuing Chain')['fields']}
    assert chain['owner_name']['fieldtype'] == 'Data'
    assert chain['owner_name']['read_only'] == 1
