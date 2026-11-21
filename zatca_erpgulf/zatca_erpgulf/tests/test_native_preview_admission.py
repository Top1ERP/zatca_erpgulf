"""Saved-only Desk classification; normal waiting does not create Error Logs."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import native_publication as publication
from zatca_erpgulf.zatca_erpgulf.tests.test_native_print_admission import printing, entry


def preview(e):
    return publication.preview_result(e.source.doctype, e.source.name,
        runtime=e.runtime, translate=lambda text: 'AR:' + text)


def assert_no_issuance(e):
    e.publication.assert_not_called(); e.prepare.assert_not_called()
    e.dispatch.assert_not_called(); e.build.assert_not_called()
    e.runtime.log_error.assert_not_called()
    assert e.runtime.flags == {}


@pytest.mark.parametrize('doctype', ['Sales Invoice', 'POS Invoice'])
@pytest.mark.parametrize('docstatus', [0, 1])
@pytest.mark.parametrize('rollout', [0, 1])
def test_named_unissued_native_preview_has_no_qr_issuance_or_false_acceptance(printing, doctype, docstatus, rollout):
    e = printing
    del e.docs[e.source.doctype, e.source.name]
    e.source.doctype = doctype; e.source.docstatus = docstatus
    e.docs[doctype, e.source.name] = e.source
    e.runtime.conf['zatca_native_dispatch'] = rollout
    before = deepcopy(vars(e.source))
    assert preview(e) == {'status': 'UNISSUED', 'message': 'AR:' + publication.UNISSUED}
    assert vars(e.source) == before
    assert_no_issuance(e)


@pytest.mark.parametrize('policy', ['phase1', 'disabled', 'legacy', 'old-schema'])
def test_legacy_classification_needs_no_native_storage_credentials_or_company_read(printing, policy):
    e = printing
    if policy == 'phase1':
        e.company.custom_phase_1_or_2 = 'Phase-1'
    elif policy == 'disabled':
        e.company.custom_zatca_invoice_enabled = 0
    elif policy == 'legacy':
        e.company.custom_zatca_native_chain = None
    else:
        e.runtime.get_meta = lambda dt: SimpleNamespace(has_field=lambda field: False)
    if policy != 'legacy':
        e.runtime.has_permission = lambda dt, op, *, doc, user, raise_exception=True: dt == e.source.doctype and op == 'read'
    e.company.custom_private_key = 'INVALID-NOT-USED'
    assert preview(e) == {'status': 'LEGACY'}
    assert_no_issuance(e)


@pytest.mark.parametrize('target', ['source', 'company'])
def test_failed_read_is_review_not_a_legacy_restore_or_native_wait_grant(printing, target):
    e = printing
    denied = e.source.doctype if target == 'source' else 'Company'
    e.runtime.has_permission = lambda dt, op, *, doc, user, raise_exception=True: dt != denied and op == 'read'
    assert preview(e) == {'status': 'REVIEW', 'message': 'AR:' + publication.REVIEW}
    e.publication.assert_not_called(); e.runtime.log_error.assert_called_once()
    assert 'AR:' not in repr(e.runtime.log_error.call_args)


@pytest.mark.parametrize('fault', ['identity', 'missing-source', 'bad-policy'])
def test_invalid_saved_selection_does_not_echo_private_values_or_restore_legacy(printing, fault):
    e = printing
    if fault == 'identity':
        wrong = deepcopy(e.source); wrong.name = 'PRIVATE-OTHER-SOURCE'
        e.runtime.get_doc = Mock(return_value=wrong)
    elif fault == 'missing-source':
        e.runtime.get_doc = Mock(side_effect=RuntimeError('PRIVATE-SQL-CREDENTIAL'))
    else:
        e.company.custom_zatca_native_chain = 'PRIVATE-INVALID-CHAIN'
    assert preview(e) == {'status': 'REVIEW', 'message': 'AR:' + publication.REVIEW}
    e.publication.assert_not_called()
    assert 'PRIVATE' not in repr(e.runtime.log_error.call_args)
