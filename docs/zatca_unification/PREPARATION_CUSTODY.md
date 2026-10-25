# Exact preparation-original encrypted custody

Increment 102 — 2026-10-25. Offline development only: uninstalled dependencies,
not a live vault, migration, button or authority client.

Follow-up increment 103 removes repeated decryption/XML reconstruction from
access-boundary guards. Authenticate at entry and pin the whole envelope hash
plus an independent validated original; compare them before/after callbacks.
Every source/ACL/evidence boundary is retained, and SQL repositories still
authenticate each loaded envelope independently. Native tests count cipher opens:
stage 7 -> 3, protected load 4 -> 2, recovery 6 -> 4. These are operation counts,
not a measured end-to-end latency or memory guarantee. Cipher/key providers and
callbacks remain trusted server dependencies, not an arbitrary-code sandbox.
See [STATUS.md](STATUS.md) for the follow-up tests and restrictions.

## Purpose and exact format

After a durable preparation hold and one local build, retain the exact original
and ticket without relying exclusively on worker memory. The encrypted copy
feeds [saved-WRITE recovery](PREPARATION_RECOVERY.md) without exporting plaintext,
building/signing again, reserving another UUID/ICV, releasing a hold or sending
HTTP. Recovery completes only the LOCAL original/head/hold transaction.

This is a separate encrypted recovery copy. Existing plaintext journal XML,
legacy files and other stored artifacts are NOT converted to encryption.
No existing Company or invoice is modified.

The bounded versioned codec preserves site/namespace, hold ID, canonical ticket,
optional completion manifest, candidate context and exact lexical XML bytes.
Only bounded framing is shared with primary receipts; receipt wire bytes and
acceptance policy are unchanged.

AES-256-GCM uses an explicitly supplied independent 32-byte storage key and
fresh 12-byte cryptographic nonce. Authenticated associated data binds domain,
site, namespace, hold/ticket/candidate/manifest/payload hashes and key ID.
Authentication AND canonical round-trip reconstruction are mandatory.
Envelopes, plaintext contracts, resources and keyrings redact repr and refuse
pickle; they are not logging, UI, queue or RPC payloads.

## Immutable storage and recovery

Seal ONCE and retain that same envelope across uncertainty. Exact ciphertext
redelivery matches; independently resealing equal plaintext is a conflict,
never permission to replace the copy. No overwrite/delete/release/retry API
is provided.

The caller-owned repository checks the existing exact hold under chain/hold
locks, then stages ciphertext. It does not reserve/complete a hold, advance
a head, install schema, commit or close a caller connection. It requires
explicit transactions and poisons failed handles until whole caller rollback.
The table exists only in the private SQL fixture; no migration is installed.

The opt-in facade requires Administrator/System Manager, current site, ordinary
saved invoice WRITE and related Company/device/linked-owner READ BEFORE scoped
keys. Quiet permission-signature fixtures cover v15/v16, not installed ERP
acceptance. Draft/cancelled records remain READ review-only under the existing
conservative LOCAL policy, not a claimed ZATCA rule. Historical recovery needs
separate review; history is not reset or discarded.

Mandatory explicit guards check source, settings, financial-snapshot,
credential-epoch and custody evidence before acquisition, around writes and
after cleanup. Literal True from a supplied guard is NOT authenticated
provenance. No default accounting verifier or key-provider provenance validator
is installed.

Protected retrieval takes a saved source name, finds its exact hold/copy,
authenticates internally, rolls back/closes the owned read and returns protected
ciphertext ONLY. Recovery closes that read before opening a separate owned
write. The existing exact-original recovery service rechecks the SAME stored
envelope inside its transaction. Source -> chain -> hold -> ciphertext lock
order is consistent; no reverse custody-first locking.

Source/owner revisions, direct ACL and evidence are rechecked. Borrowed Frappe
or raw parent handles are refused without commit/rollback/close. Interrupts
clean owned handles and retain exact inputs. Commit/close failure may follow
a durable write: report unconfirmed, never reseal/retry. Late denial does not
delete/undo committed rows. Source-row locks do not atomically lock ACL tables.

## Presentation, tests and remaining gates

Stage returns fixed English metadata with false-only replay/dispatch,
signature, origin and authority-verification flags. One allowlisted summary
is translated for display, including Arabic. Internal states and retained
authority payloads are not translated. Protected load is not an operator JSON
endpoint. No live caller/frontend binding is installed.

Deployment gates remain:

- Authenticated tenant/site/namespace and scoped key-provider provenance.
- Storage keys independent from signing, credential and receipt keys; AAD does
  not make cross-domain nonce reuse safe.
- Key volume/rotation, secure retention, off-host recovery and availability.
  Re-encryption of immutable rows is not a supported rotation API.
- Authentic accounting/source/settings/credential-epoch evidence, not test mocks.
- Full-worker lifecycle, legacy continuity, installed ERPNext 15/16 and SDK checks.
- Separate approval for fictional-company rehearsal, deployment and transport;
  the current authority-transport prohibition remains in force.

Synthetic tests cover exact codecs, authenticated metadata, malformed framing,
wrong/missing keys, immutable ciphertext, access-before-key ordering, source/ACL
drift, parent isolation, interrupts, uncertain storage/recovery commits, actual
SQL visibility/contention and private database crash/restart recovery.
Unsigned synthetic artifacts and synthetic keys do not prove signature,
SDK, remote acceptance or installed ERP compatibility. Executed totals:
[STATUS.md](STATUS.md). Operational restrictions:
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).
