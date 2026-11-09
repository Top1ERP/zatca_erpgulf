"""Byte/boundary parity for accelerated privately verified metadata subtrees."""

from decimal import Decimal
import json

import pytest

from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial
from zatca_erpgulf.zatca_erpgulf import source_metadata as metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta, project


def declaration(default=None):
    raw = AppliedMeta("Sales Invoice", ("grand_total",))
    raw.definitions["grand_total"].values.update(fieldtype="Currency", default=default, precision="2")
    return project(raw)


@pytest.mark.parametrize("value", [None, "", False, 0, "0", -0.0, Decimal("-0.000"),
    "العربية 😀", "\0\n\t\"\\", "x" * 8192])
def test_field_and_parent_canonical_bytes_are_unchanged(value):
    result = declaration(value)
    body = json.loads(result._payload)
    assert result._payload == json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    for name, values in body["fields"]:
        if values == ["absent"]: continue
        assert result.get_field(name)._payload == financial._canonical(values)
    assert metadata._pin_metadata(result) == result


@pytest.mark.parametrize("fault", ["oversize", "noncanonical", "invalid_scalar", "field_order"])
def test_parent_and_field_validation_are_not_bypassed(monkeypatch, fault):
    result = declaration("SYNTHETIC")
    body = json.loads(result._payload)
    if fault == "oversize":
        monkeypatch.setattr(financial, "MAX_PAYLOAD_BYTES", len(result._payload) - 1)
        payload = result._payload
    elif fault == "noncanonical": payload = json.dumps(body).encode()
    else:
        properties = dict(body["fields"])["grand_total"]
        if fault == "invalid_scalar": properties[0][1] = ["str", "Password"]
        else: properties.reverse()
        payload = financial._canonical(body)
    with pytest.raises(metadata.SourceMetadataError) as caught: metadata.SourceMetadata(result.name, payload)
    assert str(caught.value) == "source_metadata_projection" and caught.value.__context__ is None


def test_no_unverified_parent_reaches_the_one_shot_encoder(monkeypatch):
    result = declaration("x" * 200)
    original = financial._canonical_encoder
    one_shot = []
    def encoder():
        instance = original()
        encode = instance.encode
        def record(value):
            one_shot.append(True);return encode(value)
        instance.encode = record
        return instance
    monkeypatch.setattr(financial, "_canonical_encoder", encoder)
    monkeypatch.setattr(financial, "MAX_PAYLOAD_BYTES", 100)
    with pytest.raises(metadata.SourceMetadataError): metadata.SourceMetadata(result.name, result._payload)
    assert one_shot == []


def test_independent_field_payloads_still_require_streamed_canonical_equality():
    result = declaration()
    properties = json.loads(result.get_field("grand_total")._payload)
    with pytest.raises(metadata.SourceMetadataError):
        metadata.SourceFieldDefinition("grand_total", json.dumps(properties).encode())
