"""Execution-local issuer material and consumed-source observations.

The ContextVar owns only this synchronous call's lifetime, not a site cache,
permission grant, durable epoch, receipt or transaction. Child contexts retained
past exit are invalidated. No object here may be queued, persisted or logged.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType

from .api_routing import ENVIRONMENT_FIELDS, resolve_api_route
from .credential_material import CredentialOwner, authorization_for_owner
from .financial_source_observation import HEADER_FIELDS, TABLE_FIELDS, _scalar
from .issuing_settings_observation import COMPANY_FIELDS as ISSUING_COMPANY_FIELDS


REVIEW = "The invoice source or ZATCA issuer settings changed during preparation, or the credential context could not be confirmed. No request was sent. Reload the source and review the selected issuer, environment and credentials."
ACTIVE = ContextVar('zatca_issuing_attempt', default=None)
OWNER_FIELDS = (
    'custom_private_key', 'custom_certificate', 'custom_certficate',
    'custom_basic_auth_from_csid', 'custom_basic_auth_from_production',
    'custom_final_auth_csid', 'custom_pih', 'tax_id',
    'custom_linked_doctype', 'custom__use_company_certificate__keys',
)
COMPANY_FIELDS = tuple(dict.fromkeys((
    *ISSUING_COMPANY_FIELDS, *OWNER_FIELDS,
    'phase_1_or_2', 'custom_zatca_clearance_enabled',
    'custom_clearance_enabled', 'clearance_enabled',
)))


class IssuingAttemptError(RuntimeError):
    """Typed local review outside legacy failure writers, with Frappe HTTP417."""
    http_status_code = 417

    def __init__(self, code):
        self.code = code
        self.template = REVIEW
        self.diagnostic_logged = False
        super().__init__(REVIEW)

    def __str__(self):
        return REVIEW


def _identity(doc):
    if doc is None:
        return None
    if isinstance(doc, str):
        import json
        try:
            doc = json.loads(doc)
        except (TypeError, ValueError):
            return None
    getter = getattr(doc, 'get', None)
    if callable(getter):
        return getter('doctype'), getter('name')
    return getattr(doc, 'doctype', None), getattr(doc, 'name', None)


def _site(runtime):
    site = getattr(getattr(runtime, 'local', None), 'site', None)
    return ('site', site) if isinstance(site, str) and site else ('runtime', id(runtime))


def _value(value):
    """Freeze exact native scalar/table values, without float/JSON coercion."""
    if type(value) in (list, tuple):
        return ('rows', tuple(_value(row) for row in value))
    if isinstance(value, dict):
        return ('map', tuple(sorted((key, _value(val)) for key, val in value.items())))
    converter = getattr(value, 'as_dict', None)
    if callable(converter):
        return _value(converter())
    if type(value) is str:
        return ('str', value)
    return tuple(_scalar(value))


def _source_observation(doc):
    values = [(name, _value(doc.get(name))) for name in HEADER_FIELDS]
    for table, fields in TABLE_FIELDS.items():
        rows = doc.get(table)
        if rows is None:
            values.append((table, ('null',)))
        else:
            values.append((table, tuple(tuple(
                (name, _value(row.get(name))) for name in fields
            ) for row in rows)))
    # Native v16 item/tax child rows are authoritative, including an empty table.
    details = doc.get('item_wise_tax_details')
    values.append(('item_wise_tax_details', ('null',) if details is None else tuple(
        tuple((name, _value(row.get(name))) for name in
              ('name', 'item_row', 'tax_row', 'rate', 'amount', 'idx'))
        for row in details
    )))
    for name in ('custom_zatca_invoice_type', 'zatca_invoice_type'):
        values.append((name, _value(doc.get(name))))
    return tuple(values)


@dataclass(frozen=True, repr=False)
class _Record:
    doctype: str
    name: str
    values: object = field(repr=False)
    fields_present: frozenset = field(repr=False)

    def get(self, name, default=None):
        return self.values.get(name, default)

    def __contains__(self, name):
        return name in self.fields_present


@dataclass(repr=False)
class IssuingAttempt:
    runtime: object = field(repr=False)
    translate: object = field(repr=False)
    site: object
    company_abbr: str
    purpose: str
    source_identity: tuple
    company: _Record = field(repr=False)
    owner: CredentialOwner = field(repr=False)
    records: dict = field(repr=False)
    source_observation: object = field(repr=False)
    source_revision: object = field(repr=False)
    signing_snapshot: object = field(default=None, repr=False)
    closed: bool = False

    def __reduce_ex__(self, protocol):
        raise TypeError('issuing_attempt_not_serializable')

    def review(self, code):
        error = IssuingAttemptError(code)
        self.runtime.log_error(title='ZATCA issuing context review', message=f'{code}: {REVIEW}')
        error.diagnostic_logged = True
        self.runtime.throw(self.translate(REVIEW), exc=error)
        raise error

    def require(self, company_abbr, source_doc, runtime, *, purpose=None):
        source = _identity(source_doc)
        if source is None and self.source_identity == ('Company', self.company.name):
            source = self.source_identity
        if self.closed or _site(runtime) != self.site:
            self.review('issuing_context_lifetime')
        if company_abbr != self.company_abbr or source != self.source_identity:
            self.review('issuing_context_source')
        if purpose is not None and purpose != self.purpose:
            self.review('issuing_context_purpose')

    def confirm_current(self):
        """Observe drift before request; not locks or proof against a later race.

        Ignore output/status/modified changes on the invoice itself. Compare its
        business fields and row values, not an output field the caller just set.
        The original modified value remains provenance, not a trusted epoch.
        """
        if self.closed or _site(self.runtime) != self.site:
            self.review('issuing_context_lifetime')
        for key, record in self.records.items():
            current = self.runtime.get_doc(*key)
            if any(_value(current.get(name)) != _value(value) for name, value in record.values.items()):
                self.review('issuing_settings_changed')
        if self.source_identity[0] in ('Sales Invoice', 'POS Invoice'):
            current = self.runtime.get_doc(*self.source_identity)
            if _source_observation(current) != self.source_observation:
                self.review('issuing_source_changed')

    def signing_material(self):
        """Bind native signing and purpose authentication before the first sign.

        Debug remains local and can inspect certificate/key material without API
        credentials. Ordinary/Compliance native signing uses the existing strict
        material constructor; this does not activate versioned storage or an epoch.
        """
        if self.closed or _site(self.runtime) != self.site:
            self.review('issuing_context_lifetime')
        if self.purpose == 'debug':
            return None
        if self.signing_snapshot is None:
            from .credential_settings import _certificate_for_owner
            from .credential_snapshot import CredentialSnapshot, CredentialSnapshotError
            endpoint = ('compliance/invoices' if self.purpose == 'compliance'
                        else 'invoices/reporting/single')
            failed = None
            try:
                route = resolve_api_route(self.company.values, endpoint)
                captured = CredentialSnapshot(self.owner, route, _certificate_for_owner(self.owner),
                                              datetime.now(timezone.utc))
            except CredentialSnapshotError as error:
                failed = error.code
            if failed is not None:
                self.review(failed)
            self.signing_snapshot = captured
        return self.signing_snapshot

    def selection(self, endpoint, *, source_doc, runtime, require_issuing_unit=False):
        """Route and authorization from the same captured Company/owner."""
        self.require(self.company_abbr, source_doc, runtime)
        route = resolve_api_route(self.company.values, endpoint)
        self.require(self.company_abbr, source_doc, runtime, purpose=route.required_credential)
        if require_issuing_unit:
            source = self.runtime.get_doc(*self.source_identity)
            if not source.get('custom_zatca_pos_name'):
                self.review('issuing_unit_missing')
        self.confirm_current()
        authorization = authorization_for_owner(self.owner, route.required_credential)
        if self.signing_snapshot is not None:
            from .credential_snapshot import CredentialSnapshotError, validate_snapshot_time
            now = datetime.now(timezone.utc)
            validate_snapshot_time(now)
            certificate = self.signing_snapshot.certificate
            before = getattr(certificate, 'not_valid_before_utc', None)
            after = getattr(certificate, 'not_valid_after_utc', None)
            before = before if before is not None else certificate.not_valid_before.replace(tzinfo=timezone.utc)
            after = after if after is not None else certificate.not_valid_after.replace(tzinfo=timezone.utc)
            if not before <= now <= after:
                self.review('snapshot_certificate_time')
            if authorization != self.signing_snapshot.authorization:
                self.review('snapshot_request_material_changed')
        return route, authorization


def active_attempt(company_abbr, source_doc, *, runtime, purpose=None):
    current = ACTIVE.get()
    if current is not None:
        current.require(company_abbr, source_doc, runtime, purpose=purpose)
    return current


def _capture(company_abbr, source_doc, purpose, runtime, translate):
    from .credential_settings import _resolve_owner_record_from_saved_company

    records = {}

    def freeze(doc):
        fields = COMPANY_FIELDS if doc.doctype == 'Company' else OWNER_FIELDS
        values = {name: doc.get(name) for name in fields}
        # Preserve alias presence separately from blank/false values.
        meta = getattr(doc, 'meta', None)
        has_field = getattr(meta, 'has_field', None)
        present = frozenset(name for name in fields if (
            has_field(name) if callable(has_field) else hasattr(doc, name)
        ))
        record = _Record(doc.doctype, doc.name, MappingProxyType(values), present)
        records[(doc.doctype, doc.name)] = record
        return record

    company = freeze(runtime.get_doc('Company', {'abbr': company_abbr}))
    source_key = _identity(source_doc) or ('Company', company.name)
    if (source_key[0] not in ('Company', 'Sales Invoice', 'POS Invoice', 'ZATCA Multiple Setting')
            or not isinstance(source_key[1], str) or not source_key[1].strip()):
        from .credential_material import CredentialConfigurationError
        raise CredentialConfigurationError('source')
    source = company if source_key == ('Company', company.name) else runtime.get_doc(*source_key)
    if source_key[0] in ('Company', 'ZATCA Multiple Setting') and not isinstance(source, _Record):
        source = freeze(source)
    observation = _source_observation(source) if source_key[0] in ('Sales Invoice', 'POS Invoice') else None

    def load(doctype, name):
        key = doctype, name
        if key == source_key:
            return source
        if key not in records:
            return freeze(runtime.get_doc(doctype, name))
        return records[key]

    owner, kind = _resolve_owner_record_from_saved_company(company, source_doc, load_doc=load)
    captured_owner = CredentialOwner(company.name, owner.doctype, owner.name, kind, owner.values)
    return IssuingAttempt(runtime, translate, _site(runtime), company_abbr, purpose,
                         source_key, company, captured_owner, records, observation, source.get('modified'))


@contextmanager
def issuing_attempt(company_abbr, source_doc, *, purpose, runtime, translate):
    """Own one in-memory scope; nesting cannot switch source, site or purpose."""
    if purpose not in ('production', 'compliance', 'debug'):
        raise ValueError('issuing_attempt_purpose')
    current = active_attempt(company_abbr, source_doc, runtime=runtime, purpose=purpose)
    if current is not None:
        yield current
        return
    current = _capture(company_abbr, source_doc, purpose, runtime, translate)
    token = ACTIVE.set(current)
    try:
        yield current
    finally:
        current.closed = True
        ACTIVE.reset(token)
