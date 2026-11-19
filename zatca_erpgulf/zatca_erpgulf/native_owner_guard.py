"""Protect native owner identity/credentials from ordinary ORM form writes.

Owned services use their checked fixed SQL transaction. This guard neither
activates credentials nor grants rename/delete permission. Privileged raw SQL
and schema administration remain outside an application-controller boundary.
"""

import frappe
from frappe import _

from .credential_material import (
    NATIVE_OWNER_MARKER as MARKER, NATIVE_CREDENTIAL_FIELDS as PROTECTED_FIELDS,
    NATIVE_OWNER_TABLES as OWNER_TABLES,
)


REVIEW = 'Native ZATCA settings are owned by their onboarding and issuing services. Reload these settings before saving; changing credentials, issuer identity or chain state requires its reviewed service.'
LIFECYCLE_REVIEW = 'This owner has a native ZATCA unit. Rename or deletion requires a reviewed identity and history transition.'
FIELDS = (*PROTECTED_FIELDS,MARKER,'custom_csr_config','custom_pih','custom_zatca_icv_counter',
    'tax_id','custom_select','custom_production_url','custom_simulation_url','custom_sandbox_url',
    'custom_linked_doctype','custom__use_company_certificate__keys')


def reject_legacy_owner_credentials(runtime, target):
    from .native_onboarding import NativeOnboardingError, native_onboarding_selected
    if native_onboarding_selected(runtime,target):
        raise NativeOnboardingError('native_onboarding_service_required')


def _saved(doc):
    meta = frappe.get_meta(doc.doctype)
    if not meta.has_field(MARKER):
        return None
    fields = tuple(name for name in FIELDS if meta.has_field(name))
    rows = frappe.db.sql('SELECT '+','.join('`'+name+'`' for name in fields)+' FROM '+OWNER_TABLES[doc.doctype]+
        ' WHERE name=%s LOCK IN SHARE MODE NOWAIT',(doc.name,),as_dict=True)
    return rows[0] if rows else {}


def validate_native_owner(doc, event=None):
    if doc.doctype not in OWNER_TABLES:
        return
    failed = False
    try:
        saved = _saved(doc)
        if saved is None:
            return
        marker = saved.get(MARKER)
        if marker in (None,''):
            failed = doc.get(MARKER) not in (None,'')
        else:
            for name, value in saved.items():
                candidate = doc.get(name)
                if candidate != value and not (candidate in (None,'') and value in (None,'')):
                    failed = True
                    break
    except Exception:
        failed = True
    if failed:
        frappe.throw(_(REVIEW))


def protect_native_owner_lifecycle(doc, event=None, *args, **kwargs):
    if doc.doctype not in OWNER_TABLES:
        return
    failed = False
    try:
        saved = _saved(doc)
        failed = saved is not None and saved.get(MARKER) not in (None,'')
    except Exception:
        failed = True
    if failed:
        frappe.throw(_(LIFECYCLE_REVIEW))
