# Native storage readiness and declared EGS reservation

Source implementation,2026-11-19. This is workstream2 development, without an
installed site, live activation or authority API request.

## Owned initial setup

`native_storage.initialize_native_storage(runtime=...)` is an internal service;
there is no public RPC, install/migrate hook or implicit invoice-time bootstrap.
It requires System Manager and a clean current-site transaction/connection. It
creates neither a database/schema nor an encryption key/configuration. The
service tables named in native_storage.TABLES and read-only Single metadata must
already be installed. Source declarations now include encrypted legacy history
pages: [NATIVE_HISTORY_CAPTURE.md](NATIVE_HISTORY_CAPTURE.md).

The setup service shares the worker's physical connection/site/actor/key binding,
parent-write/callback refusal and unknown-commit semantics. A submit-hook context
is rejected even before its first ERP write, so setup cannot commit inside invoice
submission. Normal workers have no missing-storage bypass.

The Single stores exactly the namespace UUID, format version1 and an authenticated
key-check ciphertext. Setup creates all three in one commit only when the control
is absent and all declared service tables are empty. Orphan records, partial settings,
duplicates, unsupported state and insufficient physical column capacity require
review. No automatic reset, repair, orphan adoption or deletion is performed.

An existing valid control is reused without a write. A lost commit acknowledgment
remains uncertain; a subsequent call can read the same committed namespace. A
partial insert failure rolls back all three rows. The existing site key remains
unchanged. An older development prototype with only namespace/version or without
an EGS reservation is intentionally held; no working site is migrated here.

## Concurrency and key binding

Frappe15's local `frappe/database/mariadb/framework_mariadb.sql` declares Singles'
doctype/field index without uniqueness. Empty-row locking therefore is not used
as a uniqueness guarantee. Setup uses a database-specific MariaDB named mutex with
zero wait, pinned to the same physical connection. Normal workers do not acquire
that setup mutex. A preexisting parent session lock is refused, never recursively
acquired or released. Cleanup releases only this invocation's same-connection
acquisition, including a lost GET_LOCK acknowledgment; no foreign connection is
repaired. A returning/unknown COMMIT does not imply an advisory lock was released.
These semantics are documented in the official [MariaDB GET_LOCK reference](https://mariadb.com/docs/server/reference/sql-functions/secondary-functions/miscellaneous-functions/get_lock).

`dispatch_storage_context` preserves the previous HKDF/AES key derivation. Its
small fixed probe uses a separate `storage-probe` authenticated domain bound to
site/namespace/record/version. Every worker verifies that probe before obtaining a
cipher or appending custody. A changed key/site/namespace, missing/duplicated probe
or tamper stops the worker. This avoids mixing new ciphertext under a changed key
while older retained records have become unreadable. No old request/receipt bytes
or financial/hash/signature algorithms are rewritten.

This is not key rotation, a privileged SQL/configuration sandbox or clone detection
when an administrator copies the complete same site/key/database identity. The
private tests use one MariaDB server; installed15/16 and database topology/
replication compatibility remain acceptance work, not proof from these fixtures.

## Declared EGS identity is separate from key and owner

`credential_identity.declared_egs_identity_key` binds the configured environment,
taxpayer and exact declared EGS serial. It contains neither the signing key nor
the human Company/device name. Initial CSR staging reserves that identity in a
nullable unique Issuing Chain slot. Opening the encrypted CSR intent recomputes
and checks the slot. A different owner with a fresh key cannot reserve the same
declared unit. An inactive legacy review does not occupy an activation slot.

Registry checks also recognize that identity through supported CSR/certificate/
auth claims and saved CSR configuration. Credential writers use the authorized
routing Company's environment; production request/preparation guards pass the
resolved/captured environment. Whitespace normalization follows API routing.
Thus a new key with a copied known unit declaration cannot bypass the registry by
using an unmarked legacy owner. The prior public-key checks remain independent.
Registry lookup receives hashes only; it returns no other owner's name/material.
Ordinary legacy material without a matching native registration keeps its path.

This is a reservation of a **known local declaration**, not proof of all legacy or
remote history, semantic equivalence of changed serial declarations, CA trust or
NEW_EGS genesis. It does not activate any chain or reset any counter. Renewal must
retain the stable opaque chain; the deferred renewal service must handle declared
identity changes explicitly. Complete legacy-consumer inventory/drain and reviewed
initial/cutover activation remain open. FINAL_READY is still inactive.

## Evidence and limits

Focused logs: `/tmp/zatca-axis2-storage-local.log` and
`/tmp/zatca-axis2-storage-private.log`. Fixtures exercise actual InnoDB, the
nonunique Singles shape, two physical connections, zero-wait contention, lost
mutex/commit acknowledgments, partial inserts, wrong key/site/schema, orphan
custody and duplicate declared units. ERP permissions/metadata/source loaders are
explicit doubles. Native endpoint responses are mocked under the offline guard.

The final focused runs pass166 local cases across8 suites in0.91s and188 private
SQL cases across6 suites in12.29s. The fixed81-suite issuer-binding profile passes
20,750 in116.12s (`/tmp/zatca-axis2-storage-regression-final.log`). Only the worker
module description was corrected afterward, with non-docstring AST equality
checked. Counts overlap and are not additive release totals. The fixed manifest
now declares225 local/63 private suites; this increment did not run them all.
Original240 financial comparison/reference expectations91/117/32 are unchanged.

No installed Frappe/ERP15/16, full financial/SDK parity, complete legacy inventory,
public worker adoption or genuine authority acceptance is established here.
