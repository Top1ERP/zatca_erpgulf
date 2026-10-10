-- Isolated development rehearsal only. NOT a Frappe migration/install hook.
-- Tables require controlled access, recovery, encryption and tenant mapping
-- before any live adoption. The caller owns all transaction boundaries.

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
