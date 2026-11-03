"""Read-only base-controller paid/change comparisons on one owned source.

Sales Invoice, including its POS flag, is distinct from standalone POS Invoice.
No payment table, amount, cache, document, GL entry or authority request is written.
"""
from dataclasses import dataclass, field
import json

from .calculation_rounding_stage import RoundingStageAcquisition, RoundingStageRequest, SavedRoundingStageRead, pin_stage, require_call_trace
from .calculation_child_format_access import require_field_read
from .payment_controls_source import LockedPaymentControlsRead, MariaDBPaymentControlsReader, pin_payment_controls
from .source_metadata import PAYMENT_CONTROLS_PROFILE, project_source_metadata, _pin_metadata
from .invoice_rounding_source import _meta
from .financial_source_observation import _scalar
from .financial_numeric_view import _native_cells, _expected, FIXED_TYPES
from .calculated_totals import _input_tag
from .calculation_field_rounding_access import _result_tag
from .field_rounding import round_field_value

PAID_FIELDS = ("paid_amount", "base_paid_amount")
CHANGE_FIELDS = ("change_amount", "base_change_amount")
STAGE_FIELDS = (*PAID_FIELDS, *CHANGE_FIELDS)


class PaymentCalculationError(ValueError):
    """Static English diagnostics, without invoice or payment values."""


@dataclass(frozen=True)
class PaymentCalculationRequest:
    """Internal fixed base-controller inspection, never a runtime writer."""


@dataclass(frozen=True, repr=False)
class SavedPaymentCalculationRead:
    """Co-owned saved amounts, controls, payment categories and precisions."""
    stage: SavedRoundingStageRead = field(repr=False)
    controls: LockedPaymentControlsRead = field(repr=False)
    payment_types: tuple = field(repr=False)

    def __post_init__(self):
        try:
            stage, controls = pin_stage(self.stage), pin_payment_controls(self.controls)
            native = stage.numeric.view.financial
            if (native.financial.doctype != "Sales Invoice" or controls.financial != native
                    or stage.targets != tuple(("header", native.financial.name, name) for name in STAGE_FIELDS)
                    or stage.do_not_round_fields is not None):
                raise ValueError
            table = dict(json.loads(native.financial._payload)["tables"])["payments"]
            if type(table) is not dict:
                raise ValueError
            meta = next(row.applied for row in native.metadata if row.applied.name == table["doctype"])
            if meta.get_field("amount") is None or meta.get_field("amount").fieldtype not in FIXED_TYPES:
                raise ValueError
            expected = tuple((row[0], tuple(dict(row[2]).get("type", ["absent"]))) for row in table["rows"])
            expected = tuple((name, ("null",) if tag == ("absent",) else tag) for name, tag in expected)
            if (type(self.payment_types) is not tuple or self.payment_types != expected
                    or any(type(row) is not tuple or type(row[0]) is not str or type(row[1]) is not tuple
                        or row[1] != ("null",) and (len(row[1]) != 2 or row[1][0] != "str" or type(row[1][1]) is not str)
                        for row in self.payment_types)):
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PaymentCalculationError("payment_calculation_context")
        object.__setattr__(self, "stage", stage)
        object.__setattr__(self, "controls", controls)

    def pin(self):
        pinned = SavedPaymentCalculationRead(self.stage, self.controls, self.payment_types)
        if pinned != self:
            raise PaymentCalculationError("payment_calculation_context")
        return pinned

    def __repr__(self):
        return "<SavedPaymentCalculationRead protected base-controller context, NOT execution proof>"

    def __reduce__(self):
        raise TypeError("payment_calculation_not_serializable")


class PaymentCalculationAcquisition(RoundingStageAcquisition):
    """Share graph/method/format/cleanup paths; add only bound native controls."""
    def __init__(self, policy, actor, invoice_name, doctype, major, *, controls_metadata, **dependencies):
        if doctype != "Sales Invoice" or not callable(controls_metadata):
            raise PaymentCalculationError("payment_calculation_dependencies")
        self.definition = None
        self._controls_metadata, self.actor = controls_metadata, actor
        super().__init__(policy, actor, invoice_name, doctype, RoundingStageRequest(STAGE_FIELDS), major, **dependencies)
        if "payments" not in dict(self.root.tables):
            raise PaymentCalculationError("payment_calculation_table")
        self.definition, self.levels, self.values = self._observe(self.root.document)
        self.payment_types = self._observe_types(original=True)
        self.recheck_access()

    def _observe_types(self, *, original):
        """Cash decisions require categorical getters as well as numeric rows.

        Bind original/direct/fresh child reads and parent references. The shared
        graph owns their identities, membership, revisions and READ checks.
        """
        access = dict(self.root._tables)["payments"]
        parent = self.root.document if original else self.root._parent_load(self.root._doctype, self.root._name)
        docs = access.documents if original else tuple(access._load(access.childtype, row.name) for row in access.rows)
        refs = access.references if original else parent.get("payments")
        if len(docs) != len(access.rows) or len(refs) != len(docs):
            raise PaymentCalculationError("payment_calculation_type_membership")
        result = []
        for doc, ref, row in zip(docs, refs, access.rows):
            tag = tuple(_scalar(doc.get("type")))
            if tag != tuple(_scalar(ref.get("type"))) or (tag != ("null",) and
                    (len(tag) != 2 or tag[0] != "str" or type(tag[1]) is not str)):
                raise PaymentCalculationError("payment_calculation_type_getter")
            result.append((row.name, tag))
        return tuple(result)

    def _observe(self, doc):
        meta = _meta(project_source_metadata(doc.meta, base_fields={}, profile=PAYMENT_CONTROLS_PROFILE),
            profile=PAYMENT_CONTROLS_PROFILE, fields=LockedPaymentControlsRead.FIELDS, checks=LockedPaymentControlsRead.CHECKS)
        levels = tuple(require_field_read(doc, name, self.actor, self.root._policy._dependencies()[0], self.root._policy.DENIED_MESSAGE)
            if meta.has_field(name) else None for name in LockedPaymentControlsRead.FIELDS)
        values = tuple((name, tuple(_scalar(doc.get(name)))) for name in LockedPaymentControlsRead.FIELDS)
        if any(not meta.has_field(name) and tag != ("null",) for name, tag in values):
            raise PaymentCalculationError("payment_calculation_absent_getter")
        return meta, levels, values

    def recheck_access(self):
        super().recheck_access()
        if self.definition is not None:
            expected = self.definition, self.levels, self.values
            if (self._observe(self.root.document) != expected
                    or self._observe(self.root._parent_load(self.root._doctype, self.root._name)) != expected
                    or self._observe_types(original=True) != self.payment_types
                    or self._observe_types(original=False) != self.payment_types):
                raise PaymentCalculationError("payment_calculation_getter_changed")

    def _applied(self):
        supplied = self._controls_metadata(self.root._policy._scope, (self.root._doctype,))
        if type(supplied) is not dict or set(supplied) != {self.root._doctype} or _pin_metadata(supplied[self.root._doctype]) != self.definition:
            raise PaymentCalculationError("payment_calculation_metadata")
        return self.definition

    def prepare_metadata(self):
        super().prepare_metadata()
        self._applied()
        self.recheck_access()

    def load_for_update(self, connection, financial):
        result = super().load_for_update(connection, financial)
        self.reader = MariaDBPaymentControlsReader(connection)
        self.native_controls = self.reader.load_for_update(financial, applied_metadata=self.definition)
        self._check_controls()
        return result

    def _check_controls(self):
        values = dict(self.values)
        self.native_controls.require_saved_check_match({name: self.root.document.get(name) for name in self.native_controls.CHECKS})
        expected = dict(json.loads(self.native_controls._payload)["fields"])["loyalty_amount"]
        if list(values["loyalty_amount"]) != expected and not (expected == ["absent"] and values["loyalty_amount"] == ("null",)):
            raise PaymentCalculationError("payment_calculation_native_loyalty")
        self.recheck_access()

    def check_getters(self, observed):
        super().check_getters(observed)
        self._check_controls()

    def require_metadata_unchanged(self):
        super().require_metadata_unchanged()
        self._applied()
        self.recheck_access()

    def require_unchanged(self, observed):
        super().require_unchanged(observed)
        self.reader.require_unchanged(self.native_controls)
        self._check_controls()

    def build_result(self, financial, observed):
        return SavedPaymentCalculationRead(super().build_result(financial, observed), self.native_controls, self.payment_types)


def _header_inputs(source, values, names, representation):
    if (type(representation) is not str or representation not in ("NUMERIC_FIXED", "CALCULATED")
            or type(values) is not tuple or len(values) != len(names)):
        raise ValueError
    native = source.stage.numeric.view.financial
    cells = {cell[:3]: cell for cell in _native_cells(native)}
    controls = dict(json.loads(source.controls._payload)["fields"])
    for entry, name in zip(values, names):
        if type(entry) is not tuple or len(entry) != 2 or type(entry[0]) is not str or entry[0] != name:
            raise ValueError
        tag = _input_tag(entry[1], nullable=True)
        if representation == "NUMERIC_FIXED":
            if name == "loyalty_amount":
                original = controls[name]
                expected = ["null"] if original == ["absent"] else _expected(original, "NUMERIC_FIXED", "Currency")
            else:
                cell = cells["header", native.financial.name, name]
                expected = _expected(cell[4], "NUMERIC_FIXED", cell[3])
            if tag != expected:
                raise ValueError
    return dict(values)


def _payment_rows(source, rows, representation):
    native = source.stage.numeric.view.financial
    table = dict(json.loads(native.financial._payload)["tables"])["payments"]
    if type(rows) is not tuple or len(rows) != len(table["rows"]):
        raise ValueError
    cells = {cell[:3]: cell for cell in _native_cells(native)}
    for entry, saved in zip(rows, table["rows"]):
        if type(entry) is not tuple or len(entry) != 2 or type(entry[0]) is not str or entry[0] != saved[0]:
            raise ValueError
        tag = _input_tag(entry[1], nullable=True)
        if representation == "NUMERIC_FIXED":
            cell = cells["payments", saved[0], "amount"]
            if tag != _expected(cell[4], representation, cell[3]):
                raise ValueError


def _flt(source, value, precision=None):
    method = source.stage.method
    return round_field_value(value, precision=precision, method=method.method, erp_major=method.erp_major)


def _exact_values(actual, expected):
    if type(actual) is not tuple or len(actual) != len(expected):
        raise ValueError
    for a, b in zip(actual, expected):
        if type(a) is not tuple or len(a) != len(b) or type(a[0]) is not str or a[0] != b[0]:
            raise ValueError
        if any(_result_tag(x) != _result_tag(y) for x, y in zip(a[1:], b[1:])):
            raise ValueError


@dataclass(frozen=True, repr=False)
class PaidAmountCalculation:
    """Compare paid totals and planned row effects without applying them.

    Loyalty is company currency. Payment rows are converted without field
    precision; only the final invoice/base totals consume their own precision.
    """
    source: SavedPaymentCalculationRead = field(repr=False)
    representation: str
    headers: tuple = field(repr=False)
    rows: tuple = field(repr=False)
    payments: tuple = field(init=False, repr=False)
    totals: tuple = field(init=False, repr=False)
    clear_payments: bool = field(init=False)

    def __post_init__(self):
        try:
            if type(self.source) is not SavedPaymentCalculationRead:
                raise ValueError
            source = self.source.pin()
            headers = _header_inputs(source, self.headers, ("conversion_rate", "loyalty_amount"), self.representation)
            _payment_rows(source, self.rows, self.representation)
            flags = dict(source.controls.normalized_checks)
            paid = base = 0.0
            payments = []
            if flags["is_pos"]:
                for name, amount in self.rows:
                    fixed = _flt(source, amount)
                    converted = fixed * _flt(source, headers["conversion_rate"])
                    paid += fixed
                    base += converted
                    payments.append((name, fixed, converted))
            clear = not bool(flags["is_pos"]) and not bool(flags["is_return"])
            loyalty = headers["loyalty_amount"]
            if flags["redeem_loyalty_points"] and loyalty:
                base += loyalty
                paid += loyalty / _flt(source, headers["conversion_rate"])
            totals = tuple((name, _flt(source, value, proof.precision.precision))
                for name, value, proof in zip(PAID_FIELDS, (paid, base), source.stage.fields[:2]))
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PaymentCalculationError("payment_calculation_paid")
        for name, value in (("source", source), ("payments", tuple(payments)), ("totals", totals), ("clear_payments", clear)):
            object.__setattr__(self, name, value)

    def pin(self):
        pinned = PaidAmountCalculation(self.source, self.representation, self.headers, self.rows)
        _exact_values(self.payments, pinned.payments)
        _exact_values(self.totals, pinned.totals)
        if pinned != self or type(self.clear_payments) is not bool:
            raise PaymentCalculationError("payment_calculation_paid")
        return pinned

    def require_match(self, *, payments, totals, clear_payments, setting_trace, precision_trace):
        try:
            pinned = self.pin()
            _exact_values(payments, pinned.payments)
            _exact_values(totals, pinned.totals)
            if type(clear_payments) is not bool or clear_payments != pinned.clear_payments:
                raise ValueError
            precisions = tuple((name, proof.precision.precision) for name, proof in zip(PAID_FIELDS, pinned.source.stage.fields[:2]))
            require_call_trace(pinned.source.stage.method.rounding.value, setting_trace, precision_trace, precisions, 2)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PaymentCalculationError("payment_calculation_paid_observation")

    def __repr__(self):
        return "<PaidAmountCalculation protected base-controller comparison, NOT payment authority>"

    def __reduce__(self):
        raise TypeError("payment_paid_not_serializable")


@dataclass(frozen=True, repr=False)
class ChangeAmountCalculation:
    """Compare the Sales Invoice cash-change suffix after this paid result."""
    paid: PaidAmountCalculation = field(repr=False)
    representation: str
    headers: tuple = field(repr=False)
    totals: tuple = field(init=False, repr=False)
    applies: bool = field(init=False)

    def __post_init__(self):
        try:
            if type(self.paid) is not PaidAmountCalculation:
                raise ValueError
            paid = self.paid.pin()
            source = paid.source
            headers = _header_inputs(source, self.headers,
                ("grand_total", "rounded_total", "base_grand_total", "base_rounded_total"), self.representation)
            grand = headers["rounded_total"] or headers["grand_total"]
            base_grand = headers["base_rounded_total"] or headers["base_grand_total"]
            amounts = dict(paid.totals)
            cash = not paid.clear_payments and any(tag == ("str", "Cash") for _, tag in source.payment_types)
            applies = bool(amounts["paid_amount"] > grand and not dict(source.controls.normalized_checks)["is_return"] and cash)
            values = (0.0, 0.0)
            if applies:
                values = tuple(_flt(source, value, proof.precision.precision) for value, proof in
                    zip((amounts["paid_amount"] - grand, amounts["base_paid_amount"] - base_grand), source.stage.fields[2:]))
            totals = tuple(zip(CHANGE_FIELDS, values))
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PaymentCalculationError("payment_calculation_change")
        object.__setattr__(self, "paid", paid)
        object.__setattr__(self, "totals", totals)
        object.__setattr__(self, "applies", applies)

    def require_match(self, *, totals, setting_trace, precision_trace):
        try:
            pinned = ChangeAmountCalculation(self.paid, self.representation, self.headers)
            _exact_values(self.totals, pinned.totals)
            _exact_values(totals, pinned.totals)
            if pinned != self or type(self.applies) is not bool:
                raise ValueError
            expected = tuple((name, proof.precision.precision) for name, proof in zip(CHANGE_FIELDS, pinned.paid.source.stage.fields[2:])) if pinned.applies else ()
            require_call_trace(pinned.paid.source.stage.method.rounding.value, setting_trace, precision_trace, expected, 2 if pinned.applies else 0)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PaymentCalculationError("payment_calculation_change_observation")

    def __repr__(self):
        return "<ChangeAmountCalculation protected cash-change comparison, NOT POS Invoice validation>"

    def __reduce__(self):
        raise TypeError("payment_change_not_serializable")
