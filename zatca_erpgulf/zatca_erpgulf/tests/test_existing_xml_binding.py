"""Captured metadata binding; fake HTTP and document writes only.

Parent comparison is not original financial, installed ERP, SDK or receipt proof.
"""

import ast
import base64
import csv
import hashlib
from pathlib import Path
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf.existing_xml_binding import (
    REVIEW, existing_xml_binding_issue,
)
from zatca_erpgulf.zatca_erpgulf.existing_xml_submission import (
    ExistingXmlSubmissionError, read_bound_invoice_payload,
)
from zatca_erpgulf.zatca_erpgulf.invoice_payload import InvoicePayload, read_invoice_payload
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import boundary, select_owner
from zatca_erpgulf.zatca_erpgulf.tests.test_legacy_submission_context import (
    ADAPTERS, XML, legacy_boundary,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_invoice_payload import observable, outcome
from zatca_erpgulf.zatca_erpgulf.tests.test_background_scheduling import worker_boundary

REFERENCE = Path(__file__).with_name('fixtures') / 'existing_xml_binding_e96fb20.py'
REFERENCE_SHA = '66ccae53a75393cf23a4a46c5d987739353a48f01026acc404db587a71f77898'
CBC = 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'
DS = 'http://www.w3.org/2000/09/xmldsig#'


def payload(xml=XML, uuid='test-uuid', digest='test-hash'):
    return InvoicePayload(digest, uuid, base64.b64encode(xml).decode())


def previous(module, name):
    raw = REFERENCE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == REFERENCE_SHA
    source = ast.literal_eval(ast.parse(raw).body[1].value)
    key = 'zatca_erpgulf/zatca_erpgulf/' + module.__name__.rsplit('.', 1)[-1] + '.py'
    namespace = dict(vars(module), read_invoice_payload=read_invoice_payload)
    exec(compile(source[key], str(REFERENCE), 'exec'), namespace)
    return namespace[name]


def typed_throw(message, *, exc=None, **kwargs):
    raise exc if isinstance(exc, Exception) else AssertionError(message)


def configured(monkeypatch, tmp_path, adapter, owner='linked', language='en'):
    b = boundary.__wrapped__(monkeypatch)
    b = legacy_boundary.__wrapped__(b, monkeypatch, tmp_path)
    doc = getattr(b, adapter[3])
    select_owner(b, doc, owner)
    b.frappe.throw = Mock(side_effect=typed_throw)
    with (Path(__file__).resolve().parents[2] / 'translations/ar.csv').open(newline='') as stream:
        catalog = dict(csv.reader(stream))
    translate = lambda text: catalog.get(text, text) if language == 'ar' else text
    monkeypatch.setattr(adapter[0], '_', translate)
    return b, doc, translate


def call(b, doc, fn, wrapper):
    if wrapper:
        return fn(doc, b.relative_path, doc.name)
    return fn('test-uuid', 'test-hash', str(b.path), doc.name, doc)


@pytest.mark.parametrize('adapter', ADAPTERS)
@pytest.mark.parametrize('owner', ['company', 'device', 'linked'])
@pytest.mark.parametrize('environment', ['Sandbox', 'Simulation', 'Production'])
@pytest.mark.parametrize('status', [200, 202, 409, 400])
@pytest.mark.parametrize('wrapper', [False, True])
def test_complete_parent_stable_api_and_wrapper_parity(monkeypatch, tmp_path, adapter, owner, environment, status, wrapper):
    observed = []
    for old in (True, False):
        with monkeypatch.context() as patch:
            # Original rejection paths need the legacy fixture's original throw.
            b = boundary.__wrapped__(patch)
            b = legacy_boundary.__wrapped__(b, patch, tmp_path)
            doc = getattr(b, adapter[3])
            select_owner(b, doc, owner)
            b.company.custom_select = environment
            b.response.status_code = status
            name = adapter[2] if wrapper else adapter[1]
            fn = previous(adapter[0], name) if old else getattr(adapter[0], name)
            result = outcome(lambda: call(b, doc, fn, wrapper))
            observed.append((result, observable(b, doc)))
    assert observed[0] == observed[1]


MUTATIONS = {
    'uuid_changed': XML.replace(b'test-uuid', b'other-uuid'),
    'digest_changed': XML.replace(b'test-hash', b'other-hash'),
    'uuid_missing': XML.replace(b'<cbc:UUID>test-uuid</cbc:UUID>', b''),
    'uuid_duplicate': XML.replace(b'</cbc:UUID>', b'</cbc:UUID><cbc:UUID>test-uuid</cbc:UUID>'),
    'uuid_empty': XML.replace(b'test-uuid', b' '),
    'uuid_child': XML.replace(b'test-uuid', b'<cbc:Note>test-uuid</cbc:Note>'),
    'uuid_nested': XML.replace(b'<cbc:UUID>test-uuid</cbc:UUID>', b'<cbc:Note><cbc:UUID>test-uuid</cbc:UUID></cbc:Note>'),
    'digest_missing': XML.replace(b'<ds:DigestValue>test-hash</ds:DigestValue>', b''),
    'digest_duplicate': XML.replace(b'</ds:DigestValue>', b'</ds:DigestValue><ds:DigestValue>test-hash</ds:DigestValue>'),
    'digest_empty': XML.replace(b'test-hash', b' '),
    'reference_missing': XML.replace(b'invoiceSignedData', b'xadesSignedProperties'),
    'reference_duplicate': XML.replace(b'</Invoice>', b'<ds:Reference Id="invoiceSignedData"><ds:DigestValue>test-hash</ds:DigestValue></ds:Reference></Invoice>'),
    'wrong_root': XML.replace(b'<Invoice ', b'<CreditNote ').replace(b'</Invoice>', b'</CreditNote>'),
    'wrong_uuid_namespace': XML.replace(CBC.encode(), b'urn:wrong'),
    'malformed_private': b'<Invoice>PRIVATE-PARSER-TEXT credential/path',
    'dtd': XML.replace(b'<Invoice ', b'<!DOCTYPE Invoice [<!ENTITY x SYSTEM "file:///not-a-source">]><Invoice '),
}


@pytest.mark.parametrize('adapter', ADAPTERS)
@pytest.mark.parametrize('mutation', list(MUTATIONS))
@pytest.mark.parametrize('language', ['en', 'ar'])
def test_invalid_captured_xml_stops_without_invoice_artifact_or_chain_writes(monkeypatch, tmp_path, adapter, mutation, language):
    b, doc, translate = configured(monkeypatch, tmp_path, adapter, language=language)
    b.path.write_bytes(MUTATIONS[mutation])
    baseline = observable(b, doc)
    with pytest.raises(ExistingXmlSubmissionError) as caught:
        call(b, doc, getattr(adapter[0], adapter[1]), False)
    assert observable(b, doc) == baseline
    b.frappe.throw.assert_called_once()
    assert b.frappe.throw.call_args.args[0] == translate(REVIEW)
    b.frappe.log_error.assert_called_once()
    logged = b.frappe.log_error.call_args.kwargs['message']
    assert REVIEW in logged and 'PRIVATE' not in logged
    if language == 'ar':
        assert translate(REVIEW) != REVIEW and translate(REVIEW) not in logged
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert str(caught.value) == REVIEW and set(vars(caught.value)) == {'code', 'diagnostic_logged'}
    assert b.files == [] and b.path.read_bytes() == MUTATIONS[mutation]


@pytest.mark.parametrize('adapter', ADAPTERS)
@pytest.mark.parametrize('language', ['en', 'ar'])
@pytest.mark.parametrize('changed', ['uuid_changed', 'digest_changed'])
def test_real_wrapper_change_between_extraction_and_request_is_blocked(monkeypatch, tmp_path, adapter, language, changed):
    b, doc, translate = configured(monkeypatch, tmp_path, adapter, language=language)
    extractor_name = ('extract_invoice_data_from_field' if adapter[0].__name__.endswith('pos_submit_with_xml_qr')
                      else 'extract_uuid_and_invoicehash' if adapter[4]
                      else 'extract_uuid_and_invoicehash_simplifeid')
    original = getattr(adapter[0], extractor_name)
    def extract_then_change(path):
        identity = original(path)
        b.path.write_bytes(MUTATIONS[changed])
        return identity
    monkeypatch.setattr(adapter[0], extractor_name, extract_then_change)
    baseline = observable(b, doc)
    with pytest.raises(ExistingXmlSubmissionError):
        call(b, doc, getattr(adapter[0], adapter[2]), True)
    assert observable(b, doc) == baseline
    b.post.assert_not_called()
    b.frappe.throw.assert_called_once()
    assert b.frappe.throw.call_args.args[0] == translate(REVIEW)
    b.frappe.log_error.assert_called_once()


@pytest.mark.parametrize('adapter', ADAPTERS)
def test_frozen_wrapper_can_send_different_metadata_than_its_xml(monkeypatch, tmp_path, adapter):
    b, doc, _ = configured(monkeypatch, tmp_path, adapter)
    extractor_name = ('extract_invoice_data_from_field' if adapter[0].__name__.endswith('pos_submit_with_xml_qr')
                      else 'extract_uuid_and_invoicehash' if adapter[4]
                      else 'extract_uuid_and_invoicehash_simplifeid')
    original = getattr(adapter[0], extractor_name)
    def extract_then_change(path):
        identity = original(path)
        b.path.write_bytes(MUTATIONS['uuid_changed'])
        return identity
    monkeypatch.setattr(adapter[0], extractor_name, extract_then_change)
    call(b, doc, previous(adapter[0], adapter[2]), True)
    sent = b.post.call_args.kwargs['json']
    assert sent['uuid'] == 'test-uuid' and b'other-uuid' in base64.b64decode(sent['invoice'])


@pytest.mark.parametrize('adapter', ADAPTERS)
@pytest.mark.parametrize('failure', ['missing_auth', 'invalid_environment', 'other_taxpayer'])
def test_existing_authorization_precedes_file_validation(legacy_boundary, monkeypatch, adapter, failure):
    b = legacy_boundary
    doc = getattr(b, adapter[3])
    owner, _ = select_owner(b, doc, 'linked')
    if failure == 'missing_auth': owner.custom_basic_auth_from_production = ''
    elif failure == 'invalid_environment': b.company.custom_select = ''
    else: owner.tax_id = 'OTHER-TAXPAYER'
    reader = Mock(side_effect=AssertionError('Unauthorized request read XML'))
    monkeypatch.setattr(adapter[0], 'xml_base64_decode', reader)
    outcome(lambda: call(b, doc, getattr(adapter[0], adapter[1]), False))
    reader.assert_not_called()
    b.post.assert_not_called()
    owner.save.assert_not_called()


@pytest.mark.parametrize('uuid,digest', [('test-uuid', 'test-hash'), (' test-uuid', 'test-hash'), ('test-uuid', 'test-hash '), (None, 'test-hash'), ('test-uuid', None)])
def test_exact_comparison_without_format_normalization(uuid, digest):
    issue = existing_xml_binding_issue(payload(uuid=uuid, digest=digest))
    assert (issue is None) == (uuid == 'test-uuid' and digest == 'test-hash')


@pytest.mark.parametrize('raw', [None, '', 'MOCK_XML', b'\xff', '<SECRET raw XML>', '===='])
def test_unreadable_base64_has_static_code(raw):
    assert existing_xml_binding_issue(InvoicePayload('test-hash', 'test-uuid', raw)) == 'existing_xml_unreadable'


@pytest.mark.parametrize('change', [lambda x: x.replace(b'cbc:', b'b:').replace(b'xmlns:cbc=', b'xmlns:b='),
    lambda x: x.replace(b'</Invoice>', b'<ds:Reference Id="xadesSignedProperties"><ds:DigestValue>different</ds:DigestValue></ds:Reference></Invoice>'),
    lambda x: x.replace('اختبار'.encode(), b'OTHER')])
def test_match_does_not_verify_signature_or_unrelated_content(change):
    assert existing_xml_binding_issue(payload(change(XML))) is None


def test_reader_is_observed_once_and_original_dict_is_unchanged():
    reader = Mock(return_value=payload().invoice_base64)
    runtime = Mock()
    result = read_bound_invoice_payload('test-uuid', 'test-hash', 'path', read_xml=reader, runtime=runtime, translate=lambda text:text)
    reader.assert_called_once_with('path')
    assert result.as_payload() == payload().as_payload()
    runtime.throw.assert_not_called()
    runtime.log_error.assert_not_called()


class MessageDict(dict):
    """Only the attribute contract needed by the pinned message functions."""
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__


@pytest.mark.parametrize('adapter', ADAPTERS)
@pytest.mark.parametrize('language', ['en', 'ar'])
@pytest.mark.parametrize('wrapper', [False, True])
@pytest.mark.parametrize('muted', [False, True])
def test_pinned_frappe15_throw_keeps_one_display_and_english_diagnostic(monkeypatch, tmp_path, adapter, language, wrapper, muted):
    from types import SimpleNamespace

    b, doc, translate = configured(monkeypatch, tmp_path, adapter, language=language)
    reference = REFERENCE.with_name('frappe15_messages_7b430f5.py')
    raw = reference.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '99a0eb0f585e564bb430c30dd93f1d77961fa49b69d429ee7a5f985da1f268e5'
    source = ast.literal_eval(ast.parse(raw).body[1].value)
    messages = []
    namespace = dict(
        safe_decode=lambda text:text, _dict=MessageDict,
        flags=SimpleNamespace(mute_messages=muted, print_messages=False),
        message_log=messages, generate_hash=lambda:'synthetic-message-id',
        _=lambda text, **kwargs:translate(text), ValidationError=ExistingXmlSubmissionError,
    )
    exec(compile('from __future__ import annotations\n'+source, str(reference), 'exec'), namespace)
    b.frappe.throw = namespace['throw']
    b.path.write_bytes(MUTATIONS['digest_changed'])
    if wrapper:
        extractor = ('extract_invoice_data_from_field' if adapter[0].__name__.endswith('pos_submit_with_xml_qr')
                     else 'extract_uuid_and_invoicehash' if adapter[4]
                     else 'extract_uuid_and_invoicehash_simplifeid')
        monkeypatch.setattr(adapter[0], extractor, lambda path:('test-uuid', 'test-hash'))
    with pytest.raises(ExistingXmlSubmissionError) as caught:
        call(b, doc, getattr(adapter[0], adapter[2] if wrapper else adapter[1]), wrapper)
    assert len(messages) == (0 if muted else 1)
    if not muted:
        assert messages[0].message == translate(REVIEW)
        assert messages[0].raise_exception == 1 and messages[0].indicator == 'red'
    # Native Frappe replaces exception.args with the display string. The explicit
    # diagnostic was recorded in English before that mutation; it is not a log of args.
    assert str(caught.value) == REVIEW and caught.value.args == (translate(REVIEW),)
    assert b.frappe.log_error.call_count == 1
    assert b.frappe.log_error.call_args.kwargs['message'].endswith(REVIEW)
    b.post.assert_not_called()
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()
    b.frappe.db.commit.assert_not_called()


PARENTS = (
    ('sign_invoice', 'zatca_background', 'manual'),
    ('sign_invoice', 'zatca_background_on_submit', 'hook'),
    ('sign_invoice', 'resubmit_invoices', 'batch'),
    ('pos_sign', 'zatca_background_', 'manual'),
    ('pos_sign', 'zatca_background_on_submit', 'hook'),
    ('pos_sign', 'resubmit_invoices_pos', 'batch'),
)


@pytest.mark.parametrize('module_name,name,kind', PARENTS)
@pytest.mark.parametrize('language', ['en', 'ar'])
def test_real_public_parent_boundaries_preserve_review_object(monkeypatch, module_name, name, kind, language):
    import importlib
    import inspect
    from types import SimpleNamespace

    module = importlib.import_module('zatca_erpgulf.zatca_erpgulf.' + module_name)
    error = ExistingXmlSubmissionError('existing_xml_identity_changed')
    error.diagnostic_logged = True
    if language == 'ar': error.args = ('رسالة العرض العربية',)
    runtime = SimpleNamespace(
        get_doc=Mock(side_effect=error), throw=Mock(),
        ValidationError=ExistingXmlSubmissionError.__mro__[1],
    )
    monkeypatch.setattr(module, 'frappe', runtime)
    monkeypatch.setattr(module, '_', lambda text:text)
    args = ('TEST', None) if kind == 'manual' else (['TEST'],) if kind == 'batch' else (SimpleNamespace(name='TEST'),)
    # With the real superclass binding, old handlers caught and wrapped the review.
    outcome(lambda:previous(module, name)(*args))
    runtime.throw.assert_called_once()
    runtime.throw.reset_mock()
    with pytest.raises(ExistingXmlSubmissionError) as caught:
        inspect.unwrap(getattr(module, name))(*args)
    assert caught.value is error
    runtime.throw.assert_not_called()


@pytest.mark.parametrize('doctype', ['Sales Invoice', 'POS Invoice'])
@pytest.mark.parametrize('commit', [False, True])
@pytest.mark.parametrize('already_logged', [False, True])
def test_background_review_keeps_other_invoices_running_without_duplicate_log(worker_boundary, doctype, commit, already_logged):
    from zatca_erpgulf.zatca_erpgulf import background_worker

    b = worker_boundary
    b.company('OPEN')
    bad = b.invoice(doctype, 'review', 'OPEN')
    good = b.invoice(doctype, 'next', 'OPEN')
    error = ExistingXmlSubmissionError('existing_xml_identity_changed')
    error.diagnostic_logged = already_logged
    if already_logged:
        b.frappe.log_error(title='ZATCA existing XML review', message=str(error))
    callback = Mock(side_effect=[error, None])
    background_worker.run_pending_background_invoices(doctype, callback, commit_per_invoice=commit)
    assert [c.args[0] for c in callback.call_args_list] == [bad, good]
    assert b.frappe.log_error.call_count == 1
    assert b.frappe.log_error.call_args.kwargs['message'] == REVIEW
    assert b.frappe.db.commit.call_count == int(commit)
    assert bad.custom_zatca_status == 'Not Submitted'
    bad.submit.assert_not_called()
