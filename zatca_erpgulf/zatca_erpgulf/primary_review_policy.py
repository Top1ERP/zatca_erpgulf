"""Pure non-authorizing review of exact supplied primary capture/pair outcomes.

No lookup, ORM, SQL, file, clock, transport, resealing or retry action. This
classifies supplied observations ONLY; it cannot recover a lost response or
attest original custody/provenance. An authorized saved-source boundary must
gate any future operator disclosure. No runtime caller is installed here.
"""

from dataclasses import dataclass

from .primary_capture import CAPTURE_STATES, PrimaryCaptureResult
from .primary_receipt_reconciliation import PrimaryReconciliationResult


CAPTURE_REASONS = dict(zip(CAPTURE_STATES, (
    "REVIEW_START_AND_HOLD_UNCERTAINTY", "REVIEW_STOPPED_PREFLIGHT",
    "REVIEW_MISSING_RESPONSE_CUSTODY", "REVIEW_UNBOUND_RESPONSE",
    "REVIEW_UNSEALED_RESPONSE", "REVIEW_LOCAL_PAIR_UNCERTAINTY",
    "REVIEW_RECORDED_RESPONSE_NOT_ACCEPTANCE",
)))
PAIR_REASONS = {
    "PAIR_MISSING_OBSERVATION_NO_REPLAY": "REVIEW_MISSING_PAIR_NOT_NONDELIVERY",
    "PAIR_MATCHED_OBSERVATION_NO_REPLAY": "REVIEW_MATCHED_PAIR_NOT_ACCEPTANCE",
    "CUSTODY_ONLY_REVIEW_NO_REPLAY": "REVIEW_CUSTODY_ONLY_NO_REPAIR",
    "JOURNAL_ONLY_REVIEW_NO_REPLAY": "REVIEW_JOURNAL_ONLY_NO_REPAIR",
    "PAIR_CONFLICT_REVIEW_NO_REPLAY": "REVIEW_PAIR_CONFLICT_NO_ADOPTION",
    "PAIR_INSPECTION_UNCONFIRMED_NO_REPLAY": "REVIEW_LOCAL_PAIR_UNCERTAINTY",
    "PAIR_PERSISTENCE_UNCONFIRMED_NO_REPLAY": "REVIEW_LOCAL_PAIR_UNCERTAINTY",
    "PAIR_STORED_OBSERVATION_NO_REPLAY": "REVIEW_MATCHED_PAIR_NOT_ACCEPTANCE",
    "PAIR_ALREADY_STORED_OBSERVATION_NO_REPLAY": "REVIEW_MATCHED_PAIR_NOT_ACCEPTANCE",
}
_DISAGREEING_PAIRS = frozenset(("PAIR_MISSING_OBSERVATION_NO_REPLAY", "CUSTODY_ONLY_REVIEW_NO_REPLAY",
    "JOURNAL_ONLY_REVIEW_NO_REPLAY", "PAIR_CONFLICT_REVIEW_NO_REPLAY"))


class PrimaryReviewError(ValueError):
    """Static internal input error, never a raw body/identity/cipher exception."""


@dataclass(frozen=True, repr=False)
class PrimaryReviewObservation:
    """No protected input references and no action capability or acceptance."""

    capture_state: str
    pair_state: str | None = None

    def __post_init__(self):
        if (type(self.capture_state) is not str or self.capture_state not in CAPTURE_REASONS
                or self.pair_state is not None and (type(self.pair_state) is not str
                    or self.pair_state not in PAIR_REASONS or self.capture_state not in CAPTURE_STATES[5:])):
            raise PrimaryReviewError("primary_review_observation")

    def diagnostic_projection(self):
        self.__post_init__()
        return {"state": "PRIMARY_OUTCOME_REVIEW_NO_AUTOMATIC_ACTION",
            "review_reason": CAPTURE_REASONS[self.capture_state] if self.pair_state is None else PAIR_REASONS[self.pair_state],
            "capture_state": self.capture_state, "pair_state": self.pair_state,
            "response_supplied": self.capture_state in CAPTURE_STATES[3:],
            "sealed_input_supplied": self.capture_state in CAPTURE_STATES[5:],
            "local_history_disagreement": self.capture_state == CAPTURE_STATES[-1] and self.pair_state in _DISAGREEING_PAIRS,
            "provider_origin_verified": False, "historical_source_verified": False,
            "credential_epoch_verified": False, "transport_verified": False,
            "durable_custody_verified": False, "remote_receipt_verified": False,
            "remote_acceptance_verified": False, "automatic_follow_up_authorized": False,
            "identity_change_authorized": False, "hold_release_authorized": False,
            "raw_export_authorized": False, "dispatch_authorized": False, "replay_authorized": False}

    def __repr__(self):
        return "PrimaryReviewObservation(<non-authorizing local metadata>)"

    def __reduce_ex__(self, protocol):
        raise PrimaryReviewError("primary_review_not_pickleable")


def review_primary_outcome(captured, pair_observation=None):
    """Classify exact original inputs, never rebind/resequence a late response.

    An optional pair observation must refer to the SAME request/start and full
    original envelope; independently reloaded identical envelopes are allowed.
    No pair may be attached to a missing/unbound/unsealed capture. A local SQL
    match resolves only that observation, not remote acceptance or send policy.
    History disagreement flags a difference between supplied observations, NOT
    proof of deletion/corruption/chronology or permission to repair either half.
    """
    try:
        if type(captured) is not PrimaryCaptureResult:
            raise ValueError
        captured.__post_init__()
        if pair_observation is not None:
            if type(pair_observation) is not PrimaryReconciliationResult or captured.sealed is None:
                raise ValueError
            pair_observation.__post_init__()
            if (pair_observation.request != captured.request or pair_observation.sealed != captured.sealed):
                raise ValueError
        result = PrimaryReviewObservation(captured.state, None if pair_observation is None else pair_observation.state)
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        raise PrimaryReviewError("primary_review_input")
    return result
