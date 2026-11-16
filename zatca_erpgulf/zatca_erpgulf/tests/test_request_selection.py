"""One observed request selection; no tenant, HTTP or material-validation claim."""

import ast
import hashlib
from pathlib import Path
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import api_settings, credential_settings, submission_context
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import (
    boundary, select_owner, ValidationError,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_invoice_payload import outcome

REFERENCE = Path(__file__).with_name('fixtures') / 'request_selection_4e5d9be.py'
REFERENCE_SHA = 'f79cb7222fe18bc5fd857de92292205b28bb7c3c894de5ace135266dd7a0a21c'
ENDPOINTS = ('invoices/reporting/single', 'invoices/clearance/single')


def previous(module, name):
    raw = REFERENCE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == REFERENCE_SHA
    sources = ast.literal_eval(ast.parse(raw).body[1].value)
    key = 'zatca_erpgulf/zatca_erpgulf/' + module.__name__.rsplit('.', 1)[-1] + '.py'
    namespace = dict(vars(module),
        get_company_api_route=api_settings.get_company_api_route,
        get_api_authorization=credential_settings.get_api_authorization,
    )
    exec(compile(sources[key], str(REFERENCE), 'exec'), namespace)
    return namespace[name]


def invoke(b, fn, endpoint, require):
    return fn('TC', b.sales, b.sales.name, endpoint,
              expected_doctype='Sales Invoice', require_issuing_unit=require)


@pytest.mark.parametrize('owner', ['company', 'device', 'linked'])
@pytest.mark.parametrize('environment', ['Sandbox', 'Simulation', 'Production'])
@pytest.mark.parametrize('endpoint', ENDPOINTS)
@pytest.mark.parametrize('require', [False, True])
def test_parent_policy_route_header_and_owner_are_preserved(monkeypatch, owner, environment, endpoint, require):
    observed = []
    for old in (True, False):
        with monkeypatch.context() as patch:
            b = boundary.__wrapped__(patch)
            select_owner(b, b.sales, owner)
            b.company.custom_select = environment
            fn = previous(submission_context, 'get_submission_context') if old else submission_context.get_submission_context
            result = outcome(lambda: invoke(b, fn, endpoint, require))
            if result[0] == 'return':
                context = result[1]
                result = (result[0], context.route, context.authorization)
            observed.append(result)
            b.post.assert_not_called()
            assert not b.files
            for doc in (b.sales, b.company, b.linked, b.device):
                doc.save.assert_not_called()
                doc.db_set.assert_not_called()
            b.frappe.db.commit.assert_not_called()
    assert observed[0] == observed[1]


@pytest.mark.parametrize('owner', ['company', 'device', 'linked'])
@pytest.mark.parametrize('endpoint', ENDPOINTS)
@pytest.mark.parametrize('require', [False, True])
def test_company_and_source_are_not_reloaded_for_separate_policies(boundary, owner, endpoint, require):
    b = boundary
    select_owner(b, b.sales, owner)
    if require and owner == 'company':
        with pytest.raises(ValidationError): invoke(b, submission_context.get_submission_context, endpoint, require)
        return
    invoke(b, submission_context.get_submission_context, endpoint, require)
    calls = b.frappe.get_doc.call_args_list
    assert sum(c.args == ('Company', {'abbr': 'TC'}) for c in calls) == 1
    assert sum(c.args == ('Sales Invoice', b.sales.name) for c in calls) == 1
    assert sum(c.args == ('ZATCA Multiple Setting', 'DEVICE') for c in calls) == int(owner != 'company')


@pytest.mark.parametrize('old', [True, False])
@pytest.mark.parametrize('endpoint', ENDPOINTS)
def test_rotation_between_company_and_source_read_cannot_mix_route_and_auth(boundary, old, endpoint):
    b = boundary
    original = b.frappe.get_doc.side_effect
    company_reads = 0
    def load(doctype, name):
        nonlocal company_reads
        if doctype == 'Company' and isinstance(name, dict):
            company_reads += 1
            if company_reads == 2:
                b.company.custom_select = 'Sandbox'
                b.company.custom_basic_auth_from_production = 'ROTATED-TOKEN'
        return original(doctype, name)
    b.frappe.get_doc.side_effect = load
    fn = previous(submission_context, 'get_submission_context') if old else submission_context.get_submission_context
    context = invoke(b, fn, endpoint, False)
    assert context.route.environment == 'Production'
    assert context.authorization.header == ('Basic ROTATED-TOKEN' if old else 'Basic COMPANY-PRODUCTION')
    assert company_reads == (2 if old else 1)


@pytest.mark.parametrize('owner', ['company', 'device', 'linked'])
def test_freeze_company_before_source_callback_mutates_original_row(boundary, owner):
    b = boundary
    select_owner(b, b.sales, owner)
    original = b.frappe.get_doc.side_effect
    def load(doctype, name):
        if doctype == 'Sales Invoice':
            b.company.tax_id = 'AFTER-TAXPAYER'
            b.company.custom_basic_auth_from_production = 'AFTER-COMPANY-TOKEN'
            b.company.custom_select = 'Sandbox'
        return original(doctype, name)
    b.frappe.get_doc.side_effect = load
    context = invoke(b, submission_context.get_submission_context, ENDPOINTS[0], False)
    assert context.route.environment == 'Production'
    expected = 'Basic COMPANY-PRODUCTION' if owner == 'company' else 'Basic DEVICE-PRODUCTION' if owner == 'device' else 'Basic LINKED-PRODUCTION'
    assert context.authorization.header == expected


def test_device_flags_and_auth_are_copied_before_linked_company_load(boundary):
    b = boundary
    select_owner(b, b.sales, 'device')
    b.device.custom_linked_doctype = 'B'
    original = b.frappe.get_doc.side_effect
    def load(doctype, name):
        if doctype == 'Company' and name == 'B':
            b.device.custom__use_company_certificate__keys = '1'
            b.device.custom_final_auth_csid = 'MUTATED'
        return original(doctype, name)
    b.frappe.get_doc.side_effect = load
    context = invoke(b, submission_context.get_submission_context, ENDPOINTS[0], False)
    assert context.authorization.owner_name == 'DEVICE'
    assert context.authorization.header == 'Basic DEVICE-PRODUCTION'


def test_issuing_unit_precheck_and_owner_resolution_use_same_saved_link(boundary):
    b = boundary
    select_owner(b, b.sales, 'device')
    original = b.frappe.get_doc.side_effect
    source_reads = 0
    def load(doctype, name):
        nonlocal source_reads
        if doctype == 'Sales Invoice':
            source_reads += 1
            if source_reads == 2: b.sales.custom_zatca_pos_name = ''
        return original(doctype, name)
    b.frappe.get_doc.side_effect = load
    context = invoke(b, submission_context.get_submission_context, ENDPOINTS[0], True)
    assert source_reads == 1 and context.authorization.owner_name == 'DEVICE'


@pytest.mark.parametrize('failure', ['environment', 'base_url', 'missing_auth', 'cross_taxpayer', 'link_flag'])
@pytest.mark.parametrize('endpoint', ENDPOINTS)
def test_existing_local_failures_preserved_without_write(monkeypatch, failure, endpoint):
    observed = []
    for old in (True, False):
        with monkeypatch.context() as patch:
            b = boundary.__wrapped__(patch)
            select_owner(b, b.sales, 'linked')
            if failure == 'environment': b.company.custom_select = ''
            elif failure == 'base_url': b.company.custom_production_url = 'http://bad.invalid/'
            elif failure == 'missing_auth': b.linked.custom_basic_auth_from_production = ''
            elif failure == 'cross_taxpayer': b.linked.tax_id = 'OTHER'
            else: b.device.custom__use_company_certificate__keys = 'unknown'
            fn = previous(submission_context, 'get_submission_context') if old else submission_context.get_submission_context
            observed.append(outcome(lambda:invoke(b, fn, endpoint, False)))
            b.post.assert_not_called()
            b.frappe.db.commit.assert_not_called()
    assert observed[0] == observed[1]


def test_no_cache_between_attempts_and_no_secret_in_context_repr(boundary):
    b = boundary
    first = invoke(b, submission_context.get_submission_context, ENDPOINTS[0], False)
    b.company.custom_basic_auth_from_production = 'SECOND-TOKEN'
    second = invoke(b, submission_context.get_submission_context, ENDPOINTS[0], False)
    assert first.authorization.header == 'Basic COMPANY-PRODUCTION'
    assert second.authorization.header == 'Basic SECOND-TOKEN'
    assert 'SECOND-TOKEN' not in repr(second) and 'COMPANY-PRODUCTION' not in repr(first)
