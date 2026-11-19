"""Versioned native invoice observation for retained publication/exact reuse.

Keep all invoice-owned fields except explicitly identified collection state.
This never recalculates money, changes the full generation observation, or grants
acceptance. Legacy originals without captured evidence keep their full comparison.
Master/template rendering provenance remains a separate publication boundary.
"""

from datetime import date, datetime, time, timedelta

from .native_preparation import source_observation_sha256


PROFILE = 'native-invoice-publication/v1'
RENDER_PROFILE = 'native-invoice-render/v1'
COLLECTION_FIELDS = frozenset(('outstanding_amount', 'status'))
POS_BOOKKEEPING_FIELDS = frozenset(('consolidated_invoice',))
SCHEDULE_COLLECTION_FIELDS = frozenset((
    'paid_amount', 'base_paid_amount', 'discounted_amount', 'outstanding', 'base_outstanding',
))


def _map(value):
    if (type(value) is tuple and len(value) == 2 and value[0] == 'map'
            and type(value[1]) is tuple):
        return dict(value[1])
    return None


def _schedule(value, identity):
    """Only the native Sales Invoice payment_schedule row collection metrics.

    Do not ignore similarly named values in items/payments/advances/custom rows,
    scheduled amount, discount terms, due dates, row identity or row order.
    Unrecognized data retains its exact observation and cannot gain an exception.
    """
    if not (type(value) is tuple and len(value) == 2 and value[0] in ('list', 'tuple')
            and type(value[1]) is tuple):
        return value
    rows = []
    for row in value[1]:
        fields = _map(row)
        if (fields is not None and fields.get('doctype') == ('str', 'Payment Schedule')
                and fields.get('parenttype') == ('str', identity[0])
                and fields.get('parent') == ('str', identity[1])
                and fields.get('parentfield') == ('str', 'payment_schedule')):
            row = ('map', tuple((key, item) for key, item in row[1]
                if key not in SCHEDULE_COLLECTION_FIELDS))
        rows.append(row)
    return value[0], tuple(rows)


def publication_source_sha256(identity, observation):
    """Project an already captured typed native record, never a fresh document.

    Partial injected test adapters return None; they cannot assert native fiscal
    provenance. Actual Frappe15/16 as_dict observations retain unknown custom
    fields and native children, with no numeric/date/string coercion here.
    """
    fields = _map(observation)
    if fields is None:
        return None
    if (type(identity) is not tuple or len(identity) != 2
            or identity[0] not in ('Sales Invoice', 'POS Invoice')
            or fields.get('doctype') != ('str', identity[0])
            or fields.get('name') != ('str', identity[1])):
        raise ValueError('publication_source_identity')
    ignored = COLLECTION_FIELDS | (POS_BOOKKEEPING_FIELDS if identity[0] == 'POS Invoice' else frozenset())
    selected = tuple((key, _schedule(value, identity)
        if key == 'payment_schedule' and identity[0] == 'Sales Invoice' else value)
        for key, value in observation[1] if key not in ignored)
    return source_observation_sha256((PROFILE, *identity), ('map', selected))


def render_source_sha256(identity, observation):
    """Compare native and JSON print dates without weakening fiscal capture.

    Frappe's print endpoint can load a saved native document or supplied JSON.
    Match its date/time/timedelta wire text, without translating dates, creating
    a clock, changing XML or converting any numeric value (including Decimal).
    This request-local projection is not the persisted fiscal profile.
    """
    from frappe.utils import format_timedelta
    temporal = {'date': date, 'datetime': datetime, 'time': time}
    def project(value):
        if type(value) is not tuple:
            return value
        if len(value) == 2 and type(value[0]) is str and type(value[1]) is str and value[0] in temporal:
            return 'str', str(temporal[value[0]].fromisoformat(value[1]))
        if len(value) == 4 and value[0] == 'timedelta' and all(type(item) is int for item in value[1:]):
            native = timedelta(days=value[1], seconds=value[2], microseconds=value[3])
            return 'str', format_timedelta(native)
        return tuple(project(item) for item in value)
    return source_observation_sha256((RENDER_PROFILE, *identity), project(observation))
