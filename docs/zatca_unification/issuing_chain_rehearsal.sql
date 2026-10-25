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
