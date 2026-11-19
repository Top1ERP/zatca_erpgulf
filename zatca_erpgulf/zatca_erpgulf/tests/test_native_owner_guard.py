"""Saved-owner guards and Arabic display; explicit fake DB and no site init."""

import csv
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import native_owner_guard as guard
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document


class Review(Exception):pass


@pytest.fixture
def owner(monkeypatch):
    values={name:None for name in guard.FIELDS}
    values.update({guard.MARKER:'30000000-0000-4000-8000-000000000001','custom_private_key':'PRIVATE-KEY',
        'custom_csr_data':'PRIVATE-CSR','tax_id':'TEST-VAT'})
    doc=Document(doctype='Company',name='SYNTHETIC',**values)
    runtime=SimpleNamespace(get_meta=lambda dt:SimpleNamespace(has_field=lambda field:field in values),
        db=SimpleNamespace(sql=Mock(return_value=[dict(values)])),throw=Mock(side_effect=lambda message:(_ for _ in ()).throw(Review(message))))
    monkeypatch.setattr(guard,'frappe',runtime)
    monkeypatch.setattr(guard,'_',lambda text:'AR:'+text)
    return SimpleNamespace(doc=doc,values=values,runtime=runtime)


@pytest.mark.parametrize('name',[guard.MARKER,'custom_private_key','custom_csr_data','tax_id','custom_pih',
    'custom_basic_auth_from_csid','custom_basic_auth_from_production','custom_linked_doctype'])
def test_native_form_cannot_clear_or_replace_owned_state(owner,name):
    setattr(owner.doc,name,None if name==guard.MARKER else 'CHANGED')
    with pytest.raises(Review,match='AR:Native ZATCA settings'):guard.validate_native_owner(owner.doc)
    owner.runtime.throw.assert_called_once()


def test_unrelated_business_changes_and_otp_entry_keep_the_owned_state(owner):
    owner.doc.company_name='Updated display name';owner.doc.custom_otp='123456'
    guard.validate_native_owner(owner.doc)
    owner.runtime.throw.assert_not_called()


@pytest.mark.parametrize('method',['before_rename','on_trash'])
def test_native_owner_rename_or_delete_needs_a_reviewed_transition(owner,method):
    with pytest.raises(Review,match='AR:This owner has a native ZATCA unit'):
        guard.protect_native_owner_lifecycle(owner.doc,method,'OLD','NEW',False)


def test_a_stale_form_cannot_clear_the_new_marker_even_if_it_was_open_before_csr(owner):
    owner.doc.custom_zatca_native_chain=None;owner.doc.custom_private_key=None;owner.doc.custom_csr_data=None
    with pytest.raises(Review):guard.validate_native_owner(owner.doc)


def test_legacy_rows_remain_editable_and_client_cannot_invent_a_native_marker(owner):
    owner.values[guard.MARKER]=None
    owner.runtime.db.sql.return_value=[dict(owner.values)]
    owner.doc.custom_zatca_native_chain=None;owner.doc.custom_private_key='LEGACY-EDIT'
    guard.validate_native_owner(owner.doc)
    owner.doc.custom_zatca_native_chain='CLIENT-INVENTED'
    with pytest.raises(Review):guard.validate_native_owner(owner.doc)


def test_both_user_visible_review_templates_have_arabic_entries():
    path=Path(__file__).resolve().parents[2]/'translations'/'ar.csv'
    with path.open(newline='',encoding='utf-8') as handle:rows={row[0]:row[1] for row in csv.reader(handle) if len(row)>1}
    assert all(any('\u0600'<=c<='\u06ff' for c in rows[message]) for message in (guard.REVIEW,guard.LIFECYCLE_REVIEW))
