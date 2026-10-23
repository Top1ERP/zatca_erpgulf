"""Exact saved-source authorization for CSR/key/CSID writers.

Only identity is read from caller data. This loader performs ordinary row ACL
checks, not field-level custody, an epoch lock, consent or rotation activation.
The caller owns messages and all subsequent crypto/HTTP/save effects.
"""

import json
from dataclasses import dataclass, field

from zatca_erpgulf.zatca_erpgulf.permission_compat import saved_row_has_permission
from zatca_erpgulf.zatca_erpgulf.saved_form_source import saved_form_name


ACCESS_DENIED = "You do not have permission to generate CSR or CSID for these saved settings."
ACCESS_UNCONFIRMED = "Saved CSR/CSID source access could not be verified. Review permissions and Company settings."


class CredentialWriteAccessError(ValueError):
    """Static source/permission code; no record, payload or diagnostic detail."""

    def __init__(self, code):
        self.code = code if type(code) is str and code in ("source", "binding", "permission") else "source"
        super().__init__(self.code)


@dataclass(frozen=True, repr=False)
class CredentialWriteSource:
    target: object = field(repr=False)
    company: object = field(repr=False)


def load_credential_write_source(runtime, permission_engine, company_abbr, supplied):
    """Require READ+WRITE target and READ routing Company, with exact binding.

    A device writes itself, never its linked Company; Company WRITE is not
    required for that read-only routing dependency. No abbreviation-based source
    fallback, taxpayer bridge, client flags or ignore-permissions shortcut.
    """
    saved_form_name(company_abbr)
    if type(supplied) is str:
        if len(supplied) > 16384:
            raise CredentialWriteAccessError("source")
        supplied = json.loads(supplied)
    if not isinstance(supplied, dict):
        raise CredentialWriteAccessError("source")
    doctype = supplied.get("doctype")
    if type(doctype) is not str or doctype not in ("Company", "ZATCA Multiple Setting"):
        raise CredentialWriteAccessError("source")
    name = saved_form_name(supplied.get("name"))
    user = runtime.session.user
    if not user or user == "Guest":
        raise CredentialWriteAccessError("permission")

    def load(kind, identity, operations):
        saved_form_name(identity)
        doc = runtime.get_doc(kind, identity)
        if doc.doctype != kind or doc.name != identity:
            raise CredentialWriteAccessError("source")
        if not all(saved_row_has_permission(permission_engine, kind, operation, doc=doc, user=user)
                   for operation in operations):
            raise CredentialWriteAccessError("permission")
        return doc

    target = load(doctype, name, ("read", "write"))
    company = target if doctype == "Company" else load("Company", target.custom_linked_doctype, ("read",))
    if company.abbr != company_abbr:
        raise CredentialWriteAccessError("binding")
    return CredentialWriteSource(target, company)
