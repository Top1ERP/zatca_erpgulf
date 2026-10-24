# Encrypted pending CSR staging — increment 86 (development only)

## Scope and separation

Increment 87 adds an internal [saved-source/ACL boundary](PENDING_CSR_ACCESS.md)
around these primitives, not an installed provider or runtime adoption. The
primitive-only limitations below still apply; protected key provisioning and
independent historical source/credential epoch remain gates.

`pending_csr` seals the exact unissued `PreparedCSRDraft` from increment 85.
`pending_csr_repository` stages that envelope on an explicitly supplied MariaDB
transaction. This is a separate pre-certificate representation, not a relaxation
of the issued-credential bundle's required certificate/auth material.

These are internal primitives, **not an installed vault, permissioned service,
whitelisted method, button, provider, migration or activation path**. No existing
Company/device key, certificate, auth, signing selection, invoice, XML, QR or
authority route changes. Existing guarded CSR/CSID operations are not connected
to these primitives. No tenant schema is installed.

## Exact encrypted envelope

The caller supplies a canonical nonzero UUID storage namespace and a bounded,
copied keyring of distinct 32-byte AES keys with explicit key IDs. No site,
filesystem, environment, provider or fallback key is discovered. Missing keys
fail closed; adding an explicit new key does not rewrite stored envelopes.

The version-1 compact UTF-8 manifest is bounded to 8,192 bytes. It contains the
declared Compliance slot, Company/source kind/revision, draft/flow UUIDs, explicit
UTC preparation time, and SPKI/CSR-DER/exact-config SHA256 fingerprints. These
are **restricted business metadata**, not anonymous/public data or independently
verified saved-source/credential-epoch evidence. Its exact bytes are immutable
envelope fields; interpretation is decoded afresh, not cached in a mutable object.

The bounded encrypted payload holds only schema version, exact configuration
text and canonical base64 private-key/CSR PEM. AES-256-GCM authenticates the
namespace, key ID and exact manifest using a dedicated versioned AAD prefix and
a fresh random 12-byte nonce. Opening authenticates before reading the payload,
then rechecks strict object/schema fields, duplicate keys, canonical base64,
configuration, key/CSR shape, curve, signature/hash, subject/extension order,
public-key binding and all manifest fingerprints. Malformed material is rejected,
not repaired, regenerated or inferred from another certificate/auth field.

**AAD domain separation is not nonce-reuse protection.** Real adoption requires
independent protected storage keys and an audited per-actual-key nonce/volume,
rotation, backup and recovery policy. The SQL nonce constraint is scoped to
namespace/key ID; it is neither a global allocator nor proof that aliases,
different namespaces or other stores cannot reuse an actual key/nonce. A rejected
insert cannot undo an encryption already performed with a repeated nonce.

Re-sealing a draft produces a different envelope. Retain and redeliver the
original envelope; do not re-seal or generate a new key as a local retry.
This does not make preparation/remote issuance durably idempotent.

## Explicit caller-owned transaction

`MariaDBPendingCSRRepository` requires autocommit disabled. It never begins,
commits, rolls back, closes, retries or repairs the caller's transaction. Only
the rehearsal fixture installs [the private DDL](pending_csr_rehearsal.sql).

| Operation | Bounded behavior |
| --- | --- |
| `stage(envelope)` | Authenticate/revalidate, insert without replacement, locked readback, accept only the exact original envelope |
| Same ID, different envelope | Reject, including a re-sealed identical draft; do not overwrite |
| `load(context)` | Locked exact namespace/draft lookup and complete declared-context equality; no latest/owner/environment fallback |
| Stored-row mutation | Reject metadata/identity/ciphertext mismatch; never reconstruct or repair |
| Any operation failure | Poison this repository handle; caller must roll back the entire transaction and discard it |
| Cancellation | Poison and propagate the original interruption, without automatic transaction cleanup |

Both staged work and unrelated parent work remain subject to the **same caller's**
commit/rollback decision. Returned storage metadata deliberately does not claim
commit/durability confirmation or source/remote/activation authority. Driver
exceptions become allowlisted English codes without raw driver strings or child
exception context; numeric classification reads the base exception's stored args
without invoking overridden diagnostic properties.

This is not a transaction sandbox: the supplied connection/provider, source
reads, locks, permissions, key custody and caller lifecycle need separate review.
Poisoning is local to the handle, not a durable cross-process hold. Metadata
comparison authenticates a declaration, not the actual saved source or actor.

## Privacy limits and integration gate

Repr/diagnostic projection hide raw keys/config/CSR and owner names. Implicit
pickle transport of cipher/envelope/repository is refused. Plaintext still
exists in ordinary Python memory while preparing/sealing/opening; explicit field
reads, `asdict`, reflection, generic RPC/logging and traces with locals can leak
it. There is no secure erasure, memory isolation or general serialization sandbox.
Even ciphertext and manifest require scoped access and retention controls.

Next build a permissioned internal service which acquires the exact saved
Company/device source, enforces write/related-read access and source/credential
revision continuity **before key access**, and owns a reviewed transaction/provider
handoff. Review late revocation/drift, protected key provisioning and original
envelope retention before any issuance transport is considered. Bind the exact
CSR, response certificate, Compliance evidence and final activation to one flow;
do not clear existing credentials or bypass preservation checks. Known initial
Company shared-certificate/device-alias defects remain unfixed.

No expiry or current-clock decision is inferred here. Pending-draft lifetime,
abandonment, failed/unknown commit outcomes, loss/recovery and concurrency across
all credential writers remain policy/integration gates. Installed ERPNext/Frappe
15/16, real roles/hooks/transactions, Desk/browser, SDK and authority acceptance
are not established by these tests. Full development precedes separately approved
fictional-Company rehearsal and later adoption/cancellation/pilot decisions.

## Offline evidence

Only the reviewed `pending_csr` and `pending_csr_mariadb` suites join the fixed
manifest. Tests use fictional declarations, ephemeral test keys, synthetic ERP
boundaries and the fixture's own TCP-disabled MariaDB subprocess under `/tmp`.
No tenant database, active credential, live process or authority is accessed.

The 80 new local cases cover owner/environment combinations, strict manifest/
payload/material validation, AAD tampering, keyring copy/rotation, metadata/privacy,
preflight and sanitized driver/cancellation/transaction errors. The 27 new private
SQL cases cover parent visibility and commit/rollback, exact redelivery/conflict,
row corruption, full context/namespace isolation, competing writes under READ
COMMITTED and REPEATABLE READ, lock timeout, connection loss and exact owned-server
crash/restart durability. One deliberately invalid **test-only** nonce provider
demonstrates SQL collision rejection, not safe cryptographic nonce reuse.

The first combined run had **12 failures and 15,159 passes in 155.66 seconds**:
a generator context manager reattached the original exception to the normalized
error. Replacing it with an ordinary call boundary fixes the cause without
weakening the no-raw-context tests or any offline/permission/crypto guard.

Final guarded combined verification: **13,344 local + 1,827 private SQL =
15,171 passed in 154.19 seconds**, across thirteen owned-private SQL suites,
including **107 new cases**. All nine standalone Node VM scripts passed
**1,444 cases**. These are offline development results, not installed v15/v16,
Desk/browser, SDK, remote Compliance or production acceptance.
