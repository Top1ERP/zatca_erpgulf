"""Compare the paid recalculation after a proposed POS-return row replacement.

No new saved-row identity is invented. The observed append name is explicit;
the default-row query result/party currency remain supplied, partial evidence.
"""
from dataclasses import dataclass, field
import json

from .calculation_payments import PaidAmountCalculation, _paid_values, _exact_values, PAID_FIELDS
from .calculation_pos_adjustments import DefaultMopRedistributionCalculation, PosTailCalculation, PosAdjustmentError
from .calculation_rounding_stage import require_call_trace
from .financial_source_observation import _name


@dataclass(frozen=True, repr=False)
class PosReturnPaidCalculation:
    paid_before: PaidAmountCalculation = field(repr=False)
    tail: PosTailCalculation = field(repr=False)
    redistribution: DefaultMopRedistributionCalculation = field(repr=False)
    appended_row_name: str | None = field(repr=False)
    payments: tuple = field(init=False,repr=False)
    totals: tuple = field(init=False,repr=False)

    def __post_init__(self):
        try:
            if (type(self.paid_before) is not PaidAmountCalculation or type(self.redistribution) is not DefaultMopRedistributionCalculation
                    or type(self.tail) is not PosTailCalculation):
                raise ValueError
            paid=self.paid_before.pin();redistribution=self.redistribution.pin();tail=self.tail.pin()
            source=paid.source;flags=dict(source.controls.normalized_checks)
            if not flags['is_pos'] or not flags['is_return'] or paid.clear_payments:raise ValueError
            if not tail.redistributes or tail.inputs.doctype!='Sales Invoice':raise ValueError
            _exact_values(redistribution.rows,paid.payments)
            header=dict(json.loads(source.stage.numeric.view.financial.financial._payload)['header'])
            if header['currency']!=['str',redistribution.currency]:raise ValueError
            profile=header.get('pos_profile',['absent'])
            expected=None if profile in (['null'],['absent']) else profile[1]
            if redistribution.pos_profile!=expected or type(redistribution.pos_profile) is not type(expected):raise ValueError
            if tail.inputs.pos_profile!=expected or type(tail.inputs.pos_profile) is not type(expected):raise ValueError
            if redistribution.replaces:
                _name(self.appended_row_name)
                if (any(name==self.appended_row_name for name,_,_ in redistribution.rows)
                        or any(name==self.appended_row_name for name,_ in source.payment_types)):raise ValueError
                rows=((self.appended_row_name,redistribution.pending),)
            else:
                if self.appended_row_name is not None:raise ValueError
                rows=tuple((name,amount) for name,amount,_ in paid.payments)
            payments,totals,clear=_paid_values(source,dict(paid.headers),rows)
            if clear:raise ValueError
        except Exception:
            raise PosAdjustmentError('pos_return_paid') from None
        for name,value in (('paid_before',paid),('tail',tail),('redistribution',redistribution),('payments',payments),('totals',totals)):
            object.__setattr__(self,name,value)

    def pin(self):
        result=PosReturnPaidCalculation(self.paid_before,self.tail,self.redistribution,self.appended_row_name)
        _exact_values(self.payments,result.payments);_exact_values(self.totals,result.totals)
        if result!=self:raise PosAdjustmentError('pos_return_paid')
        return result

    def require_match(self,*,payments,totals,setting_trace,precision_trace):
        try:
            pinned=self.pin()
            _exact_values(payments,pinned.payments);_exact_values(totals,pinned.totals)
            if pinned!=self:raise ValueError
            source=pinned.paid_before.source
            trace=tuple((name,proof.precision.precision) for name,proof in zip(PAID_FIELDS,source.stage.fields[:2]))
            require_call_trace(source.stage.method.rounding.value,setting_trace,precision_trace,trace,2)
        except Exception:
            raise PosAdjustmentError('pos_return_paid_observation') from None

    def __repr__(self):return '<PosReturnPaidCalculation derived-row comparison, NOT saved payment authority>'
    def __reduce__(self):raise TypeError('pos_return_paid_not_serializable')
