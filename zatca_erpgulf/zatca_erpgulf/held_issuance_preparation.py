"""Opt-in owned two-transaction local preparation, with NO authority transport.

Only explicit NEW, private connections from a trusted server factory are allowed;
never pass the borrowed Frappe request/worker connection. Tenant/ACL/credential
provenance and durable encrypted custody remain outer-adapter acceptance gates.
"""

from .compliance_capture import _owned_transaction
from .issuance_candidate import PreparedIssuanceCandidate, _canonical_uuid
from .issuing_chain import IssuingChainError, _check
from .preparation_hold import MariaDBPreparationHoldRepository


class HeldIssuancePreparation:
    """Commit/close a no-rebuild hold BEFORE invoking a supplied local builder.

    No callback is inferred, no exception releases a hold and no second call is
    allowed. Exact original and initial ticket remain protected on the handle
    for explicit local reconciliation after an unknown final commit. Pending
    holds without a retained original require operator review, not regeneration.
    """

    def __init__(self, connection_factory, storage_namespace):
        _check(storage_namespace, "chain_namespace", _canonical_uuid)
        if not callable(connection_factory):
            raise IssuingChainError("held_preparation_factory")
        self._factory, self._namespace = connection_factory, storage_namespace
        self._used, self._invalidated = False, False
        self._hold, self._original = None, None
        self._phase = "UNSTARTED"

    def __repr__(self):
        return "<HeldIssuancePreparation " + self._phase + ">"

    def __reduce__(self):
        raise TypeError("held_preparation_not_serializable")

    @property
    def protected_hold(self):
        return self._hold

    @property
    def protected_original(self):
        return self._original

    def _check_source(self, guard, ticket):
        if self._invalidated:
            raise IssuingChainError("held_preparation_unusable")
        if guard(ticket) is not True:
            raise IssuingChainError("preparation_source_guard")
        if self._invalidated:
            raise IssuingChainError("held_preparation_unusable")
        return True

    def prepare(self, registration, context, invoice_uuid, hold_id, *, build, retain, guard):
        """Own only preparation transactions; no caller parent work or HTTP here.

        The saved ERP source must already be authorized/stable by a trusted
        adapter. guard must recheck source/settings/ACL/epoch, not just existence.
        retain must acknowledge exact protected custody with literal True.
        """
        if self._used:
            self._invalidated = True
            raise IssuingChainError("held_preparation_unusable")
        self._used = True
        try:
            if not all(callable(callback) for callback in (build, retain, guard)):
                raise IssuingChainError("preparation_callbacks")
            _check(invoice_uuid, "preparation_uuid", _canonical_uuid)
            _check(hold_id, "preparation_hold_id", _canonical_uuid)
            def reserve(connection):
                self._hold = MariaDBPreparationHoldRepository(connection, self._namespace).reserve(
                    registration, context, invoice_uuid, hold_id,
                    guard=lambda ticket: self._check_source(guard, ticket))
                return self._hold
            self._phase = "RESERVATION_UNCONFIRMED_NO_BUILD"
            _owned_transaction(self._factory, reserve)  # Commit AND close before build.
            self._phase = "HELD_NO_REBUILD"
            ticket = self._hold.ticket
            self._check_source(guard, ticket)
            candidate = build(ticket)
            if type(candidate) is not PreparedIssuanceCandidate:
                raise IssuingChainError("preparation_candidate")
            self._original = candidate  # Keep exact bytes even if later checks fail.
            self._phase = "ORIGINAL_UNCONFIRMED_NO_REBUILD"
            self._check_source(guard, ticket)
            ticket.validate_candidate(candidate)
            if retain(ticket, candidate) is not True:
                raise IssuingChainError("preparation_custody")
            self._check_source(guard, ticket)
            def complete(connection):
                self._check_source(guard, ticket)
                _, after = MariaDBPreparationHoldRepository(connection, self._namespace).complete(self._hold, candidate)
                self._check_source(guard, ticket)
                return after
            after = _owned_transaction(self._factory, complete)
            self._phase = "ORIGINAL_STORED_LOCAL"
            return after
        except BaseException as error:
            self._invalidated = True
            if isinstance(error, IssuingChainError) or not isinstance(error, Exception):
                raise
            raise IssuingChainError("held_preparation_unconfirmed") from None
