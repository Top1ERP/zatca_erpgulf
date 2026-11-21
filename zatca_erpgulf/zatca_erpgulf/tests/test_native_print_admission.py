"""Unissued native print admission; no installed ERP, storage or transport."""

from copy import deepcopy
import csv
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import native_publication as publication
from zatca_erpgulf.zatca_erpgulf.native_provider import NativeProviderError
from zatca_erpgulf.zatca_erpgulf.tests.test_native_provider import entry, UNIT
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document


@pytest.fixture
def printing(entry, monkeypatch):
    e = entry
    monkeypatch.setattr(publication, 'frappe', e.runtime)
    monkeypatch.setattr(publication, '_', lambda text: 'AR:' + text)
    e.runtime.has_permission = lambda dt, op, *, doc, user, raise_exception=True: op == 'read'
    e.source.ksa_einv_qr = '/private/files/OLD-PHASE1.png'
    e.source.custom_uuid = 'A-UUID-IS-NOT-AN-ISSUED-ORIGINAL'
    e.publication = Mock()
    monkeypatch.setattr(publication, 'load_publication', e.publication)
    return e


def assert_held(e, rendered, code='native_publication_unissued'):
    before = deepcopy(vars(rendered))
    with pytest.raises(publication.NativePublicationError) as failed:
        publication.before_print(rendered)
    assert failed.value.code == code and failed.value.__context__ is None
    assert str(failed.value).startswith('AR:')
    assert vars(rendered) == before
    e.runtime.log_error.assert_called_once()
    assert 'AR:' not in repr(e.runtime.log_error.call_args)
    assert e.runtime.flags == {}
    e.publication.assert_not_called()
    e.prepare.assert_not_called(); e.dispatch.assert_not_called(); e.build.assert_not_called()


@pytest.mark.parametrize('doctype', ['Sales Invoice', 'POS Invoice'])
@pytest.mark.parametrize('docstatus', [0, 1])
@pytest.mark.parametrize('rollout', [0, 1])
def test_registered_native_owner_blocks_stale_qr_even_before_a_request_exists(printing, doctype, docstatus, rollout):
    e = printing
    del e.docs[e.source.doctype, e.source.name]
    e.source.doctype = doctype; e.source.docstatus = docstatus
    e.docs[doctype, e.source.name] = e.source
    e.runtime.conf['zatca_native_dispatch'] = rollout
    rendered = deepcopy(e.source)
    rendered.company = 'FORGED-LEGACY-COMPANY'  # Saved identity selects policy.
    assert_held(e, rendered)
    assert e.runtime.log_error.call_args.kwargs['message'] == 'native_publication_unissued: ' + publication.UNISSUED


@pytest.mark.parametrize('policy', ['phase1', 'disabled', 'legacy', 'old-schema', 'phase1-no-company-read'])
def test_unissued_phase1_disabled_and_legacy_print_remain_unchanged(printing, policy):
    e = printing
    if policy.startswith('phase1'):
        e.company.custom_phase_1_or_2 = 'Phase-1'
    elif policy == 'disabled':
        e.company.custom_zatca_invoice_enabled = 0
    elif policy == 'legacy':
        e.company.custom_zatca_native_chain = None
    else:
        e.runtime.get_meta = lambda dt: SimpleNamespace(has_field=lambda field: False)
    if policy == 'phase1-no-company-read':
        e.runtime.has_permission = Mock(return_value=False)
    rendered = deepcopy(e.source); before = deepcopy(vars(rendered))
    publication.before_print(rendered)
    assert vars(rendered) == before
    e.runtime.log_error.assert_not_called(); e.publication.assert_not_called()
    if policy == 'phase1-no-company-read':
        e.runtime.has_permission.assert_not_called()


@pytest.mark.parametrize('kind', ['device-native', 'device-legacy', 'delegate-native', 'delegate-legacy'])
def test_saved_device_and_certificate_delegate_select_the_actual_owner(printing, kind):
    e = printing
    device = Document(doctype='ZATCA Multiple Setting', name='DEVICE', custom_linked_doctype=e.company.name,
        custom__use_company_certificate__keys=0)
    e.source.custom_zatca_pos_name = device.name
    e.docs[device.doctype, device.name] = device
    if kind.startswith('delegate'):
        linked = Document(doctype='Company', name='DELEGATE', tax_id='TEST-VAT',
            custom_zatca_native_chain=UNIT if kind.endswith('native') else None)
        e.company.tax_id = linked.tax_id
        device.custom_linked_doctype = linked.name
        device.custom__use_company_certificate__keys = 1
        e.docs[linked.doctype, linked.name] = linked
    else:
        device.custom_zatca_native_chain = UNIT if kind.endswith('native') else None
    rendered = deepcopy(e.source)
    if kind.endswith('native'):
        assert_held(e, rendered)
    else:
        publication.before_print(rendered)
        e.runtime.log_error.assert_not_called()
        assert rendered.ksa_einv_qr == e.source.ksa_einv_qr


@pytest.mark.parametrize('target', ['Sales Invoice', 'Company', 'ZATCA Multiple Setting'])
def test_missing_read_permission_never_grants_legacy_fallback(printing, target):
    e = printing
    device = Document(doctype='ZATCA Multiple Setting', name='DEVICE', custom_linked_doctype=e.company.name,
        custom__use_company_certificate__keys=0, custom_zatca_native_chain=UNIT)
    e.source.custom_zatca_pos_name = device.name; e.docs[device.doctype, device.name] = device
    e.runtime.has_permission = lambda dt, op, *, doc, user, raise_exception=True: dt != target and op == 'read'
    assert_held(e, deepcopy(e.source), 'native_publication_unavailable')


@pytest.mark.parametrize('problem', ['invalid-marker', 'missing-device', 'wrong-company'])
def test_unresolved_native_policy_holds_without_disclosing_exception_details(printing, problem):
    e = printing
    if problem == 'invalid-marker':
        e.company.custom_zatca_native_chain = 'PRIVATE-NON-UUID'
    elif problem == 'missing-device':
        e.source.custom_zatca_pos_name = 'PRIVATE-MISSING-DEVICE'
    else:
        e.company.name = 'PRIVATE-WRONG-COMPANY'
    assert_held(e, deepcopy(e.source), 'native_publication_company_identity' if problem == 'wrong-company'
        else 'native_publication_unavailable')
    assert 'PRIVATE' not in repr(e.runtime.log_error.call_args)


def test_phase_compatibility_fallback_is_used_before_unissued_admission(printing):
    e = printing
    del e.company.custom_phase_1_or_2
    e.company.phase_1_or_2 = 'Phase-2'
    assert_held(e, deepcopy(e.source))


def test_read_only_print_selection_does_not_relax_processing_write_permission(printing):
    e = printing
    with pytest.raises(NativeProviderError):
        e.run()
    e.prepare.assert_not_called(); e.dispatch.assert_not_called(); e.build.assert_not_called()


def test_unissued_message_has_one_arabic_display_translation():
    path = Path(publication.__file__).parents[1] / 'translations' / 'ar.csv'
    with path.open(encoding='utf-8', newline='') as stream:
        matches = [row for row in csv.reader(stream) if row and row[0] == publication.UNISSUED]
    assert len(matches) == 1 and len(matches[0]) == 2
    assert 'لم تُولّد الطباعة' in matches[0][1]
