"""Explicit-connection append-only encrypted credential STAGING repository.

No active pointer, schema installation, configuration discovery, transaction
commit/rollback, expiry clock, issuance HTTP or migration. Returning a staged
envelope does not prove commit, remote provenance or activation. After ANY error,
roll back the whole transaction and discard the repository. Never log parameters.
"""

from contextlib import contextmanager

from zatca_erpgulf.zatca_erpgulf.credential_bundle import (
    MAX_MANIFEST_BYTES, MAX_PLAINTEXT_BYTES, CredentialBundleCipher,
    CredentialBundleError, CredentialSlot, SealedCredentialBundle, _validate,
)
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import _canonical_uuid


class MariaDBCredentialBundleRepository:
    def __init__(self, connection, storage_namespace, cipher):
        _validate(storage_namespace, "bundle_namespace", _canonical_uuid)
        if type(cipher) is not CredentialBundleCipher:
            raise CredentialBundleError("bundle_cipher")
        self._connection, self._namespace, self._cipher = connection, storage_namespace, cipher
        self._failed = False

    @contextmanager
    def _operation(self):
        if self._failed:
            raise CredentialBundleError("bundle_transaction_unusable")
        try:
            # Preflight is inside this boundary so invalid arguments also poison
            # an already-used transaction. Caller must not commit partial work.
            yield
        except CredentialBundleError:
            self._failed = True
            raise
        except Exception as error:
            self._failed = True
            number = error.args[0] if error.args else None
            code = {1062: "bundle_unique_conflict", 1205: "bundle_lock_timeout", 1213: "bundle_deadlock"}.get(number, "bundle_database_error") if type(number) is int else "bundle_database_error"
            raise CredentialBundleError(code) from None

    @staticmethod
    def _transaction(cursor):
        cursor.execute("SELECT @@session.autocommit")
        if cursor.fetchone() != (0,):
            raise CredentialBundleError("bundle_autocommit")

    def stage(self, sealed):
        """Store exact envelope once. Identical redelivery does not overwrite.

        Resealing under the same version generates a different envelope and is a
        conflict, even if public certificate fingerprints remain unchanged.
        Production parent checks enforce local flow consistency, not completion.
        """
        with self._operation():
            if type(sealed) is not SealedCredentialBundle or sealed.storage_namespace != self._namespace:
                raise CredentialBundleError("bundle_namespace_or_envelope")
            manifest = sealed.manifest
            self._cipher.open(sealed, observed_at=manifest.prepared_at)
            with self._connection.cursor() as cursor:
                self._transaction(cursor)
                if manifest.parent_compliance_version_id is not None:
                    # Lock parent first in a fixed dependency order. No activation
                    # or chain lock is taken and no HTTP occurs under these locks.
                    parent = self._load(cursor, manifest.parent_compliance_version_id).manifest
                    if (
                        parent.slot != CredentialSlot(manifest.slot.owner_doctype, manifest.slot.owner_name,
                                                      manifest.slot.environment, "compliance")
                        or parent.flow_id != manifest.flow_id
                        or parent.compliance_request_id != manifest.compliance_request_id
                        or parent.public_key_sha256 != manifest.public_key_sha256
                        or parent.company_name != manifest.company_name or parent.source_kind != manifest.source_kind
                    ):
                        raise CredentialBundleError("bundle_parent_mismatch")
                cursor.execute(
                    "INSERT INTO zatca_credential_bundle_v1 "
                    "(storage_namespace,version_id,slot_sha256,environment,purpose,flow_id,parent_version_id,"
                    "manifest_bytes,manifest_sha256,key_id,nonce,ciphertext) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON DUPLICATE KEY UPDATE version_id=version_id",
                    (self._namespace, manifest.version_id, manifest.slot.sha256, manifest.slot.environment,
                     manifest.slot.purpose, manifest.flow_id, manifest.parent_compliance_version_id,
                     sealed.manifest_bytes, sealed.manifest_sha256, sealed.key_id, sealed.nonce, sealed.ciphertext),
                )
                stored = self._load(cursor, manifest.version_id, missing_code="bundle_identity_collision")
                if stored != sealed:
                    raise CredentialBundleError("bundle_version_conflict")
                return stored

    def load(self, slot, version_id):
        """Require exact purpose/environment/owner AND version; never select latest."""
        with self._operation():
            if type(slot) is not CredentialSlot:
                raise CredentialBundleError("bundle_slot")
            _validate(version_id, "bundle_version", _canonical_uuid)
            with self._connection.cursor() as cursor:
                self._transaction(cursor)
                sealed = self._load(cursor, version_id)
                if sealed.manifest.slot != slot:
                    raise CredentialBundleError("bundle_slot_mismatch")
                return sealed

    def _load(self, cursor, version_id, *, missing_code="bundle_missing"):
        cursor.execute(
            "SELECT slot_sha256,environment,purpose,flow_id,parent_version_id,"
            "SUBSTRING(manifest_bytes,1,%s),manifest_sha256,key_id,nonce,SUBSTRING(ciphertext,1,%s) "
            "FROM zatca_credential_bundle_v1 WHERE storage_namespace=%s AND version_id=%s FOR UPDATE",
            (MAX_MANIFEST_BYTES + 1, MAX_PLAINTEXT_BYTES + 17, self._namespace, version_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise CredentialBundleError(missing_code)
        if type(row) is not tuple or len(row) != 10:
            raise CredentialBundleError("bundle_row_format")
        slot_hash, environment, purpose, flow, parent, metadata, metadata_hash, key_id, nonce, ciphertext = row
        sealed = SealedCredentialBundle(self._namespace, metadata, key_id, nonce, ciphertext)
        manifest = sealed.manifest
        if (
            manifest.version_id != version_id or manifest.slot.sha256 != slot_hash
            or manifest.slot.environment != environment or manifest.slot.purpose != purpose
            or manifest.flow_id != flow or manifest.parent_compliance_version_id != parent
            or sealed.manifest_sha256 != metadata_hash
        ):
            raise CredentialBundleError("bundle_row_fingerprint")
        # Authentication is checked before any envelope is returned, even if an
        # attacker rewrote all public hashes. Historical preparation time allows
        # staging audit; actual use must open with an explicit current UTC time.
        self._cipher.open(sealed, observed_at=manifest.prepared_at)
        return sealed
