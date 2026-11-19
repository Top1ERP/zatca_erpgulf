"""Admit an attached exact native original to the owned delivery coordinator.

This is a fixed server adapter, not a whitelisted import/upload endpoint. It
cannot adopt unowned XML as a new issuance, regenerate, infer acceptance, or retry
an unknown outcome. Legacy unmarked owners retain their separate existing path.
"""

from pathlib import Path
from urllib.parse import quote, unquote

from .artifact_evidence import ArtifactEvidenceError
from .artifact_inventory import _read_local_attachment
from .native_dispatch import read_retained_invoice
from .native_preparation import active_preparation
from .native_provider import (
    _schema_available, _selection, _run_selected, _permitted,
    NativeProviderError, reviewed_native_operation,
)
from .operation_messages import mute_operation_messages


PREFIX = '/private/files/'


def _context(runtime):
    value = runtime.local.site, runtime.session.user
    if any(type(item) is not str or not item for item in value):
        raise NativeProviderError('native_existing_xml_context')
    return value


def _require_context(runtime, expected):
    if _context(runtime) != expected:
        raise NativeProviderError('native_existing_xml_context_changed')


def _url(path, *, runtime, path_kind):
    """Recognize this site's URL/legacy concatenation/own private folder only.

    No caller path is opened, resolved or fetched. File metadata and the bounded
    private attachment reader select the actual local file after authorization.
    """
    if type(path) is not str or not 0 < len(path) <= 4096 or '\0' in path:
        raise NativeProviderError('native_existing_xml_path')
    value = path
    if path_kind == 'file' and not value.startswith(PREFIX):
        site = runtime.local.site
        if value.startswith(site + PREFIX):
            value = value[len(site):]
        else:
            folder = Path(runtime.get_site_path('private', 'files'))
            for root in (str(folder), str(folder.absolute())):
                if value.startswith(root.rstrip('/') + '/'):
                    value = PREFIX + value[len(root.rstrip('/') + '/'):]
                    break
    elif path_kind != 'url' and path_kind != 'file':
        raise NativeProviderError('native_existing_xml_path_kind')
    decoded = unquote(value)
    if not decoded.startswith(PREFIX):
        raise NativeProviderError('native_existing_xml_path')
    basename = decoded[len(PREFIX):]
    if (not basename or basename in ('.', '..')
            or any(char in basename for char in ('/', '\\', '\0'))):
        raise NativeProviderError('native_existing_xml_path')
    # Both raw/encoded local URLs occur in saved legacy fields. An ambiguous
    # metadata result is held rather than choosing an arbitrary File record.
    return decoded, tuple(dict.fromkeys((value, decoded, quote(decoded, safe='/'))))


def _attached_original(source, path, *, runtime, path_kind, context):
    decoded, choices = _url(path, runtime=runtime, path_kind=path_kind)
    _require_context(runtime, context)
    rows = runtime.get_all('File', filters={'attached_to_doctype': source.doctype,
        'attached_to_name': source.name, 'file_url': ['in', list(choices)]},
        fields=['name'], order_by='name asc', limit_page_length=2)
    if len(rows) != 1 or type(rows[0].get('name')) is not str:
        raise NativeProviderError('native_existing_xml_attachment_ambiguous')
    document = runtime.get_doc('File', rows[0]['name'])
    if (document.doctype, document.name) != ('File', rows[0]['name']):
        raise NativeProviderError('native_existing_xml_attachment_identity')
    _permitted(runtime, document)
    _require_context(runtime, context)
    if type(document.get('file_url')) is not str or unquote(document.file_url) != decoded:
        raise NativeProviderError('native_existing_xml_attachment_changed')
    try:
        content = _read_local_attachment(document, source.doctype, source.name, runtime=runtime)
    except ArtifactEvidenceError as error:
        raise NativeProviderError('native_existing_xml_' + error.code) from None
    _require_context(runtime, context)
    return content


def _no_build(source):
    raise NativeProviderError('native_existing_xml_original_required')


def maybe_process_native_existing_xml(doctype, invoice_name, path, *, runtime, translate,
                                     source=None, path_kind='url', require_issuing_unit=False,
                                     supplied_identity=None):
    """None selects legacy; a native result never reaches its legacy writers.

    A current owned preparation continues to its existing exact-payload handoff.
    Otherwise, saved Source/Company WRITE/READ and File READ bind a private local
    attachment to the current immutable original. Only its retained request may
    dispatch under the normal entry policy. No callback/document is queued.
    """
    def operation():
        if active_preparation(runtime) is not None:
            return None
        hint = source.get('custom_zatca_issuing_unit') if source is not None else None
        if not (type(hint) is str and hint.startswith('egs:')) and not _schema_available(runtime):
            return None
        with mute_operation_messages(runtime):
            context = _context(runtime)
            if source is not None and (source.get('doctype'), source.get('name')) != (doctype, invoice_name):
                raise NativeProviderError('native_existing_xml_source_identity')
            selection = _selection(runtime, doctype, invoice_name, source)
            if selection is None:
                return None
            saved, company = selection
            if saved.get('docstatus') != 1:
                raise NativeProviderError('native_source_not_submitted')
            if require_issuing_unit and not saved.get('custom_zatca_pos_name'):
                raise NativeProviderError('native_existing_xml_saved_device_required')
            view = read_retained_invoice(doctype, invoice_name, runtime=runtime, require_current_source=True)
            if view is None:
                raise NativeProviderError('native_existing_xml_original_required')
            _require_context(runtime, context)
            if supplied_identity is not None and supplied_identity != (view.invoice_uuid, view.invoice_hash):
                raise NativeProviderError('native_existing_xml_supplied_identity')
            content = _attached_original(saved, path, runtime=runtime, path_kind=path_kind, context=context)
            if content != view.original_xml:
                raise NativeProviderError('native_existing_xml_original_mismatch')
            _require_context(runtime, context)
            return _run_selected(doctype, invoice_name, runtime=runtime, translate=translate,
                build=_no_build, intent='entry', source=saved, company=company,
                expected_issuance_id=view.issuance_id)
    return reviewed_native_operation(operation, runtime=runtime, translate=translate)
