"""Append-only encrypted request/receipt repository on an explicit transaction.

Not a dispatcher, outbox/lease, installer or active-CSID gate. Preserve and commit
the prepared request BEFORE future HTTP; release all DB locks before networking.
This repository never sends HTTP or commits/rolls back. After ANY error, roll back
the whole caller transaction and discard the handle. Never log SQL parameters.
"""

from contextlib import contextmanager

from zatca_erpgulf.zatca_erpgulf.compliance_archive import (
    MAX_ARCHIVE_BYTES, ComplianceArchiveCipher, ComplianceArchiveError,
    ComplianceArchiveHistory, SealedComplianceObservation, _reference,
)
from zatca_erpgulf.zatca_erpgulf.credential_bundle import CredentialBundleCipher, CredentialSlot
from zatca_erpgulf.zatca_erpgulf.credential_bundle_repository import MariaDBCredentialBundleRepository
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import _canonical_uuid


class MariaDBComplianceArchiveRepository:
    def __init__(self, connection, storage_namespace, bundle_cipher, archive_cipher):
        _reference(storage_namespace, "archive_namespace", _canonical_uuid)
        if type(bundle_cipher) is not CredentialBundleCipher or type(archive_cipher) is not ComplianceArchiveCipher:
            raise ComplianceArchiveError("archive_resource_binding")
        # Key domains must be independent even when key IDs differ. This protects
        # the two local stores; a deployment must also enforce global isolation.
        if set(bundle_cipher._keys.values()) & set(archive_cipher._keys.values()):
            raise ComplianceArchiveError("archive_key_domain_reuse")
        self._connection, self._namespace = connection, storage_namespace
        self._bundle_cipher, self._archive_cipher = bundle_cipher, archive_cipher
        self._failed = False

    def __repr__(self):
        return "MariaDBComplianceArchiveRepository(<protected explicit transaction>)"

    def __reduce_ex__(self, protocol):
        raise ComplianceArchiveError("archive_not_pickleable")

    @contextmanager
    def _operation(self):
        if self._failed:
            raise ComplianceArchiveError("archive_transaction_unusable")
        try:
            yield
        except ComplianceArchiveError:
            self._failed = True
            raise
        except Exception as error:
            self._failed = True
            number = error.args[0] if error.args else None
            code = {1062: "archive_unique_conflict", 1205: "archive_lock_timeout", 1213: "archive_deadlock"}.get(number, "archive_storage_error") if type(number) is int else "archive_storage_error"
            raise ComplianceArchiveError(code) from None

    def _bundle(self, slot, version_id, expected_manifest=None):
        if type(slot) is not CredentialSlot or slot.purpose != "compliance":
            raise ComplianceArchiveError("archive_slot")
        _reference(version_id, "archive_version", _canonical_uuid)
        stored = MariaDBCredentialBundleRepository(self._connection, self._namespace, self._bundle_cipher).load(slot, version_id)
        if expected_manifest is not None and stored.manifest_bytes != expected_manifest.encode():
            raise ComplianceArchiveError("archive_manifest_binding")
        return stored.manifest

    def _preflight(self, sealed, sequence):
        if (type(sealed) is not SealedComplianceObservation or sealed.storage_namespace != self._namespace
                or sealed.sequence != sequence):
            raise ComplianceArchiveError("archive_namespace_or_stage")
        return self._archive_cipher.open(sealed)

    def prepare(self, sealed):
        """Capture request only, not proof of dispatch; exact envelope redelivery only."""
        with self._operation():
            start = self._preflight(sealed, 1)
            self._bundle(start.requirements.manifest.slot, sealed.version_id, start.requirements.manifest)
            with self._connection.cursor() as cursor:
                self._insert(cursor, sealed)
                stored = self._load_row(cursor, sealed.exchange_id, 1)
                if stored != sealed:
                    raise ComplianceArchiveError("archive_record_conflict")
                return stored

    def append_receipt(self, sealed):
        """Add one immutable response to the exact captured request; never replace."""
        with self._operation():
            receipt = self._preflight(sealed, 2)
            self._bundle(receipt.requirements.manifest.slot, sealed.version_id, receipt.requirements.manifest)
            with self._connection.cursor() as cursor:
                start = self._archive_cipher.open(self._load_row(cursor, sealed.exchange_id, 1))
                ComplianceArchiveHistory(start, receipt)
                self._insert(cursor, sealed)
                stored = self._load_row(cursor, sealed.exchange_id, 2)
                if stored != sealed:
                    raise ComplianceArchiveError("archive_record_conflict")
                return stored

    def load(self, slot, version_id, exchange_id):
        """Explicit scope/identity only; no latest-version or latest-attempt fallback."""
        with self._operation():
            _reference(exchange_id, "archive_exchange_id", _canonical_uuid)
            manifest = self._bundle(slot, version_id)
            with self._connection.cursor() as cursor:
                start = self._archive_cipher.open(self._load_row(cursor, exchange_id, 1))
                if start.requirements.manifest != manifest:
                    raise ComplianceArchiveError("archive_manifest_binding")
                sealed = self._load_row(cursor, exchange_id, 2, optional=True)
                receipt = None if sealed is None else self._archive_cipher.open(sealed)
                return ComplianceArchiveHistory(start, receipt)

    def _insert(self, cursor, sealed):
        cursor.execute(
            "INSERT INTO zatca_compliance_archive_v1 "
            "(storage_namespace,exchange_id,sequence,parent_sequence,version_id,manifest_sha256,"
            "observation_sha256,key_id,nonce,ciphertext) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE exchange_id=exchange_id",
            (self._namespace, sealed.exchange_id, sealed.sequence, None if sealed.sequence == 1 else 1,
             sealed.version_id, sealed.manifest_sha256, sealed.observation_sha256,
             sealed.key_id, sealed.nonce, sealed.ciphertext),
        )

    def _load_row(self, cursor, exchange_id, sequence, *, optional=False):
        cursor.execute(
            "SELECT version_id,manifest_sha256,observation_sha256,key_id,nonce,SUBSTRING(ciphertext,1,%s) "
            "FROM zatca_compliance_archive_v1 WHERE storage_namespace=%s AND exchange_id=%s AND sequence=%s FOR UPDATE",
            (MAX_ARCHIVE_BYTES + 17, self._namespace, exchange_id, sequence),
        )
        row = cursor.fetchone()
        if row is None:
            if optional:
                return None
            raise ComplianceArchiveError("archive_missing")
        if type(row) is not tuple or len(row) != 6:
            raise ComplianceArchiveError("archive_row_format")
        version, manifest_hash, observation_hash, key_id, nonce, ciphertext = row
        sealed = SealedComplianceObservation(self._namespace, exchange_id, sequence, version,
                                             manifest_hash, observation_hash, key_id, nonce, ciphertext)
        self._archive_cipher.open(sealed)
        return sealed
