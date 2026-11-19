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

from .api_routing import ApiConfigurationError, resolve_api_route
from .credential_material import CredentialConfigurationError, CredentialOwner, authorization_for_owner
from .financial_source_observation import HEADER_FIELDS, TABLE_FIELDS
from .issuing_observation import freeze_native_value, native_record_observation
from .issuing_settings_observation import COMPANY_FIELDS as ISSUING_COMPANY_FIELDS
from .scheduling import WINDOW_FIELDS


REVIEW = "The invoice source or ZATCA issuer settings changed during preparation, or the credential context could not be confirmed. No request was sent. Reload the source and review the selected issuer, environment and credentials."
UNCERTAIN = "The ZATCA issuing context could not be confirmed after a transport invocation. The delivery and acceptance outcome is unknown. Review the saved response and submission history before retrying."
ACTIVE = ContextVar('zatca_issuing_attempt', default=None)
OWNER_FIELDS = (
    'custom_private_key', 'custom_certificate', 'custom_certficate',
    'custom_basic_auth_from_csid', 'custom_basic_auth_from_production',
    'custom_final_auth_csid', 'custom_pih', 'tax_id',
    'custom_linked_doctype', 'custom__use_company_certificate__keys', 'custom_zatca_native_chain',
)
COMPANY_FIELDS = tuple(dict.fromkeys((
    *ISSUING_COMPANY_FIELDS, *OWNER_FIELDS,
    'phase_1_or_2', 'custom_zatca_clearance_enabled',
    'custom_clearance_enabled', 'clearance_enabled',
)))


class IssuingAttemptError(RuntimeError):
    """Typed local review outside legacy failure writers, with Frappe HTTP417."""
    http_status_code = 417

    def __init__(self, code, *, transport_started=False):
        self.code = code
        self.template = UNCERTAIN if transport_started else REVIEW
        self.diagnostic_logged = False
        super().__init__(self.template)

    def __str__(self):
        return self.template


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
    return freeze_native_value(value)


def _source_observation(doc):
    native = native_record_observation(doc)
    if native is not None:
        return native
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
    observed_modified: object = field(default=None, repr=False)

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
    prepared_source: object = field(default=None, repr=False)
    prepared_observation: object = field(default=None, repr=False)
    consumed_records: dict = field(default_factory=dict, repr=False)
    consumed_queries: dict = field(default_factory=dict, repr=False)
    prepared_identity: object = field(default=None, repr=False)
    payload_seal: object = field(default=None, repr=False)
    observed_payload: object = field(default=None, repr=False)
    transport_started: bool = False
    closed: bool = False

    def __reduce_ex__(self, protocol):
        raise TypeError('issuing_attempt_not_serializable')

    def review(self, code):
        error = IssuingAttemptError(code, transport_started=self.transport_started)
        self.runtime.log_error(title='ZATCA issuing context review', message=f'{code}: {error.template}')
        error.diagnostic_logged = True
        self.runtime.throw(self.translate(error.template), exc=error)
        raise error

    def require(self, company_abbr, source_doc, runtime, *, purpose=None):
        source = _identity(source_doc)
        if source_doc is None and self.source_identity == ('Company', self.company.name):
            source = self.source_identity
        if self.closed or _site(runtime) != self.site:
            self.review('issuing_context_lifetime')
        if company_abbr != self.company_abbr or source != self.source_identity:
            self.review('issuing_context_source')
        if purpose is not None and purpose != self.purpose:
            self.review('issuing_context_purpose')

    def bind_prepared_invoice(self, document):
        """Bind the rendered invoice separately from a Company/device auth source."""
        key = _identity(document)
        if not key or key[0] not in ('Sales Invoice', 'POS Invoice'):
            self.review('issuing_prepared_source')
        saved = self.runtime.get_doc(*key)
        if saved.get('company') != self.company.name or document.get('company') != self.company.name:
            self.review('issuing_prepared_company')
        observed = _source_observation(saved)
        if _source_observation(document) != observed:
            self.review('issuing_prepared_source_changed')
        if self.prepared_source is not None and _identity(self.prepared_source) != key:
            self.review('issuing_prepared_source')
        if self.prepared_observation is not None and self.prepared_observation != observed:
            self.review('issuing_prepared_source_changed')
        self.prepared_source = document
        self.prepared_observation = observed

    def require_production_configuration(self):
        """Phase aliases use schema presence, never a populated-value fallback."""
        from frappe.utils import cint
        phase_field = next((name for name in ('custom_phase_1_or_2', 'phase_1_or_2')
                            if name in self.company.fields_present), None)
        phase = self.company.get(phase_field) if phase_field is not None else None
        if (not cint(self.company.get('custom_zatca_invoice_enabled'))
                or not isinstance(phase, str) or phase.strip() != 'Phase-2'):
            self.review('issuing_production_phase')

    def prime_native_signing(self, namespace):
        """Validate the native material before identity/ICV writers can run.

        Legacy integrations can replace the signing callback. That explicit
        extension preserves its contract but cannot claim native material proof.
        Never call a replacement to discover whether it performs signing/writes.
        """
        from .sign_invoice_first import _CANONICAL_DIGITAL_SIGNATURE
        if namespace.get('digital_signature') is _CANONICAL_DIGITAL_SIGNATURE:
            self.signing_material()

    def expect_prepared_payload(self, uuid, invoice_hash):
        """Bind producer metadata; the canonical writer seals its final bytes."""
        self.require_runtime(self.runtime)
        self.prepared_identity = (uuid, invoice_hash)
        self.payload_seal = None
        self.observed_payload = None

    def seal_xml(self, path, xml, *, identity=None):
        """Retain one output digest, not another XML/Base64 copy or a signature proof.

        Match the existing request readers' UTF-8 and lstrip contract only. No
        XML canonicalization, financial rounding or cryptographic hash changes.
        Existing XML extractors seal content before their separate metadata gate.
        """
        import hashlib
        self.require_runtime(self.runtime)
        text = xml.decode('utf-8') if isinstance(xml, bytes) else xml
        # Native readers use text-mode universal newline decoding before lstrip.
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        self.payload_seal = (str(path), hashlib.sha256(text.lstrip().encode('utf-8')).digest(),
                             identity if identity is not None else self.prepared_identity)
        self.observed_payload = None

    def observe_payload(self, payload, path):
        """Observe the actual immutable request value once, before HTTP."""
        import base64
        import hashlib
        self.require_runtime(self.runtime)
        if self.payload_seal is None:
            return  # Request-only/custom writer adapters make no producer claim.
        try:
            digest = hashlib.sha256(base64.b64decode(payload.invoice_base64, validate=True)).digest()
        except (ValueError, TypeError):
            invalid = True
        else:
            invalid = False
        if invalid:
            self.review('issuing_payload_encoding')
        self.observed_payload = (str(path), digest, (payload.uuid, payload.invoice_hash))

    def confirm_payload(self):
        """Check exact sealed content, including same-UUID/hash file replacement."""
        if self.payload_seal is None:
            return
        if self.observed_payload is None:
            self.review('issuing_payload_not_observed')
        path, digest, identity = self.payload_seal
        observed_path, observed_digest, observed_identity = self.observed_payload
        if (path != observed_path or digest != observed_digest
                or (identity is not None and identity != observed_identity)):
            self.review('issuing_payload_changed')

    def require_runtime(self, runtime):
        if self.closed or _site(runtime) != self.site:
            self.review('issuing_context_lifetime')

    def observe_query(self, method, args, kwargs, result):
        """Keep an exact discovery/value result, including empty/missing results."""
        if self.transport_started:
            return result
        from copy import deepcopy
        signature = method, freeze_native_value(args), freeze_native_value(kwargs)
        observed = freeze_native_value(result)
        previous = self.consumed_queries.get(signature)
        if previous is not None and previous[2] != observed:
            self.review('issuing_discovery_changed')
        self.consumed_queries[signature] = (deepcopy(args), deepcopy(kwargs), observed)
        return result

    def record_observation(self, document):
        excluded = {name for window in WINDOW_FIELDS for name in window}
        if self.purpose == 'debug':
            excluded.update(('custom_send_invoice_to_zatca', 'custom_submit_or_not',
                             'custom_send_einvoice_background',
                             'custom_send_pos_invoices_to_zatca_on_background'))
        return native_record_observation(document, omit_fields=(
            excluded if getattr(document, 'doctype', None) in ('Company', 'ZATCA Multiple Setting') else ()
        ))

    def observe_record(self, document):
        """Pin a consumed saved master; never collect post-request output reads."""
        if self.closed or _site(self.runtime) != self.site:
            self.review('issuing_context_lifetime')
        if self.transport_started:
            return document
        observed = self.record_observation(document)
        if observed is None:
            return document  # Minimal test adapters are not full native records.
        key = document.doctype, document.name
        if key in self.consumed_records and self.consumed_records[key] != observed:
            self.review('issuing_dependency_changed')
        if key in self.records:
            record = self.records[key]
            if any(_value(document.get(name)) != _value(value) for name, value in record.values.items()):
                self.review('issuing_settings_changed')
        self.consumed_records[key] = observed
        return document

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
            meta = getattr(current, 'meta', None)
            has_field = getattr(meta, 'has_field', None)
            present = frozenset(name for name in record.values if (
                has_field(name) if callable(has_field) else hasattr(current, name)
            ))
            if present != record.fields_present:
                self.review('issuing_settings_schema_changed')
            if any(_value(current.get(name)) != _value(value) for name, value in record.values.items()):
                self.review('issuing_settings_changed')
        for (method, _args, _kwargs), (args, kwargs, observed) in self.consumed_queries.items():
            reader = self.runtime.db.get_value if method == 'db.get_value' else getattr(self.runtime, method)
            if freeze_native_value(reader(*args, **kwargs)) != observed:
                self.review('issuing_discovery_changed')
        for key, observed in self.consumed_records.items():
            current = self.runtime.get_doc(*key)
            if self.record_observation(current) != observed:
                self.review('issuing_dependency_changed')
        if self.prepared_source is not None:
            saved = self.runtime.get_doc(*_identity(self.prepared_source))
            if (_source_observation(saved) != self.prepared_observation
                    or _source_observation(self.prepared_source) != self.prepared_observation):
                self.review('issuing_prepared_source_changed')
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
            from .credential_snapshot import (
                CredentialSnapshot, CredentialSnapshotError, authentication_certificate_der,
            )
            from .certificate_evidence import parse_public_certificate_text
            from .artifact_evidence import ArtifactEvidenceError
            from .credential_identity import CredentialIdentityError, require_certificate_taxpayer
            import base64
            endpoint = ('compliance/invoices' if self.purpose == 'compliance'
                        else 'invoices/reporting/single')
            failed = None
            try:
                route = resolve_api_route(self.company.values, endpoint)
                authorization = authorization_for_owner(self.owner, self.purpose)
                purpose_der = authentication_certificate_der(authorization.header)
                # This purpose's token is the explicit certificate source. A
                # generic legacy field is retained byte-for-byte only when it
                # already contains the same certificate; absent/malformed legacy
                # text cannot substitute a different certificate for this token.
                selected_text = base64.b64encode(purpose_der).decode('ascii')
                try:
                    legacy_text = _certificate_for_owner(self.owner)
                except CredentialConfigurationError as legacy_error:
                    if legacy_error.code != 'certificate':
                        raise
                else:
                    try:
                        _certificate, declared_der = parse_public_certificate_text(legacy_text)
                    except ArtifactEvidenceError:
                        declared_der = None
                    if purpose_der == declared_der:
                        selected_text = legacy_text
                # A completed onboarding cycle can legitimately retain both
                # Compliance and Production tokens for different certificates
                # sharing one CSR key. Select this purpose's token certificate;
                # never copy it into the other purpose or overwrite stored aliases.
                captured = CredentialSnapshot(self.owner, route, selected_text,
                                              datetime.now(timezone.utc))
                require_certificate_taxpayer(captured.certificate, self.company.get('tax_id'))
            except (CredentialSnapshotError, CredentialConfigurationError, ApiConfigurationError,
                    ArtifactEvidenceError, CredentialIdentityError) as error:
                failed = error.code
            if failed is not None:
                self.review(failed)
            self.signing_snapshot = captured
        from .native_preparation import active_preparation
        prepared=active_preparation(self.runtime)
        if prepared is not None:
            prepared.bind_material(self.signing_snapshot)
        return self.signing_snapshot

    def selection(self, endpoint, *, source_doc, runtime, require_issuing_unit=False):
        """Route and authorization from the same captured Company/owner."""
        self.require(self.company_abbr, source_doc, runtime)
        try:
            route = resolve_api_route(self.company.values, endpoint)
        except ApiConfigurationError as error:
            from .api_settings import _throw_configuration_error
            _throw_configuration_error(error)
            raise
        self.require(self.company_abbr, source_doc, runtime, purpose=route.required_credential)
        if require_issuing_unit:
            source = self.runtime.get_doc(*self.source_identity)
            if not source.get('custom_zatca_pos_name'):
                runtime.throw(self.translate('A saved ZATCA issuing unit is required for this XML submission path.'))
                raise IssuingAttemptError('issuing_unit_missing')
        self.confirm_current()
        try:
            authorization = authorization_for_owner(self.owner, route.required_credential)
        except CredentialConfigurationError as error:
            from .credential_settings import _throw_configuration_error
            _throw_configuration_error(error)
            raise
        if self.signing_snapshot is not None:
            from .credential_snapshot import validate_snapshot_time
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
        from .native_preparation import active_preparation
        prepared=active_preparation(self.runtime)
        if prepared is not None:
            prepared.bind_selection(route,authorization)
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
        # Window eligibility belongs to the worker, never to local Debug.
        excluded = {name for window in WINDOW_FIELDS for name in window}
        if purpose == 'debug':
            excluded.update(('custom_send_invoice_to_zatca', 'custom_submit_or_not',
                             'custom_send_einvoice_background',
                             'custom_send_pos_invoices_to_zatca_on_background'))
        fields = tuple(name for name in fields if name not in excluded)
        values = {name: doc.get(name) for name in fields}
        # Preserve alias presence separately from blank/false values.
        meta = getattr(doc, 'meta', None)
        has_field = getattr(meta, 'has_field', None)
        present = frozenset(name for name in fields if (
            has_field(name) if callable(has_field) else hasattr(doc, name)
        ))
        record = _Record(doc.doctype, doc.name, MappingProxyType(values), present, doc.get('modified'))
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
                         source_key, company, captured_owner, records, observation,
                         source.observed_modified if isinstance(source, _Record) else source.get('modified'))


@contextmanager
def issuing_attempt(company_abbr, source_doc, *, purpose, runtime, translate, invoice_doc=None):
    """Own one in-memory scope; nesting cannot switch source, site or purpose."""
    if purpose not in ('production', 'compliance', 'debug'):
        raise ValueError('issuing_attempt_purpose')
    current = active_attempt(company_abbr, source_doc, runtime=runtime, purpose=purpose)
    if current is not None:
        current.transport_started = False
        if invoice_doc is not None:
            current.bind_prepared_invoice(invoice_doc)
        yield current
        return
    current = _capture(company_abbr, source_doc, purpose, runtime, translate)
    token = ACTIVE.set(current)
    try:
        if invoice_doc is not None:
            current.bind_prepared_invoice(invoice_doc)
        yield current
    finally:
        current.closed = True
        ACTIVE.reset(token)


def confirm_issuing_transport(company_abbr, source_doc, *, runtime, purpose=None):
    """Last observed-source check before the caller enters its HTTP function.

    This marker is not proof that bytes reached a socket or an authority receipt.
    Post-invocation reads must not be mistaken for preparation-source observations.
    """
    from .deferred_submission import reject_submit_hook_transport
    reject_submit_hook_transport(runtime, getattr(runtime, '_', lambda text:text))
    if purpose not in (None,'production','compliance'):
        raise ValueError('issuing_transport_purpose')
    current = active_attempt(company_abbr, source_doc, runtime=runtime, purpose=purpose)
    if (current is None and purpose!='compliance') or (current is not None and current.purpose=='production'):
        from .native_preparation import reject_legacy_native_preparation
        reject_legacy_native_preparation(current.prepared_source if current is not None else source_doc,runtime)
    if current is None:
        from .native_preparation import active_preparation, NativePreparationError
        if active_preparation(runtime) is not None:
            raise NativePreparationError('native_preparation_scope_missing')
        return  # Standalone request helpers keep their request-only contract.
    try:
        current.confirm_current()
        current.confirm_payload()
    except IssuingAttemptError:
        # Existing API paths may already have shown their progress overlay.
        # Preserve the source review if best-effort overlay cleanup itself fails.
        try:
            runtime.publish_realtime('hide_gif', user=runtime.session.user)
        except Exception:
            pass
        raise
    from .native_preparation import active_preparation
    prepared=active_preparation(runtime)
    if prepared is not None:
        prepared.handoff(current)
    current.transport_started = True


def collect_issuing_compliance(runtime, validation_types, submit, *, company_abbr,
                              source_doc, translate):
    """Keep one purpose/owner/material capture for a complete check collection."""
    from .compliance_messages import collect_compliance_results

    with issuing_attempt(company_abbr, source_doc, purpose='compliance',
                         runtime=runtime, translate=translate) as current:
        def checked_submit(validation_type):
            current.transport_started = False
            current.confirm_current()
            return submit(validation_type)
        return collect_compliance_results(runtime, validation_types, checked_submit)


def seal_current_xml(path, xml, *, runtime, identity=None):
    """Native writer/extractor hook; no context means no producer binding claim."""
    current = ACTIVE.get()
    if current is not None:
        current.require_runtime(runtime)
        current.seal_xml(path, xml, identity=identity)


@contextmanager
def invoice_issuing_attempt(doctype, invoice_number, *, runtime, translate, namespace):
    """Authorize and bind the saved source before native UUID/ICV preparation.

    The ordinary invoice entry requires READ/WRITE on its invoice and READ on
    its Company. Linked issuer policy remains the existing same-taxpayer policy;
    this boundary does not grant access to linked credential records or export
    their content. Workers use their normal executing principal, no role bypass.
    """
    from .permission_compat import PermissionCompatibilityError, saved_row_has_permission
    if doctype not in ('Sales Invoice', 'POS Invoice'):
        raise ValueError('issuing_invoice_doctype')
    invoice = runtime.get_doc(doctype, invoice_number)
    company = runtime.get_doc('Company', invoice.get('company'))
    with issuing_attempt(company.get('abbr'), invoice, purpose='production',
                         runtime=runtime, translate=translate, invoice_doc=invoice) as current:
        denied = False
        try:
            user = runtime.session.user
            engine = runtime.has_permission
            denied = not all(saved_row_has_permission(engine, kind, operation, doc=doc, user=user)
                             for kind, operation, doc in (
                                 (doctype, 'read', invoice), (doctype, 'write', invoice),
                                 ('Company', 'read', company)))
        except (AttributeError, PermissionCompatibilityError):
            denied = True
        if denied:
            current.review('issuing_source_access')
        current.require_production_configuration()
        current.prime_native_signing(namespace)
        yield current
