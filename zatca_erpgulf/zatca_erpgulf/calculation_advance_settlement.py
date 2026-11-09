"""Read-only advance-to-settlement inspection on one owned source graph.

Compose existing precision, aggregation, ceiling and outstanding kernels in the
primary controller order. This is not an installed controller, historical
advance search, allocation/GL validation, document writer or ZATCA operation.
"""

from dataclasses import dataclass, field

from .calculation_advance_rounding import AdvanceRoundingStageMixin
from .calculation_advance_limit import AdvanceLimitCalculation, CURRENT_FIELDS, settlement_limit_context
from .calculation_rounding_stage import RoundingStageAcquisition
from .calculation_settlement_access import SettlementAcquisition, SavedSettlementRead, SettlementAccessError
from .calculation_settlement_plan import SettlementPlanAcquisition, SettlementPlanRequest, SavedSettlementPlan, _saved_inputs
from .calculation_settlement_advances import aggregate_saved_advances


@dataclass(frozen=True, repr=False)
class AdvanceSettlementRequest:
    """Fixed internal inspection; labels do not allocate actual payment rows."""
    append_names: tuple = field(default=(None, None), repr=False)

    def __repr__(self): return "<AdvanceSettlementRequest internal comparison>"
    def __reduce__(self): raise TypeError("advance_settlement_request_not_serializable")


@dataclass(frozen=True, repr=False)
class SavedAdvanceSettlementPlan:
    """LIMIT_EXCEEDED or CALCULATED concerns arithmetic only, never acceptance."""
    source: SavedSettlementRead = field(repr=False)
    limit: AdvanceLimitCalculation = field(repr=False)
    settlement: SavedSettlementPlan | None = field(repr=False)
    status: str = field(init=False)
    calls: tuple = field(init=False)

    def __post_init__(self):
        try:
            if type(self.source) is not SavedSettlementRead or type(self.limit) is not AdvanceLimitCalculation:
                raise ValueError
            source, limit = self.source.pin(), self.limit.pin()
            if (limit.representation != "NUMERIC_FIXED" or limit.aggregate.rows.representation != "NUMERIC_FIXED"
                    or limit.aggregate.rows.table != "advances"
                    or settlement_limit_context(source, limit.source.advance) != limit.source):
                raise ValueError
            settlement = self.settlement
            calls = ["aggregate_advances", "check_advance_limit"]
            if limit.blocked:
                if settlement is not None or source.pos is not None: raise ValueError
                status = "LIMIT_EXCEEDED"
            else:
                if type(settlement) is not SavedSettlementPlan: raise ValueError
                settlement = settlement.pin()
                if settlement.source != source or settlement.advance != limit: raise ValueError
                if settlement.followup is None: raise ValueError
                if limit.reset_write_off: calls.append("reset_write_off")
                calls.extend(("calculate_outstanding_amount", "calculate_write_off_amount"))
                if settlement.second is not None: calls.append("calculate_outstanding_amount")
                status = "CALCULATED"
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid: raise SettlementAccessError("advance_settlement_plan")
        for name, value in (("source", source), ("limit", limit), ("settlement", settlement),
                ("status", status), ("calls", tuple(calls))):
            object.__setattr__(self, name, value)

    def pin(self):
        result = SavedAdvanceSettlementPlan(self.source, self.limit, self.settlement)
        if (result != self or type(self.status) is not str or type(self.calls) is not tuple
                or any(type(value) is not str for value in self.calls)):
            raise SettlementAccessError("advance_settlement_plan")
        return result

    def __repr__(self): return "<SavedAdvanceSettlementPlan arithmetic inspection, NOT advance/GL/ZATCA eligibility>"
    def __reduce__(self): raise TypeError("advance_settlement_plan_not_serializable")


class AdvanceSettlementAcquisition(AdvanceRoundingStageMixin, SettlementPlanAcquisition):
    """Share root, defaults, row evidence, callbacks, handle and final checks."""

    def __init__(self, policy, actor, invoice_name, doctype, major, request, *, child_metadata,
                 party_metadata=None, **dependencies):
        if type(request) is not AdvanceSettlementRequest:
            raise SettlementAccessError("advance_settlement_request")
        self._init_advance_dependencies(actor, child_metadata, party_metadata, dependencies)
        super().__init__(policy, actor, invoice_name, doctype, major,
            SettlementPlanRequest(request.append_names), **dependencies)
        self._bind_advance_access()

    def resolve_plan(self, connection, financial, observed):
        if self.plan is not None: raise SettlementAccessError("settlement_plan_already_resolved")
        source = SettlementAcquisition.build_result(self, financial, observed)
        union = RoundingStageAcquisition.build_result(self, financial, observed)
        advance = self.build_advance_result(union, financial)
        context = settlement_limit_context(source, advance)
        aggregate = aggregate_saved_advances(advance.stage, advance_context=advance)
        _, _, values = _saved_inputs(source)
        values = dict(values)
        limit = AdvanceLimitCalculation(context, aggregate, "NUMERIC_FIXED",
            tuple((name, values[name]) for name in CURRENT_FIELDS))
        settlement = None if limit.blocked else self._resolve_settlement(connection, financial, observed, limit)
        source = SettlementAcquisition.build_result(self, financial, observed)
        self.plan = SavedAdvanceSettlementPlan(source, limit, settlement)
        self.recheck_access()

    def build_result(self, financial, observed):
        if (type(self.plan) is not SavedAdvanceSettlementPlan
                or SettlementAcquisition.build_result(self, financial, observed) != self.plan.source):
            raise SettlementAccessError("advance_settlement_binding")
        return self.plan
