from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from zatca_erpgulf.setup_customizations import (
    CRITICAL_CUSTOM_FIELDS,
    ensure_critical_custom_fields,
)
from zatca_erpgulf.zatca_erpgulf.advance_deduction import (
    validate_sales_invoice_advance_deductions,
)
from zatca_erpgulf.zatca_erpgulf.zatca_runtime import (
    get_b2c_submission_method,
    get_zatca_environment,
    is_advance_payment_invoice,
    is_zatca_invoice_enabled,
    resolve_zatca_phase,
)


class _Meta:
    def __init__(self, fields=()):
        self.fields = set(fields)

    def has_field(self, fieldname):
        return fieldname in self.fields


class _Doc(SimpleNamespace):
    def __init__(self, *, fields=(), **values):
        super().__init__(**values)
        self.meta = _Meta(fields)

    def get(self, fieldname, default=None):
        return getattr(self, fieldname, default)


def _marker_doc(*, standard_exists=False, standard=0, custom_exists=False, custom=0):
    fields = set()
    values = {}

    if standard_exists:
        fields.add("is_advance_payment")
        values["is_advance_payment"] = standard

    if custom_exists:
        fields.add("custom_is_advance_payment")
        values["custom_is_advance_payment"] = custom

    return _Doc(fields=fields, **values)


def _company(**values):
    return _Doc(fields=values.keys(), **values)


def _advance_field_definition():
    return next(
        row
        for row in CRITICAL_CUSTOM_FIELDS["Sales Invoice"]
        if row["fieldname"] == "is_advance_payment"
    )


def _run_field_setup(existing_fields):
    def field_exists(dt, alternatives):
        if dt != "Sales Invoice":
            return True
        marker_names = {"is_advance_payment", "custom_is_advance_payment"}
        if marker_names.intersection(alternatives):
            return any(fieldname in existing_fields for fieldname in alternatives)
        return True

    with patch(
        "zatca_erpgulf.setup_customizations._doctype_exists",
        return_value=True,
    ), patch(
        "zatca_erpgulf.setup_customizations._any_field_exists",
        side_effect=field_exists,
    ), patch(
        "zatca_erpgulf.setup_customizations._resolve_insert_after",
        side_effect=lambda _dt, requested, _fallback: requested,
    ), patch(
        "zatca_erpgulf.setup_customizations._ensure_alternative_field_visible",
    ), patch(
        "zatca_erpgulf.setup_customizations.create_custom_fields",
    ) as create_fields, patch(
        "zatca_erpgulf.setup_customizations.frappe.clear_cache",
    ):
        result = ensure_critical_custom_fields()

    return result, create_fields


class TestPhase2AdvanceMarker(FrappeTestCase):
    def test_mark_001_neither_marker_creates_exact_field(self):
        result, create_fields = _run_field_setup(set())
        created = create_fields.call_args.args[0]["Sales Invoice"]
        self.assertEqual(created[0]["fieldname"], "is_advance_payment")
        self.assertIn("Sales Invoice.is_advance_payment", result["created"])

    def test_mark_002_exact_marker_is_reused(self):
        result, create_fields = _run_field_setup({"is_advance_payment"})
        self.assertFalse(create_fields.called)
        self.assertIn("Sales Invoice.is_advance_payment", result["already_available"])

    def test_mark_003_legacy_custom_marker_prevents_duplicate(self):
        result, create_fields = _run_field_setup({"custom_is_advance_payment"})
        self.assertFalse(create_fields.called)
        self.assertIn("Sales Invoice.is_advance_payment", result["already_available"])

    def test_mark_004_both_markers_reuse_existing_and_standard_wins(self):
        _result, create_fields = _run_field_setup(
            {"is_advance_payment", "custom_is_advance_payment"}
        )
        self.assertFalse(create_fields.called)
        self.assertFalse(
            is_advance_payment_invoice(
                _marker_doc(
                    standard_exists=True,
                    standard=0,
                    custom_exists=True,
                    custom=1,
                )
            )
        )

    def test_mark_005_fieldname(self):
        self.assertEqual(_advance_field_definition()["fieldname"], "is_advance_payment")

    def test_mark_006_label(self):
        self.assertEqual(
            _advance_field_definition()["label"],
            "Is Advance Payment Invoice",
        )

    def test_mark_007_fieldtype(self):
        self.assertEqual(_advance_field_definition()["fieldtype"], "Check")

    def test_mark_008_insert_after(self):
        self.assertEqual(_advance_field_definition()["insert_after"], "is_debit_note")

    def test_mark_009_no_copy(self):
        self.assertEqual(_advance_field_definition()["no_copy"], 1)

    def test_mark_010_second_setup_run_creates_no_duplicate(self):
        _result, create_fields = _run_field_setup({"is_advance_payment"})
        self.assertFalse(create_fields.called)

    def test_mark_011_both_zero_resolves_zero(self):
        self.assertFalse(
            is_advance_payment_invoice(
                _marker_doc(
                    standard_exists=True,
                    standard=0,
                    custom_exists=True,
                    custom=0,
                )
            )
        )

    def test_mark_012_standard_one_custom_zero_resolves_one(self):
        self.assertTrue(
            is_advance_payment_invoice(
                _marker_doc(
                    standard_exists=True,
                    standard=1,
                    custom_exists=True,
                    custom=0,
                )
            )
        )

    def test_mark_013_standard_zero_custom_one_resolves_zero(self):
        self.assertFalse(
            is_advance_payment_invoice(
                _marker_doc(
                    standard_exists=True,
                    standard=0,
                    custom_exists=True,
                    custom=1,
                )
            )
        )

    def test_mark_014_both_one_resolves_one(self):
        self.assertTrue(
            is_advance_payment_invoice(
                _marker_doc(
                    standard_exists=True,
                    standard=1,
                    custom_exists=True,
                    custom=1,
                )
            )
        )

    def test_mark_015_custom_is_fallback_when_standard_absent(self):
        self.assertTrue(
            is_advance_payment_invoice(
                _marker_doc(custom_exists=True, custom=1)
            )
        )


class TestPhase2CompanyResolver(FrappeTestCase):
    def test_cfg_t_001_general_enablement_zero_disables(self):
        self.assertFalse(is_zatca_invoice_enabled(_company(custom_zatca_invoice_enabled=0)))

    def test_cfg_t_002_general_enablement_one_enables(self):
        self.assertTrue(is_zatca_invoice_enabled(_company(custom_zatca_invoice_enabled=1)))

    def test_cfg_t_003_primary_phase_one(self):
        self.assertEqual(resolve_zatca_phase(_company(custom_phase_1_or_2="Phase-1")), "Phase-1")

    def test_cfg_t_004_primary_phase_two(self):
        self.assertEqual(resolve_zatca_phase(_company(custom_phase_1_or_2="Phase-2")), "Phase-2")

    def test_cfg_t_005_legacy_phase_one_fallback(self):
        self.assertEqual(resolve_zatca_phase(_company(phase_1_or_2="Phase-1")), "Phase-1")

    def test_cfg_t_006_legacy_phase_two_fallback(self):
        self.assertEqual(resolve_zatca_phase(_company(phase_1_or_2="Phase-2")), "Phase-2")

    def test_cfg_t_007_primary_phase_wins_conflict(self):
        self.assertEqual(
            resolve_zatca_phase(
                _company(custom_phase_1_or_2="Phase-1", phase_1_or_2="Phase-2")
            ),
            "Phase-1",
        )

    def test_cfg_t_008_empty_phase_is_controlled_empty_result(self):
        self.assertEqual(
            resolve_zatca_phase(_company(custom_phase_1_or_2="", phase_1_or_2="")),
            "",
        )

    def test_cfg_t_009_general_environment_is_used(self):
        self.assertEqual(get_zatca_environment(_company(custom_select="Simulation")), "Simulation")

    def test_cfg_t_010_general_b2c_method_is_used(self):
        self.assertEqual(
            get_b2c_submission_method(
                _company(custom_send_invoice_to_zatca="Background")
            ),
            "Background",
        )

    def test_cfg_t_011_obsolete_advance_controls_cannot_override_general_controls(self):
        company = _company(
            custom_zatca_invoice_enabled=0,
            custom_phase_1_or_2="Phase-1",
            phase_1_or_2="Phase-2",
            custom_select="Production",
            custom_send_invoice_to_zatca="Background",
            custom_zatca_advance_payment_enabled=1,
            custom_zatca_advance_payment_submission_mode="Submit to ZATCA",
            custom_zatca_advance_signing_enabled=1,
            custom_zatca_advance_api_submission_enabled=1,
        )

        self.assertFalse(is_zatca_invoice_enabled(company))
        self.assertEqual(resolve_zatca_phase(company), "Phase-1")
        self.assertEqual(get_zatca_environment(company), "Production")
        self.assertEqual(get_b2c_submission_method(company), "Background")


class _DeductionDoc(_Doc):
    def __init__(self, *, is_return=0, marker=0, marker_fields=("is_advance_payment",)):
        super().__init__(
            fields=set(marker_fields),
            doctype="Sales Invoice",
            name="TEST-PHASE2-SINV",
            is_return=is_return,
            is_advance_payment=marker,
            custom_is_advance_payment=marker,
            docstatus=0,
            net_total=-100 if is_return else 100,
            grand_total=-115 if is_return else 115,
            taxes=[],
            advances=[],
            custom_zatca_advance_deduction_details=[],
            custom_zatca_prepaid_amount=0,
            custom_zatca_advance_deducted_taxable_amount=0,
            custom_zatca_advance_deducted_vat_amount=0,
            custom_zatca_advance_deduction_count=0,
        )
        self.calculate_calls = 0

    def set(self, fieldname, value):
        setattr(self, fieldname, value)

    def calculate_taxes_and_totals(self):
        self.calculate_calls += 1


class TestPhase2MutualExclusion(FrappeTestCase):
    def _validate(self, doc, *, has_positive_allocation):
        doc.custom_zatca_advance_deduction_details = (
            [SimpleNamespace(advance_invoice="SINV-ADV", allocated_total_amount=115)]
            if has_positive_allocation
            else []
        )
        with patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction."
            "_validate_and_enrich_row",
            return_value={
                "advance": _Doc(custom_zatca_payment_entry=None),
                "allocated_total_amount": 115,
                "allocated_taxable_amount": 100,
                "allocated_tax_amount": 15,
            },
        ):
            validate_sales_invoice_advance_deductions(doc)

    def test_mut_001_advance_without_deductions_is_allowed(self):
        doc = _DeductionDoc(marker=1)
        self._validate(doc, has_positive_allocation=False)
        self.assertEqual(doc.calculate_calls, 0)

    def test_mut_002_advance_with_empty_rows_is_allowed(self):
        doc = _DeductionDoc(marker=1)
        doc.advances = []
        self._validate(doc, has_positive_allocation=False)
        self.assertEqual(doc.calculate_calls, 0)

    def test_mut_003_advance_with_positive_deduction_is_blocked(self):
        doc = _DeductionDoc(marker=1)
        with self.assertRaisesRegex(
            frappe.ValidationError,
            "cannot be both an advance payment invoice and a final invoice",
        ):
            self._validate(doc, has_positive_allocation=True)

    def test_mut_004_final_invoice_with_positive_deduction_remains_allowed(self):
        doc = _DeductionDoc(marker=0)
        self._validate(doc, has_positive_allocation=True)
        self.assertEqual(doc.calculate_calls, 0)

    def test_mut_005_advance_with_zero_allocation_is_allowed(self):
        doc = _DeductionDoc(marker=1)
        doc.advances = [SimpleNamespace(reference_name="ACC-PAY-ZERO", allocated_amount=0)]
        self._validate(doc, has_positive_allocation=False)
        self.assertEqual(doc.calculate_calls, 0)

    def test_mut_006_return_uses_existing_credit_note_rule(self):
        doc = _DeductionDoc(is_return=1, marker=1)
        with self.assertRaisesRegex(
            frappe.ValidationError,
            "cannot be applied directly to a return or credit note",
        ):
            self._validate(doc, has_positive_allocation=True)
