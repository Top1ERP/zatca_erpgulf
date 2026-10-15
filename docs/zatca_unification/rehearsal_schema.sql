-- Isolated development rehearsal only. NOT a Frappe migration/install hook.
-- Tables require controlled access, recovery, encryption and tenant mapping
-- before any live adoption. The caller owns all transaction boundaries.

-- Synthetic provisioning marker ONLY; no runtime installer creates this table.
CREATE TABLE zatca_receipt_storage_binding_v1 (
    storage_namespace CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    site VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    registration_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL
) ENGINE=InnoDB;

-- Protected custody ONLY in the owned isolated rehearsal, never installed live.
CREATE TABLE zatca_primary_receipt_custody_v1 (
    storage_namespace CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    candidate_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    attempt_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    predecessor_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    receipt_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    key_id VARCHAR(80) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    nonce BINARY(12) NOT NULL,
    ciphertext MEDIUMBLOB NOT NULL,
    PRIMARY KEY (storage_namespace,candidate_sha256,attempt_id),
    UNIQUE KEY receipt_custody_nonce (key_id,nonce)
) ENGINE=InnoDB;

CREATE TABLE zatca_issuance_candidate_v1 (
    storage_namespace CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    key_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    manifest_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    context_bytes VARBINARY(16384) NOT NULL,
    xml_bytes MEDIUMBLOB NOT NULL,
    file_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    environment VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    chain_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    invoice_uuid CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    icv VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    journal_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    revision TINYINT UNSIGNED NOT NULL DEFAULT 0,
    attempt_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
    PRIMARY KEY (storage_namespace, key_sha256),
    UNIQUE KEY issuance_uuid (storage_namespace, environment, invoice_uuid),
    UNIQUE KEY issuance_icv (storage_namespace, environment, chain_id, icv),
    UNIQUE KEY issuance_attempt (storage_namespace, attempt_id),
    CONSTRAINT issuance_revision CHECK (revision <= 3),
    CONSTRAINT issuance_xml_size CHECK (OCTET_LENGTH(xml_bytes) BETWEEN 1 AND 5242880)
) ENGINE=InnoDB;

CREATE TABLE zatca_dispatch_event_v1 (
    storage_namespace CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    key_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    sequence TINYINT UNSIGNED NOT NULL,
    event_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    payload_bytes VARBINARY(4096) NOT NULL,
    response_bytes MEDIUMBLOB NULL,
    PRIMARY KEY (storage_namespace, key_sha256, sequence),
    UNIQUE KEY dispatch_event (storage_namespace, event_id),
    CONSTRAINT dispatch_candidate FOREIGN KEY (storage_namespace, key_sha256)
        REFERENCES zatca_issuance_candidate_v1 (storage_namespace, key_sha256)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT dispatch_sequence CHECK (sequence BETWEEN 1 AND 3),
    CONSTRAINT dispatch_response_size CHECK (
        response_bytes IS NULL OR OCTET_LENGTH(response_bytes) <= 8388608
    )
) ENGINE=InnoDB;

-- Synthetic atomic-start/no-replay reservation, NOT a runtime installer.
CREATE TABLE zatca_primary_attempt_hold_v1 (
    storage_namespace CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    candidate_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    manifest_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    attempt_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    started_journal_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    PRIMARY KEY (storage_namespace,source_sha256),
    UNIQUE KEY primary_hold_candidate (storage_namespace,candidate_sha256),
    UNIQUE KEY primary_hold_attempt (storage_namespace,attempt_id),
    CONSTRAINT primary_hold_candidate_fk FOREIGN KEY (storage_namespace,candidate_sha256)
        REFERENCES zatca_issuance_candidate_v1 (storage_namespace,key_sha256)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

-- Exact deterministic auth-free body binding, owned private rehearsal ONLY.
CREATE TABLE zatca_primary_request_binding_v1 (
    storage_namespace CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    candidate_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    attempt_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    request_codec TINYINT UNSIGNED NOT NULL,
    request_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    PRIMARY KEY (storage_namespace,source_sha256),
    UNIQUE KEY primary_request_candidate (storage_namespace,candidate_sha256),
    UNIQUE KEY primary_request_attempt (storage_namespace,attempt_id),
    CONSTRAINT primary_request_hold_fk FOREIGN KEY (storage_namespace,source_sha256)
        REFERENCES zatca_primary_attempt_hold_v1 (storage_namespace,source_sha256)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT primary_request_codec CHECK (request_codec = 1)
) ENGINE=InnoDB;
