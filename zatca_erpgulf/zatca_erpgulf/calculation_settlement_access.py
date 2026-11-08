"""Co-owned Sales paid/guard/receivable/POS evidence, never controller execution.

Use one field union, numeric graph, method and format pool on the existing owned
service. Substage projection preserves the old calculators' strict shapes. The
optional POS lookup is an explicit inspection selection, not branch authority.
No independent capture, transaction owner, writer, cache update or transport.
"""

from dataclasses import dataclass, field
import json

from .calculation_guarded_payments import GuardedPaymentAcquisition, SavedGuardedPaymentRead
from .calculation_payments import SavedPaymentCalculationRead, STAGE_FIELDS as PAYMENT_FIELDS
from .calculation_receivable import SavedReceivableRead, STAGE_FIELDS as RECEIVABLE_FIELDS
from .calculation_write_off_access import WriteOffStageMixin, WriteOffInputsAcquisition, WRITE_FIELDS
from .calculation_rounding_stage import RoundingStageAcquisition, SavedRoundingStageRead, pin_stage, project_stage
from .calculation_invoice_rounding_access import InvoiceRoundingAcquisition, SavedInvoiceRoundingContext
from .calculation_pos_profile_access import PosProfileRequest, PosProfileAcquisition, SavedPosProfileContext
from .calculation_child_format_access import link_definition, require_field_read
from .financial_source_observation import _scalar

PREFIX_FIELDS = ("grand_total", "total_advance")


class SettlementAccessError(ValueError):
    """Static English codes without invoice/payment/profile disclosure."""


@dataclass(frozen=True, repr=False)
class SettlementRequest:
    """Bounded explicit inspection; enum validation is inside the UI boundary."""
    pos_lookup: str | None = field(default=None, repr=False)

    def __repr__(self): return "<SettlementRequest internal source inspection>"
    def __reduce__(self): raise TypeError("settlement_request_not_serializable")


@dataclass(frozen=True, repr=False)
class SavedSettlementRead:
    """Same-owned partial stages, NOT full issuance or accounting authority."""
    guarded: SavedGuardedPaymentRead = field(repr=False)
    receivable: SavedReceivableRead = field(repr=False)
    controls: SavedInvoiceRoundingContext = field(repr=False)
    pos: SavedPosProfileContext | None = field(repr=False)
    prefix: SavedRoundingStageRead = field(repr=False)

    def __post_init__(self):
        try:
            if (type(self.guarded) is not SavedGuardedPaymentRead or type(self.receivable) is not SavedReceivableRead
                    or type(self.controls) is not SavedInvoiceRoundingContext):
                raise ValueError
            guarded, receivable = self.guarded.pin(), self.receivable.pin()
            controls = SavedInvoiceRoundingContext(self.controls.financial, self.controls.controls,
                                                  self.controls.tables, self.controls.checks)
            stage = guarded.payment.stage
            prefix = pin_stage(self.prefix)
            if (prefix.numeric != stage.numeric or prefix.method != stage.method
                    or prefix.owner_document != stage.owner_document or prefix.do_not_round_fields is not None
                    or prefix.targets != tuple(("header", stage.numeric.view.financial.financial.name, name)
                                               for name in PREFIX_FIELDS)
                    or prefix.fields[0] != receivable.stage.fields[0]):
                raise ValueError
            root_meta = next(row.applied for row in stage.numeric.view.financial.metadata
                             if row.applied.name == "Sales Invoice")
            link = root_meta.get_field("pos_profile")
            if (controls != self.controls or receivable.stage.numeric != stage.numeric
                    or receivable.stage.method != stage.method or receivable.stage.owner_document != stage.owner_document
                    or controls.financial != stage.numeric.financial or controls.tables != stage.numeric.tables
                    or controls.controls.financial != stage.numeric.view.financial
                    or link is None or link.fieldtype != "Link" or link.options != "POS Profile"):
                raise ValueError
            pos = None
            if self.pos is not None:
                if type(self.pos) is not SavedPosProfileContext:
                    raise ValueError
                pos = self.pos.pin()
                if (pos.financial != stage.numeric.financial or pos.tables != stage.numeric.tables
                        or pos.owner_document != stage.owner_document):
                    raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise SettlementAccessError("settlement_context")
        for name, value in (("guarded", guarded), ("receivable", receivable), ("controls", controls), ("pos", pos), ("prefix", prefix)):
            object.__setattr__(self, name, value)

    def pin(self):
        result = SavedSettlementRead(self.guarded, self.receivable, self.controls, self.pos, self.prefix)
        if result != self:
            raise SettlementAccessError("settlement_context")
        return result

    def __repr__(self): return "<SavedSettlementRead co-owned PARTIAL evidence, NOT full settlement>"
    def __reduce__(self): raise TypeError("settlement_context_not_serializable")


class SettlementAcquisition(WriteOffStageMixin, GuardedPaymentAcquisition):
    """Extend the shared paid/guard stage; add no second root/method/pool."""

    STAGE_FIELDS = (*PAYMENT_FIELDS, *RECEIVABLE_FIELDS, "total_advance")

    def __init__(self, policy, actor, invoice_name, doctype, major, request, *, write_off_metadata,
                 invoice_rounding_metadata, pos_metadata, **dependencies):
        if (type(request) is not SettlementRequest or request.pos_lookup is not None
                and (type(request.pos_lookup) is not str or request.pos_lookup not in ("limit", "default"))):
            raise SettlementAccessError("settlement_request")
        self.write_inputs, self.invoice_controls, self.pos, self.profile_state = None, None, None, None
        super().__init__(policy, actor, invoice_name, doctype, major, **dependencies)
        self.profile_state = self._profile_state(self.root.document)
        self.write_inputs = WriteOffInputsAcquisition(self.root, actor, write_off_metadata,
                                                       dependencies["owner_metadata"], WRITE_FIELDS)
        self.invoice_controls = InvoiceRoundingAcquisition(policy, actor, invoice_name, doctype,
                                                            invoice_rounding_metadata, _shared_graph=self.root)
        if request.pos_lookup is not None:
            self.pos = PosProfileAcquisition(policy, actor, invoice_name, doctype,
                PosProfileRequest(request.pos_lookup), pos_metadata, _shared_graph=self.root)
        self.recheck_access()

    def _profile_state(self, doc):
        definition = link_definition(doc, "pos_profile", "POS Profile")
        level = require_field_read(doc, "pos_profile", self.actor,
            self.root._policy._dependencies()[0], self.root._policy.DENIED_MESSAGE)
        value = doc.get("pos_profile")
        if value is not None and type(value) is not str:
            raise SettlementAccessError("settlement_profile_getter")
        return definition, level, tuple(_scalar(value))

    def recheck_access(self):
        super().recheck_access()
        if self.profile_state is not None and any(self._profile_state(doc) != self.profile_state for doc in
                (self.root.document, self.root._parent_load(self.root._doctype, self.root._name))):
            raise SettlementAccessError("settlement_profile_changed")
        for component in (self.invoice_controls, self.pos):
            if component is not None: component.recheck_access()

    def prepare_metadata(self):
        super().prepare_metadata()
        for component in (self.invoice_controls, self.pos):
            if component is not None: component.prepare_metadata()
        self.recheck_access()

    def require_financial_metadata(self, metadata):
        super().require_financial_metadata(metadata)
        if metadata[0].get_field("pos_profile") != self.profile_state[0]:
            raise SettlementAccessError("settlement_profile_metadata")
        for component in (self.invoice_controls, self.pos):
            if component is not None: component.require_financial_metadata(metadata)

    def load_for_update(self, connection, financial):
        observed = super().load_for_update(connection, financial)
        if tuple(dict(json.loads(financial.financial._payload)["header"])["pos_profile"]) != self.profile_state[2]:
            raise SettlementAccessError("settlement_native_profile")
        self.observed_controls = self.invoice_controls.load_for_update(connection, financial)
        self.observed_pos = None if self.pos is None else self.pos.load_for_update(connection, financial)
        return observed

    def check_getters(self, observed):
        super().check_getters(observed)
        self.invoice_controls.check_getters(self.observed_controls)
        if self.pos is not None: self.pos.check_getters(self.observed_pos)

    def require_metadata_unchanged(self):
        super().require_metadata_unchanged()
        for component in (self.invoice_controls, self.pos):
            if component is not None: component.require_metadata_unchanged()
        self.recheck_access()

    def require_unchanged(self, observed):
        super().require_unchanged(observed)
        self.invoice_controls.require_unchanged(self.observed_controls)
        if self.pos is not None: self.pos.require_unchanged(self.observed_pos)

    def build_result(self, financial, observed):
        stage = RoundingStageAcquisition.build_result(self, financial, observed)
        payment = SavedPaymentCalculationRead(project_stage(stage, PAYMENT_FIELDS), self.native_controls, self.payment_types)
        guarded = SavedGuardedPaymentRead(payment, self.guards.build_result(financial, self.tables))
        inputs = self.write_inputs
        caches = tuple((name, inputs.precision_cache(name), inputs.field_currency_cache(name)) for name in WRITE_FIELDS)
        tag = tuple(dict(json.loads(stage.numeric.view.financial.financial._payload)["header"])["is_return"])
        receivable = SavedReceivableRead(project_stage(stage, RECEIVABLE_FIELDS), inputs.native, inputs.owner.native, caches, tag)
        controls = SavedInvoiceRoundingContext(financial, self.observed_controls, self.tables, self.invoice_controls.checks)
        pos = None if self.pos is None else self.pos.build_result(financial, self.observed_pos)
        return SavedSettlementRead(guarded, receivable, controls, pos, project_stage(stage, PREFIX_FIELDS))
