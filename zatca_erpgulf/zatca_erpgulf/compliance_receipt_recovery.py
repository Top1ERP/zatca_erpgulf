"""Explicit LOCAL persistence recovery; no transport, clock or resealing.

This internal primitive is NOT a permissioned operator endpoint. Authorize the
tenant/role/saved owner and reviewed resource provenance before constructing it.
Never whitelist, queue, pickle, log or expose the protected input/output. It
stores supplied observations, not proven remote acceptance or activation rights.
"""

from dataclasses import replace

from zatca_erpgulf.zatca_erpgulf.compliance_archive import ComplianceArchiveCipher
from zatca_erpgulf.zatca_erpgulf.compliance_archive_repository import MariaDBComplianceArchiveRepository
from zatca_erpgulf.zatca_erpgulf.compliance_capture import ComplianceCaptureResult, _owned_transaction
from zatca_erpgulf.zatca_erpgulf.credential_bundle import CredentialBundleCipher, _validate
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import _canonical_uuid


class ComplianceReceiptRecoveryError(ValueError):
    """Static internal code only; no parser/driver/key details for operators."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _validate_recovery_input(result, storage_namespace):
    """Pure protected-envelope binding only, NOT ciphertext authentication.

    Permissioned adapters can reject wrong stage/scope before acquiring keys.
    Ciphertext authentication is still mandatory before any SQL acquisition.
    """
    try:
        if type(result) is not ComplianceCaptureResult:
            raise ComplianceReceiptRecoveryError("recovery_input")
        result.__post_init__()
        if (result.state != "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY"
                or result.observation.requirements.storage_namespace != storage_namespace):
            raise ComplianceReceiptRecoveryError("recovery_input")
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        raise ComplianceReceiptRecoveryError("recovery_input")
    return result.observation


class ComplianceReceiptRecovery:
    """One owned transaction for one exact retained uncertain-commit receipt.

    There is deliberately NO transport/clock dependency, current credential
    selection or active-CSID write. Historical archive authentication does not
    require the certificate to be valid today; it grants no permission to send.
    The factory must return a fresh owned non-autocommit connection, never a
    shared Frappe handle. Unknown commit/close preserves the exact original input.
    No automatic retry or fallback to another exchange/version/key exists.
    """

    def __init__(self, storage_namespace, bundle_cipher, archive_cipher, *, connection_factory, source_guard=None):
        try:
            _validate(storage_namespace, "recovery_namespace", _canonical_uuid)
            if (type(bundle_cipher) is not CredentialBundleCipher or type(archive_cipher) is not ComplianceArchiveCipher
                    or set(bundle_cipher._keys.values()) & set(archive_cipher._keys.values())
                    or not callable(connection_factory)
                    or (source_guard is not None and not callable(source_guard))):
                raise ComplianceReceiptRecoveryError("recovery_dependencies")
        except ValueError:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise ComplianceReceiptRecoveryError("recovery_dependencies")
        self._namespace, self._bundle_cipher, self._archive_cipher = storage_namespace, bundle_cipher, archive_cipher
        self._factory = connection_factory
        self._source_guard = source_guard

    def __repr__(self):
        return "ComplianceReceiptRecovery(<protected explicit local dependencies>)"

    def __reduce_ex__(self, protocol):
        raise ComplianceReceiptRecoveryError("recovery_not_pickleable")

    def persist_receipt(self, result):
        """Authenticate before acquisition; persist only identical ciphertext.

        Only RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY is accepted. A successful owned
        commit AND close advances local storage state, never any authority flag.
        Storage failure returns the SAME protected result for reviewed recovery.
        Interruptions propagate after cleanup; callers must retain their input.
        """
        try:
            _validate_recovery_input(result, self._namespace)
            start = self._archive_cipher.open(result.start_envelope)
            receipt = self._archive_cipher.open(result.receipt_envelope)
            if (receipt != result.observation or start != replace(
                    receipt, http_status=None, response_bytes=None, received_at=None)):
                raise ComplianceReceiptRecoveryError("recovery_binding")
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise ComplianceReceiptRecoveryError("recovery_input")

        def persist(connection):
            # Optional saved-source policy uses this SAME owned transaction;
            # recheck after storage and before commit without adding any send.
            if self._source_guard is not None and self._source_guard(connection, result) is not True:
                raise ComplianceReceiptRecoveryError("recovery_source_guard")
            stored = MariaDBComplianceArchiveRepository(connection, self._namespace, self._bundle_cipher,
                self._archive_cipher).append_receipt(result.receipt_envelope, expected_start=result.start_envelope)
            if self._source_guard is not None and self._source_guard(connection, result) is not True:
                raise ComplianceReceiptRecoveryError("recovery_source_guard")
            return stored
        try:
            _owned_transaction(self._factory, persist)
        except Exception:
            return result
        return replace(result, state="RECEIPT_CAPTURED_OBSERVATION")
