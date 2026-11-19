"""Known owner/delegate/counter contradictions to an inactive legacy review.

Discover public-key/declared-unit aliases transitively, including explicit
Company-key delegates. Inspect the full bounded saved counter catalog under
current shared range locks and ordinary READ permissions. No maximum, merge,
retirement, genesis or activation follows from this negative inventory.
"""

from collections import defaultdict, deque
from dataclasses import dataclass

from .chain_registration import ChainRegistrationError
from .dispatch_store import _fingerprint
from .native_identity_inventory import collect_identity_inventory, require_range_engines, _owned
from .permission_compat import saved_row_has_permission
from .saved_form_source import saved_form_name


MAX_COUNTERS = 4096
COUNTER_FIELDS = ('company', 'issuing_unit', 'environment', 'counter_key', 'active',
    'last_issued_icv', 'last_invoice_doctype', 'last_invoice')


@dataclass(frozen=True, repr=False)
class LegacyConsumerInventory:
    owner_inventory_sha256: str
    consumers: tuple
    production_counters: tuple
    other_purpose_counters: tuple
    unattributed_counters: int

    def __reduce_ex__(self, protocol):
        raise TypeError('registration_consumer_inventory_not_serializable')


def _family(inventory, selected, public_key_sha256):
    """Compute closure without treating matching VAT alone as a shared EGS."""
    _fingerprint(public_key_sha256)
    records = {(row.doctype, row.name): row for row in inventory.owners}
    root = (selected.doctype, selected.name)
    if root not in records or public_key_sha256 not in records[root].public_keys:
        raise ChainRegistrationError('registration_consumer_owner_review')
    identities, links = defaultdict(set), defaultdict(set)
    for reference, row in records.items():
        for kind, values in (('key', row.public_keys), ('unit', row.declared_units)):
            for value in values:
                identities[kind, value].add(reference)
        if row.doctype == 'ZATCA Multiple Setting' and row.delegates_to_company:
            parent = ('Company', row.linked_company)
            links[reference].add(parent)
            links[parent].add(reference)
    pending, scheduled, visited, expanded = deque((root,)), {root}, set(), set()
    def schedule(references):
        fresh = references - scheduled
        scheduled.update(fresh)
        pending.extend(fresh)
    while pending:
        reference = pending.popleft()
        if reference not in records:
            raise ChainRegistrationError('registration_consumer_link_review')
        visited.add(reference)
        row = records[reference]
        if row.doctype == 'ZATCA Multiple Setting' and ('Company', row.linked_company) not in records:
            raise ChainRegistrationError('registration_consumer_link_review')
        for kind, values in (('key', row.public_keys), ('unit', row.declared_units)):
            for value in values:
                token = kind,value
                # Expand a shared key/serial bucket once, even for hundreds of
                # copies/delegates. Do not build a quadratic pending queue.
                if token not in expanded:
                    expanded.add(token)
                    schedule(identities[token])
        schedule(links[reference])
    return tuple(records[reference] for reference in sorted(visited))


def _counter_catalog(runtime, owner):
    _owned(owner)
    rows = owner.database.sql('SELECT * FROM `tabZATCA ICV Counter` FORCE INDEX (PRIMARY) '
        'ORDER BY name LIMIT %s LOCK IN SHARE MODE NOWAIT', (MAX_COUNTERS + 1,), as_dict=True)
    if len(rows) > MAX_COUNTERS:
        raise ChainRegistrationError('registration_consumer_counter_limit')
    saved = {}
    for row in rows:
        _owned(owner)
        name = saved_form_name(row['name'])
        record = runtime.get_doc('ZATCA ICV Counter', name)
        if record.doctype != 'ZATCA ICV Counter' or record.name != name or name in saved:
            raise ChainRegistrationError('registration_consumer_counter_identity')
        if any(record.get(field) != row.get(field) for field in COUNTER_FIELDS):
            raise ChainRegistrationError('registration_consumer_counter_changed')
        if not saved_row_has_permission(runtime.has_permission, record.doctype, 'read', doc=record, user=owner.actor):
            raise ChainRegistrationError('registration_consumer_counter_permission')
        saved[name] = record
    require_range_engines(owner, ('tabZATCA ICV Counter',))
    _owned(owner)
    return saved


def require_single_legacy_counter(runtime, owner, selected, public_key_sha256, unit, counter_name):
    """Require the already-verified anchor's one known production counter.

    The caller has verified the exact original, saved counter/anchor and issuer
    material. This internal helper adds negative consumer evidence only. Unknown
    historical token aliases remain unattributed, not evidence of no history.
    """
    saved_form_name(counter_name)
    identity = collect_identity_inventory(runtime, owner)
    family = _family(identity, selected, public_key_sha256)
    units = {row.legacy_unit for row in family} | {unit}
    references = {row.counter_reference for row in family if row.counter_reference is not None} | {counter_name}
    counters = _counter_catalog(runtime, owner)
    if not references <= counters.keys():
        raise ChainRegistrationError('registration_consumer_counter_missing')
    matched = {name: record for name, record in counters.items()
        if name in references or record.get('issuing_unit') in units}
    if any(counters[name].get('environment') != 'Production' for name in references):
        raise ChainRegistrationError('registration_consumer_counter_purpose')
    production = tuple(sorted(name for name, record in matched.items() if record.get('environment') == 'Production'))
    if production != (counter_name,):
        raise ChainRegistrationError('registration_consumer_counter_ambiguous')
    if any(record.get('environment') not in ('Production', 'Compliance', 'Debug') for record in matched.values()):
        raise ChainRegistrationError('registration_consumer_counter_purpose')
    _owned(owner)
    return LegacyConsumerInventory(identity.sha256, tuple((row.doctype, row.name) for row in family),
        production, tuple(sorted(set(matched) - set(production))), len(counters) - len(matched))
