# Encrypted credential staging — development increment 19

This is a bounded staging storage boundary, **not** an installed Frappe credential
store, active credential selector, key-management service, migration or remote
authorization check. No live generator, onboarding button or scheduler uses it.
No tenant schema, saved credential, key/configuration or invoice was changed.

## Implemented separation

`credential_bundle.py` defines an explicit slot
`(owner doctype/name, environment, purpose)` and immutable version/flow declarations.
Compliance has no parent; Production must name a staged Compliance version.
Public metadata binds the company/source-kind declaration, request/flow IDs,
explicit preparation time and DER/SPKI/exact certificate-text fingerprints.
Version IDs are caller-supplied canonical UUIDs, not generated from a certificate
or password. A version remains distinct when only the authentication secret changes.

Only the protected plaintext contains private-key PEM, the original authorization
field text, original certificate text and captured route. Exact certificate text
survives encryption/decryption without digest repair or XML reserialization.
The existing purpose-specific field policy and `CredentialSnapshot` validation
are reused; this is not another saved-owner/settings resolver.

`CredentialBundleCipher` takes an explicit in-memory mapping of key IDs to 32-byte
keys. It uses AES-256-GCM with fresh 12-byte random nonces; namespace, key ID and
exact canonical public manifest are authenticated associated data. Changed
ciphertext, nonce, key, namespace or manifest cannot decrypt with the original
context. This follows the library's
[authenticated encryption API](https://cryptography.io/en/42.0.8/hazmat/primitives/aead/).
Nonce reuse under a key must never occur; SQL collision rejection is **not** a
safe nonce allocator or permission to reuse a nonce. Deployment needs an approved
key-volume/rotation/nonce policy and protected key custody/recovery.

Keys are not discovered in site configuration, read from environment variables,
generated/persisted by the store, or written beside ciphertext. No password-derived
keys or application key defaults are provided. The test keys are generated only
in memory. Key-ring copies exclude later caller mutation and reject duplicate
material under multiple IDs in that ring. Old versions remain decryptable only
while their original key ID/material is retained securely.

## Explicit SQL repository

`MariaDBCredentialBundleRepository` requires a caller-supplied transactional
DB-API connection, storage namespace and cipher. It authenticates/revalidates
material before storing/returning an envelope. Only the exact encrypted envelope
and bounded public metadata are SQL parameters; no plaintext key/auth value is
stored in the rehearsal table.

| Operation | Boundary |
| --- | --- |
| `stage(envelope)` | Insert once, or accept exact envelope redelivery; changed envelope under the same version conflicts |
| Production parent check | Same declared owner/environment, source context, flow/request ID and public key; not remote compliance completion |
| `load(slot, version)` | Exact explicit slot/version only; no cross-purpose/environment/owner or “latest” fallback |
| Local decryption | Reconstruct material and recheck certificate validity at caller-supplied explicit UTC time |
| Activation | Deliberately absent; staging never switches active credentials |

Resealing identical material produces a new nonce/ciphertext. Do not reseal an
already staged version as an idempotent retry: retain the exact envelope, or create
an explicitly new version. Public fingerprints alone cannot detect password
rotation. SQL unique constraints cover namespace/version and namespace/key-ID/
nonce; a collision cannot overwrite an older version.

Parent-before-child row locks and exact record comparison serialize competing
stages. Every failure, including invalid preflight, poisons that repository
handle: roll back the **whole** caller transaction and discard it. Deadlocks,
timeouts and unknown commit outcomes are not retried automatically. The repository
never creates connections, installs DDL, manages begin/commit/rollback, reads the
clock, calls HTTP, or changes Company/device fields, invoice identity, ICV or PIH.
Returning an envelope does not prove that the caller committed it.

The repository checks stored material at its explicit historical preparation
time so expired versions can remain auditable. Any future credential use must
decrypt/revalidate with an explicit current UTC time and separately verify saved
source/settings, trusted taxpayer/unit/environment provenance and activation.
The captured encrypted route is a declaration, not today's effective configuration.

## Privacy and authority limits

- Secret/ciphertext fields are hidden from printable representations. Errors are
  static codes; raw driver/parser/cryptography messages are not returned.
- Cipher/envelope pickle is refused. Do not log parameters, plaintext, snapshots,
  exceptions with local-variable dumps or arbitrary `asdict` output. SQL tracing
  and operational diagnostics need independent redaction/access controls.
- Public metadata is not public-to-every-user data. Owner names and identifiers
  still require restricted access and tenant mapping before Frappe integration.
- AES-GCM proves integrity under the supplied key, not ZATCA issuance, taxpayer
  authorization, trust/revocation, Compliance completion or a verified epoch.
- Diagnostic authority flags remain false. There is no active pointer, dispatch,
  replay, rollback-to-previous-credential or migration API. Encryption does not
  provide secure Python memory erasure, database-admin protection when keys are
  also compromised, or production-grade vault/key recovery by itself.
- Existing secret-bearing legacy issuance responses remain a release gate. This
  staging store does not modify or endorse those response/UI behaviors.

## Rehearsal and verification

`credential_bundle_rehearsal.sql` creates one private staging table. It is not a
fixture, patch, install hook or Frappe migration. Its DDL is installed only by the
opt-in test fixture using the socket of a newly created, owned, TCP-disabled
MariaDB subprocess. No external site/socket/host override is accepted.

`test_credential_bundle.py` adds 92 local cases: all owner/environment/purpose
slots, exact material preservation, known encodings, encryption/tamper/namespace
binding, key rotation/unavailability, bounds/strict schemas, owner/time declarations,
safe diagnostics, immutable SQL comparisons, poisoned transactions and no external
discovery, activation, HTTP or implicit commits.

`test_credential_bundle_mariadb.py` adds 23 real private InnoDB cases: committed
roundtrip, ciphertext-only secret fields, purpose/version separation, altered-secret
conflicts, connection loss/rollback, parent mismatches, slot isolation, corruption,
nonce collision, concurrent identical/conflicting stages at both isolation levels,
lock timeout and owned-server crash recovery of committed/uncommitted work.

The full selected local suite passes **2,752** cases. The separate private SQL
command passes **48** cases (25 journal + 23 bundle), **2,800 total**. Reproduce
the opt-in SQL test from the development worktree only:

```sh
ZATCA_RUN_ISOLATED_MARIADB=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  ../../env/bin/python -m pytest -q -p no:cacheprovider \
  zatca_erpgulf/zatca_erpgulf/tests/test_journal_repository_mariadb.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_credential_bundle_mariadb.py
```

This may need scoped permission to bind its own Unix socket. Only its own test
subprocess is stopped/restarted. No live bench/worker/database service is touched.
No SDK, browser language switch, remote CSID/Compliance, real invoice, restored
Frappe application or ERPNext 16 runtime was tested. No compatibility/deployment
claim follows from these local SQL/crypto tests.

## Next adoption gates

1. Choose and validate protected key custody/nonce/rotation/backup/recovery policy;
   do not repurpose site encryption settings without an explicit design review.
2. Build permissioned Frappe storage/service adapters on restored sites with an
   approved schema migration, tenant namespace mapping, redacted errors and Arabic
   UI keys. Preserve originals and rollback evidence; never overwrite legacy fields
   to resolve alias conflicts automatically.
3. Capture trustworthy transactional source/settings and remote onboarding evidence
   for the exact version/flow. A staged Production parent does not mean the six
   tests passed. Define controlled epoch/activation CAS only after those checks;
   leave the prior active Production version unchanged on failure.
4. Wire one immutable material capture through the shared preparation/request
   services, then rehearse issuance/renewal/retries/chain continuity in v15/v16.
5. Obtain pilot approval and notify the user before any live source/schema/config
   change, migration or bench restart. Broader gates remain in [PLAN.md](PLAN.md).
