"""Destructive hook wiring, legacy isolation and redacted display boundaries."""

import ast
import csv
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import native_invoice_lifecycle as guard
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document


@pytest.mark.parametrize('doctype',['Sales Invoice','POS Invoice','Customer'])
def test_old_installations_without_native_schema_do_not_start_a_storage_service(doctype):
    runtime=SimpleNamespace(get_meta=lambda dt:SimpleNamespace(has_field=lambda field:False),db=Mock())
    guard.inspect_source_lifecycle(Document(doctype=doctype,name='TEST',custom_uuid='EXISTS'),runtime=runtime)
    runtime.db.sql.assert_not_called()


@pytest.mark.parametrize('failure',[RuntimeError('PRIVATE SQL PASSWORD'),guard.NativeInvoiceLifecycleError('static_code')])
@pytest.mark.parametrize('broken_log',[False,True])
def test_one_translated_error_keeps_private_context_out_even_when_logging_fails(monkeypatch,failure,broken_log):
    runtime=SimpleNamespace(log_error=Mock(side_effect=RuntimeError('PRIVATE LOG') if broken_log else None))
    monkeypatch.setattr(guard,'frappe',runtime)
    monkeypatch.setattr(guard,'_',lambda message:'AR:'+message)
    monkeypatch.setattr(guard,'inspect_source_lifecycle',Mock(side_effect=failure))
    with pytest.raises(guard.NativeInvoiceLifecycleError) as caught:
        guard.protect_native_invoice_lifecycle(Document(doctype='Sales Invoice',name='TEST'),'before_cancel')
    assert str(caught.value)=='AR:'+guard.REVIEW and caught.value.__context__ is None
    assert 'PRIVATE' not in repr(runtime.log_error.call_args)
    runtime.log_error.assert_called_once()


def test_sales_and_pos_destructive_hooks_preserve_other_cancel_validators():
    tree=ast.parse((Path(__file__).resolve().parents[2]/'hooks.py').read_text())
    events=next(ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign)
        and any(isinstance(target,ast.Name) and target.id=='doc_events' for target in node.targets))
    method='zatca_erpgulf.zatca_erpgulf.native_invoice_lifecycle.protect_native_invoice_lifecycle'
    for dt in ('Sales Invoice','POS Invoice'):
        assert events[dt]['on_trash']==events[dt]['before_rename']==method
        assert events[dt]['before_cancel'][0]==method
        assert 'zatca_erpgulf.zatca_erpgulf.validations.before_save' in events[dt]['before_cancel']
    assert 'zatca_erpgulf.zatca_erpgulf.advance_deduction.validate_advance_payment_invoice_cancellation' in events['Sales Invoice']['before_cancel']


def test_display_message_has_real_arabic_translation():
    with (Path(__file__).resolve().parents[2]/'translations'/'ar.csv').open(newline='',encoding='utf-8') as handle:
        rows={row[0]:row[1] for row in csv.reader(handle) if len(row)>1}
    assert any('\u0600'<=letter<='\u06ff' for letter in rows[guard.REVIEW])
