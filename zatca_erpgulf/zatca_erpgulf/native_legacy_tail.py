"""Saved-source contradictions for an inactive legacy continuity review.

A matching counter/anchor alone cannot rule out a manually rewound counter or a
later generated POS/Sales document. Check both fixed source tables under owned
range locks. This is not full chain reconstruction, remote acceptance, a drained
worker proof or permission to activate. No latest/max value is adopted as a seed.
"""

from .chain_registration import ChainRegistrationError
from .dispatch_store import _counter
from .native_identity_inventory import require_range_isolation, require_range_engines, _owned


SOURCE_TABLES = {'Sales Invoice': '`tabSales Invoice`', 'POS Invoice': '`tabPOS Invoice`'}
CANONICAL_ICV = r'\A[1-9][0-9]{0,63}\z'
CANONICAL_UUID = r'\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\z'
EXACT_COLUMN_TYPES = frozenset(('tinyint', 'smallint', 'mediumint', 'int', 'bigint',
    'char', 'varchar', 'tinytext', 'text', 'mediumtext', 'longtext'))


def _require_exact_counter_columns(owner):
    """A rounded floating column cannot establish a historical identity order."""
    _owned(owner)
    rows = owner.database.sql('SELECT TABLE_NAME AS table_name,COLUMN_NAME AS column_name,'
        'DATA_TYPE AS data_type,NUMERIC_SCALE AS numeric_scale FROM information_schema.columns '
        'WHERE table_schema=DATABASE() AND ((table_name IN (%s,%s) AND column_name=%s) '
        'OR (table_name=%s AND column_name=%s))',
        ('tabSales Invoice', 'tabPOS Invoice', 'custom_zatca_icv', 'tabZATCA ICV Counter', 'last_issued_icv'),
        as_dict=True)
    expected = {('tabSales Invoice', 'custom_zatca_icv'), ('tabPOS Invoice', 'custom_zatca_icv'),
        ('tabZATCA ICV Counter', 'last_issued_icv')}
    if (len(rows) != 3 or {(row.get('table_name'), row.get('column_name')) for row in rows} != expected
            or any(row.get('data_type') not in EXACT_COLUMN_TYPES and not (
                row.get('data_type') == 'decimal' and row.get('numeric_scale') == 0) for row in rows)):
        raise ChainRegistrationError('registration_counter_column_review')


def _require_unique_saved_unit_slots(owner, unit):
    """Audit known saved slots, not gap-free history or archived XML ancestry.

    Every probe is a current locking read, including aggregates and both joined
    tables. A plain consistent read could reuse an older ORM read view and hide
    a duplicate committed before the preceding range locks were acquired.
    Return only a contradiction bit; no unrelated invoice details are exposed.
    """
    for table in SOURCE_TABLES.values():
        _owned(owner)
        bad = owner.database.sql('SELECT 1 AS conflict FROM ' + table +
            ' WHERE custom_zatca_issuing_unit=%s AND (custom_uuid IS NULL OR BINARY custom_uuid NOT REGEXP %s) '
            'LIMIT 1 LOCK IN SHARE MODE NOWAIT', (unit, CANONICAL_UUID), as_dict=True)
        if bad:
            raise ChainRegistrationError('registration_saved_uuid_review')
    for field, code in (('custom_zatca_icv', 'registration_saved_icv_duplicate'),
            ('custom_uuid', 'registration_saved_uuid_duplicate')):
        for table in SOURCE_TABLES.values():
            _owned(owner)
            bad = owner.database.sql('SELECT 1 AS conflict FROM ' + table +
                ' WHERE custom_zatca_issuing_unit=%s GROUP BY BINARY CAST(`' + field + '` AS CHAR) '
                'HAVING COUNT(*)>1 LIMIT 1 LOCK IN SHARE MODE NOWAIT', (unit,), as_dict=True)
            if bad:
                raise ChainRegistrationError(code)
        _owned(owner)
        bad = owner.database.sql('SELECT 1 AS conflict FROM `tabSales Invoice` AS s '
            'INNER JOIN `tabPOS Invoice` AS p ON BINARY CAST(s.`' + field + '` AS CHAR)='
            'BINARY CAST(p.`' + field + '` AS CHAR) WHERE s.custom_zatca_issuing_unit=%s '
            'AND p.custom_zatca_issuing_unit=%s LIMIT 1 LOCK IN SHARE MODE NOWAIT', (unit, unit), as_dict=True)
        if bad:
            raise ChainRegistrationError(code)
    _owned(owner)


def require_unambiguous_saved_tail(owner, source, unit, icv):
    """Retain the exact supplied counter tail only if no local contradiction exists.

    The caller already holds ordinary anchor READ and counter/anchor locks. Only
    the selected anchor may match: another row at/above its ICV, a noncanonical
    ICV, a draft, or another Company is a review condition. A missing POS table
    cannot be silently skipped. LIMIT2 bounds returned rows, not examined rows;
    large sites must plan their index/maintenance window before actual cutover.
    """
    _counter(icv)
    if (source.doctype not in SOURCE_TABLES or type(unit) is not str or not unit or unit.startswith('egs:')):
        raise ChainRegistrationError('registration_legacy_unit_required')
    require_range_isolation(owner)
    found = False
    for doctype, table in SOURCE_TABLES.items():
        _owned(owner)
        # DECIMAL(65,0) is exact for the supported 64-digit identity. Invalid
        # strings are selected as contradictions, never repaired/coerced into a
        # new anchor. No float comparison, MAX(), status-only acceptance or
        # Company-only filter can conceal a competing source in the same unit.
        rows = owner.database.sql('SELECT name,company,docstatus,custom_uuid,'
            'SUBSTRING(CAST(custom_zatca_icv AS CHAR),1,65) AS icv,custom_zatca_issuing_unit FROM ' + table +
            ' WHERE custom_zatca_issuing_unit=%s AND ('
            'custom_zatca_icv IS NULL OR CAST(custom_zatca_icv AS CHAR) NOT REGEXP %s '
            'OR CAST(custom_zatca_icv AS DECIMAL(65,0))>=CAST(%s AS DECIMAL(65,0)) '
            'OR docstatus IS NULL OR docstatus NOT IN (1,2) OR company IS NULL OR company<>%s) '
            'ORDER BY name LIMIT 2 LOCK IN SHARE MODE NOWAIT',
            (unit, CANONICAL_ICV, icv, source.company), as_dict=True)
        for row in rows:
            if (found or doctype != source.doctype or row.get('name') != source.name
                    or row.get('company') != source.company or row.get('docstatus') != source.get('docstatus')
                    or row.get('custom_uuid') != source.get('custom_uuid') or row.get('icv') != icv
                    or row.get('custom_zatca_issuing_unit') != unit):
                raise ChainRegistrationError('registration_saved_tail_conflict')
            found = True
    if not found:
        raise ChainRegistrationError('registration_saved_tail_missing')
    require_range_engines(owner, (*tuple(table.strip('`') for table in SOURCE_TABLES.values()),
        'tabZATCA ICV Counter'))
    _require_exact_counter_columns(owner)
    _require_unique_saved_unit_slots(owner,unit)
    _owned(owner)
