"""Strict durable payload reconstruction; synthetic signatures remain untrusted."""

import json
from dataclasses import replace
from datetime import timedelta

import pytest

from zatca_erpgulf.zatca_erpgulf import journal_storage as storage
from zatca_erpgulf.zatca_erpgulf.dispatch_journal import DispatchJournal
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_dispatch_journal import event
from zatca_erpgulf.zatca_erpgulf.tests.test_issuance_candidate import candidate, scope


@pytest.fixture(scope="module")
def prepared(certificates):
    return candidate(certificates[0])


def changed(content, change):
    body = json.loads(content)
    change(body)
    return json.dumps(body).encode()


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
def test_candidate_roundtrip_exact_bytes_scope_route_epoch_and_no_authority(certificates, environment, doctype, indicator):
    prepared = candidate(certificates[0], selected_scope=scope(environment=environment, doctype=doctype), indicator=indicator)
    encoded = storage.encode_candidate_context(prepared)
    restored = storage.decode_candidate_context(encoded, prepared.xml_bytes)
    assert restored == prepared
    assert restored.xml_bytes == prepared.xml_bytes
    assert storage.encode_candidate_context(restored) == encoded
    assert DispatchJournal(restored).journal_sha256 == DispatchJournal(prepared).journal_sha256
    assert restored.diagnostic_projection()["persistence_verified"] is False
    assert b"SignatureValue" not in encoded


def test_candidate_codec_does_not_normalize_unicode_names_or_xml(prepared):
    context = replace(prepared.context, scope=replace(prepared.context.scope, company_name="شركة / الشرق"))
    prepared = replace(prepared, context=context, xml_bytes=prepared.xml_bytes.replace(b"><", b">\n<"))
    restored = storage.decode_candidate_context(storage.encode_candidate_context(prepared), prepared.xml_bytes)
    assert restored == prepared
    assert restored.context.scope.company_name == "شركة / الشرق"


@pytest.mark.parametrize("kind", ["ATTEMPT_STARTED", "TRANSPORT_UNKNOWN", "HTTP_RESPONSE"])
@pytest.mark.parametrize("microseconds", [0, 1, 999999])
def test_event_roundtrip_response_bytes_none_or_empty_and_utc_precision(prepared, kind, microseconds):
    observed = event(prepared, kind)
    observed = replace(observed, occurred_at=observed.occurred_at + timedelta(microseconds=microseconds))
    if kind == "HTTP_RESPONSE":
        observed = replace(observed, response_bytes=b"")
    encoded = storage.encode_dispatch_event(observed)
    restored = storage.decode_dispatch_event(encoded, observed.response_bytes)
    assert restored == observed
    assert storage.encode_dispatch_event(restored) == encoded


@pytest.mark.parametrize("raw", [b"\xff\x00PRIVATE", b"{}", b"not JSON PRIVATE", b"<html>PRIVATE</html>"])
def test_receipt_codec_never_requires_json_body_or_loses_exact_bytes(prepared, raw):
    observed = event(prepared, "HTTP_RESPONSE", response_bytes=raw)
    encoded = storage.encode_dispatch_event(observed)
    assert b"PRIVATE" not in encoded
    assert storage.decode_dispatch_event(encoded, raw) == observed


@pytest.mark.parametrize("invalid", [None, {}, [], "candidate", object()])
def test_encode_rejects_untyped_claims(invalid):
    with pytest.raises(storage.JournalStorageError, match="^storage_candidate$"):
        storage.encode_candidate_context(invalid)
    with pytest.raises(storage.JournalStorageError, match="^storage_event$"):
        storage.encode_dispatch_event(invalid)


@pytest.mark.parametrize("content,code", [
    (None, "storage_payload_size"), ("{}", "storage_payload_size"), (b"", "storage_payload_size"),
    (b"{}{}", "storage_payload_json"), (b"ZATCA Response: {}", "storage_payload_json"),
    (b'{"schema_version":1,"schema_version":1}', "storage_payload_json"),
    (b'{"schema_version":NaN}', "storage_payload_json"),
    (b'{}', "storage_schema_version"), (b'{"schema_version":true}', "storage_schema_version"),
    (b'{"schema_version":2}', "storage_schema_version"),
])
def test_codec_rejects_malformed_or_future_versions(prepared, content, code):
    with pytest.raises(storage.JournalStorageError, match=f"^{code}$"):
        storage.decode_candidate_context(content, prepared.xml_bytes)
    with pytest.raises(storage.JournalStorageError, match=f"^{code}$"):
        storage.decode_dispatch_event(content, None)


@pytest.mark.parametrize("section", [None, "scope", "credential_epoch", "route"])
@pytest.mark.parametrize("mutation", ["unknown", "missing", "not_object"])
def test_candidate_exact_schema_rejects_extra_fields_and_secrets(prepared, section, mutation):
    def change(body):
        target = body if section is None else body[section]
        if mutation == "unknown":
            target["private_key"] = "PRIVATE"
        elif mutation == "missing":
            del target[next(iter(target))]
        elif section is not None:
            body[section] = []
        else:
            body.clear()

    payload = changed(storage.encode_candidate_context(prepared), change)
    with pytest.raises(storage.JournalStorageError) as error:
        storage.decode_candidate_context(payload, prepared.xml_bytes)
    assert error.value.code in ("storage_payload_fields", "storage_schema_version")
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("section,key,value", [
    ("scope", "environment", "Unknown"), ("scope", "issuance_version", True),
    ("scope", "seller_tax_id", "OTHER"), ("scope", "chain_id", "raw auth"),
    ("credential_epoch", "certificate_der_sha256", "a" * 64),
    ("credential_epoch", "public_key_sha256", "b" * 64),
    ("credential_epoch", "purpose", "compliance"),
    ("route", "url", "https://PRIVATE.invalid/wrong"),
    ("route", "required_credential", "otp"), ("route", "environment", "Sandbox"),
])
def test_candidate_revalidates_every_stored_declaration(prepared, section, key, value):
    payload = changed(storage.encode_candidate_context(prepared), lambda body: body[section].update({key: value}))
    with pytest.raises(storage.JournalStorageError, match="^storage_candidate_invalid$"):
        storage.decode_candidate_context(payload, prepared.xml_bytes)


@pytest.mark.parametrize("content", [None, "XML", bytearray(b"XML"), b"<PRIVATE/>", b"not XML"])
def test_candidate_revalidates_stored_xml(prepared, content):
    with pytest.raises(storage.JournalStorageError, match="^storage_candidate_invalid$"):
        storage.decode_candidate_context(storage.encode_candidate_context(prepared), content)


@pytest.mark.parametrize("key,value,code", [
    ("occurred_at", "2026-10-09T12:00:00", "storage_event_timestamp"),
    ("occurred_at", "2026-10-09T12:00:00.000000+03:00", "storage_event_invalid"),
    ("occurred_at", "2026-99-09T12:00:00.000000+00:00", "storage_event_invalid"),
    ("occurred_at", [], "storage_event_timestamp"),
    ("event_id", "PRIVATE", "storage_event_invalid"),
    ("sequence", True, "storage_event_invalid"),
    ("response_sha256", "0" * 64, "storage_response_fingerprint"),
    ("response_byte_length", True, "storage_response_fingerprint"),
    ("response_byte_length", 999, "storage_response_fingerprint"),
    ("http_status", 199, "storage_event_invalid"),
])
def test_event_metadata_is_revalidated_and_response_hash_recomputed(prepared, key, value, code):
    observed = event(prepared, "HTTP_RESPONSE")
    payload = changed(storage.encode_dispatch_event(observed), lambda body: body.update({key: value}))
    with pytest.raises(storage.JournalStorageError, match=f"^{code}$"):
        storage.decode_dispatch_event(payload, observed.response_bytes)


@pytest.mark.parametrize("mutation", ["unknown", "missing"])
def test_event_exact_schema(prepared, mutation):
    observed = event(prepared)
    body = json.loads(storage.encode_dispatch_event(observed))
    if mutation == "unknown":
        body["secret"] = "PRIVATE"
    else:
        del body["attempt_id"]
    with pytest.raises(storage.JournalStorageError, match="^storage_payload_fields$"):
        storage.decode_dispatch_event(json.dumps(body).encode(), None)


def test_changed_body_cannot_keep_old_metadata_fingerprint(prepared):
    observed = event(prepared, "HTTP_RESPONSE")
    with pytest.raises(storage.JournalStorageError, match="^storage_response_fingerprint$"):
        storage.decode_dispatch_event(storage.encode_dispatch_event(observed), b"OTHER")


def test_codec_bounds_are_enforced_both_directions(prepared, monkeypatch):
    observed = event(prepared)
    context_bytes, event_bytes = storage.encode_candidate_context(prepared), storage.encode_dispatch_event(observed)
    monkeypatch.setattr(storage, "MAX_CONTEXT_BYTES", len(context_bytes) - 1)
    monkeypatch.setattr(storage, "MAX_EVENT_BYTES", len(event_bytes) - 1)
    for call in (
        lambda: storage.encode_candidate_context(prepared),
        lambda: storage.decode_candidate_context(context_bytes, prepared.xml_bytes),
        lambda: storage.encode_dispatch_event(observed),
        lambda: storage.decode_dispatch_event(event_bytes, None),
    ):
        with pytest.raises(storage.JournalStorageError, match="^storage_payload_size$"):
            call()
