"""One owned Sales Invoice paid stage followed by return/internal guards.

The comparison stops before ordinary balance rounding. No saved controller,
cache update, accounting write, background job or authority request is run.
"""
from dataclasses import dataclass, field

from .calculation_payments import PaymentCalculationAcquisition, SavedPaymentCalculationRead, PaidAmountCalculation
from .calculation_outstanding_guard import (
    OutstandingGuardControlsAccess, SavedOutstandingGuardRead,
    OutstandingGuardDecision, OutstandingGuardError,
)


@dataclass(frozen=True)
class GuardedPaymentRequest:
    """Internal co-owned paid/guard inspection, not a runtime invoice action."""


@dataclass(frozen=True, repr=False)
class SavedGuardedPaymentRead:
    payment: SavedPaymentCalculationRead = field(repr=False)
    guard: SavedOutstandingGuardRead = field(repr=False)

    def __post_init__(self):
        try:
            if type(self.payment) is not SavedPaymentCalculationRead or type(self.guard) is not SavedOutstandingGuardRead:
                raise ValueError
            payment, guard = self.payment.pin(), self.guard.pin()
            if (guard.financial != payment.stage.numeric.financial
                    or guard.owner_document != payment.stage.owner_document
                    or guard.tables != payment.stage.numeric.tables
                    or guard.controls.financial != payment.controls.financial):
                raise ValueError
        except Exception:
            raise OutstandingGuardError("guarded_payment_context") from None
        object.__setattr__(self, "payment", payment)
        object.__setattr__(self, "guard", guard)

    def pin(self):
        result = SavedGuardedPaymentRead(self.payment, self.guard)
        if result != self:
            raise OutstandingGuardError("guarded_payment_context")
        return result

    def __repr__(self):return "<SavedGuardedPaymentRead co-owned entry evidence, NOT full settlement>"
    def __reduce__(self):raise TypeError("guarded_payment_context_not_serializable")


class GuardedPaymentAcquisition(PaymentCalculationAcquisition):
    """Add guard source binding on the paid stage's SAME root and SQL handle."""

    def __init__(self, policy, actor, invoice_name, doctype, major, *, guard_metadata, **dependencies):
        self.guards = None
        super().__init__(policy, actor, invoice_name, doctype, major, **dependencies)
        self.guards = OutstandingGuardControlsAccess(self.root, actor, guard_metadata)
        self.recheck_access()

    def recheck_access(self):
        super().recheck_access()
        if self.guards is not None:self.guards.recheck_access()

    def prepare_metadata(self):
        super().prepare_metadata()
        self.guards.prepare_metadata()
        self.recheck_access()

    def load_for_update(self, connection, financial):
        result = super().load_for_update(connection, financial)
        self.guards.load_for_update(connection, financial)
        return result

    def check_getters(self, observed):
        super().check_getters(observed)
        self.guards.check_getters()

    def require_metadata_unchanged(self):
        super().require_metadata_unchanged()
        self.guards.require_metadata_unchanged()
        self.recheck_access()

    def require_unchanged(self, observed):
        super().require_unchanged(observed)
        self.guards.require_unchanged()

    def build_result(self, financial, observed):
        return SavedGuardedPaymentRead(super().build_result(financial, observed), self.guards.build_result(financial, self.tables))


@dataclass(frozen=True, repr=False)
class GuardedOutstandingEntry:
    """Require the actual paid observation before the entry's reset/continuation.

    No balance rounding, POS Profile limit or redistribution is certified here.
    """
    source: SavedGuardedPaymentRead = field(repr=False)
    paid: PaidAmountCalculation = field(repr=False)
    decision: OutstandingGuardDecision = field(init=False, repr=False)

    def __post_init__(self):
        try:
            if type(self.source) is not SavedGuardedPaymentRead or type(self.paid) is not PaidAmountCalculation:
                raise ValueError
            source, paid = self.source.pin(), self.paid.pin()
            if paid.source != source.payment:
                raise ValueError
            decision = OutstandingGuardDecision.from_saved(source.guard)
        except Exception:
            raise OutstandingGuardError("guarded_outstanding_entry") from None
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "paid", paid)
        object.__setattr__(self, "decision", decision)

    def require_match(self, *, payments, totals, clear_payments, paid_setting_trace, paid_precision_trace, calls, reset, continues):
        try:
            if type(self.decision) is not OutstandingGuardDecision:
                raise ValueError
            pinned = GuardedOutstandingEntry(self.source, self.paid)
            if pinned != self:
                raise ValueError
            self.paid.require_match(payments=payments, totals=totals, clear_payments=clear_payments,
                setting_trace=paid_setting_trace, precision_trace=paid_precision_trace)
            self.decision.require_match(calls=calls, reset=reset, continues=continues)
        except Exception:
            raise OutstandingGuardError("guarded_outstanding_observation") from None

    def __repr__(self):return "<GuardedOutstandingEntry paid-before-guard comparison, NOT runtime execution>"
    def __reduce__(self):raise TypeError("guarded_outstanding_entry_not_serializable")
