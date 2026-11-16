"""Protected exact native record observations for one preparation call.

No rounding, JSON conversion, source repair, hashing, SQL or authorization. The
native Document.as_dict projection covers saved custom fields and v16 children;
Frappe installation/lifecycle correctness is a separate acceptance boundary.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal


METADATA = frozenset((
    'owner', 'creation', 'modified', 'modified_by', '_assign', '_comments',
    '_user_tags', '_liked_by', '_seen', '__onload', '__islocal', '__unsaved',
))
INVOICE_OUTPUTS = frozenset((
    'custom_uuid', 'custom_zatca_icv', 'custom_zatca_issuing_unit',
    'custom_zatca_status', 'custom_zatca_full_response',
    'custom_ksa_einvoicing_xml', 'ksa_einv_qr',
))


def freeze_native_value(value):
    """Keep native type/scale/lexical values, including invalid numeric inputs.

    Observing NaN or Infinity must not preempt the existing financial validator
    with a different numeric rule. This routine never serializes to XML/JSON.
    """
    kind = type(value)
    if value is None:
        return ('null',)
    if kind in (bool, str, bytes):
        return (kind.__name__, value)
    if isinstance(value, int):
        # Frappe's docstatus getter replaces int with its DocStatus int wrapper.
        # That normal native read is not a business-data change.
        return ('int', int(value))
    if kind is float:
        return ('float', value.hex())
    if kind is Decimal:
        return ('decimal', value.as_tuple())
    if kind in (datetime, date, time):
        return (kind.__name__, value.isoformat())
    if kind is timedelta:
        return ('timedelta', value.days, value.seconds, value.microseconds)
    if kind in (tuple, list):
        return (kind.__name__, tuple(freeze_native_value(row) for row in value))
    if isinstance(value, dict):
        doctype = value.get('doctype')
        ignored = set(METADATA) if isinstance(doctype, str) else set()
        if doctype in ('Sales Invoice', 'POS Invoice'):
            ignored.update(INVOICE_OUTPUTS)
        if doctype in ('Company', 'ZATCA Multiple Setting'):
            # The existing ICV allocator may bind its counter during preparation.
            ignored.add('custom_zatca_icv_counter')
        if not all(isinstance(key, str) for key in value):
            raise ValueError('issuing_observation_key')
        return ('map', tuple(sorted((key, freeze_native_value(item))
                                    for key, item in value.items() if key not in ignored)))
    converter = getattr(value, 'as_dict', None)
    if callable(converter):
        return native_record_observation(value)
    raise ValueError('issuing_observation_type')


def native_record_observation(document, *, omit_fields=()):
    """Return a protected native projection, or None for a partial test adapter.

    Actual Frappe15/16 documents expose as_dict. Minimal injected adapters keep
    the separately declared scalar/row profile; they are not native site proof.
    """
    converter = getattr(document, 'as_dict', None)
    if not callable(converter):
        return None
    body = converter()
    if not isinstance(body, dict) or body.get('doctype') != document.doctype or body.get('name') != document.name:
        raise ValueError('issuing_observation_identity')
    # Use the native projection only to select fields. Its values may already
    # have passed through Frappe's float/date conversion; read original values
    # through get so high-precision Decimal data is not hidden by observation.
    getter = getattr(document, 'get', None)
    if not callable(getter):
        raise ValueError('issuing_observation_reader')
    return freeze_native_value({name: getter(name) for name in body if name not in omit_fields})
