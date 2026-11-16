"""Native-shaped saved records and dependency drift; no site or database."""

from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from frappe.model.docstatus import DocStatus

from zatca_erpgulf.zatca_erpgulf.issuing_attempt import IssuingAttemptError
from zatca_erpgulf.zatca_erpgulf.issuing_observation import freeze_native_value, native_record_observation
from zatca_erpgulf.zatca_erpgulf.issuing_reads import (
    read_issuing_doc, read_issuing_cached_doc, read_issuing_all, read_issuing_value,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_issuing_attempt import (
    boundary, materials, setup, scope,
)


class NativeShape(SimpleNamespace):
    """as_dict selects fields; get returns the uncoerced original values."""
    def get(self, key, default=None):
        return getattr(self, key, default)

    def as_dict(self):
        return {key:value for key,value in vars(self).items() if not callable(value)}


def test_native_int_docstatus_read_is_not_a_false_data_change():
    plain = NativeShape(doctype='Sales Invoice', name='TEST', docstatus=1)
    expected = native_record_observation(plain)
    plain.docstatus = DocStatus(1)
    assert native_record_observation(plain) == expected
    plain.docstatus = DocStatus(2)
    assert native_record_observation(plain) != expected


@pytest.mark.parametrize('value', [
    Decimal('0.00000000000000000000001'), Decimal('-0.00'), Decimal('1.000'),
    Decimal('NaN'), Decimal('Infinity'), float('nan'), float('inf'), 'x'*100000,
])
def test_native_projection_does_not_hide_raw_values_behind_float_conversion(value):
    class ConvertsForExport(NativeShape):
        def as_dict(self):
            data = super().as_dict()
            data['grand_total'] = 0.0
            return data
    doc = ConvertsForExport(doctype='Sales Invoice', name='TEST', grand_total=value)
    actual = native_record_observation(doc)
    expected = freeze_native_value({'doctype':doc.doctype, 'name':doc.name, 'grand_total':value})
    assert actual == expected


def test_native_child_rows_and_unknown_custom_input_fields_are_observed():
    row = NativeShape(doctype='Sales Invoice Item', name='ROW', net_amount=Decimal('1.234567890123456789'))
    doc = NativeShape(doctype='Sales Invoice', name='TEST', items=[row], custom_future_field='input')
    expected = native_record_observation(doc)
    row.net_amount += Decimal('0.000000000000000001')
    assert native_record_observation(doc) != expected
    row.net_amount -= Decimal('0.000000000000000001')
    assert native_record_observation(doc) == expected
    doc.custom_future_field = 'changed'
    assert native_record_observation(doc) != expected


def test_invoice_output_and_framework_metadata_are_separate_from_business_fields():
    doc = NativeShape(doctype='Sales Invoice', name='TEST', grand_total=115)
    original = native_record_observation(doc)
    doc.modified = 'later'
    doc.custom_uuid = 'output'
    doc.custom_zatca_icv = 15
    doc.custom_zatca_full_response = 'received'
    doc.ksa_einv_qr = '/private/qr.png'
    assert native_record_observation(doc) == original
    doc.custom_xml = '/private/source.xml'
    assert native_record_observation(doc) != original


def test_ordinary_json_keys_named_modified_are_not_treated_as_record_metadata():
    value = {'modified':[15, 1.50], 'sku':[5, 0.50]}
    actual = freeze_native_value(value)
    value['modified'] = [15, 3.00]
    assert freeze_native_value(value) != actual


def test_same_master_reloaded_with_changed_values_is_rejected(boundary, monkeypatch):
    b = boundary
    setup(b, monkeypatch, 'company')
    master = NativeShape(doctype='Item Tax Template', name='VAT', tax_category='Standard')
    base = b.frappe.get_doc.side_effect
    b.frappe.get_doc.side_effect = lambda dt,name:master if dt=='Item Tax Template' else base(dt,name)
    with scope(b, b.sales) as current:
        assert read_issuing_doc(b.frappe, 'Item Tax Template', 'VAT') is master
        master.tax_category = 'Exempted'
        with pytest.raises(IssuingAttemptError):
            read_issuing_doc(b.frappe, 'Item Tax Template', 'VAT')
    b.request.assert_not_called()


def test_master_changed_after_last_builder_read_is_rejected_before_selection(boundary, monkeypatch):
    b = boundary
    setup(b, monkeypatch, 'company')
    address = NativeShape(doctype='Address', name='ADDR', city='Riyadh')
    base = b.frappe.get_doc.side_effect
    b.frappe.get_doc.side_effect = lambda dt,name:address if dt=='Address' else base(dt,name)
    with scope(b, b.sales) as current:
        read_issuing_doc(b.frappe, 'Address', 'ADDR')
        address.city = 'changed'
        with pytest.raises(IssuingAttemptError): current.confirm_current()
    b.request.assert_not_called()


@pytest.mark.parametrize('first,last', [([], [{'name':'new'}]), ([{'name':'A'}], [{'name':'B'}]), ([{'name':'A'},{'name':'B'}], [{'name':'B'},{'name':'A'}])])
def test_changed_discovery_result_cannot_hide_behind_unchanged_selected_record(boundary, monkeypatch, first, last):
    b = boundary
    setup(b, monkeypatch, 'company')
    b.frappe.get_all = Mock(return_value=deepcopy(first))
    with scope(b, b.sales) as current:
        assert read_issuing_all(b.frappe, 'Address', filters={'link_name':'A'}, fields=['name']) == first
        b.frappe.get_all.return_value = last
        with pytest.raises(IssuingAttemptError): current.confirm_current()
    b.request.assert_not_called()


def test_scoped_cached_read_uses_saved_record_without_clearing_cache(boundary, monkeypatch):
    b = boundary
    setup(b, monkeypatch, 'company')
    customer = NativeShape(doctype='Customer', name='C', tax_id='CURRENT')
    old = NativeShape(doctype='Customer', name='C', tax_id='STALE')
    base = b.frappe.get_doc.side_effect
    b.frappe.get_doc.side_effect = lambda dt,name:customer if dt=='Customer' else base(dt,name)
    b.frappe.get_cached_doc = Mock(return_value=old)
    assert read_issuing_cached_doc(b.frappe, 'Customer', 'C') is old
    with scope(b, b.sales):
        assert read_issuing_cached_doc(b.frappe, 'Customer', 'C') is customer
    b.frappe.get_cached_doc.assert_called_once()


def test_wrong_site_is_rejected_before_even_reading_a_record(boundary, monkeypatch):
    b = boundary
    setup(b, monkeypatch, 'company')
    b.frappe.local = SimpleNamespace(site='A')
    with scope(b, b.sales):
        b.frappe.local.site = 'B'
        before = b.frappe.get_doc.call_count
        with pytest.raises(IssuingAttemptError): read_issuing_doc(b.frappe, 'Company', 'A')
        assert b.frappe.get_doc.call_count == before
        b.frappe.local.site = 'A'


def test_debug_native_master_observation_does_not_consume_scheduling_fields(boundary, monkeypatch):
    from zatca_erpgulf.zatca_erpgulf.scheduling import WINDOW_FIELDS
    b = boundary
    setup(b, monkeypatch, 'company')
    scheduling = {name for window in WINDOW_FIELDS for name in window}
    scheduling.update(('custom_send_invoice_to_zatca','custom_send_einvoice_background'))
    class NoSchedulingReads(NativeShape):
        def get(self, key, default=None):
            if key in scheduling: raise AssertionError('Debug consumed scheduling data')
            return super().get(key, default)
    # Capture the normal saved issuer first, then model a consumed native builder
    # read whose declared shape also contains window fields.
    with scope(b, b.sales, 'debug') as current:
        values = {key:value for key,value in vars(b.company).items() if not callable(value)}
        values.update({name:'unused' for name in scheduling})
        native = NoSchedulingReads(**values)
        current.observe_record(native)
        original = b.frappe.get_doc.side_effect
        b.frappe.get_doc.side_effect = lambda dt,name:native if dt=='Company' else original(dt,name)
        current.confirm_current()


def test_phase_alias_schema_change_is_not_hidden_by_identical_blank_values(boundary, monkeypatch):
    b = boundary
    setup(b, monkeypatch, 'company')
    present = {'phase_1_or_2'}
    b.company.meta = SimpleNamespace(has_field=lambda name:name in present)
    with scope(b, b.sales) as current:
        present.add('custom_phase_1_or_2')
        with pytest.raises(IssuingAttemptError) as caught: current.confirm_current()
        assert caught.value.code == 'issuing_settings_schema_changed'
