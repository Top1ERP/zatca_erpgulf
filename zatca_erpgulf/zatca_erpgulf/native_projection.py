"""Project accepted native custody onto bookkeeping fields, never financial data.

Receipt custody and ledger assessment are committed before this separate owned
transaction. No credential lookup, API, PIH/counter update, File save, source save
hook or accounting hook runs here. QR/XML publication uses its own rules.
"""

from dataclasses import dataclass

from .dispatch_store import DispatchStore
from .native_dispatch import NativeDispatchError, SOURCE_TABLES, _require_access, _changed_once
from .native_response import assess_native_receipt
from .permission_compat import saved_row_has_permission
from .worker_transaction import owned_worker_transaction


@dataclass(frozen=True)
class StatusProjection:
    issuance_id: str | None
    status: str | None
    updated: bool = False
    skipped_readonly: bool = False

    @property
    def projected(self):
        return self.status in ('REPORTED', 'CLEARED') and not self.skipped_readonly


def _status_columns(database, doctype, status, text):
    """Check storage without truncating a retained response or altering schema."""
    rows = database.sql('SELECT column_name AS fieldname,data_type AS kind,'
        'character_maximum_length AS max_chars,character_octet_length AS max_bytes '
        'FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=%s '
        'AND column_name IN (%s,%s)',
        ('tab'+doctype, 'custom_zatca_status', 'custom_zatca_full_response'), as_dict=True)
    fields = {row['fieldname']: row for row in rows}
    if len(rows) != 2 or set(fields) != {'custom_zatca_status', 'custom_zatca_full_response'}:
        raise NativeDispatchError('native_projection_schema_required')
    strings = ('char', 'varchar', 'tinytext', 'text', 'mediumtext', 'longtext')
    for fieldname, value in (('custom_zatca_status', status), ('custom_zatca_full_response', text)):
        column = fields[fieldname]
        if (column['kind'] not in strings or type(column['max_chars']) is not int
                or type(column['max_bytes']) is not int or len(value) > column['max_chars']
                or len(value.encode('utf-8')) > column['max_bytes']):
            raise NativeDispatchError('native_projection_capacity')


def project_accepted_status(doctype, invoice_name, *, runtime, skip_if_readonly=False, expected_issuance_id=None):
    """Recover source status from exact current custody, even after key expiry.

    Ordinary projection requires source write permission. The cached-result path
    may explicitly skip a read-only viewer; that does not grant write permission.
    A stale/historical version never overwrites the current source. Only accepted
    statuses are projected; unknown/rejected outcomes do not downgrade acceptance.
    """
    if doctype not in SOURCE_TABLES or type(invoice_name) is not str or not invoice_name:
        raise NativeDispatchError('native_source_identity')
    with owned_worker_transaction(runtime) as owner:
        source = runtime.get_doc(doctype, invoice_name)
        company = runtime.get_doc('Company', source.company)
        _require_access(runtime, source, company, owner.actor, write=False)
        if skip_if_readonly and not saved_row_has_permission(runtime.has_permission, doctype,
                'write', doc=source, user=owner.actor):
            if expected_issuance_id is not None:
                # A read-only cached viewer still cannot acknowledge a different
                # current version after attachment admission. No write ticket is
                # acquired and the existing source/Company READ checks remain.
                marker = source.get('custom_zatca_issuing_unit')
                value = source.get('custom_zatca_icv')
                if (type(marker) is not str or not marker.startswith('egs:')
                        or type(value) not in (int, str) or source.get('docstatus') != 1):
                    raise NativeDispatchError('native_projection_source_identity')
                repository = DispatchStore(owner.database, storage_namespace=owner.storage_namespace,
                    cipher=owner.cipher, owner_check=owner.owner_current)
                saved = repository.find_source_issuance(doctype=doctype, invoice_name=invoice_name,
                    company=source.company, chain_id=marker[4:], invoice_uuid=source.get('custom_uuid'), icv=str(value))
                if saved['record_id'] != expected_issuance_id:
                    raise NativeDispatchError('native_expected_issuance_changed')
            return StatusProjection(None, None, skipped_readonly=True)
        _require_access(runtime, source, company, owner.actor)
        marker = source.get('custom_zatca_issuing_unit')
        if type(marker) is not str or not marker.startswith('egs:'):
            raise NativeDispatchError('native_projection_source_identity')
        repository = DispatchStore(owner.database, storage_namespace=owner.storage_namespace,
            cipher=owner.cipher, owner_check=owner.owner_current)
        chain = repository.lock_chain_reference(marker[4:])
        # Lock order matches generation/reservation: chain, current source, issue.
        source = runtime.get_doc(doctype, invoice_name, for_update=True)
        company = runtime.get_doc('Company', source.company)
        _require_access(runtime, source, company, owner.actor)
        value = source.get('custom_zatca_icv')
        if (source.get('custom_zatca_issuing_unit') != marker or source.get('docstatus') != 1
                or type(value) not in (int, str)):
            raise NativeDispatchError('native_projection_source_identity')
        saved = repository.find_source_issuance(doctype=doctype, invoice_name=invoice_name,
            company=source.company, chain_id=chain['record_id'], invoice_uuid=source.get('custom_uuid'), icv=str(value))
        if expected_issuance_id is not None and saved['record_id']!=expected_issuance_id:
            raise NativeDispatchError('native_expected_issuance_changed')
        saved = repository.lock_issuance(chain, saved['record_id'])
        latest = repository.latest_issuance(chain['record_id'], doctype, invoice_name)
        if latest is None or latest['record_id'] != saved['record_id']:
            raise NativeDispatchError('native_projection_historical_version')
        status = saved['state']
        if status not in ('REPORTED', 'CLEARED'):
            return StatusProjection(saved['record_id'], None)
        if not saved['active_attempt']:
            raise NativeDispatchError('native_retained_acceptance_review')
        header, original = repository.open_issuance(saved['record_id'])
        from .late_acceptance_evidence import accepted_receipt
        receipt, body = accepted_receipt(repository,saved)
        fallback = repository.open_clearance_fallback(saved) if header['endpoint'] != receipt['endpoint'] else None
        assessment = assess_native_receipt(header, original, receipt, body, fallback_receipt=fallback)
        expected = ('REPORTING_MATCHED', 'REPORTING_DUPLICATE_MATCHED') if status == 'REPORTED' else (
            'CLEARANCE_MATCHED', 'CLEARANCE_DUPLICATE_MATCHED')
        if assessment.outcome not in expected:
            raise NativeDispatchError('native_retained_acceptance_review')
        # Assessment requires strict UTF-8 JSON; decoding here preserves all
        # original whitespace/key order and is never translated or normalized.
        text = body.decode('utf-8')
        _status_columns(owner.database, doctype, status, text)
        if source.get('custom_zatca_status') in ('REPORTED', 'CLEARED') and source.get('custom_zatca_status') != status:
            raise NativeDispatchError('native_projection_status_conflict')
        if source.get('custom_zatca_status') == status and source.get('custom_zatca_full_response') == text:
            return StatusProjection(saved['record_id'], status)
        owner.require_owner()
        owner.database.sql('UPDATE '+SOURCE_TABLES[doctype]+
            ' SET custom_zatca_status=%s,custom_zatca_full_response=%s '
            'WHERE name=%s AND company=%s AND custom_uuid=%s '
            'AND CAST(custom_zatca_icv AS CHAR)=%s AND custom_zatca_issuing_unit=%s',
            (status, text, invoice_name, source.company, header['invoice_uuid'], header['icv'], marker))
        _changed_once(owner.database)
        owner.commit()
        return StatusProjection(saved['record_id'], status, updated=True)
