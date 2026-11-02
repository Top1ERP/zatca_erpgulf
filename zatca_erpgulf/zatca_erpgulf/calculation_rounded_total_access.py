"""Consumed rounded-total sources on the existing owned financial pipeline.

Authorize conditional related records before their own providers/SQL; one owned
transaction and final rechecks cover all selected sources. The adjustment getter
is a truthiness witness only. No money conversion, writes or runtime adoption.
"""

from dataclasses import dataclass, field

from .calculation_invoice_rounding_access import InvoiceRoundingAcquisition, SavedInvoiceRoundingContext
from .calculation_global_rounding_access import GlobalRoundingAcquisition, SavedGlobalRoundingContext
from .calculation_fraction_access import FractionAcquisition, SavedCurrencyFractionContext
from .calculation_rounding_access import RoundingAcquisition, SavedRoundingContext
from .financial_source_observation import _scalar
from .rounded_total_control import _initial_branch, _numeric
from .rounded_total_selection import RoundingDependencyPlan, RoundingSelectionError, _control_stage, _pin_plan, _requires_method


class RoundedTotalAcquisition:
    """Compose existing acquisitions; never call independent capture methods."""

    def __init__(self, policy, actor, invoice_name, doctype, *, control_metadata,
            global_metadata, global_cache, fraction_metadata, fraction_cache, method_metadata, method_cache):
        self.root = InvoiceRoundingAcquisition(policy, actor, invoice_name, doctype, control_metadata)
        self._policy, self._actor, self._name, self._doctype = policy, actor, invoice_name, doctype
        self.tables = self.root.tables
        self.adjustment = self._adjustment_state(self.root.document)
        self.early_branch = _initial_branch(bool(dict(self.root.checks)["is_consolidated"]),
            None if self.adjustment is None else list(self.adjustment), self.root.definition.has_field("rounded_total"))
        self.global_source = None
        self.fraction_source = self.method_source = None
        self._fraction_metadata, self._fraction_cache = fraction_metadata, fraction_cache
        self._method_metadata, self._method_cache = method_metadata, method_cache
        if self.early_branch is None and not self.root.definition.has_field("disable_rounded_total"):
            self.global_source = GlobalRoundingAcquisition(policy, actor, global_metadata, global_cache)
        self.recheck_access()

    def _adjustment_state(self, doc):
        if not dict(self.root.checks)["is_consolidated"]:
            return None
        encoded = _scalar(doc.get("rounding_adjustment"))
        _numeric(encoded)
        if not self.root.definition.has_field("rounding_adjustment") and encoded != ["null"]:
            raise RoundingSelectionError("rounded_total_absent_adjustment_getter")
        return tuple(encoded)

    def recheck_access(self):
        self.root.recheck_access()
        if (self._adjustment_state(self.root.document) != self.adjustment
                or self._adjustment_state(self.root._parent_load(self._doctype, self._name)) != self.adjustment):
            raise RoundingSelectionError("rounded_total_adjustment_getter_drift")
        for source in (self.global_source, self.fraction_source, self.method_source):
            if source is not None:
                source.recheck_access()

    def prepare_metadata(self):
        self.root.prepare_metadata()
        if self.global_source is not None:
            self.global_source.prepare_metadata()
        self.recheck_access()

    def require_financial_metadata(self, metadata):
        self.root.require_financial_metadata(metadata)
        self._financial_metadata = metadata

    def load_for_update(self, connection, financial):
        controls = self.root.load_for_update(connection, financial)
        global_read = fraction_read = method_read = None
        if self.global_source is not None:
            global_read = self.global_source.load_for_update(connection)
            self.global_source.check_cache(global_read)
        branch, _, _ = _control_stage(controls, self.adjustment, global_read)
        if branch is None:
            # These dependencies are selected only after native disable evidence
            # on THIS handle. Each normal READ precedes its own provider calls.
            self.fraction_source = FractionAcquisition(self._policy, self._actor, self._name, self._doctype,
                self._fraction_metadata, self._fraction_cache, financial_graph=self.root)
        if _requires_method(branch, financial.financial.erp_major):
            self.method_source = RoundingAcquisition(self._policy, self._actor, self._method_metadata, self._method_cache, None)
        if self.fraction_source is not None:
            self.fraction_source.prepare_metadata()
            self.fraction_source.require_financial_metadata(self._financial_metadata)
        if self.method_source is not None:
            self.method_source.prepare_metadata()
        self.recheck_access()
        if self.fraction_source is not None:
            fraction_read = self.fraction_source.load_for_update(connection, financial)
        if self.method_source is not None:
            method_read = self.method_source.load_for_update(connection)
            self.method_source.check_cache(method_read)
        result = RoundingDependencyPlan(controls, self.adjustment, global_read, fraction_read, method_read)
        self.recheck_access()
        return result

    def check_getters(self, observed):
        observed = _pin_plan(observed)
        if observed.adjustment != self.adjustment:
            raise RoundingSelectionError("rounded_total_adjustment_binding")
        self.root.check_getters(observed.controls)
        for source, value in ((self.global_source, observed.global_rounding),
                (self.fraction_source, observed.fraction), (self.method_source, observed.rounding)):
            if (source is None) != (value is None):
                raise RoundingSelectionError("rounded_total_consumed_sources")
            if source is not None:
                if source is self.fraction_source:
                    source.check_getters(value)
                else:
                    source.check_cache(value)
        self.recheck_access()

    def require_metadata_unchanged(self):
        for source in (self.root, self.global_source, self.fraction_source, self.method_source):
            if source is not None:
                source.require_metadata_unchanged()
        self.recheck_access()

    def require_unchanged(self, observed):
        # Every trusted metadata/cache callback has already completed. Do not
        # acquire a source or invoke an API cache after these final SQL checks.
        observed = _pin_plan(observed)
        for source, value in ((self.root, observed.controls), (self.global_source, observed.global_rounding),
                (self.fraction_source, observed.fraction), (self.method_source, observed.rounding)):
            if source is not None:
                source.require_unchanged(value)
        self.recheck_access()

    def build_result(self, financial, selection):
        invoice = SavedInvoiceRoundingContext(financial, selection.controls, self.tables, self.root.checks)
        major = financial.financial.financial.erp_major
        global_context = None if self.global_source is None else SavedGlobalRoundingContext(
            financial.context, major, selection.global_rounding, self.global_source.rows)
        fraction_context = None if self.fraction_source is None else SavedCurrencyFractionContext(
            financial, selection.fraction, self.tables, self.fraction_source.rows, self.fraction_source.currency)
        method_context = None if self.method_source is None else SavedRoundingContext(
            financial.context, major, None, selection.rounding, self.method_source.rows)
        return SavedRoundedTotalContext(invoice, selection, global_context, fraction_context, method_context)


@dataclass(frozen=True, repr=False)
class SavedRoundedTotalContext:
    """Same-parent protected control/source plan, NOT normalized money/issuance."""

    invoice: SavedInvoiceRoundingContext = field(repr=False)
    selection: RoundingDependencyPlan = field(repr=False)
    global_context: SavedGlobalRoundingContext | None = field(default=None, repr=False)
    fraction_context: SavedCurrencyFractionContext | None = field(default=None, repr=False)
    method_context: SavedRoundingContext | None = field(default=None, repr=False)

    def __post_init__(self):
        try:
            if type(self.invoice) is not SavedInvoiceRoundingContext:
                raise ValueError
            invoice = SavedInvoiceRoundingContext(self.invoice.financial, self.invoice.controls, self.invoice.tables, self.invoice.checks)
            selection = _pin_plan(self.selection)
            if invoice != self.invoice or invoice.controls != selection.controls:
                raise ValueError
            context, major = invoice.financial.context, invoice.financial.financial.financial.erp_major
            global_context, fraction_context, method_context = None, None, None
            if selection.global_rounding is not None:
                supplied = self.global_context
                if type(supplied) is not SavedGlobalRoundingContext:
                    raise ValueError
                global_context = SavedGlobalRoundingContext(supplied.context, supplied.erp_major, supplied.global_rounding, supplied.related)
                if global_context.context != context or global_context.erp_major != major or global_context.global_rounding != selection.global_rounding:
                    raise ValueError
            elif self.global_context is not None:
                raise ValueError
            if selection.fraction is not None:
                supplied = self.fraction_context
                if type(supplied) is not SavedCurrencyFractionContext:
                    raise ValueError
                fraction_context = SavedCurrencyFractionContext(supplied.financial, supplied.fraction, supplied.tables, supplied.related, supplied.invoice_currency)
                if fraction_context.financial != invoice.financial or fraction_context.fraction != selection.fraction or fraction_context.tables != invoice.tables:
                    raise ValueError
            elif self.fraction_context is not None:
                raise ValueError
            if selection.rounding is not None:
                supplied = self.method_context
                if type(supplied) is not SavedRoundingContext or supplied.override is not None:
                    raise ValueError
                method_context = SavedRoundingContext(supplied.context, supplied.erp_major, supplied.override, supplied.rounding, supplied.related)
                if method_context.context != context or method_context.erp_major != major or method_context.rounding != selection.rounding:
                    raise ValueError
            elif self.method_context is not None:
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise RoundingSelectionError("rounded_total_context")
        for name, value in dict(invoice=invoice, selection=selection, global_context=global_context,
                fraction_context=fraction_context, method_context=method_context).items():
            object.__setattr__(self, name, value)

    def __repr__(self):
        return "<SavedRoundedTotalContext protected PARTIAL consumed plan, NOT money authority>"

    def __reduce__(self):
        raise TypeError("rounded_total_context_not_serializable")
