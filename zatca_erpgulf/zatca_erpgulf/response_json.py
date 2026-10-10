"""Shared bounded JSON primitives; wire bodies are not legacy display text."""

import json
import math

from zatca_erpgulf.zatca_erpgulf.artifact_evidence import ArtifactEvidenceError


MAX_RESPONSE_BYTES = 8 * 1024 * 1024
JSON_SPACING = " \t\r\n"


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArtifactEvidenceError("response_duplicate_key")
        result[key] = value
    return result


def _integer(value):
    if len(value) > 64:
        raise ArtifactEvidenceError("response_number")
    return int(value)


def _constant(value):
    raise ArtifactEvidenceError("response_number")


def _float(value):
    if len(value) > 64:
        raise ArtifactEvidenceError("response_number")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ArtifactEvidenceError("response_number")
    return parsed


def response_decoder():
    """Reject duplicate keys and unbounded/nonfinite numbers in both readers."""
    return json.JSONDecoder(
        object_pairs_hook=_pairs, parse_int=_integer, parse_float=_float,
        parse_constant=_constant,
    )


def parse_wire_response(content):
    """Read exactly one UTF-8 JSON object; never repair/wrap a received body.

    Known historical labels, HTML spacing and multiple objects are not an HTTP
    response contract. The journal retains exact bytes separately from parsing.
    """
    if type(content) is not bytes:
        raise ArtifactEvidenceError("response_bytes_required")
    if not content or len(content) > MAX_RESPONSE_BYTES:
        raise ArtifactEvidenceError("response_size")
    try:
        text = content.decode("utf-8").lstrip(JSON_SPACING)
    except UnicodeDecodeError:
        raise ArtifactEvidenceError("response_encoding") from None
    try:
        body, end = response_decoder().raw_decode(text)
    except (json.JSONDecodeError, RecursionError):
        raise ArtifactEvidenceError("response_json") from None
    if type(body) is not dict:
        raise ArtifactEvidenceError("response_object")
    if text[end:].strip(JSON_SPACING):
        raise ArtifactEvidenceError("response_trailing_data")
    return body
