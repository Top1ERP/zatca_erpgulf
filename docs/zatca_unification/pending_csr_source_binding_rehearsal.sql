-- PRIVATE REHEARSAL ONLY. No app fixture, hook, patch or runtime installer.
-- Restricted business/source/backing fingerprints; NOT historical attestation.
CREATE TABLE zatca_pending_csr_source_binding_v1 (
    storage_namespace CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    draft_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    slot_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    flow_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    site VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    binding_bytes LONGBLOB NOT NULL,
    binding_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    envelope_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    PRIMARY KEY (storage_namespace, draft_id)
) ENGINE=InnoDB;
