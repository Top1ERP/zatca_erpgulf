"""Read known legacy XML declarations without granting cutover or acceptance.

The caller owns the review transaction and has checked its counter/source tail.
Missing history is reported explicitly; neither ERP dates nor statuses fill it.
Even consistent declarations are not signature/hash/SDK or worker-drain proof.
"""

from dataclasses import dataclass

from .artifact_evidence import ArtifactEvidenceError, inspect_invoice_artifact, MAX_XML_BYTES as MAX_SINGLE_XML_BYTES
from .artifact_inventory import _read_local_attachment
from .certificate_evidence import inspect_embedded_certificate
from .chain_registration import ChainRegistrationError
from .dispatch_record_codec import _identifier
from .dispatch_store import _counter
from .invoice_xml_core import INITIAL_PREVIOUS_HASH
from .native_identity_inventory import _owned, require_range_engines, require_range_isolation
from .native_legacy_tail import SOURCE_TABLES
from .permission_compat import saved_row_has_permission


MAX_SOURCES = 1024
MAX_FILES_PER_SOURCE = 4
MAX_XML_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, repr=False)
class LegacyHistoryInventory:
    sources_seen: int
    source_scan_complete: bool
    inspected_sources: int
    unresolved_sources: int
    unprobed_sources: int
    missing_positions: str | None
    matched_links: int
    broken_links: int
    genesis_match: bool | None
    tail_match: bool | None
    rotated_key_sources: int
    xml_bytes: int
    known_positions: str | None = None

    def __reduce_ex__(self, protocol):
        raise TypeError('registration_history_inventory_not_serializable')


@dataclass
class _Budget:
    remaining: int
    read: int = 0


def _readable(runtime, owner, document):
    _owned(owner)
    permitted = saved_row_has_permission(runtime.has_permission, document.doctype, 'read',
        doc=document, user=owner.actor)
    _owned(owner)
    return permitted


def _source_identity(document):
    return (document.name, document.company, document.get('docstatus'), document.get('custom_uuid'),
        str(document.get('custom_zatca_icv')), document.get('custom_zatca_issuing_unit'))


def _older_xml(runtime, owner, row, seller_tax_id, budget):
    doctype, name = row['doctype'], row['name']
    document = runtime.get_doc(doctype, name, for_update=True)
    if document.doctype != doctype or _source_identity(document) != (
            name, row['company'], row['docstatus'], row['custom_uuid'], row['icv'], row['unit']):
        raise ChainRegistrationError('registration_history_source_changed')
    if not _readable(runtime, owner, document):
        return None
    files = owner.database.sql('SELECT name FROM `tabFile` WHERE attached_to_doctype=%s '
        'AND attached_to_name=%s AND LOWER(file_name) LIKE %s ORDER BY name LIMIT %s '
        'LOCK IN SHARE MODE NOWAIT', (doctype, name, '%.xml', MAX_FILES_PER_SOURCE+1), as_dict=True)
    _owned(owner)
    if not files or len(files) > MAX_FILES_PER_SOURCE:
        return None
    selected = None
    for file_row in files:
        if budget.remaining <= 0:
            return None
        file = runtime.get_doc('File', file_row['name'], for_update=True)
        if (file.doctype, file.name) != ('File', file_row['name']):
            raise ChainRegistrationError('registration_history_file_changed')
        if not _readable(runtime, owner, file):
            return None
        try:
            content = _read_local_attachment(file, doctype, name, runtime=runtime,
                max_bytes=min(budget.remaining, MAX_SINGLE_XML_BYTES))
            budget.read += len(content)
            budget.remaining -= len(content)
            evidence = inspect_invoice_artifact(content)
            key = inspect_embedded_certificate(content).public_key_sha256
        except ArtifactEvidenceError as error:
            if error.code == 'xml_size':
                budget.remaining = 0
            return None
        _owned(owner)
        if (evidence.invoice_id, evidence.uuid, str(evidence.icv), evidence.seller_tax_id) != (
                name, row['custom_uuid'], row['icv'], seller_tax_id):
            return None
        # Original/cleared copies may differ in bytes, but must declare the
        # same chain links and key. Never pick the first contradictory XML.
        candidate = (evidence, key)
        if selected is not None and (selected[0].invoice_digest, selected[0].previous_hash, selected[1]) != (
                evidence.invoice_digest, evidence.previous_hash, key):
            return None
        selected = candidate
    return selected


def summarize_history(rows, observations, *, complete, attempted, tail_icv, tail_digest, public_key, xml_bytes,
        known_positions=None):
    """Pure declaration arithmetic; no overall 'safe to activate' boolean."""
    slots = {int(row['icv']): (row['doctype'], row['name']) for row in rows}
    if len(slots) != len(rows):
        raise ChainRegistrationError('registration_history_duplicate_slot')
    known = {icv: observations[key] for icv, key in slots.items() if observations.get(key) is not None}
    matched = broken = 0
    for icv, (evidence, _key) in known.items():
        previous = known.get(icv-1)
        if previous is not None:
            if evidence.previous_hash == previous[0].invoice_digest:
                matched += 1
            else:
                broken += 1
    genesis = None if 1 not in known else known[1][0].previous_hash == INITIAL_PREVIOUS_HASH
    tail = known.get(int(tail_icv))
    tail_match = None if tail is None else tail[0].invoice_digest == tail_digest
    total = len(slots) if complete and known_positions is None else known_positions
    if total is not None and (type(total) is not int or total < len(slots)
            or (complete and total != len(slots))):
        raise ChainRegistrationError('registration_history_count_changed')
    missing = str(int(tail_icv)-total) if total is not None else None
    if missing is not None and int(missing) < 0:
        raise ChainRegistrationError('registration_history_tail_range')
    return LegacyHistoryInventory(len(rows), complete, len(attempted), len(attempted)-len(known),
        (len(rows) if total is None else total)-len(attempted), missing, matched, broken, genesis, tail_match,
        sum(key != public_key for _evidence, key in known.values()), xml_bytes,
        None if total is None else str(total))


def _count_slots(owner, unit):
    """Current aggregate census after the parent's canonical/unique-tail audit.

    An older ordinary ORM SELECT can hold an RR snapshot. LOCK IN SHARE MODE
    is mandatory even for COUNT; the count never comes from that old snapshot.
    This does not grant permission to read older invoice bodies or their XML.
    """
    total = 0
    for table in SOURCE_TABLES.values():
        _owned(owner)
        rows = owner.database.sql('SELECT COUNT(*) AS slot_count FROM '+table+
            ' WHERE custom_zatca_issuing_unit=%s AND BINARY custom_zatca_issuing_unit=BINARY %s '
            'LOCK IN SHARE MODE NOWAIT', (unit, unit), as_dict=True)
        _owned(owner)
        if (len(rows) != 1 or type(rows[0].get('slot_count')) is not int
                or rows[0]['slot_count'] < 0):
            raise ChainRegistrationError('registration_history_count_shape')
        total += rows[0]['slot_count']
    return total


def inspect_known_legacy_history(runtime, owner, source, unit, anchor, public_key):
    """Inspect both known source tables; report gaps/unreadable/budget limits.

    Caller has already verified exact positive ICV types, no duplicate slots,
    the one saved counter tail and the reviewed private anchor XML. No current
    credential/key lookup or repeated anchor-file read occurs here. The report
    is transient; future activation must recheck and authenticate its own proof.
    """
    require_range_isolation(owner)
    total = _count_slots(owner, unit)
    # Preserve the existing File/storage guard even when only a count fits.
    owner.database.sql('SELECT name FROM `tabFile` LIMIT 0', as_dict=True)
    require_range_engines(owner, ('tabSales Invoice', 'tabPOS Invoice', 'tabFile'))
    identity = (source.doctype, source.name)
    if total > MAX_SOURCES:
        # Keep the already-verified anchor as evidence. Counting all slots is
        # independent of the bounded older-document/XML scan and its budget.
        return summarize_history([dict(doctype=source.doctype, name=source.name, icv=str(anchor.icv))],
            {identity: (anchor, public_key)}, complete=False, attempted={identity},
            tail_icv=str(anchor.icv), tail_digest=anchor.invoice_digest, public_key=public_key,
            xml_bytes=0, known_positions=total)
    rows = []
    for doctype, table in SOURCE_TABLES.items():
        _owned(owner)
        found = owner.database.sql('SELECT name,company,docstatus,custom_uuid,'
            'SUBSTRING(CAST(custom_zatca_icv AS CHAR),1,65) AS icv,custom_zatca_issuing_unit AS unit '
            'FROM '+table+' WHERE custom_zatca_issuing_unit=%s AND BINARY custom_zatca_issuing_unit=BINARY %s '
            'ORDER BY name LIMIT %s LOCK IN SHARE MODE NOWAIT', (unit, unit, MAX_SOURCES+1), as_dict=True)
        rows.extend(dict(row, doctype=doctype) for row in found)
        _owned(owner)
    for row in rows:
        _counter(row['icv']); _identifier(row['custom_uuid'])
        if (row['company'] != source.company or row['docstatus'] not in (1, 2) or row['unit'] != unit
                or int(row['icv']) > anchor.icv):
            raise ChainRegistrationError('registration_history_source_changed')
    if len(rows) != total:
        raise ChainRegistrationError('registration_history_count_changed')
    if not any((row['doctype'], row['name'], row['icv'], row['custom_uuid']) == (
            *identity, str(anchor.icv), anchor.uuid) for row in rows):
        raise ChainRegistrationError('registration_history_anchor_missing')
    observations, attempted = {identity: (anchor, public_key)}, {identity}
    budget = _Budget(MAX_XML_BYTES)
    for row in sorted(rows, key=lambda row: int(row['icv'])):
        key = (row['doctype'], row['name'])
        if key == identity:
            continue
        if budget.remaining <= 0:
            break
        attempted.add(key)
        observations[key] = _older_xml(runtime, owner, row, anchor.seller_tax_id, budget)
    _owned(owner)
    return summarize_history(rows, observations, complete=True, attempted=attempted,
        tail_icv=str(anchor.icv), tail_digest=anchor.invoice_digest, public_key=public_key,
        xml_bytes=budget.read, known_positions=total)
