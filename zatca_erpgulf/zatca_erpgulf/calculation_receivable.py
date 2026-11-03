"""Read-only receivable suffix and automatic write-off comparisons.

Current amounts are explicit observations after upstream rounding/conversion.
Return/internal guards, POS Profile decisions and payment redistribution remain
separate gates. No accounting document, cache, transaction or request is written.
"""
from dataclasses import dataclass, field
import json

from .calculation_rounding_stage import RoundingStageAcquisition, RoundingStageRequest, SavedRoundingStageRead, pin_stage, require_call_trace
from .calculation_write_off_access import WriteOffStageMixin, WriteOffInputsAcquisition, resolve_write_precision, AUTO, WRITE_FIELDS
from .write_off_source import LockedWriteOffRead, pin_write_off
from .owner_currency_source import LockedOwnerCurrencyRead, pin_owner_currency
from .financial_source_observation import _scalar
from .financial_numeric_view import _native_cells, _expected
from .calculated_totals import _input_tag
from .calculation_field_rounding_access import _result_tag
from .calculation_precision import FieldPrecisionResolution
from .field_rounding import round_field_value

STAGE_FIELDS = ("grand_total", "base_grand_total", "outstanding_amount")
PAYABLE_FIELDS = ("grand_total", "rounded_total", "base_grand_total", "base_rounded_total",
    "total_advance", "write_off_amount", "base_write_off_amount")
BALANCE_FIELDS = ("paid_amount", "base_paid_amount", "change_amount", "base_change_amount")


class ReceivableCalculationError(ValueError):
    """Static English diagnostics without protected amounts or driver details."""


@dataclass(frozen=True)
class ReceivableCalculationRequest:
    """Internal bounded inspection, never a runtime submission operation."""


@dataclass(frozen=True, repr=False)
class SavedReceivableRead:
    """Co-owned native side fields, party currency and scoped precision caches."""
    stage: SavedRoundingStageRead = field(repr=False)
    write_off: LockedWriteOffRead = field(repr=False)
    party: LockedOwnerCurrencyRead = field(repr=False)
    caches: tuple = field(repr=False)
    return_tag: tuple = field(repr=False)
    precisions: tuple = field(init=False, repr=False)
    foreign: bool = field(init=False)
    is_return: bool = field(init=False)

    def __post_init__(self):
        try:
            stage = pin_stage(self.stage)
            write, party = pin_write_off(self.write_off), pin_owner_currency(self.party)
            native = stage.numeric.view.financial
            root_meta = next(row for row in native.metadata if row.applied.name == native.financial.doctype)
            if (stage.targets != tuple(("header", native.financial.name, name) for name in STAGE_FIELDS)
                    or stage.do_not_round_fields is not None or write.financial != native
                    or party.name != native.financial.name or party.metadata.applied.name != native.financial.doctype
                    or party.revision != stage.numeric.financial.context.settings.sources[1].revision
                    or json.loads(party.metadata._payload)["doctype"] != json.loads(root_meta._payload)["doctype"]
                    or type(self.caches) is not tuple or len(self.caches) != 2):
                raise ValueError
            for row, name in zip(self.caches, WRITE_FIELDS):
                if type(row) is not tuple or len(row) != 3 or type(row[0]) is not str or row[0] != name:
                    raise ValueError
            resolutions = tuple((name, resolve_write_precision(stage, write, name, cache, currency)) for name, cache, currency in self.caches)
            header = dict(json.loads(native.financial._payload)["header"])
            tag = tuple(header["is_return"])
            if type(self.return_tag) is not tuple or self.return_tag != tag or tag not in (("null",), ("int", "0"), ("int", "1")):
                raise ValueError
            foreign = header["currency"] != ["str", party.currency]
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise ReceivableCalculationError("receivable_context")
        for name, value in (("stage", stage), ("write_off", write), ("party", party),
                ("precisions", resolutions), ("foreign", foreign), ("is_return", tag == ("int", "1"))):
            object.__setattr__(self, name, value)

    def pin(self):
        pinned = SavedReceivableRead(self.stage, self.write_off, self.party, self.caches, self.return_tag)
        if (pinned != self or type(self.foreign) is not bool or type(self.is_return) is not bool
                or type(self.precisions) is not tuple or len(self.precisions) != 2
                or any(type(row) is not tuple or len(row) != 2 or type(row[0]) is not str
                    or type(row[1]) is not FieldPrecisionResolution or type(row[1].precision) is not int for row in self.precisions)):
            raise ReceivableCalculationError("receivable_context")
        return pinned

    def __repr__(self):
        return "<SavedReceivableRead protected suffix context, NOT accounting execution proof>"

    def __reduce__(self):
        raise TypeError("receivable_context_not_serializable")


class ReceivableAcquisition(WriteOffStageMixin, RoundingStageAcquisition):
    """One owned root stage with shared party/write-off evidence and caches."""

    def __init__(self, policy, actor, invoice_name, doctype, major, *, write_off_metadata, **dependencies):
        self.write_inputs, self.return_tag = None, None
        super().__init__(policy, actor, invoice_name, doctype, RoundingStageRequest(STAGE_FIELDS), major, **dependencies)
        self.write_inputs = WriteOffInputsAcquisition(self.root, actor, write_off_metadata, dependencies["owner_metadata"], WRITE_FIELDS)
        self.return_tag = tuple(_scalar(self.root.document.get("is_return")))
        self.recheck_access()

    def recheck_access(self):
        super().recheck_access()
        if self.return_tag is not None and any(tuple(_scalar(doc.get("is_return"))) != self.return_tag for doc in
                (self.root.document, self.root._parent_load(self.root._doctype, self.root._name))):
            raise ReceivableCalculationError("receivable_return_changed")

    def build_result(self, financial, observed):
        inputs = self.write_inputs
        caches = tuple((name, inputs.precision_cache(name), inputs.field_currency_cache(name)) for name in WRITE_FIELDS)
        return SavedReceivableRead(super().build_result(financial, observed), inputs.native, inputs.owner.native, caches, self.return_tag)


def _values(source, values, names, representation):
    if (type(representation) is not str or representation not in ("NUMERIC_FIXED", "CALCULATED")
            or type(values) is not tuple or len(values) != len(names)):
        raise ValueError
    native = source.stage.numeric.view.financial
    cells = {cell[:3]: cell for cell in _native_cells(native)}
    side = dict(json.loads(source.write_off._payload)["fields"])
    for row, name in zip(values, names):
        if type(row) is not tuple or len(row) != 2 or type(row[0]) is not str or row[0] != name:
            raise ValueError
        value = row[1]
        if name == AUTO:
            if value is not None and (type(value) is not int or value not in (0, 1)):
                raise ValueError
            if representation == "NUMERIC_FIXED":
                source.write_off.require_saved_check_match({AUTO: value})
            continue
        else:
            tag = _input_tag(value, nullable=True)
        if representation == "NUMERIC_FIXED":
            if name in WRITE_FIELDS:
                expected = _expected(side[name], representation, "Currency")
            else:
                cell = cells["header", native.financial.name, name]
                expected = _expected(cell[4], representation, cell[3])
            if tag != expected:
                raise ValueError
    return dict(values)


def _flt(source, value, precision=None):
    method = source.stage.method
    return round_field_value(value, precision=precision, method=method.method, erp_major=method.erp_major)


def _require_results(actual, expected):
    if type(actual) is not tuple or len(actual) != len(expected):
        raise ValueError
    for a, b in zip(actual, expected):
        if type(a) is not tuple or len(a) != 2 or type(a[0]) is not str or a[0] != b[0] or _result_tag(a[1]) != _result_tag(b[1]):
            raise ValueError


@dataclass(frozen=True, repr=False)
class PayableAmountCalculation:
    """Compare the amount to pay AFTER upstream rounding/base conversion.

    Advance is already expressed in party currency. This suffix does not
    convert it again or certify its earlier allocation/aggregation.
    """
    source: SavedReceivableRead = field(repr=False)
    representation: str
    values: tuple = field(repr=False)
    amount: int | float = field(init=False, repr=False)
    precision_trace: tuple = field(init=False, repr=False)
    setting_count: int = field(init=False, repr=False)

    def __post_init__(self):
        try:
            if type(self.source) is not SavedReceivableRead:
                raise ValueError
            source = self.source.pin()
            if source.stage.numeric.view.financial.financial.doctype != "Sales Invoice":
                raise ValueError
            values = _values(source, self.values, PAYABLE_FIELDS, self.representation)
            selected = "base_grand_total" if source.foreign else "grand_total"
            precision = next(proof.precision.precision for proof in source.stage.fields if proof.target[2] == selected)
            if source.foreign:
                grand = values["base_rounded_total"] or values["base_grand_total"]
                amount = _flt(source, _flt(source, grand, precision) - values["total_advance"] - _flt(source, values["base_write_off_amount"]), precision)
                trace = ((selected, precision),) * 2
                lookups = 1 + int(grand is not None)
            else:
                grand = values["rounded_total"] or values["grand_total"]
                amount = _flt(source, grand - values["total_advance"] - _flt(source, values["write_off_amount"]), precision)
                trace = ((selected, precision),)
                lookups = 1
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise ReceivableCalculationError("receivable_payable")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "amount", amount)
        object.__setattr__(self, "precision_trace", trace)
        object.__setattr__(self, "setting_count", lookups)

    def pin(self):
        pinned = PayableAmountCalculation(self.source, self.representation, self.values)
        if pinned != self or type(self.setting_count) is not int or _result_tag(pinned.amount) != _result_tag(self.amount):
            raise ReceivableCalculationError("receivable_payable")
        try:
            require_call_trace(None, (), self.precision_trace, pinned.precision_trace, 0)
        except Exception:
            raise ReceivableCalculationError("receivable_payable") from None
        return pinned

    def require_match(self, *, amount, setting_trace, precision_trace):
        try:
            pinned = self.pin()
            if _result_tag(amount) != _result_tag(pinned.amount):
                raise ValueError
            require_call_trace(pinned.source.stage.method.rounding.value, setting_trace, precision_trace, pinned.precision_trace, pinned.setting_count)
        except Exception:
            raise ReceivableCalculationError("receivable_payable_observation") from None

    def __repr__(self):
        return "<PayableAmountCalculation protected suffix, NOT advance/settlement approval>"

    def __reduce__(self):
        raise TypeError("receivable_payable_not_serializable")


@dataclass(frozen=True, repr=False)
class OutstandingAmountCalculation:
    """Use explicit paid/change observations after their preceding stages."""
    payable: PayableAmountCalculation = field(repr=False)
    representation: str
    values: tuple = field(repr=False)
    amount: int | float = field(init=False, repr=False)

    def __post_init__(self):
        try:
            if type(self.payable) is not PayableAmountCalculation:
                raise ValueError
            payable = self.payable.pin()
            source = payable.source
            values = _values(source, self.values, BALANCE_FIELDS, self.representation)
            paid = values["base_paid_amount" if source.foreign else "paid_amount"]
            change = 0 if source.is_return else values["base_change_amount" if source.foreign else "change_amount"]
            precision = source.stage.fields[2].precision.precision
            amount = _flt(source, payable.amount - _flt(source, paid) + _flt(source, change), precision)
        except Exception:
            raise ReceivableCalculationError("receivable_outstanding") from None
        object.__setattr__(self, "payable", payable)
        object.__setattr__(self, "amount", amount)

    def require_match(self, *, amount, setting_trace, precision_trace):
        try:
            pinned = OutstandingAmountCalculation(self.payable, self.representation, self.values)
            if pinned != self or _result_tag(self.amount) != _result_tag(pinned.amount) or _result_tag(amount) != _result_tag(pinned.amount):
                raise ValueError
            source = pinned.payable.source
            trace = (("outstanding_amount", source.stage.fields[2].precision.precision),)
            require_call_trace(source.stage.method.rounding.value, setting_trace, precision_trace, trace, 1)
        except Exception:
            raise ReceivableCalculationError("receivable_outstanding_observation") from None

    def __repr__(self):
        return "<OutstandingAmountCalculation protected suffix, NOT complete controller execution>"

    def __reduce__(self):
        raise TypeError("receivable_outstanding_not_serializable")


@dataclass(frozen=True, repr=False)
class WriteOffCalculation:
    """Plan rounded write-off/base write-off, then ONE outstanding call.

    CALCULATED permits an explicitly observed flag set by earlier POS logic;
    it does not attest that POS Profile's limit decision or recurse here.
    """
    source: SavedReceivableRead = field(repr=False)
    representation: str
    values: tuple = field(repr=False)
    amounts: tuple = field(init=False, repr=False)
    recalculate: bool = field(init=False)

    def __post_init__(self):
        try:
            if type(self.source) is not SavedReceivableRead:
                raise ValueError
            source = self.source.pin()
            values = _values(source, self.values, (AUTO, "outstanding_amount", "conversion_rate"), self.representation)
            recalculate = bool(values[AUTO])
            amounts = ()
            if recalculate:
                precisions = dict(source.precisions)
                amount = _flt(source, values["outstanding_amount"], precisions[WRITE_FIELDS[0]].precision)
                base = _flt(source, amount * values["conversion_rate"], precisions[WRITE_FIELDS[1]].precision)
                amounts = tuple(zip(WRITE_FIELDS, (amount, base)))
        except Exception:
            raise ReceivableCalculationError("receivable_write_off") from None
        for name, value in (("source", source), ("amounts", amounts), ("recalculate", recalculate)):
            object.__setattr__(self, name, value)

    def require_match(self, *, amounts, recalculate, setting_trace, precision_trace):
        try:
            pinned = WriteOffCalculation(self.source, self.representation, self.values)
            _require_results(self.amounts, pinned.amounts)
            _require_results(amounts, pinned.amounts)
            if pinned != self or type(self.recalculate) is not bool or type(recalculate) is not bool or recalculate != pinned.recalculate:
                raise ValueError
            trace = tuple((name, proof.precision) for name, proof in pinned.source.precisions) if recalculate else ()
            count = 1 + int(dict(pinned.values)["outstanding_amount"] is not None) if recalculate else 0
            require_call_trace(pinned.source.stage.method.rounding.value, setting_trace, precision_trace, trace, count)
        except Exception:
            raise ReceivableCalculationError("receivable_write_off_observation") from None

    def __repr__(self):
        return "<WriteOffCalculation protected plan, NOT GL write or recursion proof>"

    def __reduce__(self):
        raise TypeError("receivable_write_off_not_serializable")
