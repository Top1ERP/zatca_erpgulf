"""Read one invocation's route and authentication from frozen saved projections.

This binds consumed field observations, not a transaction, source revision,
material validity, certificate epoch or authorization to make an HTTP request.
No cache survives this call; no projected document is saved or returned.
"""

from dataclasses import dataclass, field
from types import MappingProxyType

from .api_routing import ENVIRONMENT_FIELDS, ApiConfigurationError, resolve_api_route
from .credential_material import (
    CredentialConfigurationError, CredentialOwner, authorization_for_owner,
)


SOURCE_FIELDS = ('company', 'custom_zatca_pos_name', 'modified')
OWNER_FIELDS = (
    'tax_id', 'custom_linked_doctype', 'custom__use_company_certificate__keys',
    'custom_basic_auth_from_csid', 'custom_basic_auth_from_production',
    'custom_final_auth_csid', 'modified',
)
COMPANY_FIELDS = (
    *OWNER_FIELDS, 'custom_select', *ENVIRONMENT_FIELDS.values(),
)


@dataclass(frozen=True, repr=False)
class _SavedProjection:
    doctype: str
    name: str
    values: object = field(repr=False)

    def get(self, key, default=None):
        return self.values.get(key, default)


def capture_request_selection(company_abbr, source_doc, endpoint, *, runtime,
                              resolve_owner_record, credential_error, route_error,
                              require_issuing_unit=False, translate):
    """Reuse existing owner/route policies with one short-lived row projection.

    Current imported runtime and translators are supplied by the adapter. Saved
    source identity and taxpayer/link checks still belong to the owner policy.
    Capturing immediately upon read avoids later mutations of returned records;
    it does not make separately loaded rows an atomic database snapshot.
    """
    projections = {}

    def project(doc, fields):
        return _SavedProjection(doc.doctype, doc.name, MappingProxyType({
            name: doc.get(name) for name in fields
        }))

    def load_saved(doctype, name):
        key = (doctype, name)
        if key not in projections:
            doc = runtime.get_doc(doctype, name)
            fields = SOURCE_FIELDS if doctype in ('Sales Invoice', 'POS Invoice') else OWNER_FIELDS
            projections[key] = project(doc, fields)
        return projections[key]

    if require_issuing_unit:
        saved = load_saved(source_doc.doctype, source_doc.name)
        if not saved.get('custom_zatca_pos_name'):
            runtime.throw(translate('A saved ZATCA issuing unit is required for this XML submission path.'))
            raise CredentialConfigurationError('source')
    company = project(runtime.get_doc('Company', {'abbr': company_abbr}), COMPANY_FIELDS)
    projections[('Company', company.name)] = company
    try:
        route = resolve_api_route(company.values, endpoint)
    except ApiConfigurationError as error:
        route_error(error)
        raise  # A replacement error callback returning cannot authorize a request.
    try:
        owner, kind = resolve_owner_record(company, source_doc, load_doc=load_saved)
        authorization = authorization_for_owner(CredentialOwner(
            company.name, owner.doctype, owner.name, kind, owner.values,
        ), route.required_credential)
    except CredentialConfigurationError as error:
        credential_error(error)
        raise
    return route, authorization
