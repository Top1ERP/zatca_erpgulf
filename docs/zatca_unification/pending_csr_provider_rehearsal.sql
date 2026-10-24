-- PRIVATE REHEARSAL ONLY. No app hook, fixture or patch installs this table.
-- Marker correctness, key provenance and database account grants require audit.
CREATE TABLE zatca_pending_csr_storage_binding_v1 (
    storage_namespace CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    site VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    registration_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    key_id VARCHAR(80) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    PRIMARY KEY (storage_namespace)
) ENGINE=InnoDB;
