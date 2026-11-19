"""Custody-backed display/print policy, not installed print-engine/SDK approval."""

import base64
from copy import deepcopy
from dataclasses import replace
import hashlib
from datetime import date,timedelta
import inspect
import json
from unittest.mock import Mock

import png
import pytest
from lxml import etree

from zatca_erpgulf import hooks
from zatca_erpgulf.zatca_erpgulf import native_publication as publication
from zatca_erpgulf.zatca_erpgulf import native_dispatch as dispatch
from zatca_erpgulf.zatca_erpgulf import native_artifact as artifact
from zatca_erpgulf.zatca_erpgulf.issuing_attempt import _source_observation
from zatca_erpgulf.zatca_erpgulf.tests.test_native_artifact import custody, ORIGINAL, RETURNED
from zatca_erpgulf.zatca_erpgulf.tests.test_native_dispatch import coordinator, boundary, materials


@pytest.fixture
def view(coordinator, monkeypatch):
    c = coordinator
    c.b.frappe.flags = {}
    c.b.frappe.log_error = Mock()
    monkeypatch.setattr(publication, 'frappe', c.b.frappe)
    monkeypatch.setattr(publication, '_', lambda text: text)
    def retain(**kwargs):
        result = custody(c, **kwargs)
        header, _raw = c.repository.open_issuance.return_value
        identifier = '10000000-0000-4000-8000-000000000001'
        header['record_id'] = identifier
        c.repository.find_source_issuance.return_value['record_id'] = identifier
        c.repository.open_receipt.return_value[0]['issuance'] = identifier
        if kwargs.get('fallback'):
            c.repository.open_clearance_fallback({})[0]['issuance'] = identifier
        header['source_sha256'] = dispatch.source_observation_sha256(
            ('Sales Invoice', 'SI'), _source_observation(c.b.sales))
        return result
    c.retain = retain
    retain()
    return c


@pytest.mark.parametrize('code', ['388', '381', '383', '386'])
@pytest.mark.parametrize('state', ['PREPARED', 'DISPATCHING', 'OUTCOME_UNKNOWN', 'REPORTED'])
def test_generated_simplified_preview_preserves_exact_qr_and_truthful_acceptance(view, state, code):
    c = view
    c.retain(state=state, code=code)
    source_before = deepcopy(vars(c.b.sales))
    result = publication.preview_result('Sales Invoice', 'SI', runtime=c.b.frappe, translate=lambda s: 'AR:' + s)
    assert result['status'] == 'READY' and result['accepted'] is (state == 'REPORTED')
    assert result['message'] == 'AR:' + (publication.ACCEPTED if result['accepted'] else publication.PENDING)
    assert result['source_kind'] == 'SIMPLIFIED_GENERATED_XML'
    binary = base64.b64decode(result['qr_data_uri'].split(',', 1)[1], validate=True)
    assert binary.startswith(b'\x89PNG\r\n\x1a\n')
    width, height, _pixels, details = png.Reader(bytes=binary).read()
    assert width == height and width > 100 and details['bitdepth'] == 1
    assert vars(c.b.sales) == source_before
    c.worker.database.sql.assert_not_called()
    c.worker.commit.assert_not_called()
    c.b.request.assert_not_called()


@pytest.mark.parametrize('state', ['REJECTED', 'REVIEW_REQUIRED', 'REPORTING_FALLBACK_READY'])
def test_review_states_keep_original_for_diagnosis_but_never_print_or_publish_qr(view, state):
    c = view
    original, _returned, _receipt = c.retain(state=state)
    with pytest.raises(dispatch.NativeDispatchError, match='native_publication_state_review'):
        publication.load_publication('Sales Invoice', 'SI', runtime=c.b.frappe)
    assert artifact.read_native_artifact('Sales Invoice', 'SI', runtime=c.b.frappe).xml_bytes == original
    issuance_id = c.repository.find_source_issuance.return_value['record_id']
    response = publication.xml_response('Sales Invoice', 'SI', issuance_id,
        original=True, runtime=c.b.frappe, translate=lambda s: s)
    assert response.get_data() == original and 'ORIGINAL_' in response.headers['Content-Disposition']


@pytest.mark.parametrize('fallback', [False, True])
def test_standard_print_and_download_use_the_same_verified_xml_and_qr(view, fallback):
    c = view
    original, returned, _receipt = c.retain(indicator='0100000',
        state='REPORTED' if fallback else 'CLEARED', fallback=fallback)
    selected, _image = publication.load_publication('Sales Invoice', 'SI', runtime=c.b.frappe)
    assert selected.xml_bytes == (original if fallback else returned)
    assert selected.qr_payload == (ORIGINAL if fallback else RETURNED)
    response = publication.xml_response('Sales Invoice', 'SI', selected.issuance_id,
        runtime=c.b.frappe, translate=lambda s: s)
    assert response.get_data() == selected.xml_bytes
    assert response.headers['Cache-Control'] == 'private, no-store, max-age=0'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.mimetype == 'application/xml'
    assert 'SI' not in response.headers['Content-Disposition'].split('filename=')[1]


@pytest.mark.parametrize('state', ['PREPARED', 'DISPATCHING', 'OUTCOME_UNKNOWN', 'REJECTED',
    'REVIEW_REQUIRED', 'REPORTING_FALLBACK_READY'])
def test_standard_never_prints_an_uncleared_original_even_with_a_qr(view, state):
    c = view
    c.retain(indicator='0100000', state=state)
    rendered = deepcopy(c.b.sales)
    rendered.ksa_einv_qr = '/private/files/STALE.png'
    with pytest.raises(publication.NativePublicationError):
        publication.before_print(rendered, 'before_print', {})
    assert rendered.ksa_einv_qr == '/private/files/STALE.png'
    assert c.b.frappe.log_error.call_count == 1
    c.worker.commit.assert_not_called()


def test_print_changes_only_its_render_copy_and_never_repairs_the_saved_invoice(view):
    c = view
    c.b.sales.ksa_einv_qr = '/private/files/old.png'
    rendered = deepcopy(c.b.sales)
    publication.before_print(rendered, 'before_print', {})
    assert rendered.ksa_einv_qr.startswith('data:image/png;base64,')
    assert c.b.sales.ksa_einv_qr == '/private/files/old.png'
    c.worker.commit.assert_not_called()
    c.worker.database.sql.assert_not_called()


@pytest.mark.parametrize('field,value', [('grand_total', 20), ('customer', 'OTHER'),
    ('posting_time', '10:00:00'), ('docstatus', 2), ('outstanding_amount', 0)])
def test_saved_source_drift_blocks_publication_but_not_exact_original_diagnosis(view, field, value):
    c = view
    original, _returned, _receipt = c.retain()
    setattr(c.b.sales, field, value)
    with pytest.raises(dispatch.NativeDispatchError, match='native_publication_source_review'):
        publication.load_publication('Sales Invoice', 'SI', runtime=c.b.frappe)
    issuance_id = c.repository.find_source_issuance.return_value['record_id']
    assert publication.xml_response('Sales Invoice', 'SI', issuance_id, original=True,
        runtime=c.b.frappe, translate=lambda s: s).get_data() == original


@pytest.mark.parametrize('change', ['amount', 'identity', 'hidden_marker'])
def test_supplied_print_json_cannot_change_data_or_hide_native_ownership(view, change):
    c = view
    rendered = deepcopy(c.b.sales)
    if change == 'amount':
        rendered.grand_total = 900
    elif change == 'identity':
        rendered.custom_uuid = 'FORGED'
    else:
        rendered.custom_zatca_issuing_unit = None
    # Output identities are excluded from the financial observation, so print
    # also needs an explicit identity comparison, not just its business digest.
    if change == 'amount':
        with pytest.raises(publication.NativePublicationError, match=publication.REVIEW):
            publication.before_print(rendered)
    else:
        with pytest.raises(publication.NativePublicationError):
            publication.before_print(rendered)


@pytest.mark.parametrize('doctype', ['Sales Invoice', 'Company', None])
def test_public_review_does_not_echo_missing_identity_parser_or_driver_details(view, doctype, monkeypatch):
    c = view
    if doctype == 'Sales Invoice':
        monkeypatch.setattr(publication, 'load_publication', Mock(side_effect=RuntimeError('PRIVATE-XML-KEY-SQL')))
    result = publication.preview_result(doctype, 'SI', runtime=c.b.frappe, translate=lambda s: 'AR:' + s)
    assert result == {'status': 'REVIEW', 'message': 'AR:' + publication.REVIEW}
    assert 'PRIVATE' not in repr(c.b.frappe.log_error.call_args)
    assert c.b.frappe.flags == {}


@pytest.mark.parametrize('target', ['Sales Invoice', 'Company'])
def test_read_denial_stops_before_decryption_without_requiring_write_permission(view, target):
    c = view
    c.b.frappe.has_permission = lambda dt, op, *, doc, user, raise_exception=True: dt != target and op == 'read'
    result = publication.preview_result('Sales Invoice', 'SI', runtime=c.b.frappe, translate=lambda s: s)
    assert result['status'] == 'REVIEW'
    c.repository.open_issuance.assert_not_called()


def test_read_only_viewer_can_preview_after_key_expiry_or_phase_change(view):
    c = view
    c.retain(state='REPORTED')
    c.b.company.custom_private_key = 'INVALID'
    c.b.company.custom_phase_1_or_2 = 'Phase-1'
    c.b.frappe.has_permission = lambda dt, op, *, doc, user, raise_exception=True: op == 'read'
    assert publication.preview_result('Sales Invoice', 'SI', runtime=c.b.frappe, translate=lambda s: s)['accepted']


def test_stale_download_id_fails_without_serving_a_new_version(view):
    with pytest.raises(publication.NativePublicationError) as error:
        publication.xml_response('Sales Invoice', 'SI', '10000000-0000-4000-8000-000000000099',
            runtime=view.b.frappe, translate=lambda s: s)
    assert error.value.__context__ is None and error.value.code == 'native_publication_version_changed'


def test_preview_rpc_is_get_only_no_store_and_exports_no_original_or_secret(view):
    response = inspect.unwrap(publication.preview)('Sales Invoice', 'SI')
    payload = json.loads(response.get_data())['message']
    assert payload['status'] == 'READY' and 'xml' not in payload and 'qr_payload' not in payload
    assert response.headers['Cache-Control'].startswith('private, no-store')
    import frappe
    for endpoint in (publication.preview, publication.download_xml, publication.download_original):
        function = endpoint
        assert function not in frappe.guest_methods
        assert frappe.allowed_http_methods_for_whitelisted_func[function] == ['GET']


def test_hook_and_assets_adopt_both_invoice_types_without_changing_legacy_rendering(view):
    c = view
    c.b.sales.custom_zatca_issuing_unit = None
    rendered = deepcopy(c.b.sales)
    rendered.ksa_einv_qr = '/private/files/PHASE1.png'
    publication.before_print(rendered)
    assert rendered.ksa_einv_qr == '/private/files/PHASE1.png'
    c.factory.assert_not_called()
    for doctype in ('Sales Invoice', 'POS Invoice'):
        assert hooks.doc_events[doctype]['before_print'].endswith('native_publication.before_print')
        assert 'public/js/native_publication.js' in hooks.doctype_js[doctype]


def test_oversize_qr_stops_instead_of_truncating_a_retained_payload(view, monkeypatch):
    monkeypatch.setattr(publication.pyqrcode, 'create', Mock(side_effect=ValueError('PRIVATE-QR')))
    result = publication.preview_result('Sales Invoice', 'SI', runtime=view.b.frappe, translate=lambda s: s)
    assert result['status'] == 'REVIEW' and 'qr_data_uri' not in result


@pytest.mark.parametrize('field,value', [('invoice_uuid', '10000000-0000-4000-8000-000000000099'),
    ('icv', '88'), ('chain_id', '10000000-0000-4000-8000-000000000099')])
def test_print_identity_is_bound_to_the_selected_custody_view_not_an_earlier_source_read(view, monkeypatch, field, value):
    c = view
    retained = artifact.read_native_artifact('Sales Invoice', 'SI', runtime=c.b.frappe)
    later = replace(retained, **{field: value})
    monkeypatch.setattr(publication, 'read_native_artifact', Mock(return_value=later))
    rendered = deepcopy(c.b.sales)
    with pytest.raises(publication.NativePublicationError) as error:
        publication.before_print(rendered)
    assert error.value.code == 'native_publication_render_identity'
    assert not rendered.get('ksa_einv_qr')


def test_download_keeps_returned_xml_encoding_and_bytes_without_an_invented_http_charset(view):
    c = view
    c.retain(indicator='0100000', state='CLEARED')
    receipt, raw = c.repository.open_receipt.return_value
    body = json.loads(raw)
    xml = etree.fromstring(base64.b64decode(body['clearedInvoice']))
    encoded = etree.tostring(xml, xml_declaration=True, encoding='UTF-16')
    body['clearedInvoice'] = base64.b64encode(encoded).decode()
    raw = json.dumps(body).encode()
    receipt['response_sha256'] = hashlib.sha256(raw).hexdigest()
    c.repository.open_receipt.return_value = (receipt, raw)
    identifier = c.repository.find_source_issuance.return_value['record_id']
    response = publication.xml_response('Sales Invoice', 'SI', identifier,
        runtime=c.b.frappe, translate=lambda s: s)
    assert response.get_data() == encoded and encoded.startswith((b'\xff\xfe', b'\xfe\xff'))
    assert response.headers['Content-Type'] == 'application/xml'


def test_full_native_custom_field_drift_is_seen_while_metadata_and_output_updates_are_ignored(view):
    c = view
    source = c.b.sales
    source.custom_fiscal_note = 'ORIGINAL'
    fields = ('doctype', 'name', 'company', 'docstatus', 'grand_total', 'custom_fiscal_note',
        'modified', 'custom_zatca_status', 'custom_uuid', 'custom_zatca_icv', 'custom_zatca_issuing_unit')
    source.as_dict = lambda: {name: source.get(name) for name in fields}
    c.retain()
    source.modified = 'LATER'
    source.custom_zatca_status = 'FORGED'
    assert publication.preview_result('Sales Invoice', 'SI', runtime=c.b.frappe, translate=lambda s: s)['status'] == 'READY'
    source.custom_fiscal_note = 'CHANGED'
    result = publication.preview_result('Sales Invoice', 'SI', runtime=c.b.frappe, translate=lambda s: 'AR:' + s)
    assert result['status'] == 'REVIEW' and result['message'].startswith('AR:')
    log = c.b.frappe.log_error.call_args.kwargs['message']
    assert publication.REVIEW in log and 'AR:' not in log and 'CHANGED' not in log


def test_ordinary_unsaved_draft_does_not_enter_native_storage_or_reload_saved_documents(view):
    c = view
    source = deepcopy(c.b.sales)
    source.name = None
    c.b.frappe.get_doc.reset_mock()
    publication.before_print(source)
    c.b.frappe.get_doc.assert_not_called()
    c.factory.assert_not_called()


def test_normal_json_print_dates_match_saved_dates_without_changing_xml_or_qr(view):
    c=view
    c.b.sales.posting_date=date(2026,9,27)
    c.b.sales.posting_time=timedelta(hours=9,minutes=5,seconds=42)
    original,_,_=c.retain()
    from frappe.utils.response import json_handler
    rendered=deepcopy(c.b.sales)
    rendered.posting_date=json_handler(c.b.sales.posting_date)
    rendered.posting_time=json_handler(c.b.sales.posting_time)
    publication.before_print(rendered)
    assert rendered.ksa_einv_qr.startswith('data:image/png;base64,')
    assert artifact.read_native_artifact('Sales Invoice','SI',runtime=c.b.frappe).xml_bytes==original
    c.worker.commit.assert_not_called()
