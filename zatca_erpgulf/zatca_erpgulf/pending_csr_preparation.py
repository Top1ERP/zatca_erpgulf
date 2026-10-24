"""Protected one-shot preparation/sealing, not saved-source authorization.

Only the owned coordinator calls this after the shared saved-source/ACL/locked
state and unused-identity checks. No existing key is selected or replaced. The
caller must retain the exact encrypted result before any SQL staging attempt.
"""

from .csr_draft import prepare_csr_draft
from .pending_csr import _copy_context
from .pending_csr_access import PendingCSRAccessError, PendingCSRResources


def prepare_sealed_csr(resources, context, configuration):
    """One shared preparation and one seal; no retries, active writes or HTTP."""
    if type(resources) is not PendingCSRResources:
        raise PendingCSRAccessError()
    resources.__post_init__()
    declared = _copy_context(context)
    draft = prepare_csr_draft(declared, configuration)
    return resources.cipher.seal(draft, storage_namespace=resources.scope.storage_namespace,
                                key_id=resources.key_id)
