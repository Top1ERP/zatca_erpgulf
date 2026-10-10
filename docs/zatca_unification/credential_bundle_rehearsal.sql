-- Private development rehearsal only. NOT an install hook/Frappe migration.
-- Ciphertext only; caller owns key management, access and transaction boundaries.
-- There is deliberately NO active credential pointer or activation operation.

CREATE TABLE zatca_credential_bundle_v1 (
    storage_namespace CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    slot_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    environment VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    purpose VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    flow_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    parent_version_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
    manifest_bytes VARBINARY(8192) NOT NULL,
    manifest_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    key_id VARCHAR(80) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    nonce BINARY(12) NOT NULL,
    ciphertext MEDIUMBLOB NOT NULL,
    PRIMARY KEY (storage_namespace, version_id),
    UNIQUE KEY bundle_nonce (storage_namespace,key_id,nonce),
    KEY bundle_slot (storage_namespace,slot_sha256),
    CONSTRAINT bundle_parent FOREIGN KEY (storage_namespace,parent_version_id)
        REFERENCES zatca_credential_bundle_v1 (storage_namespace,version_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT bundle_ciphertext_size CHECK (OCTET_LENGTH(ciphertext) BETWEEN 17 AND 1048592),
    CONSTRAINT bundle_purpose CHECK (purpose IN ('compliance','production')),
    CONSTRAINT bundle_environment CHECK (environment IN ('Sandbox','Simulation','Production')),
    CONSTRAINT bundle_parent_purpose CHECK (
        (purpose='compliance' AND parent_version_id IS NULL)
        OR (purpose='production' AND parent_version_id IS NOT NULL)
    )
) ENGINE=InnoDB;
