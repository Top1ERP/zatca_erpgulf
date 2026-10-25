-- OWNED PRIVATE DEVELOPMENT DATABASE ONLY. Not an installer or migration.
-- Enrollment declarations require independent source/tenant/epoch verification.
-- No production service, existing credential/counter or Company field uses it.
CREATE TABLE zatca_issuing_chain_v1 (
    storage_namespace CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    chain_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    registration_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    environment VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    certificate_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    payload_bytes VARBINARY(16384) NOT NULL,
    state_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    last_icv VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    PRIMARY KEY (storage_namespace,chain_id),
    UNIQUE KEY chain_registration (storage_namespace,registration_id),
    UNIQUE KEY chain_certificate (storage_namespace,environment,certificate_sha256)
) ENGINE=InnoDB;

-- Independent key custody is external. This stores ciphertext ONLY; staging
-- never completes a preparation hold or advances a generated chain position.
CREATE TABLE zatca_preparation_custody_v1 (
    site VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    storage_namespace CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    hold_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    ticket_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    candidate_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    manifest_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    payload_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    key_id VARCHAR(80) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    nonce BINARY(12) NOT NULL,
    ciphertext MEDIUMBLOB NOT NULL,
    PRIMARY KEY (storage_namespace,hold_id),
    UNIQUE KEY preparation_custody_candidate (storage_namespace,candidate_sha256)
) ENGINE=InnoDB;

-- A pending hold is committed BEFORE any local builder is called. No expiry,
-- automatic release, installer, raw credentials or authority receipt lives here.
CREATE TABLE zatca_preparation_hold_v1 (
    storage_namespace CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    hold_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    chain_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    active_chain_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
    source_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    environment VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    invoice_uuid CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    candidate_key_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    ticket_bytes VARBINARY(40960) NOT NULL,
    ticket_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    original_manifest_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    PRIMARY KEY (storage_namespace,hold_id),
    UNIQUE KEY preparation_active_chain (storage_namespace,active_chain_id),
    UNIQUE KEY preparation_source (storage_namespace,source_sha256),
    UNIQUE KEY preparation_uuid (storage_namespace,environment,invoice_uuid),
    UNIQUE KEY preparation_candidate (storage_namespace,candidate_key_sha256)
) ENGINE=InnoDB;
