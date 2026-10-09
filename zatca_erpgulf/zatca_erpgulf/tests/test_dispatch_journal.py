"""Memory-only attempt traces with synthetic candidates and no live dispatch."""

import ast
import hashlib
import inspect
import json
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import frappe
import pytest
import requests

from zatca_erpgulf.zatca_erpgulf import dispatch_journal as dispatch
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_issuance_candidate import candidate, scope


ATTEMPT_ID = "6325af99-db35-434d-a8af-05af7bb1656f"
OTHER_ID = "04295c78-332f-4bc4-9a7b-f669a041db19"
REQUEST_ID = "c0000000-0000-4000-8000-000000000009"
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def prepared(certificates):
    return candidate(certificates[0])


def event(prepared, kind="ATTEMPT_STARTED", sequence=1, **changes):
    values = dict(
        event_id=f"70000000-0000-4000-8000-{sequence:012d}", attempt_id=ATTEMPT_ID,
        sequence=sequence, occurred_at=NOW + timedelta(seconds=sequence), kind=kind,
        key_sha256=prepared.key_sha256, manifest_sha256=prepared.manifest_sha256,
    )
    if kind == "HTTP_RESPONSE":
        values.update(http_status=200, response_bytes=b"{}", request_id=REQUEST_ID)
    elif kind == "TRANSPORT_UNKNOWN":
        values["unknown_cause"] = "TIMEOUT"
    values.update(changes)
    return dispatch.DispatchEvent(**values)


def start(prepared):
    return dispatch.append_dispatch_event(dispatch.DispatchJournal(prepared), event(prepared))


def assert_code(call, code):
    with pytest.raises(dispatch.DispatchJournalError) as error:
        call()
    assert error.value.code == code
    assert str(error.value) == code


def assert_no_authority(journal):
    report = journal.diagnostic_projection()
    for flag in ("persistence_verified", "lease_verified", "remote_acceptance_verified",
                 "dispatch_authorized", "replay_authorized"):
        assert report[flag] is False


def test_empty_journal_never_authorizes_dispatch(prepared):
    journal = dispatch.DispatchJournal(prepared)
    assert journal.events == ()
    assert journal.state == "PREPARED_CANDIDATE"
    assert journal.active_attempt_id is None
    assert_no_authority(journal)
    assert journal.journal_sha256 == dispatch.DispatchJournal(prepared).journal_sha256


def test_start_is_an_observation_not_a_real_lease(prepared):
    before = dispatch.DispatchJournal(prepared)
    after = dispatch.append_dispatch_event(before, event(prepared))
    assert before.events == ()
    assert after.state == "IN_FLIGHT_OBSERVED"
    assert after.active_attempt_id == ATTEMPT_ID
    assert after.events == (event(prepared),)
    assert before.journal_sha256 != after.journal_sha256
    assert after.candidate is prepared
    assert_no_authority(after)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
def test_same_protocol_covers_sales_pos_reporting_and_clearance(certificates, doctype, indicator):
    prepared = candidate(certificates[0], selected_scope=scope(doctype=doctype), indicator=indicator)
    journal = dispatch.append_dispatch_event(start(prepared), event(prepared, "HTTP_RESPONSE", 2))
    assert journal.state == "HTTP_RESPONSE_OBSERVED"
    assert journal.candidate is prepared
    assert_no_authority(journal)


@pytest.mark.parametrize("cause", ["TIMEOUT", "CONNECTION_ERROR", "WORKER_INTERRUPTION"])
def test_transport_unknown_preserves_issued_identity_and_bytes(prepared, cause):
    before = start(prepared)
    after = dispatch.append_dispatch_event(before, event(prepared, "TRANSPORT_UNKNOWN", 2, unknown_cause=cause))
    assert after.state == "OUTCOME_UNKNOWN"
    assert after.active_attempt_id is None
    assert len(before.events) == 1
    assert len(after.events) == 2
    assert after.candidate is prepared
    assert after.candidate.xml_bytes == prepared.xml_bytes
    assert after.candidate.artifact.uuid == prepared.artifact.uuid
    assert after.candidate.artifact.icv == prepared.artifact.icv
    assert after.candidate.artifact.previous_hash == prepared.artifact.previous_hash
    assert_no_authority(after)


@pytest.mark.parametrize("status", [200, 201, 202, 204, 302, 400, 401, 403, 406, 409, 422, 500, 503, 599])
def test_http_status_never_manufactures_acceptance_or_replay(prepared, status):
    before = start(prepared)
    body = b'{"reportingStatus":"REPORTED","validationResults":{"status":"PASS","errorMessages":[]}}'
    receipt = event(prepared, "HTTP_RESPONSE", 2, http_status=status, response_bytes=body)
    after = dispatch.append_dispatch_event(before, receipt)
    expected = "AUTHORIZATION_FAILURE_OBSERVED" if status in (401, 403) else "HTTP_RESPONSE_OBSERVED"
    assert after.state == expected
    assert after.active_attempt_id is None
    assert after.events[-1].response_bytes == body
    assert after.candidate is prepared
    assert_no_authority(after)


@pytest.mark.parametrize("body", [b"", b"not JSON PRIVATE-BODY", b"\xff\x00", b"<html>PRIVATE-BODY</html>",
                                b'{"status":"CLEARED"}', b'{"status":"ERROR"}'])
def test_response_receipt_preserves_bytes_without_body_inference(prepared, body):
    receipt = event(prepared, "HTTP_RESPONSE", 2, response_bytes=body)
    journal = dispatch.append_dispatch_event(start(prepared), receipt)
    assert journal.state == "HTTP_RESPONSE_OBSERVED"
    assert receipt.response_sha256 == hashlib.sha256(body).hexdigest()
    assert receipt.response_byte_length == len(body)
    assert receipt.response_bytes == body
    assert "PRIVATE-BODY" not in repr(receipt)
    assert "PRIVATE-BODY" not in repr(journal)
    assert "PRIVATE-BODY" not in json.dumps(journal.diagnostic_projection())
    assert_no_authority(journal)


@pytest.mark.parametrize("status", [200, 400, 401, 409, 503])
def test_late_response_retains_the_prior_unknown_event(prepared, status):
    unknown = dispatch.append_dispatch_event(start(prepared), event(prepared, "TRANSPORT_UNKNOWN", 2))
    late = event(prepared, "HTTP_RESPONSE", 3, http_status=status)
    after = dispatch.append_dispatch_event(unknown, late)
    assert unknown.state == "OUTCOME_UNKNOWN"
    assert [e.kind for e in after.events] == ["ATTEMPT_STARTED", "TRANSPORT_UNKNOWN", "HTTP_RESPONSE"]
    assert after.events[1] is unknown.events[1]
    assert after.candidate is prepared
    assert_no_authority(after)


@pytest.mark.parametrize("attribute", ["state", "events", "candidate", "active_attempt_id", "journal_sha256"])
def test_journal_is_frozen(prepared, attribute):
    with pytest.raises(FrozenInstanceError):
        setattr(start(prepared), attribute, None)


@pytest.mark.parametrize("attribute", ["http_status", "response_bytes", "sequence", "response_sha256", "response_byte_length"])
def test_receipt_and_derived_facts_are_frozen(prepared, attribute):
    receipt = event(prepared, "HTTP_RESPONSE", 2)
    with pytest.raises(FrozenInstanceError):
        setattr(receipt, attribute, None)


@pytest.mark.parametrize("field", ["event_id", "attempt_id"])
@pytest.mark.parametrize("value", [None, [], "raw credential", OTHER_ID.upper(), "00000000-0000-0000-0000-000000000000"])
def test_event_references_are_canonical_nonsecret_uuids(prepared, field, value):
    assert_code(lambda: event(prepared, **{field: value}), field)


@pytest.mark.parametrize("field,code", [("key_sha256", "event_key_fingerprint"), ("manifest_sha256", "event_manifest_fingerprint")])
@pytest.mark.parametrize("value", ["", "a" * 63, "A" * 64, None, [], "PRIVATE-KEY"])
def test_event_fingerprints_have_strict_shape(prepared, field, code, value):
    assert_code(lambda: event(prepared, **{field: value}), code)


@pytest.mark.parametrize("sequence", [0, -1, True, False, "1", None, 1.0, 4])
def test_event_sequence_is_a_bounded_integer(prepared, sequence):
    assert_code(lambda: replace(event(prepared), sequence=sequence), "event_sequence")


@pytest.mark.parametrize("value", [NOW.replace(tzinfo=None), NOW.replace(tzinfo=timezone(timedelta(hours=3))),
                                 "2026-10-09T12:00:00Z", None])
def test_event_time_requires_explicit_utc_without_local_time_inference(prepared, value):
    assert_code(lambda: event(prepared, occurred_at=value), "event_utc_timestamp")


@pytest.mark.parametrize("kind", [None, [], "STARTED", "CLEARED", "REPORTED", "ACCEPTED", "RETRY_ALLOWED", ""])
def test_success_or_retry_claims_are_not_event_kinds(prepared, kind):
    assert_code(lambda: replace(event(prepared), kind=kind), "event_kind")


@pytest.mark.parametrize("status", [None, True, False, "200", 200.0, 0, 199, 600, []])
def test_terminal_http_status_is_explicit_bounded_integer(prepared, status):
    assert_code(lambda: event(prepared, "HTTP_RESPONSE", 2, http_status=status), "event_http_status")


@pytest.mark.parametrize("body", [None, "raw response", bytearray(b"mutable"), {}, []])
def test_receipts_require_immutable_bytes(prepared, body):
    assert_code(lambda: event(prepared, "HTTP_RESPONSE", 2, response_bytes=body), "event_response_bytes")


def test_oversized_response_is_rejected_without_discarding_old_history(prepared):
    before = start(prepared)
    assert_code(lambda: event(prepared, "HTTP_RESPONSE", 2, response_bytes=b"x" * (dispatch.MAX_RESPONSE_BYTES + 1)), "event_response_size")
    assert len(before.events) == 1


@pytest.mark.parametrize("request_id", [None, REQUEST_ID])
def test_optional_canonical_request_id_is_preserved(prepared, request_id):
    receipt = event(prepared, "HTTP_RESPONSE", 2, request_id=request_id)
    assert receipt.diagnostic_projection()["request_id"] == request_id


@pytest.mark.parametrize("request_id", ["", "raw auth PRIVATE", "line\nbreak", None, REQUEST_ID.upper()])
def test_present_request_id_is_not_arbitrary_header_text(prepared, request_id):
    if request_id is None:
        request_id = []
    assert_code(lambda: event(prepared, "HTTP_RESPONSE", 2, request_id=request_id), "event_request_id")


@pytest.mark.parametrize("cause", [None, "", "PASSWORD=PRIVATE", "exception text", "timeout", []])
def test_unknown_cause_is_static_not_raw_exception(prepared, cause):
    assert_code(lambda: event(prepared, "TRANSPORT_UNKNOWN", 2, unknown_cause=cause), "event_unknown_cause")


@pytest.mark.parametrize("kind", ["ATTEMPT_STARTED", "TRANSPORT_UNKNOWN"])
@pytest.mark.parametrize("changes", [{"http_status": 200}, {"response_bytes": b""}, {"request_id": REQUEST_ID}])
def test_non_http_events_cannot_mix_response_fields(prepared, kind, changes):
    assert_code(lambda: event(prepared, kind, **changes), "event_fields_conflict")


def test_http_response_and_start_cannot_claim_transport_unknown(prepared):
    assert_code(lambda: event(prepared, "HTTP_RESPONSE", 2, unknown_cause="TIMEOUT"), "event_fields_conflict")
    assert_code(lambda: event(prepared, unknown_cause="TIMEOUT"), "event_fields_conflict")


@pytest.mark.parametrize("events", [[], None, {}, "history", (None,), ({},)])
def test_only_immutable_typed_event_history_is_accepted(prepared, events):
    code = "journal_events" if type(events) is not tuple else "journal_event"
    assert_code(lambda: dispatch.DispatchJournal(prepared, events), code)


def test_history_is_bounded_before_transition_processing(prepared):
    assert_code(lambda: dispatch.DispatchJournal(prepared, (event(prepared),) * 4), "journal_events")


@pytest.mark.parametrize("value", [None, {}, "invoice", []])
def test_journal_requires_validated_candidate(value):
    assert_code(lambda: dispatch.DispatchJournal(value), "journal_candidate")


@pytest.mark.parametrize("kind", ["TRANSPORT_UNKNOWN", "HTTP_RESPONSE"])
def test_terminal_event_requires_start(prepared, kind):
    assert_code(lambda: dispatch.DispatchJournal(prepared, (event(prepared, kind),)), "attempt_not_started")


@pytest.mark.parametrize("field,code", [("key_sha256", "event_key_mismatch"), ("manifest_sha256", "event_manifest_mismatch")])
def test_foreign_candidate_event_cannot_attach_to_this_history(prepared, field, code):
    foreign = event(prepared, **{field: "0" * 64})
    assert_code(lambda: dispatch.append_dispatch_event(dispatch.DispatchJournal(prepared), foreign), code)


def test_sequence_gaps_and_backdated_events_are_not_reordered(prepared):
    assert_code(lambda: dispatch.DispatchJournal(prepared, (event(prepared, sequence=2),)), "event_sequence_gap")
    assert_code(lambda: dispatch.append_dispatch_event(start(prepared), event(prepared, "HTTP_RESPONSE", 3)), "event_sequence_gap")
    assert_code(lambda: dispatch.append_dispatch_event(start(prepared), event(prepared, "HTTP_RESPONSE", 2, occurred_at=NOW)), "event_time_order")


def test_equal_timestamps_use_explicit_sequence_order(prepared):
    started = start(prepared)
    after = dispatch.append_dispatch_event(started, event(prepared, "HTTP_RESPONSE", 2, occurred_at=started.events[0].occurred_at))
    assert after.state == "HTTP_RESPONSE_OBSERVED"


@pytest.mark.parametrize("kind", ["TRANSPORT_UNKNOWN", "HTTP_RESPONSE"])
def test_different_attempt_id_cannot_resolve_this_attempt(prepared, kind):
    assert_code(lambda: dispatch.append_dispatch_event(start(prepared), event(prepared, kind, 2, attempt_id=OTHER_ID)), "event_attempt_mismatch")


def test_second_inflight_start_is_refused(prepared):
    assert_code(lambda: dispatch.append_dispatch_event(start(prepared), event(prepared, sequence=2, attempt_id=OTHER_ID)), "attempt_in_flight")


@pytest.mark.parametrize("kind,changes", [("TRANSPORT_UNKNOWN", {}), ("HTTP_RESPONSE", {}), ("HTTP_RESPONSE", {"http_status": 401})])
def test_second_attempt_needs_external_reconciliation_not_automatic_retry(prepared, kind, changes):
    ended = dispatch.append_dispatch_event(start(prepared), event(prepared, kind, 2, **changes))
    assert_code(lambda: dispatch.append_dispatch_event(ended, event(prepared, sequence=3, attempt_id=OTHER_ID)), "attempt_reconciliation_required")
    assert_no_authority(ended)


@pytest.mark.parametrize("kind", ["HTTP_RESPONSE", "TRANSPORT_UNKNOWN"])
def test_known_response_cannot_be_overwritten_or_downgraded_to_unknown(prepared, kind):
    ended = dispatch.append_dispatch_event(start(prepared), event(prepared, "HTTP_RESPONSE", 2))
    assert_code(lambda: dispatch.append_dispatch_event(ended, event(prepared, kind, 3)), "response_already_recorded")


def test_repeated_unknown_event_with_new_id_is_not_a_new_resolution(prepared):
    ended = dispatch.append_dispatch_event(start(prepared), event(prepared, "TRANSPORT_UNKNOWN", 2))
    assert_code(lambda: dispatch.append_dispatch_event(ended, event(prepared, "TRANSPORT_UNKNOWN", 3)), "unknown_outcome_already_recorded")


def test_equal_event_id_redelivery_is_idempotent_even_after_late_response(prepared):
    started = start(prepared)
    unknown_event = event(prepared, "TRANSPORT_UNKNOWN", 2)
    unknown = dispatch.append_dispatch_event(started, unknown_event)
    ended = dispatch.append_dispatch_event(unknown, event(prepared, "HTTP_RESPONSE", 3))
    for recorded in ended.events:
        assert dispatch.append_dispatch_event(ended, recorded) is ended
    assert len(ended.events) == 3


@pytest.mark.parametrize("changes", [{"response_bytes": b"different body"}, {"http_status": 401},
                                    {"request_id": OTHER_ID}, {"manifest_sha256": "a" * 64}])
def test_repeated_event_id_with_different_content_is_conflict(prepared, changes):
    receipt = event(prepared, "HTTP_RESPONSE", 2)
    ended = dispatch.append_dispatch_event(start(prepared), receipt)
    assert_code(lambda: dispatch.append_dispatch_event(ended, replace(receipt, **changes)), "event_id_conflict")
    assert ended.events[-1] == receipt


def test_direct_constructor_rejects_duplicate_ids_not_just_append_api(prepared):
    started = event(prepared)
    receipt = event(prepared, "HTTP_RESPONSE", 2, event_id=started.event_id)
    assert_code(lambda: dispatch.DispatchJournal(prepared, (started, receipt)), "event_id_duplicate")


def test_candidate_drift_cannot_be_retrofitted_to_existing_attempt(prepared):
    started = start(prepared)
    changed = replace(prepared, xml_bytes=prepared.xml_bytes + b"\n")
    assert changed.key_sha256 == prepared.key_sha256
    assert_code(lambda: replace(started, candidate=changed), "event_manifest_mismatch")


def test_derived_event_and_journal_fields_cannot_be_injected(prepared):
    with pytest.raises(TypeError):
        dispatch.DispatchJournal(prepared, state="CLEARED")
    values = dict(event(prepared).__dict__)
    with pytest.raises(TypeError):
        dispatch.DispatchEvent(**values)


@pytest.mark.parametrize("target", [None, {}, []])
def test_append_rejects_mutable_serialized_claims(prepared, target):
    assert_code(lambda: dispatch.append_dispatch_event(target, event(prepared)), "journal_append")
    assert_code(lambda: dispatch.append_dispatch_event(start(prepared), target), "journal_append")


def test_projection_edits_do_not_mutate_internal_history(prepared):
    ended = dispatch.append_dispatch_event(start(prepared), event(prepared, "HTTP_RESPONSE", 2))
    report = ended.diagnostic_projection()
    report["events"][1]["http_status"] = 401
    report["events"].clear()
    assert ended.events[1].http_status == 200
    assert len(ended.events) == 2


def test_contract_does_not_access_database_files_http_or_clock(prepared, monkeypatch):
    forbidden = Mock(side_effect=AssertionError("Journal attempted I/O"))
    monkeypatch.setattr(frappe, "get_doc", forbidden)
    monkeypatch.setattr(frappe, "db", SimpleNamespace(sql=forbidden, commit=forbidden, set_value=forbidden), raising=False)
    monkeypatch.setattr(requests, "post", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)
    journal = dispatch.append_dispatch_event(start(prepared), event(prepared, "TRANSPORT_UNKNOWN", 2))
    assert journal.state == "OUTCOME_UNKNOWN"
    assert_no_authority(journal)
    forbidden.assert_not_called()


def test_clock_is_not_read_inside_the_contract():
    tree = ast.parse(inspect.getsource(dispatch))
    forbidden = {"now", "utcnow", "time", "monotonic", "perf_counter"}
    assert not any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in forbidden for node in ast.walk(tree)
    )
