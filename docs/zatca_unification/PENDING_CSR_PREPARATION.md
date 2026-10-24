# Permissioned one-shot CSR preparation and custody handoff — increment 95

## Development-only scope

`PendingCSRStagingTransaction.prepare_bound` connects the existing in-memory
key/CSR builder and cipher to the shared permissioned initial-pair storage path.
It is an internal opt-in method, not a Company button, whitelist, wizard, worker,
runtime provider/schema or active signing selector. No installed source/tenant,
saved key/CSR/certificate/authentication field or authority endpoint is changed.
Existing save/create/review methods keep accepting independently retained inputs.

The server supplies an explicit `CSRPreparationContext` (IDs, UTC preparation time,
Compliance purpose and source declaration), normal exact saved-source identity,
fresh concrete owned lease and a **protected server custodian** callback. No
configuration/private key, site/namespace, resource factory, storage-key selection
or HTTP client can be passed as a request override. Constructor dependencies
remain compatible; historical lookup is never invoked for this new operation.

## Shared source checks before generation

The shared service, not a second permission policy, requires current site/non-Guest
role, normal target READ+WRITE and related Company READ. Administrator, test flags
and ignore-permission flags do not bypass row ACLs. Explicit Company or own-key
device source is required; linked/invoice/abbreviation/unknown-owner fallback is
not introduced. The copied declared context must match saved owner/Company/source
kind/revision/environment before resource acquisition.

Configuration comes only from the captured authorized saved target. Existing
legacy fields/schema and opaque Password backing state are observed for drift;
they are never selected as the new private key or decrypted as a fallback config.
The concrete provider pins the site/namespace/socket/peer/session/registration and
explicit available storage key. Source and encrypted backing observations are
checked in that same non-autocommit transaction.

Before generating anything, `repository.require_unused(context)` performs locked
exact-ID SELECTs on both pending tables. Any existing envelope or history row
blocks generation without loading/decrypting its old material. This is an absence
**observation**, not a durable reservation: missing-row/isolation races remain,
so creation still requires plain INSERTs and refuses every existing identity.
There is no adoption, replacement, identity regeneration or retry fallback.

Source/backing/normal ACLs are checked again before the protected callback. The
one-shot helper delegates to existing `prepare_csr_draft` and `PendingCSRCipher`:
strict saved-config/template validation before one SECP256K1 generation and CSR
signature, existing canonical key/CSR/material validation, then one AES-GCM seal
with the pinned key/namespace. No new cryptographic format or nonce policy exists.
There is no old-key argument, environment fallback, raw-material return or send.

## Retain the exact encrypted original before staging

The owned coordinator immediately keeps a copied `SealedPendingCSR` privately,
before any custodian callback or late permission/source failure. It passes a
separate equal copy to `retain(scope, original)`, requiring **literal `True`**.
False, `1`, strings, missing acknowledgment, exceptions or interruptions do not
permit staging. The server callback must not export/log/queue raw material or
manipulate the running owner/lease/connection. It is a trusted dependency, not a
Python sandbox or a database ownership/durability attestation.

An acknowledgment means only that the server callback accepted the exact handoff.
It does **not** prove durable custody, independent key/tenant provenance, recovery
after process loss, encryption-key backup or safe nonce-volume/rotation policy.
Successful metadata explicitly reports `server_custody_acknowledged=True` and
`server_custody_durable_verified=False`.

The trusted server owner can obtain `coordinator.prepared_original` after sealing,
including after denial/interruption/unknown commit. Before sealing it raises a
static internal error. The property returns protected ciphertext, never a UI/RPC
payload or new user export capability; it does not recheck a denied user's access
because its purpose is **server custody**, not disclosure. Never serialize the
owner, property, raw Python fields or trace locals. Repr/pickle guards are not a
capability sandbox or secure erasure. An in-memory reference alone is not durable.

## New-pair save and unknown completion

After custody acknowledgment, the service validates the returned exact context,
configuration hash, namespace/key and envelope, then rechecks locked source,
backing and normal ACLs before constructing/storing its original declaration.
Any retainer-induced source/backing/permission drift refuses staging while keeping
the protected original. The shared strict new-pair storage, authenticated readback
and final exact binding/envelope/source/backing guards then precede one commit and
close. Current visible source/normal access are checked before metadata disclosure.

Success remains `PENDING_CSR_BOUND_TRANSACTION_COMPLETED_OBSERVATION`, not a
certificate or active credential. All source/epoch/storage/remote/activation/
dispatch/renewal proof/authority flags remain false. Old saved credentials are
not replaced even when populated; this is separate pending custody, not renewal
approval or a bypass of legacy CSR/Final-CSID preservation guards.

Generation/sealing failure is not retried. Before a successful seal no encrypted
original exists; transient raw material is not guaranteed recoverable/erased.
After sealing, retention failure, reentry, late denial and uncertain commit/close
preserve the same original for server review. The existing owner cleans only its
newly owned resources, with interruption priority and no automatic reacquisition.
An unknown commit may have saved both rows; rollback is not compensation. A fresh
separately supplied owner can use `observe_bound` on the retained original without
regeneration. This is review, never permission to resend or recreate the identity.

Child preparation/retainer/cleanup messages are muted. One comprehensive redacted
preparation/storage failure is displayed, with Arabic only at presentation and
English keys/metadata retained. No raw crypto/custodian/SQL diagnostic is exported.

## Limits and next gate

This wires the shared builder to authorized NEW local custody, not live onboarding.
It does not attest committed historical source, atomic permission epochs, actual
storage-key/tenant/custodian provenance or monotonic credential versions. Caches,
ABA, weaker isolation, out-of-band writers, trusted callback side effects and
post-close backing changes remain limits. External key custody/privileges,
retained-envelope durability/recovery, field/log/backup controls and all-writer
epoch policy need independent review before request/receipt/activation integration.
Known legacy initial certificate/device-alias conflicts are not hidden or fixed.

Next review durable retained-envelope custody and independent key/source/tenant/
epoch binding before issuance integration. Installed ERPNext/Frappe 15/16,
Desk/browser, SDK and remote acceptance remain unverified. Finish development
before separately approved isolated fictional-Company rehearsal and later
adoption/cancellation or active-client pilots. No live or authority operation occurs.

## Offline evidence

Only the reviewed `pending_csr_preparation` suite joins the fixed local manifest;
native composition extends the existing owned temporary TCP-disabled SQL suite.
Tests trap historical lookup and verify both owner/permission signatures, all
environment declarations, Password profiles, pre-generation identity/source/config
refusal, literal custody acknowledgment, one generation/seal/handoff, active-field
preservation, retainer drift/failure/interruption, reentry, redaction and Arabic.
Native cases verify committed pair contents, absence of old-key decryption on
existing identities, no staging after custody/guard failure, both-row unknown
completion and fresh read-only review of the same generated envelope.

The first guarded local-only run passed **14,081 in 85.93 seconds**, adding 57
local cases. Final guarded combined: **14,081 local + 2,022 private SQL = 16,103
passed in 173.24 seconds**, across thirteen private suites, adding **73 cases**
(57 local + 16 native SQL). All nine Node VM scripts passed **1,444 cases**.
No resource/ordinary-ACL/crypto/transport guard or assertion was waived. These
tests do not establish installed v15/v16 or remote acceptance.
