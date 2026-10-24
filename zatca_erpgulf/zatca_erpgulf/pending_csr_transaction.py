"""Owned LOCAL pending-CSR save/review; no runtime/authority activation.

The existing service still stages on caller-owned transactions. This optional
server-only coordinator exclusively claims a fresh concrete provider lease,
rechecks exact source/backing/binding/ciphertext before ONE commit, closes, and
rechecks visible permissions/source before metadata disclosure. The optional
read-only review shares these guards but rolls back/closes without a save or
commit. Checks observe state; they do not lock permissions or prove an epoch.
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
REVIEW_DENIED_MESSAGE = (
    "You do not have permission to review pending ZATCA CSR storage. Keep the original sealed draft. "
    "No draft was stored or replaced, certificate activated or request sent by this review."
)
REVIEW_FAILED_MESSAGE = (
    "Pending ZATCA CSR storage review could not be confirmed. Keep the original sealed draft. "
    "Do not regenerate, store again or resend automatically. "
    "No draft was stored or replaced, certificate activated or request sent by this review."
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
        return self._run("save", company_abbr, source_identity, sealed)

    def observe(self, company_abbr, source_identity, original):
        """Read-only exact/absent/conflict observation on a NEW owned lease.

        After unknown save completion, retain the original and separately supply
        a fresh coordinator/lease. This call never invokes stage or commit and
        never authorizes a retry, activation or authority call. Fresh source/ACL
        drift fails closed; this is not historical binding discovery or proof of
        a previous commit's outcome. Rollback/close must finish before disclosure.
        """
        return self._run("observe", company_abbr, source_identity, original)

    def create_bound(self, company_abbr, source_identity, original):
        """Capture authorized current source state and commit ONE new pair.

        Uses no historical lookup; existing draft IDs are refused even if exact.
        This is initial local custody, not credential activation or issuance.
        Retain the original on every unknown outcome; do not replay this method.
        """
        return self._run("create_bound", company_abbr, source_identity, original)

    def _run(self, operation, company_abbr, source_identity, sealed):
        writing = operation in ("save", "create_bound")
        entered, claimed = False, False
        close_attempted, commit_returned, rollback_attempted = False, False, False
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
                    nonlocal close_attempted, commit_returned, rollback_attempted
                    if resources is not self._lease.resources:
                        raise PendingCSRTransactionError()
                    self._check_running()
                    locked_guard(resources.connection)
                    self._check_running()
                    if writing:
                        resources.connection.commit()
                        commit_returned = True
                    else:
                        rollback_attempted = True
                        resources.connection.rollback()
                    close_attempted = True
                    resources.connection.close()
                    current_guard()  # No SQL/new connection after closure.
                    self._check_running()
                    result = dict(report)
                    if writing:
                        result.update(state=("PENDING_CSR_BOUND_TRANSACTION_COMPLETED_OBSERVATION" if operation == "create_bound"
                                             else "PENDING_CSR_TRANSACTION_COMPLETED_OBSERVATION"), local_transaction_completed=True)
                    else:
                        result.update(state="PENDING_CSR_LOCAL_REVIEW_OBSERVATION", local_read_transaction_closed=True)
                    return result

                policy = SavedPendingCSRService(self._scope, self._lookup, acquire)
                if operation == "save":
                    result = policy._stage_for_commit(company_abbr, source_identity, sealed, complete)
                elif operation == "create_bound":
                    result = policy._create_bound_for_commit(company_abbr, source_identity, sealed, complete)
                else:
                    result = policy._observe_for_review(company_abbr, source_identity, sealed, complete)
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
                    if not commit_returned and not rollback_attempted:
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
        message = ((DENIED_MESSAGE if denied else FAILED_MESSAGE) if writing
                   else (REVIEW_DENIED_MESSAGE if denied else REVIEW_FAILED_MESSAGE))
        frappe.throw(_(message),
                     frappe.PermissionError if denied else frappe.ValidationError)
