"""Transaction-bound local owner inventory, never an activation authorization.

Enumerate both saved owner tables under shared range locks, then apply ordinary
row READ permissions. Public-key fingerprints detect copied material; declared
environment/VAT/full-serial identities survive key rotation. Linked settings
are recorded separately from material claims. No credentials leave this module.

This inventory cannot prove remote history, absence of old workers, or a complete
legacy invoice/counter inventory. In particular, an empty match is not genesis.
"""

from dataclasses import dataclass
import hashlib
import json

from .credential_material import NATIVE_OWNER_TABLES, NATIVE_OWNER_MARKER, use_linked_company
from .native_owner_registry import _material_evidence
from .permission_compat import saved_row_has_permission
from .saved_form_source import saved_form_name
from .invoice_xml_core import INITIAL_PREVIOUS_HASH


MAX_OWNERS_PER_TABLE = 1024
MAX_MATERIAL_BYTES = 1024 * 1024
ENVIRONMENTS = ('Sandbox', 'Simulation', 'Production')
MATERIAL_FIELDS = ('custom_private_key', 'custom_public_key', 'custom_csr_data',
    'custom_certificate', 'custom_certficate', 'custom_basic_auth_from_csid',
    'custom_basic_auth_from_production', 'custom_final_auth_csid', 'custom_csr_config')
OBSERVED_FIELDS = (*MATERIAL_FIELDS, 'custom_select', 'custom_linked_doctype',
    'custom__use_company_certificate__keys', NATIVE_OWNER_MARKER,
    'custom_zatca_icv_counter', 'custom_pih')


class IdentityInventoryError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class OwnerIdentity:
    doctype: str
    name: str
    environment: str | None
    linked_company: str | None
    delegates_to_company: bool
    public_keys: tuple
    declared_units: tuple
    unparsed_fields: tuple
    has_material_or_history: bool


@dataclass(frozen=True, repr=False)
class IdentityInventory:
    owners: tuple
    sha256: str

    def __reduce_ex__(self, protocol):
        raise TypeError('native_identity_inventory_not_serializable')

    def declaring(self, identity):
        return tuple(row for row in self.owners if identity in row.declared_units)


def _owned(owner):
    if owner.owner_current() is not True:
        raise IdentityInventoryError('native_identity_inventory_owner_changed')


def _material(record, environments):
    """Keep malformed aliases visible instead of inferring that they are empty."""
    total, keys, units, unparsed = 0, set(), set(), []
    for name in MATERIAL_FIELDS:
        value = record.get(name)
        if value in (None, ''):
            continue
        if type(value) is not str:
            raise IdentityInventoryError('native_identity_inventory_material_shape')
        total += len(value.encode('utf-8'))
        if total > MAX_MATERIAL_BYTES:
            raise IdentityInventoryError('native_identity_inventory_material_limit')
        parsed = False
        for environment in environments:
            fingerprints, identities = _material_evidence({name: value}, environment)
            keys.update(fingerprints)
            units.update(identities)
            parsed = parsed or bool(fingerprints or identities)
        if not parsed:
            unparsed.append(name)
    return tuple(sorted(keys)), tuple(sorted(units)), tuple(unparsed)


def _scan(runtime, owner):
    _owned(owner)
    isolation = owner.database.sql('SELECT @@tx_isolation AS isolation_level', as_dict=True)
    if (len(isolation) != 1 or isolation[0].get('isolation_level') not in
            ('REPEATABLE-READ', 'SERIALIZABLE')):
        raise IdentityInventoryError('native_identity_inventory_isolation')
    saved = {}
    for doctype, table in NATIVE_OWNER_TABLES.items():
        _owned(owner)
        # Exhausting the PRIMARY range, including its final gap, is deliberate:
        # concurrent insert/rename/copy cannot appear between scan and commit.
        # An overflow is review, never a truncated claim of completeness.
        rows = owner.database.sql('SELECT * FROM ' + table +
            ' FORCE INDEX (PRIMARY) ORDER BY name LIMIT %s LOCK IN SHARE MODE NOWAIT',
            (MAX_OWNERS_PER_TABLE + 1,), as_dict=True)
        if len(rows) > MAX_OWNERS_PER_TABLE:
            raise IdentityInventoryError('native_identity_inventory_owner_limit')
        for row in rows:
            _owned(owner)
            name = saved_form_name(row['name'])
            record = runtime.get_doc(doctype, name)
            if record.doctype != doctype or record.name != name or (doctype, name) in saved:
                raise IdentityInventoryError('native_identity_inventory_source_identity')
            # Locking SELECT reads the latest committed version; an earlier ORM
            # consistent-read snapshot must not conceal a newly copied key/link.
            if any(record.get(field) != row.get(field) for field in OBSERVED_FIELDS):
                raise IdentityInventoryError('native_identity_inventory_source_changed')
            if not saved_row_has_permission(runtime.has_permission, doctype, 'read', doc=record, user=owner.actor):
                raise IdentityInventoryError('native_identity_inventory_permission')
            saved[doctype, name] = record
    # Check after opening both ranges: transaction metadata locks now prevent
    # an engine-changing DDL race between this check and the caller's commit.
    _owned(owner)
    tables = tuple(table.strip('`') for table in NATIVE_OWNER_TABLES.values())
    engines = owner.database.sql('SELECT TABLE_NAME AS table_name, ENGINE AS engine FROM information_schema.tables '
        'WHERE table_schema=DATABASE() AND table_name IN (%s,%s)', tables, as_dict=True)
    if (len(engines) != len(tables) or {row.get('table_name') for row in engines} != set(tables)
            or any(row.get('engine') != 'InnoDB' for row in engines)):
        raise IdentityInventoryError('native_identity_inventory_engine')
    return saved


def collect_identity_inventory(runtime, owner):
    """Internal service: use only inside an already-owned clean transaction.

    Unknown routing examines claims in all three namespaces conservatively; it
    never silently assumes Production. The digest contains only public identity
    observations and references, not raw configuration/certificate/key/auth data.
    Returned observations are valid only while this transaction owns its locks.
    """
    try:
        saved = _scan(runtime, owner)
        observations = []
        for (doctype, name), record in saved.items():
            _owned(owner)
            linked, delegates, company = None, False, record
            if doctype == 'ZATCA Multiple Setting':
                linked = record.get('custom_linked_doctype')
                if linked not in (None, ''):
                    linked = saved_form_name(linked)
                else:
                    linked = None
                delegates = use_linked_company(record.get('custom__use_company_certificate__keys'))
                company = saved.get(('Company', linked))
            environment = company.get('custom_select') if company is not None else None
            environment = environment.strip() if type(environment) is str else None
            environment = environment if environment in ENVIRONMENTS else None
            keys, units, unparsed = _material(record, (environment,) if environment else ENVIRONMENTS)
            has_material_or_history = (any(record.get(field) not in (None, '') for field in MATERIAL_FIELDS
                if field != 'custom_csr_config') or record.get(NATIVE_OWNER_MARKER) not in (None, '')
                or record.get('custom_zatca_icv_counter') not in (None, '')
                or record.get('custom_pih') not in (None, '', INITIAL_PREVIOUS_HASH))
            observations.append(OwnerIdentity(doctype, name, environment, linked, delegates, keys, units,
                unparsed, has_material_or_history))
        _owned(owner)
        encoded = json.dumps([[row.doctype, row.name, row.environment, row.linked_company,
            row.delegates_to_company, row.public_keys, row.declared_units, row.unparsed_fields,
            row.has_material_or_history]
            for row in observations], ensure_ascii=False, separators=(',', ':')).encode()
        return IdentityInventory(tuple(observations), hashlib.sha256(b'zatca-owner-inventory/v1\0' + encoded).hexdigest())
    except IdentityInventoryError as error:
        code = error.code
    except Exception:
        code = 'native_identity_inventory_review'
    # Raise outside every handler: driver/ACL/parser diagnostics can contain
    # credentials, paths or SQL parameters and must not become public context.
    raise IdentityInventoryError(code)


def require_distinct_new_declaration(runtime, owner, target, identity):
    """Reject another material/history-backed claim before a new initial key.

    This is a negative collision guard only. It is not evidence of no previous
    invoices, and never enables an inactive chain, retires counters or sends HTTP.
    An unused configuration template is reported but has no key/history yet;
    native intent's unique identity reservation arbitrates its eventual first use.
    """
    inventory = collect_identity_inventory(runtime, owner)
    matches = inventory.declaring(identity)
    if (not any((row.doctype, row.name) == (target.doctype, target.name) for row in matches)
            or any((row.doctype, row.name) != (target.doctype, target.name)
                and row.has_material_or_history for row in matches)):
        raise IdentityInventoryError('native_identity_inventory_declaration_conflict')
    return inventory
