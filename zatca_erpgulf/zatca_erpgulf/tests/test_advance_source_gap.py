"""Synthetic QR gap observations; no file/customer/authority or migration."""

import base64
from dataclasses import FrozenInstanceError
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import advance_source_gap as gap
from zatca_erpgulf.zatca_erpgulf import advance_lifecycle, create_qr, advance_deduction
from zatca_erpgulf.zatca_erpgulf.tests.test_issue_timestamp_adapters import local_qr
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document


SELLER = "300000000000003"


def tlv(values=None):
    values = values or ["شركة اختبار", SELLER, "2026-09-27T00:05:42+03:00", "8.70", "1.13"]
    return b"".join(bytes((tag, len(value.encode("utf-8")))) + value.encode("utf-8")
                    for tag, value in enumerate(values, 1))


def observation(raw=None, **options):
    return gap.FiveTagQRObservation(base64.b64encode(tlv() if raw is None else raw), options.get("seller", SELLER))


@pytest.mark.parametrize("timestamp", ["2026-09-27T00:05:42", "2026-09-27T00:05:42Z",
    "2026-09-27T00:05:42+03:00", "2026-09-27T23:59:59.123456-02:00"])
@pytest.mark.parametrize("total,vat", [("8.70", "1.13"), ("-8.7", "-1.13"), ("0", "0.0"), ("+0008.700", "999999.99")])
def test_preserves_raw_clock_and_amounts_without_math_or_timezone(timestamp, total, vat):
    raw = tlv(["شركة اختبار", SELLER, timestamp, total, vat])
    found = observation(raw)
    assert found.timestamp == timestamp and found.total_text == total and found.vat_text == vat
    assert found.payload_sha256 == hashlib.sha256(base64.b64encode(raw)).hexdigest()
    assert found.tlv_byte_length == len(raw)
    assert found.offset_declared is (timestamp.endswith("Z") or "+" in timestamp or timestamp.endswith("-02:00"))
    report = found.diagnostic_projection()
    assert report["missing_reference_fields"] == list(gap.MISSING_REFERENCE_FIELDS)
    assert not report["phase2_reference_ready"] and not report["phase_verified"]
    assert timestamp not in repr(found) and SELLER not in repr(found)
    assert timestamp not in json.dumps(report)
    assert not {"seller_name", "seller_tax_id", "timestamp", "total_text", "vat_text", "payload"}.intersection(report)


@pytest.mark.parametrize("field", ["timestamp", "total_text", "payload_sha256", "offset_declared"])
def test_observations_frozen_and_fields_derived(field):
    found = observation()
    with pytest.raises(FrozenInstanceError):
        setattr(found, field, None)
    with pytest.raises(TypeError):
        gap.FiveTagQRObservation(found.payload, SELLER, **{field: None})


@pytest.mark.parametrize("payload,code", [(None, "gap_payload_type"), (True, "gap_payload_type"),
    (bytearray(b"AAAA"), "gap_payload_type"), ("", "gap_payload_size"),
    (b"x" * (gap.MAX_PAYLOAD_BYTES + 1), "gap_payload_size"), ("شركة", "gap_payload_base64"),
    (b"/private/files/QR.png", "gap_payload_base64"), (b"data:image/png;base64,AAAA", "gap_payload_base64"),
    (b"AAAA\n", "gap_payload_base64"), (b"@@@@", "gap_payload_base64"),
    (b"AB==", "gap_payload_noncanonical")])
def test_payload_bounds_paths_and_noncanonical_base64_fail_static(payload, code):
    with pytest.raises(gap.AdvanceSourceGapError) as error:
        gap.FiveTagQRObservation(payload, SELLER)
    assert str(error.value) == code and error.value.__context__ is None


@pytest.mark.parametrize("seller", [None, True, 300000000000003, "PRIVATE-TAX", "٣" * 15, "3" * 16])
def test_explicit_expected_seller_required(seller):
    with pytest.raises(gap.AdvanceSourceGapError, match="gap_expected_seller"):
        observation(seller=seller)


@pytest.mark.parametrize("mutation,code", [
    (lambda raw: raw[:1], "gap_tlv_truncated"),
    (lambda raw: b"\x01\x00" + raw[2:], "gap_tlv_length"),
    (lambda raw: raw[:-1], "gap_tlv_length"),
    (lambda raw: b"\x02" + raw[1:], "gap_tlv_tags"),
    (lambda raw: raw + b"\x06\x01x", "gap_tlv_extra"),
    (lambda raw: raw + b"\x00", "gap_tlv_extra"),
    (lambda raw: b"\x01\x01\xff" + raw[2 + raw[1]:], "gap_tlv_utf8"),
])
def test_exact_five_tags_no_first_match_or_phase2_truncation(mutation, code):
    with pytest.raises(gap.AdvanceSourceGapError) as error:
        observation(mutation(tlv()))
    assert str(error.value) == code and error.value.__context__ is None


@pytest.mark.parametrize("field,value,code", [
    (0, "PRIVATE\x00NAME", "gap_tlv_text"), (1, "300000000000013", "gap_seller_mismatch"),
    (2, "PRIVATE-TIME", "gap_timestamp"), (2, "2026-02-29T00:05:42Z", "gap_timestamp"),
    (2, "2026-09-27T24:00:00Z", "gap_timestamp"), (2, "2026-09-27T00:05:42+14:01", "gap_timestamp"),
    (2, "2026-09-27T00:05:42.1234567Z", "gap_timestamp"),
    (3, "NaN", "gap_amount_text"), (3, "1e20", "gap_amount_text"), (4, "1,000", "gap_amount_text"),
])
def test_invalid_fields_never_get_default_time_or_totals(field, value, code):
    values = ["شركة اختبار", SELLER, "2026-09-27T00:05:42Z", "8.70", "1.13"]
    values[field] = value
    with pytest.raises(gap.AdvanceSourceGapError) as error:
        observation(tlv(values))
    assert str(error.value) == code and error.value.__context__ is None


@pytest.mark.parametrize("origin", gap.ORIGINS)
@pytest.mark.parametrize("phase", gap.PHASES)
def test_missing_source_plan_is_review_not_reconstruction_or_accounting_mutation(origin, phase):
    plan = gap.MissingAdvanceSourcePlan(origin, phase)
    report = plan.diagnostic_projection()
    assert report["outcome"] == "SOURCE_GAP_REVIEW_REQUIRED"
    assert not report["accounting_eligibility_changed"] and not report["missing_source_verified"]
    assert all(value is False for key, value in report.items() if key.endswith(("_authorized", "_verified", "_ready")))
    assert report["required_action"] == ("KEEP_EXISTING_PHASE1_WORKFLOW" if origin == "PHASE1_QR_ONLY" and phase == "Phase-1"
                                         else "EXPLICIT_HISTORICAL_RECONCILIATION")


@pytest.mark.parametrize("origin,phase,qr,code", [(None, "Phase-2", None, "gap_origin"),
    ("LATEST_FILE", "Phase-2", None, "gap_origin"), ("PHASE1_QR_ONLY", None, None, "gap_target_phase"),
    ("PHASE1_QR_ONLY", "Production", None, "gap_target_phase"),
    ("PHASE1_QR_ONLY", "Phase-2", {"accepted": True}, "gap_qr_binding")])
def test_gap_declarations_must_be_explicit_known_inputs(origin, phase, qr, code):
    with pytest.raises(gap.AdvanceSourceGapError, match=code):
        gap.MissingAdvanceSourcePlan(origin, phase, qr)


def test_qr_presence_never_promotes_phase2_readiness_and_non_qr_origins_reject_it():
    found = observation()
    for phase in gap.PHASES:
        plan = gap.MissingAdvanceSourcePlan("PHASE1_QR_ONLY", phase, found)
        assert plan.diagnostic_projection()["phase2_reference_ready"] is False
        with pytest.raises(FrozenInstanceError):
            plan.target_phase = "Phase-1"
    for origin in gap.ORIGINS[1:]:
        with pytest.raises(gap.AdvanceSourceGapError, match="gap_qr_binding"):
            gap.MissingAdvanceSourcePlan(origin, "Phase-2", found)


@pytest.mark.parametrize("route", ["sales", "pos", "advance"])
def test_actual_mocked_phase1_builders_produce_no_invoice_identity_in_five_tags(local_qr, route):
    invoice, runtime, payloads, _ = local_qr
    if route == "advance":
        advance_deduction.ensure_final_sales_invoice_qr_for_print(invoice)
    else:
        if route == "pos":
            invoice.doctype = "POS Invoice"
        create_qr.create_qr_code(invoice)
    generation_commit_count = runtime.db.commit.call_count
    found = gap.FiveTagQRObservation(payloads[0], SELLER)
    assert found.timestamp == "2026-09-27T06:05:42Z"
    assert found.total_text == ("9.50" if route == "advance" else "11.5")
    assert gap.MissingAdvanceSourcePlan("PHASE1_QR_ONLY", "Phase-2", found).diagnostic_projection()["phase2_reference_ready"] is False
    # Existing ordinary generation commits once; this is a separate runtime
    # migration gate, NOT a side effect of the new pure observation/plan.
    assert generation_commit_count == (0 if route == "advance" else 1)
    assert runtime.db.commit.call_count == generation_commit_count


@pytest.mark.parametrize("status", ["PHASE 1 QR CREATED", "PHASE-1 QR GENERATED", "REPORTED", "CLEARED"])
def test_characterize_existing_accounting_eligibility_separate_from_xml_reference(status):
    doc = Document(doctype="Sales Invoice", docstatus=1, is_advance_payment=1, custom_zatca_status=status,
                   meta=SimpleNamespace(has_field=lambda name: name == "is_advance_payment"))
    assert advance_lifecycle.is_accepted_advance_sales_invoice(doc) is True
    # This existing eligibility is unchanged, not proof of authentic artifact.
    assert gap.MissingAdvanceSourcePlan("PHASE1_QR_ONLY", "Phase-2").diagnostic_projection()["settlement_authorized"] is False


def test_observation_never_discovers_erp_timezone_file_or_clock(monkeypatch):
    import frappe
    forbidden = Mock(side_effect=AssertionError("No source discovery or repair"))
    for name in ("get_doc", "get_all", "get_site_path", "get_system_settings", "init", "connect"):
        monkeypatch.setattr(frappe, name, forbidden)
    found = observation()
    report = gap.MissingAdvanceSourcePlan("PHASE1_QR_ONLY", "Phase-2", found).diagnostic_projection()
    report["phase2_reference_ready"] = True
    assert found.diagnostic_projection()["phase2_reference_ready"] is False
    forbidden.assert_not_called()
