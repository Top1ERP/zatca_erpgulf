"""Flat response assessment for retained native originals and receipts.

No DB, transport, credential, retry or status mutation occurs here. A matching
contract is an input to the owned service, not caller-supplied proof of receipt
provenance, signature validity, certificate trust or business reconciliation.
"""

import base64
from dataclasses import dataclass, field
import hashlib

from .artifact_evidence import ArtifactEvidenceError, inspect_invoice_artifact
from .issuance_candidate import IssuanceContractError, _invoice_classification
from .response_contract import REPORTING, CLEARANCE, _validation, _outcome_issues, _returned_xml
from .response_json import parse_wire_response, response_decoder


STANDARD_PRODUCTION_BASE_SHA256 = hashlib.sha256(
    b'https://gw-fatoora.zatca.gov.sa/e-invoicing/core').hexdigest()
DUPLICATE_MESSAGE = 'invoice was already reported successfully earlier.'


@dataclass(frozen=True, repr=False)
class NativeAssessment:
    outcome: str
    issues: tuple = ()
    warning_count: int = 0
    has_warnings: bool = False
    returned_xml: bytes | None = field(default=None, repr=False)

    def __reduce_ex__(self, protocol):
        raise TypeError('native_assessment_not_serializable')


def _original(header, body):
    if (type(body) is not bytes or not body or len(body) > 16 * 1024 * 1024
            or hashlib.sha256(body).hexdigest() != header['artifact_sha256']):
        raise ArtifactEvidenceError('response_original_binding')
    try:
        request = response_decoder().decode(body.decode('utf-8'))
        if (type(request) is not dict or set(request) != {'invoiceHash', 'uuid', 'invoice'}
                or any(type(value) is not str for value in request.values())
                or request['invoiceHash'] != header['invoice_hash'] or request['uuid'] != header['invoice_uuid']):
            raise ValueError
        xml = base64.b64decode(request['invoice'], validate=True)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ArtifactEvidenceError('response_original_binding') from None
    observed = inspect_invoice_artifact(xml)
    if (observed.invoice_id != header['source_name'] or observed.uuid != header['invoice_uuid']
            or str(observed.icv) != header['icv'] or observed.invoice_digest != header['invoice_hash']
            or observed.previous_hash != header['previous_hash']):
        raise ArtifactEvidenceError('response_original_binding')
    return xml, observed


def _reporting_duplicate(body):
    """Recognize one explicit English duplicate diagnostic, never any409 body.

    This deployment rule additionally requires the bound standard Production
    route and Reporting operation. Null optional diagnostic code/category values
    are allowed; conflicting or additional validation errors remain review-only.
    """
    validation = body.get('validationResults')
    if (type(validation) is not dict or validation.get('status') != 'ERROR'
            or validation.get('infoMessages', []) != [] or validation.get('warningMessages', []) != []
            or body.get('reportingStatus') != 'NOT_REPORTED'
            or body.get('clearanceStatus') is not None or body.get('clearedInvoice') is not None
            or body.get('reportedInvoice') is not None):
        return False
    errors = validation.get('errorMessages')
    if type(errors) is not list or len(errors) != 1 or type(errors[0]) is not dict:
        return False
    error = errors[0]
    return (error.get('type') == 'ERROR' and error.get('status') == 'ERROR'
        and type(error.get('message')) is str and error['message'].strip().casefold() == DUPLICATE_MESSAGE
        and all(error.get(key) is None or type(error[key]) is str for key in ('code', 'category')))


def _receipt_bound(header, receipt, body):
    return (receipt['issuance'] == header['record_id']
        and receipt['request_sha256'] == header['artifact_sha256']
        and receipt['environment'] == header['environment']
        and hashlib.sha256(body).hexdigest() == receipt['response_sha256'])


def assess_native_receipt(header, original, receipt, body, *, fallback_receipt=None):
    """Assess only this exact artifact/operation/receipt; preserve raw messages.

   208 requires matching cleared XML.409 recognition is restricted to the
    documented Production Reporting duplicate diagnostic and exact bound route.
    Unknown response shapes stay review-only rather than becoming new reissues.
    Returned XML checks compare metadata/type, not computed hashes/signatures.
    """
    try:
        xml, expected = _original(header, original)
        if not _receipt_bound(header, receipt, body):
            raise ArtifactEvidenceError('response_receipt_binding')
        endpoint, status = receipt['endpoint'], receipt['http_status']
        fallback = False
        if endpoint != header['endpoint']:
            if (header['endpoint'] == CLEARANCE and endpoint == REPORTING
                    and type(fallback_receipt) is tuple and len(fallback_receipt) == 2):
                prior, raw_prior = fallback_receipt
                fallback = (_receipt_bound(header, prior, raw_prior)
                    and prior['endpoint'] == CLEARANCE and prior['http_status'] == 303)
            if not fallback:
                raise ArtifactEvidenceError('response_receipt_binding')
        if endpoint not in (REPORTING, CLEARANCE):
            raise ArtifactEvidenceError('response_operation_mismatch')
        code, indicator = _invoice_classification(xml)
        if (endpoint == CLEARANCE and not indicator.startswith('01')) or (endpoint == REPORTING
                and not (indicator.startswith('02') or (fallback and indicator.startswith('01')))):
            raise ArtifactEvidenceError('response_operation_mismatch')
        if status == 303 and endpoint == CLEARANCE:
            return NativeAssessment('CLEARANCE_DISABLED')
        if status in (401, 403):
            return NativeAssessment('AUTHORIZATION_FAILED')
        if status in (413, 429) or status >= 500:
            return NativeAssessment('TECHNICAL_FAILURE')
        parsed = parse_wire_response(body)
        if (('invoiceHash' in parsed and parsed['invoiceHash'] != header['invoice_hash'])
                or ('uuid' in parsed and parsed['uuid'] != header['invoice_uuid'])):
            raise ArtifactEvidenceError('response_invoice_identity_mismatch')
        standard = (header['environment'] == 'Production'
            and header['base_url_sha256'] == STANDARD_PRODUCTION_BASE_SHA256)
        if status == 409:
            if endpoint == REPORTING and indicator.startswith('02') and standard and _reporting_duplicate(parsed):
                return NativeAssessment('REPORTING_DUPLICATE_MATCHED')
            return NativeAssessment('DUPLICATE_REVIEW_REQUIRED')
        validation, warnings, problems = _validation(parsed)
        issues = list(problems + _outcome_issues(parsed, endpoint))
        has_warnings = status == 202 or validation == 'WARNING' or warnings > 0
        if status == 400:
            if (not issues and validation == 'ERROR'
                    and parsed.get('reportingStatus') != 'REPORTED' and parsed.get('clearanceStatus') != 'CLEARED'):
                return NativeAssessment('VALIDATION_REJECTED', warning_count=warnings, has_warnings=has_warnings)
            return NativeAssessment('UNCONFIRMED', tuple(issues))
        if status not in (200, 202, 208):
            return NativeAssessment('UNCONFIRMED', tuple(issues))
        if status == 208 and (endpoint != CLEARANCE or not standard):
            return NativeAssessment('DUPLICATE_REVIEW_REQUIRED')
        if validation not in ('PASS', 'WARNING'):
            issues.append('response_validation_unconfirmed')
        field_name, required = ('reportingStatus', 'REPORTED') if endpoint == REPORTING else ('clearanceStatus', 'CLEARED')
        if parsed.get(field_name) != required:
            issues.append('response_acceptance_missing')
        if 'invoiceHash' in parsed and parsed['invoiceHash'] != header['invoice_hash']:
            issues.append('response_invoice_hash_mismatch')
        wrong_xml = 'clearedInvoice' if endpoint == REPORTING else 'reportedInvoice'
        if parsed.get(wrong_xml) is not None:
            issues.append('response_xml_operation_mismatch')
        returned = None
        xml_field = 'reportedInvoice' if endpoint == REPORTING else 'clearedInvoice'
        if endpoint == CLEARANCE or parsed.get(xml_field) is not None:
            returned = _returned_xml(parsed.get(xml_field))
            observed = inspect_invoice_artifact(returned)
            for attribute in ('invoice_id', 'uuid', 'icv', 'seller_tax_id', 'invoice_digest', 'previous_hash'):
                if getattr(observed, attribute) != getattr(expected, attribute):
                    issues.append('response_xml_' + attribute + '_mismatch')
            if _invoice_classification(returned) != (code, indicator):
                issues.append('response_xml_type_mismatch')
        if issues:
            return NativeAssessment('UNCONFIRMED', tuple(dict.fromkeys(issues)), warnings, has_warnings)
        outcome = 'REPORTING_MATCHED' if endpoint == REPORTING else 'CLEARANCE_MATCHED'
        if status == 208:
            outcome = 'CLEARANCE_DUPLICATE_MATCHED'
        return NativeAssessment(outcome, warning_count=warnings, has_warnings=has_warnings, returned_xml=returned)
    except (ArtifactEvidenceError, IssuanceContractError) as error:
        return NativeAssessment('UNCONFIRMED', (error.code,))
