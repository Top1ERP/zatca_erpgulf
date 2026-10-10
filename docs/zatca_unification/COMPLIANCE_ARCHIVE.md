# Encrypted Compliance archive — increment 22

## Delivered scope

Protected exact-byte codecs, an independently keyed archive cipher and an
explicit-transaction MariaDB repository preserve increment 21's supplied
Compliance observations. The schema is installed only on owned private test
servers, not through a Frappe patch/DocType/migration/install hook.

No HTTP sender, trusted transport collector, operator API, outbox/lease, key
discovery, scheduler or activation is added. Encrypting/committing supplied
observations does not prove ZATCA received the request or returned the response.
All dispatch/remote/completion/activation/replay authority remains false.

## Lifecycle and caller obligations

| Operation | Stored evidence | Caller responsibility |
| --- | --- | --- |
| prepare(start) | Sequence 1: original request, CSR, manifest, route, no response | Commit before future HTTP; release all DB locks |
| append_receipt(receipt) | Sequence 2: immutable response tied to that exact start | Explicit commit, no replacement/resealing |
| load(slot, version, exchange) | Authenticated original start and optional receipt | Explicit scope, restricted plaintext access, release read locks |

A request-only history is REQUEST_CAPTURED_OBSERVATION, not proof of dispatch
or a timeout. A receipt history is RECEIPT_CAPTURED_OBSERVATION, not verified
transport provenance or real invoice clearance/reporting. Its current observation
can feed the existing bound check-set assessment without discarding the start.

The receipt must share namespace, exact manifest/CSR, exchange identity, route,
start time and exact request bytes. Receipt ordering/fields are revalidated by the
existing model. The repository authenticates the referenced stored Compliance
bundle before accepting or returning records.

The repository cannot prove a caller committed the start in an earlier
transaction: a caller can prepare/append together. A future trusted coordinator
must enforce commit-before-HTTP, actual authentication/header/source binding and
attempt coordination. Never perform networking while these row locks are held.

## Exact-byte protection

The versioned binary codec uses a magic prefix and four bounded length-prefixed
frames: canonical private header, original DER CSR, original request and response
bytes. Bodies are not Base64-expanded or reformatted. XML declarations, wire JSON
and whitespace survive unchanged. Strict decoding rejects truncated/trailing
frames, duplicate/unknown header fields, wrong versions and noncanonical header
representation. Rehydration recomputes the existing CSR/XML/response contracts.

The full manifest, route and explicit UTC times are inside the encrypted header,
not public metadata. Existing CSR/request/response limits and a 32 KiB header
limit bound ciphertext to 16,875,582 bytes. SQL retrieval uses bounded SUBSTRING.
The private schema uses LONGBLOB because two bounded bodies can exceed MEDIUMBLOB.

An empty received HTTP body (b"") is distinct from no response (None); both are
preserved. Empty/invalid response JSON never matches successful validation,
including HTTP 200. The previous observation model was refined to allow empty
HTTP responses without turning them into successful results.

AES-256-GCM protects private header/CSR/request/response frames. AAD binds the
exposed namespace, exchange, sequence, version, manifest/observation fingerprints
and key ID. The nonce is 12 bytes and the tag is not truncated. The library's
[AES-GCM contract](https://cryptography.io/en/46.0.3/hazmat/primitives/aead/#cryptography.hazmat.primitives.ciphers.aead.AESGCM)
requires nonce uniqueness under a key; changing key/AAD/nonce/ciphertext prevents
successful authentication. AAD domain separation does not make nonce reuse safe.

Archive keys are explicit caller-owned in-memory dependencies, independent from
bundle-storage/signing keys and other stores/namespaces. The repository rejects
overlap with the supplied bundle keyring, even under other IDs. Shared bounded
key validation preserves the existing bundle envelope format and behavior; no
site key, CSID secret, filesystem or environment fallback is consulted.

Deployment still needs reviewed custody, global nonce-volume policy, rotation,
protected off-host backup and recovery. The namespace/key-ID/nonce unique SQL key
covers archive request and receipt rows, not every other system. Keep the exact
encrypted envelope for redelivery; resealing creates a different envelope and
cannot overwrite an existing identity. Old keys must remain available for old
records. No implicit key substitution or overwrite-based re-encryption exists.

Protected histories return raw material only to trusted internal code. Never
whitelist, queue, log, expose to UI, or serialize them with asdict/pickle.
Diagnostics omit raw bodies; ciphertext and private objects are hidden from repr,
and cipher/repository/history/envelope pickle is refused. SQL contains ciphertext
and public references only. Errors are static codes. Python secure memory erasure,
protection from an administrator holding keys, and transport provenance are not
provided by encryption.

## Transactions, concurrency and recovery

The archive has staged-version and start-parent foreign keys, constrained
sequences and nonce uniqueness. Bundle row locks precede request/receipt locks.
Locked current reads and exact envelope comparison serialize duplicates/conflicts
under both tested isolation levels. There is no delete/replace repository method,
but privileged DB administrators can still modify/remove records: this is not an
external tamper-proof audit. Authentication detects corruption of retrieved rows,
not every possible deletion by an administrator.

No implicit connection discovery, schema installation, autocommit change,
commit/rollback/close or retry occurs. Autocommit must be off. Any failure,
including invalid preflight, poisons the handle: roll back the whole caller
transaction and discard it. Unknown commit outcomes do not authorize another
send; reconcile the exact scoped record using a future cross-attempt policy.
Deadlocks/timeouts are not silently retried.

Company/device credentials, invoice UUID/ICV/PIH, legacy response fields, CSIDs and
active versions remain untouched. The caller must enforce tenant/role/document
authorization. At increment 22, the operator service was not yet connected to this
archive; no API exposure/access bypass was added.

Increment 23 connects [permissioned explicit metadata selection](COMPLIANCE_ARCHIVE_ACCESS.md)
through that internal service. It does not whitelist or expose the decrypting
repository and does not add trusted transport or activation authority.

## Verification

The archive adds 147 local cases covering all six types/three environments,
codec/AAD/rehydration integrity, exact bodies, start/receipt binding, independent
keys/rotation, bounds/privacy, poisoned transactions and no file/HTTP discovery.
Empty-body handling adds two net cases to the previous evidence suite (138 rather
than 136). Total new local cases: 149.

The new private SQL suite adds 27 cases for committed recovery, ciphertext-only
contents, empty bodies, rollback/connection loss, idempotence/resealing, scope,
request/version mismatch, corruption, nonce collision, competing receipt workers
at both isolation levels, lock timeout, owned-process crash recovery and recovered
six-type observation sets. The combined selection passes
**3,142 local + 82 private SQL = 3,224 cases**.

Increment 23 adds 145 local and seven private SQL operator-service cases,
raising the current totals to **3,287 local + 89 private SQL = 3,376 cases**.

Increment 24 adds [strict single-use reservation and a two-transaction collector](COMPLIANCE_CAPTURE.md),
with 137 local and 17 private SQL cases, reaching **3,424 + 106 = 3,530 cases**.
It still supplies no real HTTP sender or trusted transport provenance.

Increment 25 adds an [opt-in standard-gateway HTTPS adapter](COMPLIANCE_HTTPS.md),
tested with synthetic HTTP pools only, reaching **3,615 + 110 = 3,725 cases**.
It is not installed as a default/deployed transport and does not verify provenance.

From the development worktree:

    ZATCA_RUN_ISOLATED_MARIADB=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
      ../../env/bin/python -m pytest -q -p no:cacheprovider \
      zatca_erpgulf/zatca_erpgulf/tests/test_journal_repository_mariadb.py \
      zatca_erpgulf/zatca_erpgulf/tests/test_credential_bundle_mariadb.py \
      zatca_erpgulf/zatca_erpgulf/tests/test_compliance_archive_mariadb.py \
      zatca_erpgulf/zatca_erpgulf/tests/test_compliance_capture_mariadb.py \
      zatca_erpgulf/zatca_erpgulf/tests/test_compliance_https_mariadb.py

The fixture owns its TCP-disabled process/socket/datadir and accepts no site,
external host/socket/config override. Crash tests stop/restart only that exact
owned process, never a live database/worker/bench. Recovery uses synthetic data
and in-memory test keys, not protected-key disaster recovery or restored Frappe
boot. No SDK, live call, browser, full site integration or ERPNext 16 runtime was
tested. Broader release/unification gates remain in [PLAN.md](PLAN.md).

## Next gate

The internal permissioned metadata selection is added in increment 23, and the
explicit two-transaction capture scaffold in increment 24. Audit and provide
trusted resource acquisition, a permissioned transactional source boundary and
actual bounded HTTPS transport attestation. Complete unknown-outcome receipt
reconciliation and exact CSR-to-issuance provenance before proposing
controlled epoch activation. Rehearse on restored v15/v16 sites. Schema/key/backup
review, pilot approval and prior live-change notice are required before tenant
installation, runtime adoption or restart.
