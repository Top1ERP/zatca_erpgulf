"""Uninstalled one-shot preparation inside an explicit caller-owned transaction.

No Frappe lookup, UUID allocation, signing implementation, transport, commit or
retry. Trusted server callbacks supply source/ACL/epoch checks, an exact builder
and protected original custody. Their True acknowledgments are declarations,
not durable-custody, cryptographic or enrollment proof. Never expose these
objects through RPC, logs or UI. Legacy generators do not use this module.
"""

from dataclasses import dataclass, field

from zatca_erpgulf.zatca_erpgulf.issuance_candidate import (
    PreparationContext, PreparedIssuanceCandidate, _canonical_uuid, _fingerprint,
)
from zatca_erpgulf.zatca_erpgulf.issuing_chain import (
    MAX_CHAIN_ICV, IssuingChainError, IssuingChainState, _check,
    record_generated_candidate, validate_chain_context,
)
from zatca_erpgulf.zatca_erpgulf.issuing_chain_repository import MariaDBIssuingChainRepository


@dataclass(frozen=True)
class PreparationTicket:
    """Pinned predecessor/source/epoch/route and caller-supplied canonical UUID.

    The UUID must come from reviewed server-owned identity custody. Supplying it
    here neither proves uniqueness nor permits regeneration after uncertainty.
    """

    predecessor: IssuingChainState = field(repr=False)
    context: PreparationContext = field(repr=False)
    invoice_uuid: str

    def __post_init__(self):
        if type(self.predecessor) is not IssuingChainState:
            raise IssuingChainError("chain_state")
        validate_chain_context(self.predecessor.registration, self.context)
        _check(self.invoice_uuid, "preparation_uuid", _canonical_uuid)
        if self.predecessor.last_icv == MAX_CHAIN_ICV:
            raise IssuingChainError("chain_counter_exhausted")

    @property
    def icv(self):
        return self.predecessor.last_icv + 1

    @property
    def previous_hash(self):
        return self.predecessor.previous_hash

    @property
    def key_sha256(self):
        return _fingerprint(self.context.scope.key_projection())

    def __reduce__(self):
        raise TypeError("preparation_ticket_not_serializable")


class IssuancePreparation:
    """One build at most; keep the exact returned original on every later failure.

    The caller must retain this handle/original on an unknown outcome, roll back
    the entire transaction on any error, and review through a fresh repository.
    A successful return means STAGED only: it does not commit or authorize HTTP.
    Callbacks must not commit, roll back, close or change the owned connection.
    Same-handle callback transaction tampering is not detected by this boundary.
    """

    def __init__(self, repository):
        if type(repository) is not MariaDBIssuingChainRepository:
            raise IssuingChainError("preparation_repository")
        self._repository = repository
        self._used = False
        self._invalidated = False
        self._ticket = None
        self._original = None

    def __repr__(self):
        return "<IssuancePreparation used=" + str(self._used) + ">"

    def __reduce__(self):
        raise TypeError("preparation_handle_not_serializable")

    @property
    def protected_ticket(self):
        """Internal custody/review only; never serialize to a user response."""
        return self._ticket

    @property
    def protected_original(self):
        """Exact builder result, including on later rejection; not replay authority."""
        return self._original

    def _check_source(self, guard):
        if self._invalidated:
            raise IssuingChainError("preparation_unusable")
        if guard(self._ticket) is not True:
            raise IssuingChainError("preparation_source_guard")
        # A callback may catch a rejected recursive prepare(). Do not let that
        # turn a poisoned outer operation back into a successful staging result.
        if self._invalidated:
            raise IssuingChainError("preparation_unusable")

    def prepare(self, registration, context, invoice_uuid, *, build, retain, guard):
        """Pin, check, build once, retain, recheck and atomically stage locally.

        guard(ticket) must explicitly recheck saved source/permissions/settings/
        epoch at every call. retain(ticket, candidate) must preserve exact bytes
        before acknowledging literal True. Neither callback is a network API.
        """
        if self._used:
            self._invalidated = True
            self._repository.invalidate()
            raise IssuingChainError("preparation_unusable")
        self._used = True
        try:
            if not all(callable(callback) for callback in (build, retain, guard)):
                raise IssuingChainError("preparation_callbacks")
            # Validate the supplied UUID and binding before acquiring SQL locks.
            _check(invoice_uuid, "preparation_uuid", _canonical_uuid)
            before = self._repository.begin_preparation(registration, context)
            self._ticket = PreparationTicket(before, context, invoice_uuid)
            self._check_source(guard)
            candidate = build(self._ticket)
            if type(candidate) is not PreparedIssuanceCandidate:
                raise IssuingChainError("preparation_candidate")
            self._original = candidate  # Preserve BEFORE any subsequent callback.
            self._check_source(guard)
            if candidate.context != context:
                raise IssuingChainError("preparation_context_drift")
            if candidate.artifact.uuid != invoice_uuid:
                raise IssuingChainError("preparation_uuid_drift")
            record_generated_candidate(before, candidate)
            if retain(self._ticket, candidate) is not True:
                raise IssuingChainError("preparation_custody")
            self._check_source(guard)
            after = self._repository.record(before, candidate)
            self._check_source(guard)
            return after
        except BaseException as error:
            self._invalidated = True
            self._repository.invalidate()
            if isinstance(error, IssuingChainError) or not isinstance(error, Exception):
                raise
            raise IssuingChainError("preparation_callback_failed") from None
