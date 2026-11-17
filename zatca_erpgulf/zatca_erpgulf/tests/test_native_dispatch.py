"""Owned coordinator with real signing/capture and explicit repository doubles.

The separate private InnoDB suite verifies repository commits and locks. This
suite verifies orchestration and rollback decisions without installed schemas,
site access, HTTP, accounting records or customer credentials.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import base64
import json
from types import SimpleNamespace
from unittest.mock import Mock

from lxml import etree
import pytest

from zatca_erpgulf.zatca_erpgulf import native_dispatch as dispatch
from zatca_erpgulf.zatca_erpgulf import sign_invoice, sign_invoice_first, submission_context
from zatca_erpgulf.zatca_erpgulf.invoice_payload import read_invoice_payload
from zatca_erpgulf.zatca_erpgulf.issuing_attempt import ACTIVE, confirm_issuing_transport
from zatca_erpgulf.zatca_erpgulf.native_preparation import ACTIVE_PREPARATION
from zatca_erpgulf.zatca_erpgulf.issuing_attempt import _source_observation
from zatca_erpgulf.zatca_erpgulf.signed_xml_pipeline import SigningTools, sign_invoice_xml
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_issuing_attempt import boundary, materials, setup
from zatca_erpgulf.zatca_erpgulf.tests.test_native_preparation import registration, reader


@pytest.fixture
def coordinator(boundary, materials, monkeypatch):
    b = boundary
    b.frappe.local = SimpleNamespace(site='fictional.invalid')
    owner = setup(b, monkeypatch, 'company')
    b.company.custom_zatca_invoice_enabled = 1
    b.company.custom_phase_1_or_2 = 'Phase-2'
    b.company.company_name = 'Synthetic issuer'
    for source in (b.sales, b.pos):
        source.docstatus = 1
    original = b.frappe.get_doc.side_effect
    b.frappe.get_doc.side_effect = lambda *args, **kwargs: original(*args)
    b.frappe.get_meta = Mock(return_value=SimpleNamespace(get_table_fields=lambda: []))
    def permitted(doctype, operation, *, doc, user, raise_exception=True):
        assert raise_exception is False
        return True
    b.frappe.has_permission = permitted
    chain = registration(b, owner, materials[0])
    state = SimpleNamespace(active=False, committed=False, rolled_back=False)
    def sql(statement, values=(), **kwargs):
        if 'information_schema.columns' in statement:
            return [dict(fieldname=name, kind='varchar', max_chars=140, declaration='varchar(140)')
                for name in ('custom_uuid', 'custom_zatca_icv', 'custom_zatca_issuing_unit')]
        return [{'changed': 1}]
    database = SimpleNamespace(sql=Mock(side_effect=sql))
    worker = SimpleNamespace(database=database, actor=b.frappe.session.user, site=b.frappe.local.site,
        storage_namespace='30000000-0000-4000-8000-000000000001', cipher=object(),
        owner_current=lambda: state.active)
    worker.utc_now = lambda: datetime(2026, 11, 17, 9, 0, 0)
    def commit():
        assert state.active
        state.committed = True
    worker.commit = Mock(side_effect=commit)
    @contextmanager
    def preparing(tables):
        assert 'tabSales Invoice' in tables and 'tabCompany' in tables
        yield
    worker.preparing = preparing
    @contextmanager
    def transaction(runtime):
        assert runtime is b.frappe
        state.active = True
        try:
            yield worker
        finally:
            if not state.committed:
                state.rolled_back = True
            state.active = False
    repository = SimpleNamespace(lock_active_chain=Mock(return_value=chain),
        latest_issuance=Mock(return_value=None), open_issuance=Mock(), stage_issuance=Mock())
    factory = Mock(return_value=repository)
    monkeypatch.setattr(dispatch, 'owned_worker_transaction', transaction)
    monkeypatch.setattr(dispatch, 'DispatchStore', factory)
    return SimpleNamespace(b=b, chain=chain, state=state, worker=worker,
        repository=repository, factory=factory)


def signed_build(b, source, *, validation_type='Simplified Invoice', endpoint='invoices/reporting/single'):
    """Exercise actual native formatter, credential scope and final HTTP fence."""
    ticket = ACTIVE_PREPARATION.get()
    assert ticket is not None
    _, xml = sign_invoice._build_onboarding_invoice_xml(b.company, validation_type,
        issue_instant=datetime(2026, 11, 10, 9, 5, 42, tzinfo=timezone.utc))
    root = etree.fromstring(xml.encode())
    ns = {'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
          'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'}
    root.find('cbc:ID', ns).text = source.name
    root.find('cbc:UUID', ns).text = ticket.invoice_uuid
    root.xpath("./cac:AdditionalDocumentReference[cbc:ID='ICV']/cbc:UUID", namespaces=ns)[0].text = ticket.icv
    root.xpath("./cac:AdditionalDocumentReference[cbc:ID='PIH']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject",
        namespaces=ns)[0].text = ticket.previous_hash
    signed = sign_invoice_xml(etree.tostring(root).decode(), 'TC', source,
        tools=SigningTools.from_namespace(vars(sign_invoice_first)))
    ACTIVE.get().expect_prepared_payload(ticket.invoice_uuid, signed.encoded_hash)
    path = sign_invoice_first.structuring_signedxml(source.name, signed.xml)
    submission_context.get_submission_context('TC', source, source.name,
        endpoint, expected_doctype=source.doctype)
    read_invoice_payload(ticket.invoice_uuid, signed.encoded_hash, path, read_xml=reader)
    confirm_issuing_transport('TC', source, runtime=b.frappe)


@pytest.mark.parametrize('source_kind', ['sales', 'pos'])
def test_exact_native_handoff_is_stored_before_source_outputs_and_commit(coordinator, monkeypatch, source_kind):
    c = coordinator
    b = c.b
    source = getattr(b, source_kind)
    address = Document(address_line1='Test Street', address_line2='District', city='Riyadh',
        custom_building_number='1234', pincode='12345', state='')
    monkeypatch.setattr(sign_invoice, '_onboarding_address', lambda *args: address)
    result = dispatch.prepare_saved_invoice(source.doctype, source.name, runtime=b.frappe,
        translate=lambda text: text, build=lambda locked: signed_build(b, locked))
    assert not result.reused and result.state == 'PREPARED'
    c.repository.stage_issuance.assert_called_once()
    saved_chain, header, original = c.repository.stage_issuance.call_args.args
    assert saved_chain is c.chain
    assert header['artifact_sha256'] == hashlib.sha256(original).hexdigest()
    assert header['source_name'] == source.name and header['icv'] == '1'
    assert c.worker.database.sql.call_count == 5
    assert c.state.committed and not c.state.rolled_back
    b.request.assert_not_called()
    b.frappe.db.commit.assert_not_called()
    assert ACTIVE.get() is ACTIVE_PREPARATION.get() is None


@pytest.mark.parametrize('denied', [('Sales Invoice', 'read'), ('Sales Invoice', 'write'), ('Company', 'read')])
def test_permission_denial_precedes_retained_original_or_registration_access(coordinator, denied):
    c = coordinator
    def permission(doctype, operation, *, doc, user, raise_exception=True):
        return (doctype, operation) != denied
    c.b.frappe.has_permission = permission
    with pytest.raises(dispatch.NativeDispatchError) as caught:
        dispatch.prepare_saved_invoice('Sales Invoice', 'SI', runtime=c.b.frappe,
            translate=lambda text: text, build=Mock())
    assert caught.value.code == 'native_source_permission'
    c.factory.assert_not_called()
    assert c.state.rolled_back and not c.state.committed


def test_unknown_original_is_recovered_without_regeneration_or_counter_update(coordinator):
    c = coordinator
    c.repository.latest_issuance.return_value = {'record_id': 'SAVED', 'state': 'OUTCOME_UNKNOWN'}
    c.repository.open_issuance.return_value = (dict(company='A', environment='Production',
        chain=c.chain['record_id'], source_doctype='Sales Invoice', source_name='SI',
        base_url_sha256=hashlib.sha256(b'https://example.invalid/core').hexdigest(),
        source_sha256=dispatch.source_observation_sha256(('Sales Invoice', 'SI'), _source_observation(c.b.sales)),
        certificate_sha256=c.chain['certificate_sha256'], public_key_sha256=c.chain['public_key_sha256']), b'EXACT')
    build = Mock(side_effect=AssertionError('Unknown original must not be regenerated'))
    result = dispatch.prepare_saved_invoice('Sales Invoice', 'SI', runtime=c.b.frappe,
        translate=lambda text: text, build=build)
    assert result.reused and result.state == 'OUTCOME_UNKNOWN'
    build.assert_not_called()
    c.repository.stage_issuance.assert_not_called()
    c.worker.database.sql.assert_not_called()


@pytest.mark.parametrize('field,value', [('custom_uuid', 'OLD'), ('custom_zatca_icv', '55'),
    ('custom_zatca_issuing_unit', 'OLD-UNIT'), ('custom_xml', '/private/old.xml'), ('custom_zatca_status', 'REPORTED'),
    ('custom_zatca_status', 'ERROR'), ('custom_zatca_full_response', '{"reportingStatus":"REPORTED"}')])
def test_legacy_source_identity_requires_review_instead_of_new_genesis(coordinator, field, value):
    c = coordinator
    setattr(c.b.sales, field, value)
    build = Mock()
    with pytest.raises(dispatch.NativeDispatchError) as caught:
        dispatch.prepare_saved_invoice('Sales Invoice', 'SI', runtime=c.b.frappe,
            translate=lambda text: text, build=build)
    assert caught.value.code == 'native_legacy_issuance_review'
    assert c.state.rolled_back and not c.state.committed
    build.assert_not_called()


def test_returning_without_final_handoff_rolls_back_without_staging(coordinator):
    c = coordinator
    with pytest.raises(dispatch.NativeDispatchError) as caught:
        dispatch.prepare_saved_invoice('Sales Invoice', 'SI', runtime=c.b.frappe,
            translate=lambda text: text, build=lambda source: None)
    assert caught.value.code == 'native_preparation_did_not_handoff'
    assert c.state.rolled_back and not c.state.committed
    c.repository.stage_issuance.assert_not_called()


@pytest.mark.parametrize('value', [0, 2, True])
def test_source_update_requires_one_literal_changed_row(coordinator, value):
    c = coordinator
    c.worker.database.sql.side_effect = None
    c.worker.database.sql.return_value = [{'changed': value}]
    with pytest.raises(dispatch.NativeDispatchError) as caught:
        dispatch._changed_once(c.worker.database)
    assert caught.value.code == 'native_source_update_compare'


def saved_issuance(c):
    """A previously committed original with its matching local issuance outputs."""
    source = c.b.sales
    source.custom_uuid = '40000000-0000-4000-8000-000000000002'
    source.custom_zatca_icv = '1'
    source.custom_zatca_issuing_unit = 'egs:' + c.chain['record_id']
    original = b'EXACT-COMMITTED-ORIGINAL'
    header = dict(record_id='SAVED', company='A', environment='Production', chain=c.chain['record_id'],
        source_doctype='Sales Invoice', source_name='SI', invoice_uuid=source.custom_uuid, icv='1',
        endpoint='invoices/reporting/single', artifact_sha256=hashlib.sha256(original).hexdigest(),
        base_url_sha256=hashlib.sha256(b'https://example.invalid/core').hexdigest(),
        source_sha256=dispatch.source_observation_sha256(('Sales Invoice', 'SI'), _source_observation(source)),
        certificate_sha256=c.chain['certificate_sha256'], public_key_sha256=c.chain['public_key_sha256'])
    c.repository.latest_issuance.return_value = dict(header, state='PREPARED')
    c.repository.open_issuance.return_value = (header, original)
    c.repository.lock_issuance = Mock(return_value=header)
    c.repository.start_attempt = Mock(return_value={'endpoint': header['endpoint']})
    c.repository.lock_recorded_chain = Mock(return_value=c.chain)
    c.repository.retain_receipt = Mock(return_value=True)
    c.repository.mark_attempt_unknown = Mock(return_value=True)
    return header, original


def test_reservation_returns_exact_body_only_after_attempt_commit(coordinator):
    c = coordinator
    _, original = saved_issuance(c)
    invocation = dispatch.reserve_saved_issuance('Sales Invoice', 'SI', runtime=c.b.frappe, translate=lambda text: text)
    assert invocation.request_bytes is original and invocation.chain_id == c.chain['record_id']
    assert invocation.route.endpoint == 'invoices/reporting/single'
    c.repository.start_attempt.assert_called_once()
    reservation = c.repository.start_attempt.call_args.kwargs
    assert reservation['record_id'] == invocation.attempt_id and reservation['fence_token'] == invocation.fence_token
    assert c.state.committed and not c.state.active
    c.b.request.assert_not_called()
    c.repository.stage_issuance.assert_not_called()


@pytest.mark.parametrize('change', ['source', 'route', 'outputs', 'material'])
def test_reservation_refuses_changed_binding_without_resigning_or_starting_attempt(coordinator, change):
    c = coordinator
    header, _ = saved_issuance(c)
    if change == 'source':
        c.b.sales.grand_total = 999
    elif change == 'route':
        c.b.company.custom_production_url = 'https://another.invalid/core'
    elif change == 'outputs':
        c.b.sales.custom_uuid = 'DIFFERENT'
    elif change == 'material':
        header['certificate_sha256'] = '0' * 64
    with pytest.raises(dispatch.NativeDispatchError):
        dispatch.reserve_saved_issuance('Sales Invoice', 'SI', runtime=c.b.frappe, translate=lambda text: text)
    assert c.state.rolled_back and not c.state.committed
    c.repository.start_attempt.assert_not_called()
    c.repository.stage_issuance.assert_not_called()


def test_unknown_attempt_commit_cannot_release_invocation_for_http(coordinator):
    from zatca_erpgulf.zatca_erpgulf.worker_transaction import WorkerTransactionError
    c = coordinator
    saved_issuance(c)
    c.worker.commit.side_effect = WorkerTransactionError('worker_transaction_commit_unknown', commit_uncertain=True)
    with pytest.raises(WorkerTransactionError) as caught:
        dispatch.reserve_saved_issuance('Sales Invoice', 'SI', runtime=c.b.frappe, translate=lambda text: text)
    assert caught.value.commit_uncertain
    c.b.request.assert_not_called()


@pytest.mark.parametrize('received', [True, False])
def test_receipt_custody_does_not_require_current_source_permission_or_credentials(coordinator, received):
    c = coordinator
    saved_issuance(c)
    invocation = dispatch.reserve_saved_issuance('Sales Invoice', 'SI', runtime=c.b.frappe, translate=lambda text: text)
    c.state.committed = False
    c.b.frappe.get_doc.side_effect = AssertionError('No mutable source read while retaining a response')
    c.b.frappe.has_permission = Mock(side_effect=AssertionError('Custody must not discard a received response'))
    response = dispatch.NativeResponse(401, 'original-request', b'ORIGINAL-REJECTION') if received else None
    assert dispatch.retain_dispatch_observation(invocation, response, runtime=c.b.frappe)
    c.repository.lock_recorded_chain.assert_called_once_with(invocation.chain_id, invocation.owner_key)
    if received:
        assert c.repository.retain_receipt.call_args.kwargs['body'] is response.body
        c.repository.mark_attempt_unknown.assert_not_called()
    else:
        c.repository.mark_attempt_unknown.assert_called_once()
        c.repository.retain_receipt.assert_not_called()
    assert c.state.committed and not c.state.active


def test_assessment_uses_decrypted_original_and_receipt_then_commits_before_derived_writes(coordinator, monkeypatch):
    from zatca_erpgulf.zatca_erpgulf.native_response import NativeAssessment
    c = coordinator
    header, original = saved_issuance(c)
    invocation = dispatch.reserve_saved_issuance('Sales Invoice', 'SI', runtime=c.b.frappe, translate=lambda text: text)
    c.state.committed = False
    metadata = dict(fence_token=invocation.fence_token, endpoint=header['endpoint'])
    receipt = b'COMMITTED-ORIGINAL-RECEIPT'
    c.repository.open_receipt = Mock(return_value=(metadata, receipt))
    c.repository.record_assessment = Mock(return_value=True)
    assessment = NativeAssessment('REPORTING_MATCHED')
    assessor = Mock(return_value=assessment)
    monkeypatch.setattr(dispatch, 'assess_native_receipt', assessor)
    result, current = dispatch.assess_retained_dispatch(invocation, runtime=c.b.frappe)
    assert result is assessment and current
    assessor.assert_called_once_with(header, original, metadata, receipt, fallback_receipt=None)
    c.repository.record_assessment.assert_called_once_with(c.chain, header,
        attempt_id=invocation.attempt_id, fence_token=invocation.fence_token, outcome='REPORTING_MATCHED')
    assert c.worker.database.sql.call_count == 1  # Reservation capacity preflight only.
    assert c.state.committed and not c.state.active


@pytest.fixture
def orchestration(monkeypatch):
    from zatca_erpgulf.zatca_erpgulf.native_response import NativeAssessment
    calls = []
    invocation = SimpleNamespace(issuance_id='issued', attempt_id='attempt')
    received = dispatch.NativeResponse(200, 'request', b'ORIGINAL')
    functions = {}
    results = {'read_retained_invoice': None, 'prepare_saved_invoice': None, 'reserve_saved_issuance': invocation,
        'invoke_saved_request': received, 'retain_dispatch_observation': True,
        'assess_retained_dispatch': (NativeAssessment('REPORTING_MATCHED'), True)}
    for name, result in results.items():
        def run(*args, _name=name, _result=result, **kwargs):
            calls.append(_name)
            return _result
        functions[name] = Mock(side_effect=run)
        monkeypatch.setattr(dispatch, name, functions[name])
    def execute():
        return dispatch.dispatch_saved_invoice('Sales Invoice', 'SI', runtime=object(),
            translate=lambda text: text, build=lambda source: None)
    return SimpleNamespace(calls=calls, functions=functions, execute=execute,
        invocation=invocation, received=received)


def test_central_coordinator_retains_before_assessing_and_never_repeats_a_normal_send(orchestration):
    o = orchestration
    outcome = o.execute()
    assert outcome.current and outcome.outcome == 'REPORTING_MATCHED'
    assert o.calls == ['read_retained_invoice', 'prepare_saved_invoice', 'reserve_saved_issuance', 'invoke_saved_request',
        'retain_dispatch_observation', 'assess_retained_dispatch']
    assert o.functions['retain_dispatch_observation'].call_args.args == (o.invocation, o.received)


@pytest.mark.parametrize('invoked', [True, False])
def test_central_transport_failure_retains_uncertainty_without_regeneration(orchestration, invoked):
    o = orchestration
    o.functions['invoke_saved_request'].side_effect = dispatch.NativeTransportError('native_transport_outcome_unknown', invoked=invoked)
    with pytest.raises(dispatch.NativeDispatchReview) as caught:
        o.execute()
    assert caught.value.invoked is invoked and not caught.value.receipt_retained
    assert caught.value.issuance_id == 'issued' and caught.value.__context__ is None
    assert o.functions['retain_dispatch_observation'].call_args.args == (o.invocation, None)
    o.functions['assess_retained_dispatch'].assert_not_called()
    assert o.functions['prepare_saved_invoice'].call_count == o.functions['reserve_saved_issuance'].call_count == 1


@pytest.mark.parametrize('stage,retained', [('retain_dispatch_observation', False), ('assess_retained_dispatch', True)])
def test_received_response_local_failure_has_truthful_stage_and_no_inline_resend(orchestration, stage, retained):
    o = orchestration
    o.functions[stage].side_effect = RuntimeError('PRIVATE-LOCAL-DETAILS')
    with pytest.raises(dispatch.NativeDispatchReview) as caught:
        o.execute()
    assert caught.value.invoked and caught.value.receipt_retained is retained
    assert caught.value.__context__ is None and 'PRIVATE' not in str(caught.value)
    assert o.functions['invoke_saved_request'].call_count == 1
    if not retained:
        o.functions['assess_retained_dispatch'].assert_not_called()


@pytest.mark.parametrize('current', [True, False])
def test303_fallback_is_bounded_current_only_and_does_not_prepare_twice(orchestration, current):
    from zatca_erpgulf.zatca_erpgulf.native_response import NativeAssessment
    o = orchestration
    o.functions['assess_retained_dispatch'].side_effect = [
        (NativeAssessment('CLEARANCE_DISABLED'), current), (NativeAssessment('REPORTING_MATCHED'), True)]
    outcome = o.execute()
    assert outcome.outcome == ('REPORTING_MATCHED' if current else 'CLEARANCE_DISABLED')
    assert o.functions['prepare_saved_invoice'].call_count == 1
    assert o.functions['invoke_saved_request'].call_count == (2 if current else 1)
    if current:
        assert o.functions['reserve_saved_issuance'].call_args.kwargs['supersedes_attempt'] == 'attempt'


def test_undefined_sender_result_never_becomes_a_retained_success(orchestration):
    o = orchestration
    o.functions['invoke_saved_request'].side_effect = None
    o.functions['invoke_saved_request'].return_value = None
    with pytest.raises(dispatch.NativeDispatchReview) as caught:
        o.execute()
    assert caught.value.code == 'native_transport_contract_unknown'
    assert not caught.value.receipt_retained
    o.functions['assess_retained_dispatch'].assert_not_called()


def test_accepted_custody_short_circuits_preparation_credentials_and_http(orchestration):
    o = orchestration
    o.functions['read_retained_invoice'].side_effect = None
    o.functions['read_retained_invoice'].return_value = SimpleNamespace(accepted=True,
        issuance_id='SAVED', attempt_id='ORIGINAL-ATTEMPT', outcome='REPORTING_MATCHED',
        warning_count=1, has_warnings=True)
    result = o.execute()
    assert result.reused_accepted and result.issuance_id == 'SAVED' and result.has_warnings
    o.functions['prepare_saved_invoice'].assert_not_called()
    o.functions['reserve_saved_issuance'].assert_not_called()
    o.functions['invoke_saved_request'].assert_not_called()


def test_existing_unaccepted_original_is_reserved_without_running_the_builder(orchestration):
    o = orchestration
    o.functions['read_retained_invoice'].side_effect = None
    o.functions['read_retained_invoice'].return_value = SimpleNamespace(accepted=False)
    assert o.execute().outcome == 'REPORTING_MATCHED'
    o.functions['prepare_saved_invoice'].assert_not_called()
    o.functions['reserve_saved_issuance'].assert_called_once()


@pytest.mark.parametrize('kind,declaration,limit,value,valid', [
    ('int', 'int(11)', None, str(2**31-1), True), ('int', 'int(11)', None, str(2**31), False),
    ('bigint', 'bigint(20)', None, str(2**63-1), True), ('bigint', 'bigint(20)', None, str(2**63), False),
    ('bigint', 'bigint(20) unsigned', None, str(2**64-1), True),
    ('varchar', 'varchar(64)', 64, '9'*64, True), ('varchar', 'varchar(3)', 3, '1000', False),
    ('float', 'float', None, '1', False), ('decimal', 'decimal(20,0)', None, '1', False),
])
def test_source_capacity_uses_exact_storage_limits_without_float(kind, declaration, limit, value, valid):
    rows = [dict(fieldname=name, kind='varchar', max_chars=140, declaration='varchar(140)')
        for name in ('custom_uuid', 'custom_zatca_icv', 'custom_zatca_issuing_unit')]
    rows[1].update(kind=kind, declaration=declaration, max_chars=limit)
    database = SimpleNamespace(sql=Mock(return_value=rows))
    if valid:
        dispatch._require_source_output_capacity(database, 'POS Invoice', value)
    else:
        with pytest.raises(dispatch.NativeDispatchError) as caught:
            dispatch._require_source_output_capacity(database, 'POS Invoice', value)
        assert caught.value.code == 'native_source_counter_capacity'
    assert database.sql.call_count == 1
    assert database.sql.call_args.args[0].startswith('SELECT')


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'uuid_short', 'unit_short'])
def test_missing_or_insufficient_output_columns_stop_before_build_or_staging(coordinator, fault):
    c = coordinator
    rows = [dict(fieldname=name, kind='varchar', max_chars=140, declaration='varchar(140)')
        for name in ('custom_uuid', 'custom_zatca_icv', 'custom_zatca_issuing_unit')]
    if fault == 'missing':
        rows.pop()
    elif fault == 'duplicate':
        rows.append(rows[0])
    elif fault == 'uuid_short':
        rows[0]['max_chars'] = 35
    elif fault == 'unit_short':
        rows[2]['max_chars'] = 39
    c.worker.database.sql.side_effect = None
    c.worker.database.sql.return_value = rows
    build = Mock()
    with pytest.raises(dispatch.NativeDispatchError) as caught:
        dispatch.prepare_saved_invoice('Sales Invoice', 'SI', runtime=c.b.frappe,
            translate=lambda text: text, build=build)
    assert caught.value.code == 'native_source_output_schema_required'
    build.assert_not_called()
    c.repository.stage_issuance.assert_not_called()
    assert c.state.rolled_back and not c.state.committed


def retained_reader(c, *, accepted=True):
    from zatca_erpgulf.zatca_erpgulf.tests.test_native_response import evidence, success
    header, _unused, xml = evidence()
    xml = xml.replace(b'INV-TEST', b'SI')
    original = json.dumps(dict(invoiceHash=header['invoice_hash'], uuid=header['invoice_uuid'],
        invoice=base64.b64encode(xml).decode())).encode()
    header.update(source_name='SI', artifact_sha256=hashlib.sha256(original).hexdigest())
    source = c.b.sales
    source.custom_zatca_issuing_unit = 'egs:' + c.chain['record_id']
    source.custom_uuid = header['invoice_uuid']
    source.custom_zatca_icv = header['icv']
    saved = dict(header, state='REPORTED' if accepted else 'PREPARED', active_attempt='attempt' if accepted else None)
    c.repository.find_source_issuance = Mock(return_value=saved)
    c.repository.open_issuance.return_value = (header, original)
    body = json.dumps(success(header, xml)).encode()
    receipt = dict(issuance=header['record_id'], request_sha256=header['artifact_sha256'],
        environment=header['environment'], endpoint=header['endpoint'], http_status=200,
        response_sha256=hashlib.sha256(body).hexdigest())
    c.repository.open_receipt = Mock(return_value=(receipt, body))
    return xml, saved, receipt


@pytest.mark.parametrize('accepted', [True, False])
def test_read_view_needs_read_acl_and_stored_identity_not_current_credentials(coordinator, accepted):
    c = coordinator
    xml, saved, _receipt = retained_reader(c, accepted=accepted)
    def permission(doctype, operation, *, doc, user, raise_exception=True):
        assert raise_exception is False
        return operation == 'read'
    c.b.frappe.has_permission = permission
    c.b.company.custom_private_key = 'INVALID-MUST-NOT-BE-PARSED'
    c.b.company.custom_basic_auth_from_production = None
    c.b.company.custom_phase_1_or_2 = 'Phase-1'
    view = dispatch.read_retained_invoice('Sales Invoice', 'SI', runtime=c.b.frappe)
    assert view.original_xml == xml and view.accepted is accepted
    assert view.state == saved['state']
    assert c.state.rolled_back and not c.state.committed  # Read-only owned scope.
    c.b.request.assert_not_called()
    if not accepted:
        c.repository.open_receipt.assert_not_called()


def test_read_view_does_not_trust_a_saved_acceptance_status_without_matching_receipt(coordinator):
    c = coordinator
    _xml, _saved, receipt = retained_reader(c)
    receipt['request_sha256'] = '0' * 64
    with pytest.raises(dispatch.NativeDispatchError) as caught:
        dispatch.read_retained_invoice('Sales Invoice', 'SI', runtime=c.b.frappe)
    assert caught.value.code == 'native_retained_acceptance_review'


def test_read_denial_precedes_any_custody_or_credential_lookup(coordinator):
    c = coordinator
    retained_reader(c)
    c.b.frappe.has_permission = lambda doctype, operation, *, doc, user, raise_exception=True: False
    with pytest.raises(dispatch.NativeDispatchError) as caught:
        dispatch.read_retained_invoice('Sales Invoice', 'SI', runtime=c.b.frappe)
    assert caught.value.code == 'native_source_permission'
    c.factory.assert_not_called()


def test_float_source_counter_cannot_select_a_historical_original(coordinator):
    c = coordinator
    retained_reader(c)
    c.b.sales.custom_zatca_icv = 77.0
    with pytest.raises(dispatch.NativeDispatchError) as caught:
        dispatch.read_retained_invoice('Sales Invoice', 'SI', runtime=c.b.frappe)
    assert caught.value.code == 'native_retained_source_identity'
    c.factory.assert_not_called()
