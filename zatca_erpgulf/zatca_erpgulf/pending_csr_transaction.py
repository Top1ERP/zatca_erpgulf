"""Owned LOCAL pending-CSR save coordinator; no runtime/authority activation.

The existing service still stages on caller-owned transactions. This optional
server-only coordinator exclusively claims a fresh concrete provider lease,
rechecks exact source/backing/binding/ciphertext before ONE commit, closes, and
rechecks visible permissions/source before metadata disclosure. Checks observe
state; they do not lock permission tables or establish a credential epoch.
"""

import frappe
from frappe import _

from .credential_bundle_access import CredentialStorageScope
from .operation_messages import mute_operation_messages
from .pending_csr_access import SavedPendingCSRService
from .pending_csr_provider import UnixPendingCSRResourceProvider


DENIED_MESSAGE = (
    "You do not have permission to complete pending ZATCA CSR storage. "
    "Local storage may already have completed. Keep the original sealed draft and review its state. "
    "No certificate was activated or request sent."
)
FAILED_MESSAGE = (
    "Pending ZATCA CSR storage completion could not be confirmed. Keep the original sealed draft. "
    "Review the local transaction before retrying; do not regenerate or resend automatically. "
    "No certificate was activated or request sent."
)


class PendingCSRTransactionError(ValueError):
    """Static internal code only; never raw driver/source/key diagnostics."""

    def __init__(self):
        super().__init__("pending_csr_transaction_unconfirmed")


class PendingCSRStagingTransaction:
    """Single-use server boundary for a separately provisioned OWNED lease.

    No caller connection/factory, parent work, key generation/resealing, HTTP,
    installation or active-credential write. The caller independently retains
    its input even after denial, interruption or an unknown commit outcome.
    Never share this coordinator/lease across threads, RPC, queues or logs.
    """

    def __init__(self, scope, lookup_provider, lease):
        if (type(scope) is not CredentialStorageScope or not callable(lookup_provider)
                or type(lease) is not UnixPendingCSRResourceProvider):
            raise PendingCSRTransactionError()
        scope.__post_init__()
        if lease._binding.scope != scope:
            raise PendingCSRTransactionError()
        self._scope, self._lookup, self._lease = scope, lookup_provider, lease
        self._owner = object()
        self._used, self._running, self._poisoned = False, False, False

    def __repr__(self):
        return "PendingCSRStagingTransaction(<single-use protected local completion>)"

    def __reduce_ex__(self, protocol):
        raise PendingCSRTransactionError()

    def _check_running(self):
        if not self._running or self._poisoned:
            raise PendingCSRTransactionError()

    def save(self, company_abbr, source_identity, sealed):
        """One stage/guard/commit/close; no automatic replay or result guessing.

        Pre-commit failure rolls back/closes only this coordinator's newly owned
        handle. Failed commit may already be durable; cleanup is not compensation.
        A post-commit denial refuses success without undoing committed history.
        Cleanup tries both operations and preserves interruption priority.
        """
        entered, claimed = False, False
        close_attempted, commit_returned = False, False
        result, failure, cleanup_failure = None, None, None
        try:
            if self._used:
                if self._running:
                    self._poisoned = True
                raise PendingCSRTransactionError()
            self._used, self._running, entered = True, True, True
            self._lease._claim_for_transaction(self._owner)
            claimed = True
            with mute_operation_messages(frappe):
                def acquire(scope):
                    self._check_running()
                    return self._lease._acquire_for_transaction(scope, self._owner)

                def complete(resources, locked_guard, current_guard, report):
                    nonlocal close_attempted, commit_returned
                    if resources is not self._lease.resources:
                        raise PendingCSRTransactionError()
                    self._check_running()
                    locked_guard(resources.connection)
                    self._check_running()
                    resources.connection.commit()
                    commit_returned = True
                    close_attempted = True
                    resources.connection.close()
                    current_guard()  # No SQL/new connection after closure.
                    self._check_running()
                    result = dict(report)
                    result.update(state="PENDING_CSR_TRANSACTION_COMPLETED_OBSERVATION", local_transaction_completed=True)
                    return result

                policy = SavedPendingCSRService(self._scope, self._lookup, acquire)
                result = policy._stage_for_commit(company_abbr, source_identity, sealed, complete)
                self._check_running()
        except BaseException as error:
            failure = error
        finally:
            if entered:
                self._running = False
            # A pre-used/other-claimed lease is NOT ours to clean. Failed
            # acquisition already cleans its own newly created handle.
            if claimed and self._lease._state == "HANDED_OFF" and not close_attempted:
                connection = self._lease.resources.connection
                with mute_operation_messages(frappe):
                    if not commit_returned:
                        try:
                            connection.rollback()
                        except BaseException as error:
                            cleanup_failure = error
                    close_attempted = True
                    try:
                        connection.close()
                    except BaseException as error:
                        if cleanup_failure is None or (isinstance(cleanup_failure, Exception) and not isinstance(error, Exception)):
                            cleanup_failure = error
        if failure is None and cleanup_failure is None and result is not None:
            return result
        for error in (failure, cleanup_failure):
            if error is not None and not isinstance(error, Exception):
                raise error
        denied = isinstance(failure, frappe.PermissionError)
        failure = cleanup_failure = error = None  # Do not retain private child exceptions in public error locals.
        frappe.throw(_(DENIED_MESSAGE if denied else FAILED_MESSAGE),
                     frappe.PermissionError if denied else frappe.ValidationError)
