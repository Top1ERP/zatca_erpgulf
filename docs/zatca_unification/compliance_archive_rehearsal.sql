-- Private owned-test-server DDL only, NOT a Frappe migration/install hook.
-- Dedicated archive keys: never reuse credential-bundle AES key material.
-- All CSR/route/request/response bytes are encrypted. No activation pointer.

CREATE TABLE zatca_compliance_archive_v1 (
    storage_namespace CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    exchange_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    sequence TINYINT UNSIGNED NOT NULL,
    parent_sequence TINYINT UNSIGNED NULL,
    version_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    manifest_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    observation_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    key_id VARCHAR(80) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    nonce BINARY(12) NOT NULL,
    ciphertext LONGBLOB NOT NULL,
    PRIMARY KEY (storage_namespace,exchange_id,sequence),
    UNIQUE KEY archive_nonce (storage_namespace,key_id,nonce),
    KEY archive_version (storage_namespace,version_id),
    CONSTRAINT archive_credential FOREIGN KEY (storage_namespace,version_id)
        REFERENCES zatca_credential_bundle_v1 (storage_namespace,version_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT archive_start FOREIGN KEY (storage_namespace,exchange_id,parent_sequence)
        REFERENCES zatca_compliance_archive_v1 (storage_namespace,exchange_id,sequence)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT archive_stage CHECK ((sequence=1 AND parent_sequence IS NULL)
                                   OR (sequence=2 AND parent_sequence=1)),
    CONSTRAINT archive_ciphertext_size CHECK (OCTET_LENGTH(ciphertext) BETWEEN 17 AND 16875582)
) ENGINE=InnoDB;
