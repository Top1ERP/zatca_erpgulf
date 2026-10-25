"""Protected pre-build tickets and caller-transaction no-rebuild holds.

No installation, commit, allocator, expiry/release, signing or authority client.
A pending ticket is NOT a build lease: reserve must commit/close before a
one-shot owner builds. All fresh workers may inspect/reconcile only, never
automatically reuse a ticket to rebuild after uncertainty.
"""

import hashlib
import json
from dataclasses import dataclass, field, replace

from .issuance_candidate import (
    _canonical_uuid, _sha256, compare_prepared_candidates, preparation_source_sha256,
)
from .issuance_preparation import PreparationTicket
from .issuing_chain import IssuingChainError, _check
from .issuing_chain_repository import (
    MariaDBIssuingChainRepository, decode_chain_state, encode_chain_state,
)
from .journal_storage import (
    JournalStorageError, _decode, _encode, _keys,
    decode_preparation_context, encode_preparation_context,
)


MAX_TICKET_BYTES = 40960


def encode_preparation_ticket(ticket):
    if type(ticket) is not PreparationTicket:
        raise IssuingChainError("preparation_ticket")
    return _encode({"schema_version": 1, "predecessor": json.loads(encode_chain_state(ticket.predecessor)),
        "context": json.loads(encode_preparation_context(ticket.context)),
        "invoice_uuid": ticket.invoice_uuid}, MAX_TICKET_BYTES)


def decode_preparation_ticket(content):
    """Strict bounded reconstruction, never a current-settings fallback."""
    try:
        body = _decode(content, MAX_TICKET_BYTES)
        _keys(body, ("schema_version", "predecessor", "context", "invoice_uuid"))
        ticket = PreparationTicket(
            decode_chain_state(_encode(body["predecessor"], MAX_TICKET_BYTES)),
            decode_preparation_context(_encode(body["context"], MAX_TICKET_BYTES)), body["invoice_uuid"])
        if encode_preparation_ticket(ticket) != content:
            raise IssuingChainError("preparation_ticket_noncanonical")
        return ticket
    except (JournalStorageError, TypeError, ValueError, KeyError):
        raise IssuingChainError("preparation_ticket_invalid") from None


@dataclass(frozen=True, repr=False)
class PreparationHold:
    """Protected local binding, not custody/signature/enrollment/commit proof."""

    hold_id: str
    ticket: PreparationTicket = field(repr=False)
    original_manifest_sha256: str | None = None
    ticket_sha256: str = field(init=False)

    def __post_init__(self):
        _check(self.hold_id, "preparation_hold_id", _canonical_uuid)
        if type(self.ticket) is not PreparationTicket:
            raise IssuingChainError("preparation_ticket")
        # Rebuild nested declarations as well; frozen objects are not a sandbox.
        content = encode_preparation_ticket(self.ticket)
        if decode_preparation_ticket(content) != self.ticket:
            raise IssuingChainError("preparation_ticket_invalid")
        object.__setattr__(self, "ticket_sha256", hashlib.sha256(content).hexdigest())
        if self.original_manifest_sha256 is not None:
            _check(self.original_manifest_sha256, "preparation_original_manifest", _sha256)

    @property
    def source_sha256(self):
        return preparation_source_sha256(self.ticket.context.scope)

    def __repr__(self):
        return "<PreparationHold " + ("PENDING_NO_REBUILD" if self.original_manifest_sha256 is None else "ORIGINAL_RECORDED") + ">"

    def __reduce__(self):
        raise TypeError("preparation_hold_not_serializable")


class MariaDBPreparationHoldRepository:
    """Same explicit connection/namespace as the chain and exact-original store.

    reserve() is STRICT, including equal redelivery. load()/complete() compare
    exact retained tickets; neither permits a fresh build. No automatic repair
    of partial records, pending timeout, identity release or borrowed-site lookup.
    """

    def __init__(self, connection, storage_namespace):
        self._chain = MariaDBIssuingChainRepository(connection, storage_namespace)
        self._namespace = storage_namespace

    def __repr__(self):
        return "<MariaDBPreparationHoldRepository explicit protected transaction>"

    def __reduce__(self):
        raise TypeError("preparation_repository_not_serializable")

    def reserve(self, registration, context, invoice_uuid, hold_id, *, guard):
        with self._chain._guard():
            _check(hold_id, "preparation_hold_id", _canonical_uuid)
            _check(invoice_uuid, "preparation_uuid", _canonical_uuid)
            if not callable(guard):
                raise IssuingChainError("preparation_callbacks")
            before = self._chain.begin_preparation(registration, context)
            hold = PreparationHold(hold_id, PreparationTicket(before, context, invoice_uuid))
            if guard(hold.ticket) is not True:
                raise IssuingChainError("preparation_source_guard")
            scope = context.scope
            with self._chain._cursor() as cursor:
                cursor.execute("INSERT INTO zatca_preparation_hold_v1 "
                    "(storage_namespace,hold_id,chain_id,active_chain_id,source_sha256,environment,"
                    "invoice_uuid,candidate_key_sha256,ticket_bytes,ticket_sha256,original_manifest_sha256) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL)",
                    (self._namespace, hold_id, scope.chain_id, scope.chain_id, hold.source_sha256,
                     scope.environment, invoice_uuid, hold.ticket.key_sha256,
                     encode_preparation_ticket(hold.ticket), hold.ticket_sha256))
            return hold

    def _load(self, cursor, expected):
        if type(expected) is not PreparationHold:
            raise IssuingChainError("preparation_hold")
        cursor.execute("SELECT chain_id,active_chain_id,source_sha256,environment,invoice_uuid,"
            "candidate_key_sha256,SUBSTRING(ticket_bytes,1,%s),ticket_sha256,original_manifest_sha256 "
            "FROM zatca_preparation_hold_v1 WHERE storage_namespace=%s AND hold_id=%s FOR UPDATE",
            (MAX_TICKET_BYTES + 1, self._namespace, expected.hold_id))
        row = cursor.fetchone()
        if type(row) is not tuple or len(row) != 9:
            raise IssuingChainError("preparation_hold_missing_or_invalid")
        chain_id, active, source, environment, uuid, key, payload, digest, manifest = row
        hold = PreparationHold(expected.hold_id, decode_preparation_ticket(payload), manifest)
        scope = hold.ticket.context.scope
        if (hold.ticket != expected.ticket or digest != hold.ticket_sha256
            or chain_id != scope.chain_id or source != hold.source_sha256 or environment != scope.environment
            or uuid != hold.ticket.invoice_uuid or key != hold.ticket.key_sha256
            or active != (chain_id if manifest is None else None)
            or (expected.original_manifest_sha256 is not None and manifest != expected.original_manifest_sha256)):
            raise IssuingChainError("preparation_hold_conflict")
        if manifest is not None:
            original = self._chain._artifacts.load(key).candidate
            hold.ticket.validate_candidate(original)
            if original.manifest_sha256 != manifest:
                raise IssuingChainError("preparation_original_conflict")
        elif self._chain._has_candidate(cursor, key):
            raise IssuingChainError("preparation_partial_original")
        return hold

    def load(self, expected):
        """Inspect an exact retained hold; pending never grants another build."""
        with self._chain._guard():
            if type(expected) is not PreparationHold:
                raise IssuingChainError("preparation_hold")
            current = self._chain.load(expected.ticket.predecessor.registration)
            with self._chain._cursor() as cursor:
                stored = self._load(cursor, expected)
                if stored.original_manifest_sha256 is None and current != stored.ticket.predecessor:
                    raise IssuingChainError("preparation_predecessor_conflict")
                return stored

    def complete(self, expected, candidate):
        """Record exact original/head AND complete hold in ONE owner transaction."""
        with self._chain._guard():
            if type(expected) is not PreparationHold:
                raise IssuingChainError("preparation_hold")
            expected.ticket.validate_candidate(candidate)
            current = self._chain.load(expected.ticket.predecessor.registration)
            with self._chain._cursor() as cursor:
                stored = self._load(cursor, expected)
                if stored.original_manifest_sha256 is not None:
                    original = self._chain._artifacts.load(stored.ticket.key_sha256).candidate
                    if compare_prepared_candidates(original, candidate):
                        raise IssuingChainError("preparation_original_conflict")
                    return stored, current  # Exact review; never rewind a newer head.
                if current != stored.ticket.predecessor:
                    raise IssuingChainError("preparation_predecessor_conflict")
                after = self._chain._record(current, candidate, stored.hold_id)
                cursor.execute("UPDATE zatca_preparation_hold_v1 SET original_manifest_sha256=%s,active_chain_id=NULL "
                    "WHERE storage_namespace=%s AND hold_id=%s AND ticket_sha256=%s AND original_manifest_sha256 IS NULL",
                    (candidate.manifest_sha256, self._namespace, stored.hold_id, stored.ticket_sha256))
                if cursor.rowcount != 1:
                    raise IssuingChainError("preparation_hold_compare_and_swap")
                return replace(stored, original_manifest_sha256=candidate.manifest_sha256), after
