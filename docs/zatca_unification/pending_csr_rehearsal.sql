-- PRIVATE REHEARSAL ONLY: never installed by an app fixture, patch or hook.
-- The runtime repository owns no connection or DDL and never commits.
CREATE TABLE zatca_pending_csr_v1 (
    storage_namespace CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    draft_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    slot_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    flow_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    manifest_bytes LONGBLOB NOT NULL,
    manifest_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    key_id VARCHAR(80) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    nonce BINARY(12) NOT NULL,
    ciphertext LONGBLOB NOT NULL,
    PRIMARY KEY (storage_namespace, draft_id),
    UNIQUE KEY pending_csr_nonce (storage_namespace, key_id, nonce)
) ENGINE=InnoDB;
