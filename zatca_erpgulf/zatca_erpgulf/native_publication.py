"""Authenticated, on-demand native XML/QR views from immutable custody.

No File insertion, source save, status projection, signing or transport occurs.
The print hook changes only its transient render document. Diagnostic original
downloads remain possible after rejection or a source edit, but are explicitly
named ORIGINAL and cannot grant tax-print permission. Persisted attachment and
external print integrations remain a separate adoption boundary.
"""

import base64
from io import BytesIO
import json

import frappe
from frappe import _
import pyqrcode
from werkzeug.wrappers import Response

from .dispatch_record_codec import _identifier
from .dispatch_store import DispatchStoreError
from .issuing_attempt import _source_observation
from .native_artifact import read_native_artifact
from .native_dispatch import NativeDispatchError, read_retained_invoice, SOURCE_TABLES
from .publication_source import render_source_sha256
from .operation_messages import mute_operation_messages
from .worker_transaction import WorkerTransactionError
from .issued_parties import IssuedPartiesError
from .issued_print import render_input,apply_issued_parties
from .native_provider import _schema_available, _selection, _permitted
from .zatca_runtime import is_zatca_invoice_enabled, resolve_zatca_phase, PHASE_2_VALUE


REVIEW = 'The saved ZATCA document cannot be displayed or printed safely. Review its issuance, response and saved invoice data. No document was regenerated or sent.'
PENDING = 'Generated document; ZATCA acceptance is not confirmed.'
ACCEPTED = 'ZATCA acceptance is confirmed by the saved response.'
UNISSUED = 'This invoice uses the native ZATCA issuance path, but no verified saved print document is available yet. Review its saved preparation request and issuing unit, then refresh after preparation. Printing did not generate or send a document.'


class NativePublicationError(RuntimeError):
    """One translated display message with a static English diagnostic code."""
    http_status_code = 417

    def __init__(self, code, message=REVIEW):
        self.code = code
        super().__init__(message)


def _identity(doctype, invoice_name):
    if (doctype not in SOURCE_TABLES or type(invoice_name) is not str
            or not 0 < len(invoice_name) <= 140 or '\0' in invoice_name):
        raise NativePublicationError('native_publication_identity')


def _qr_image(payload):
    """Encode the retained payload verbatim; no TLV or money reconstruction.

    The XML reader already bounds canonical Base64. QR library capacity errors
    stop publication instead of reducing the payload or changing error recovery.
    The PNG remains in request memory, with no public URL or disk side effect.
    """
    output = BytesIO()
    pyqrcode.create(payload, error='L', mode='binary', encoding='ascii').png(
        output, scale=4, quiet_zone=4)
    return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode('ascii')


def load_publication(doctype, invoice_name, *, runtime, render_document=None):
    """Internal strict print/preview selector; historical diagnostics are separate.

    A generation-time authenticated publication projection permits only named
    collection updates. Old originals without one keep their full comparison.
    Output bookkeeping, QR links and framework metadata are already excluded by
    the native observer. No current signing credential is required.
    """
    _identity(doctype, invoice_name)
    artifact = read_native_artifact(doctype, invoice_name, runtime=runtime, for_publication=True,
        **({'for_print':True} if render_document is not None else {}))
    if artifact is None:
        raise NativePublicationError('native_publication_not_native')
    if render_document is not None:
        if (render_document.doctype, render_document.name) != (doctype, invoice_name):
            raise NativePublicationError('native_publication_render_identity')
        # Output fields are excluded from the business digest. Compare them to
        # this same custody view, not a source read preceding a version change.
        if (render_document.get('custom_zatca_issuing_unit') != 'egs:' + artifact.chain_id
                or render_document.get('custom_uuid') != artifact.invoice_uuid
                or type(render_document.get('custom_zatca_icv')) not in (str, int)
                or str(render_document.get('custom_zatca_icv')) != artifact.icv):
            raise NativePublicationError('native_publication_render_identity')
        # Fiscal matching to the issued original happened inside the saved read.
        # The whole supplied render record must now match that current saved
        # observation, including collection fields: no fabricated paid balance.
        observed = render_source_sha256((doctype, invoice_name), _source_observation(
            render_input(render_document,runtime=runtime,issuance_id=artifact.issuance_id)))
        if observed != artifact.render_source_sha256:
            raise NativePublicationError('native_publication_render_changed')
    return artifact, _qr_image(artifact.qr_payload)


def _reviewed(operation, *, runtime, translate, return_review=False):
    """No exception/body/identity interpolation and no nested popup cascades."""
    code = None
    message = REVIEW
    try:
        with mute_operation_messages(runtime):
            return operation()
    except Exception as error:
        code = error.code if isinstance(error, (NativePublicationError, NativeDispatchError,
            DispatchStoreError, WorkerTransactionError,IssuedPartiesError)) else 'native_publication_unavailable'
        if code == 'native_publication_unissued':
            message = UNISSUED
    runtime.log_error(title='Native ZATCA publication review', message=f'{code}: {message}')
    if return_review:
        return {'status': 'REVIEW', 'message': translate(message)}
    # Outside except: no protected driver/XML exception context is exported.
    raise NativePublicationError(code, translate(message))


def preview_result(doctype, invoice_name, *, runtime, translate):
    def operation():
        _identity(doctype, invoice_name)
        saved = runtime.get_doc(doctype, invoice_name)
        if (saved.doctype, saved.name) != (doctype, invoice_name):
            raise NativePublicationError('native_publication_source_identity')
        # Classification is available without installed native storage/keys on
        # older or Phase1 sites, but never without saved-source READ permission.
        _permitted(runtime, saved)
        marker = saved.get('custom_zatca_issuing_unit')
        if type(marker) is not str or not marker.startswith('egs:'):
            if _unissued_native_selected(saved, runtime=runtime):
                return {'status': 'UNISSUED', 'message': translate(UNISSUED)}
            return {'status': 'LEGACY'}
        artifact, image = load_publication(doctype, invoice_name, runtime=runtime)
        return {'status': 'READY', 'issuance_id': artifact.issuance_id,
            'state': artifact.state, 'accepted': artifact.accepted,
            'source_kind': artifact.source_kind, 'qr_data_uri': image,
            'message': translate(ACCEPTED if artifact.accepted else PENDING)}
    return _reviewed(operation, runtime=runtime, translate=translate, return_review=True)


def _response(content, content_type, *, filename=None):
    response = Response(content, content_type=content_type)
    response.headers['Cache-Control'] = 'private, no-store, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    if filename is not None:
        response.headers.set('Content-Disposition', 'attachment', filename=filename)
    return response


@frappe.whitelist(methods=['GET'])
def preview(doctype, invoice_name):
    """Identifiers only; saved selection precedes any native custody read."""
    result = preview_result(doctype, invoice_name, runtime=frappe, translate=_)
    # Frappe passes Response through; retain frappe.call's normal message shape
    # while giving QR JSON the same no-store policy as XML downloads.
    return _response(json.dumps({'message': result}, ensure_ascii=False), 'application/json; charset=utf-8')


def xml_response(doctype, invoice_name, issuance_id, *, original=False, runtime, translate):
    def operation():
        _identity(doctype, invoice_name)
        _identifier(issuance_id)
        if original:
            view = read_retained_invoice(doctype, invoice_name, runtime=runtime)
            if view is None or view.issuance_id != issuance_id:
                raise NativePublicationError('native_publication_version_changed')
            content, prefix = view.original_xml, 'ORIGINAL'
        else:
            artifact = read_native_artifact(doctype, invoice_name, runtime=runtime, for_publication=True)
            if artifact is None or artifact.issuance_id != issuance_id:
                raise NativePublicationError('native_publication_version_changed')
            content, prefix = artifact.xml_bytes, artifact.source_kind
        # Opaque validated UUID only; no source name enters a response header.
        # A returned XML may declare a different encoding. Do not contradict its
        # preserved declaration/BOM with an invented HTTP charset.
        return _response(content, 'application/xml', filename=f'{prefix}_{issuance_id}.xml')
    return _reviewed(operation, runtime=runtime, translate=translate)


@frappe.whitelist(methods=['GET'])
def download_xml(doctype, invoice_name, issuance_id):
    return xml_response(doctype, invoice_name, issuance_id, runtime=frappe, translate=_)


@frappe.whitelist(methods=['GET'])
def download_original(doctype, invoice_name, issuance_id):
    return xml_response(doctype, invoice_name, issuance_id, original=True, runtime=frappe, translate=_)


def _unissued_native_selected(saved, *, runtime):
    """Do not treat the worker's not-yet-issued native source as legacy.

    Inspect saved policy before owner resolution so Phase1/disabled sites keep
    their ordinary print permissions. Native ownership is persistent even when
    rollout is off or the registered unit is not active. READ alone suffices;
    this check neither creates a request nor promises that one is queued.
    """
    if not _schema_available(runtime):
        return False
    company = runtime.get_doc('Company', saved.company)
    if (company.doctype, company.name) != ('Company', saved.company):
        raise NativePublicationError('native_publication_company_identity')
    if not is_zatca_invoice_enabled(company) or resolve_zatca_phase(company) != PHASE_2_VALUE:
        return False
    return _selection(runtime, saved.doctype, saved.name, saved, write=False) is not None


def before_print(doc, method=None, print_settings=None):
    """Sales/POS hook: supply normal doc.ksa_einv_qr only in render memory.

    Reload the saved marker rather than trusting submitted print JSON to opt out.
    A native failure stops rendering, without falling back to an old QR/File.
    Standard needs matched clearance or the bound accepted303 fallback; Simplified
    may use its generated original before Reporting, without claiming acceptance.
    """
    if doc.get('name') in (None, ''):
        return  # Preserve ordinary unsaved draft rendering; no saved identity.
    def operation():
        _identity(doc.doctype, doc.name)
        saved = frappe.get_doc(doc.doctype, doc.name)
        marker = saved.get('custom_zatca_issuing_unit')
        if type(marker) is not str or not marker.startswith('egs:'):
            if _unissued_native_selected(saved, runtime=frappe):
                raise NativePublicationError('native_publication_unissued', UNISSUED)
            return
        artifact, image = load_publication(doc.doctype, doc.name, runtime=frappe, render_document=doc)
        apply_issued_parties(doc,artifact.issued_parties,runtime=frappe,issuance_id=artifact.issuance_id)
        doc.ksa_einv_qr = image
        doc.custom_zatca_status = artifact.state if artifact.accepted else 'Not Submitted'
    return _reviewed(operation, runtime=frappe, translate=_)
