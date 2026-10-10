"""Versioned storage codecs for protected exact bytes and frozen declarations.

No pickle, credentials, settings lookup, XML normalization or acceptance claims.
Decoding reconstructs the existing validated contracts and recomputes evidence.
Payloads are storage material, NOT safe log/UI projections or trusted provenance.
"""

import json
from datetime import datetime

from zatca_erpgulf.zatca_erpgulf.api_routing import ApiRoute
from zatca_erpgulf.zatca_erpgulf.artifact_evidence import ArtifactEvidenceError
from zatca_erpgulf.zatca_erpgulf.dispatch_journal import DispatchEvent
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import (
    DeclaredCredentialEpoch, IssuanceScope,
    PreparationContext, PreparedIssuanceCandidate,
)
from zatca_erpgulf.zatca_erpgulf.response_json import parse_wire_response


SCHEMA_VERSION = 1
MAX_CONTEXT_BYTES = 16 * 1024
MAX_EVENT_BYTES = 4 * 1024
SCOPE_FIELDS = (
    "doctype", "invoice_name", "company_name", "seller_tax_id", "environment",
    "chain_id", "legacy_issuing_unit", "issuance_version",
)
EPOCH_FIELDS = (
    "owner_doctype", "owner_name", "version_id", "certificate_der_sha256",
    "public_key_sha256", "purpose",
)
ROUTE_FIELDS = ("environment", "endpoint", "base_url_field", "required_credential", "url")
EVENT_FIELDS = (
    "event_id", "attempt_id", "sequence", "occurred_at", "kind", "key_sha256",
    "manifest_sha256", "http_status", "request_id", "unknown_cause",
    "response_sha256", "response_byte_length",
)


class JournalStorageError(ValueError):
    """Static code only: driver/parser exceptions may contain protected data."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _fields(value, names):
    return {name: getattr(value, name) for name in names}


def _keys(body, names):
    if type(body) is not dict or set(body) != set(names):
        raise JournalStorageError("storage_payload_fields")


def _encode(body, bound):
    content = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(content) > bound:
        raise JournalStorageError("storage_payload_size")
    return content


def _decode(content, bound):
    if type(content) is not bytes or not content or len(content) > bound:
        raise JournalStorageError("storage_payload_size")
    try:
        body = parse_wire_response(content)
    except ArtifactEvidenceError:
        raise JournalStorageError("storage_payload_json") from None
    if type(body.get("schema_version")) is not int or body["schema_version"] != SCHEMA_VERSION:
        raise JournalStorageError("storage_schema_version")
    return body


def encode_candidate_context(candidate):
    """Store declarations separately from the exact XML BLOB, never auth/key data."""
    if type(candidate) is not PreparedIssuanceCandidate:
        raise JournalStorageError("storage_candidate")
    context = candidate.context
    return _encode({
        "schema_version": SCHEMA_VERSION, "scope": _fields(context.scope, SCOPE_FIELDS),
        "credential_epoch": _fields(context.credential_epoch, EPOCH_FIELDS),
        "route": _fields(context.route, ROUTE_FIELDS),
        "source_snapshot_sha256": context.source_snapshot_sha256,
    }, MAX_CONTEXT_BYTES)


def decode_candidate_context(content, xml_bytes):
    """Rehydrate from stored declarations/bytes without today's ERP settings."""
    body = _decode(content, MAX_CONTEXT_BYTES)
    _keys(body, ("schema_version", "scope", "credential_epoch", "route", "source_snapshot_sha256"))
    for name, fields in (("scope", SCOPE_FIELDS), ("credential_epoch", EPOCH_FIELDS), ("route", ROUTE_FIELDS)):
        _keys(body[name], fields)
    try:
        context = PreparationContext(
            IssuanceScope(**body["scope"]), DeclaredCredentialEpoch(**body["credential_epoch"]),
            ApiRoute(**body["route"]), body["source_snapshot_sha256"],
        )
        return PreparedIssuanceCandidate(context, xml_bytes)
    except (TypeError, ValueError):
        raise JournalStorageError("storage_candidate_invalid") from None


def encode_dispatch_event(event):
    """Response bytes stay in a separate nullable BLOB; metadata binds their hash."""
    if type(event) is not DispatchEvent:
        raise JournalStorageError("storage_event")
    body = event.diagnostic_projection()
    body["occurred_at"] = event.occurred_at.isoformat(timespec="microseconds")
    return _encode({"schema_version": SCHEMA_VERSION, **body}, MAX_EVENT_BYTES)


def decode_dispatch_event(content, response_bytes):
    body = _decode(content, MAX_EVENT_BYTES)
    _keys(body, ("schema_version", *EVENT_FIELDS))
    timestamp = body["occurred_at"]
    if type(timestamp) is not str or len(timestamp) != 32:
        raise JournalStorageError("storage_event_timestamp")
    try:
        occurred_at = datetime.fromisoformat(timestamp)
        if occurred_at.isoformat(timespec="microseconds") != timestamp:
            raise ValueError
        event = DispatchEvent(
            **{name: body[name] for name in EVENT_FIELDS if name not in (
                "occurred_at", "response_sha256", "response_byte_length",
            )}, occurred_at=occurred_at, response_bytes=response_bytes,
        )
    except (TypeError, ValueError):
        raise JournalStorageError("storage_event_invalid") from None
    if (
        type(body["response_byte_length"]) is not int
        or body["response_byte_length"] != event.response_byte_length
        or body["response_sha256"] != event.response_sha256
    ):
        raise JournalStorageError("storage_response_fingerprint")
    return event
