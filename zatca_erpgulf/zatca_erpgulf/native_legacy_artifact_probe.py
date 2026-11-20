"""Bounded attached-XML contradictions for otherwise unattributed old counters.

Declarations in XML can require review, never prove acceptance/ownership or
authorize a counter merge. Missing, unreadable, changed or unprobed evidence is
unresolved. No directory scan, current signing-key load, source repair or HTTP.
"""

from dataclasses import dataclass

from .artifact_evidence import ArtifactEvidenceError, inspect_invoice_artifact
from .artifact_inventory import _read_local_attachment
from .certificate_evidence import inspect_embedded_certificate_declarations
from .chain_registration import ChainRegistrationError
from .dispatch_record_codec import _identifier, DispatchRecordError
from .dispatch_store import _counter, DispatchStoreError
from .native_identity_inventory import _owned, require_range_engines
from .permission_compat import saved_row_has_permission
from .saved_form_source import saved_form_name, SavedFormSourceError


MAX_COUNTER_PROBES = 32
MAX_FILES_PER_SOURCE = 4
MAX_TOTAL_XML_BYTES = 4 * 1024 * 1024
TABLES = {'Sales Invoice': '`tabSales Invoice`', 'POS Invoice': '`tabPOS Invoice`',
    'Company': '`tabCompany`', 'File': '`tabFile`'}


@dataclass(frozen=True, repr=False)
class LegacyArtifactProbe:
    probed: int
    unresolved: int
    unprobed: int
    xml_bytes: int


class _Unresolved(ValueError):
    pass


@dataclass
class _ReadBudget:
    remaining: int = MAX_TOTAL_XML_BYTES
    read: int = 0


def _saved_read(runtime, owner, doctype, name):
    _owned(owner)
    try:
        saved_form_name(name)
    except SavedFormSourceError:
        raise _Unresolved() from None
    rows = owner.database.sql('SELECT name FROM '+TABLES[doctype]+' WHERE name=%s '
        'LOCK IN SHARE MODE NOWAIT',(name,),as_dict=True)
    if len(rows) != 1:
        raise _Unresolved()
    record = runtime.get_doc(doctype,name,for_update=True)
    if record.doctype != doctype or record.name != name:
        raise _Unresolved()
    if not saved_row_has_permission(runtime.has_permission,doctype,'read',doc=record,user=owner.actor):
        raise _Unresolved()
    _owned(owner)
    return record


def _counter_icv(value):
    if type(value) not in (int,str):
        raise _Unresolved()
    value = str(value)
    try:
        _counter(value)
    except DispatchStoreError:
        raise _Unresolved() from None
    return value


def _probe_one(runtime, owner, counter, keys, units, budget):
    """Return whether each bounded attached declaration was inspectable."""
    doctype = counter.get('last_invoice_doctype')
    if doctype not in ('Sales Invoice','POS Invoice') or counter.get('environment') != 'Production':
        raise _Unresolved()
    source = _saved_read(runtime,owner,doctype,counter.get('last_invoice'))
    company = _saved_read(runtime,owner,'Company',source.get('company'))
    icv = _counter_icv(counter.get('last_issued_icv'))
    if (source.get('docstatus') not in (1,2) or source.get('company') != counter.get('company')
            or source.get('custom_zatca_issuing_unit') != counter.get('issuing_unit')
            or _counter_icv(source.get('custom_zatca_icv')) != icv):
        raise _Unresolved()
    try:
        _identifier(source.get('custom_uuid'))
    except DispatchRecordError:
        raise _Unresolved() from None
    _owned(owner)
    rows = owner.database.sql('SELECT name FROM `tabFile` WHERE attached_to_doctype=%s '
        'AND attached_to_name=%s AND LOWER(file_name) LIKE %s ORDER BY name LIMIT %s '
        'LOCK IN SHARE MODE NOWAIT', (doctype,source.name,'%.xml',MAX_FILES_PER_SOURCE+1),as_dict=True)
    if len(rows) > MAX_FILES_PER_SOURCE:
        raise _Unresolved()
    observed, complete = 0, bool(rows)
    for index,row in enumerate(rows):
        _owned(owner)
        try:
            file = _saved_read(runtime,owner,'File',row['name'])
            xml = _read_local_attachment(file,doctype,source.name,runtime=runtime,max_bytes=budget.remaining)
            # Charge before parsing or any later validation failure. A later
            # exception must never reset this invocation's global read budget.
            budget.read += len(xml)
            budget.remaining -= len(xml)
            invoice = inspect_invoice_artifact(xml)
            certificate, declarations = inspect_embedded_certificate_declarations(xml)
            if (invoice.invoice_id != source.name or invoice.uuid != source.get('custom_uuid')
                    or str(invoice.icv) != icv or invoice.seller_tax_id != company.get('tax_id')):
                complete = False
            else:
                observed += 1
                if certificate.public_key_sha256 in keys or set(declarations) & units:
                    raise ChainRegistrationError('registration_history_counter_related')
        except ChainRegistrationError:
            raise
        except ArtifactEvidenceError as error:
            complete = False
            if error.code == 'xml_size':
                budget.remaining = 0
        except _Unresolved:
            complete = False
        _owned(owner)
        if budget.remaining <= 0:
            complete = complete and index == len(rows)-1
            break
    require_range_engines(owner,('tab'+doctype,'tabCompany','tabFile'))
    return complete and observed>0


def probe_unattributed_counter_artifacts(runtime, owner, counters, family):
    """Internal current-transaction negative probe, not a complete census.

    At most32 counter references, four attached XMLs each and4MiB of successful
    XML reads. A lower-level reader enforces the remaining byte limit. A different
    embedded declaration is not certified independence or historical completion.
    """
    keys = {key for row in family for key in row.public_keys}
    units = {unit for row in family for unit in row.declared_units}
    candidates = tuple(counter for counter in counters if counter.get('environment') not in ('Compliance','Debug'))
    budget, probed, unresolved = _ReadBudget(MAX_TOTAL_XML_BYTES), 0, 0
    for counter in candidates[:MAX_COUNTER_PROBES]:
        _owned(owner)
        if budget.remaining <= 0:
            break
        probed += 1
        try:
            unresolved += not _probe_one(runtime,owner,counter,keys,units,budget)
        except ChainRegistrationError:
            raise
        except _Unresolved:
            unresolved += 1
        _owned(owner)
    return LegacyArtifactProbe(probed,unresolved,len(candidates)-probed,budget.read)
