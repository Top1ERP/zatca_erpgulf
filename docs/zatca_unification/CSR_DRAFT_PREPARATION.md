# Non-writing key/CSR preparation — increment 85 (development only)

## Gap and bounded implementation

Increment 86 adds a separate, unactivated encrypted envelope and caller-owned
transaction repository for this exact draft. It does not wire preparation to a
button or installed store, verify saved-source/ACL/epoch provenance, or activate
credentials. The boundaries below describe preparation itself; custody handoff
remains explicit. See [PENDING_CSR_CUSTODY.md](PENDING_CSR_CUSTODY.md).

Existing encrypted credential bundles require an issued certificate/auth
snapshot, not a pending pre-certificate key. The legacy CSR operation also saves
the shared key before construction completes. Increments 83/84 add preservation
guards, not a separate renewal workflow.

`csr_draft.prepare_csr_draft` now prepares a new key/CSR in memory without
loading/changing an existing key, certificate, auth or saved Company/device.
It is internal, **not whitelisted, activated or connected to a button, wizard,
hook, scheduler, signer, store or transport**. It does not bypass preservation
guards, encrypt/persist material, issue a certificate or activate credentials.

```text
declared context + strict configuration
  -> attribute/template preflight before generation
  -> one local key generation + CSR signature
  -> canonical material/subject/extension/key/signature validation
  -> protected ephemeral draft
  -> STOP: no custody, request, certificate, field write or activation
```

## Shared structure, not another CSR format

`csr_template` is the shared ordered subject/directory-name SAN, UTF8String label
encoder, extension construction and unsigned builder. Legacy CSR delegates after
its existing key save; the public encoder wrapper/encoded-string return remain.
Curve, SHA256, attribute/extension order, noncritical flags, OIDs and environment
labels are preserved. New preparation checks configuration **before** generation.

The legacy parser, unknown-portal fallback, key-before-build ordering, source
ACLs and preservation guards are intentionally not changed. That fallback is not
a safe renewal/environment policy. Invoice XML/SignedProperties/certificate
digests, QR, ICV/PIH and API routing are untouched.

## Context and validation

`CSRPreparationContext` declares a Compliance-purpose slot, Company/source kind,
naive revision string, canonical nonzero draft/flow UUIDs and explicit UTC time.
Existing slot/owner/time/revision validators are reused. No clock, saved source,
permission, tenant/link/taxpayer mapping, source lock or committed credential epoch
is acquired or verified. A future permissioned coordinator must enforce those
boundaries before accessing real settings.

The new profile requires exactly nine known keys once each, nonempty bounded
UTF-8 values, no unknown/duplicate/missing keys, and no control/Unicode separator
injection. Input is limited to 16,384 UTF-8 bytes and each value to 1,024 bytes.
Normal line endings/key/value spacing are accepted, while exact original text is
retained/hashed, not saved or rewritten. Shared x509 attribute construction runs
before generation. These are local hygiene/library constraints, **not** complete
VAT/unit/functionality, remote enrollment, trust or regulatory validation.

Default generation creates SECP256K1 once and SHA256-signs CSR PEM. There is no
existing-key argument, external key source, automatic retry, repair or commit.
`PreparedCSRDraft` independently checks bounded bytes (65,536 each), canonical
TraditionalOpenSSL key/CSR PEM, curve, CSR signature/hash/public-key binding,
exact subject and exactly the expected ordered noncritical extensions. Different
keys/subjects/SANs/labels/hash/extension order/critical flags, corrupted signatures
and noncanonical wrappers are rejected. Static English failures are raised
outside child catches without raw diagnostics/context; cancellation propagates.

## Privacy and explicit limits

The frozen result holds context, exact config and raw key/CSR bytes for a future
explicit protected-custody handoff. Repr hides material/identities. Implicit JSON,
pickle and ordinary shallow/deep copy transport are unsupported. Only a manual
diagnostic projection exposes declared draft/flow IDs, environment and SPKI/
CSR-DER/exact-config fingerprints; source/epoch/storage/remote/activation/
dispatch/renewal authority flags remain false. Metadata still needs restricted
access and is not a public endpoint or anonymity guarantee.

This is ordinary Python memory, **not encryption, a vault, secure erasure or a
serialization sandbox**. Explicit field/`__dict__` reads, `asdict`, manual
serialization, generic RPC export or logging/traces with locals can expose the
raw fields. Never do that. No operator/UI endpoint or durable storage exists
here. Process loss loses this pending draft, not an active key. No remote
outcome, resend rule or renewal authority can be inferred from a local draft.
Repeated calls generate new material; reusing declared flow/draft IDs is not
idempotency. Future custody must retain the exact draft and prevent duplicate
preparation/issuance where required, not regenerate a key to retry a request.

| Boundary | Current behavior |
| --- | --- |
| Existing Company/device CSR button | Guarded saved-field operation using the shared template, not switched to drafts |
| Internal preparation | No existing credential/source reads or writes; declarations only |
| Issued-credential encrypted store | Still requires an issued snapshot, not repurposed for pending keys |
| Custody/CSID/active selection | Not wired; no migration, alias choice, restore, promotion or activation |

Increment 86 supplies encrypted staging primitives, not a permissioned service.
Next provide permissioned saved-source/epoch-bound custody access,
then bind exact CSR/returned certificate/Compliance evidence to that flow before
considering Final activation. Lost/late/duplicate handling, all other writers,
secret-field/read/export/hook/log controls and coherent activation remain gates.
The Company shared-certificate overwrite and device alias conflict on initial
CSID transition are **not fixed** or selected away. Do not reconstruct an active
certificate from auth or change signing selection to hide those observations.

No live source/assets/config/schema/site/customer credential/worker or authority
operation occurs. Full development then separately approved fictional-Company
rehearsal precedes adoption/pilots. Installed Frappe/ERPNext 15/16, physical roles/
metadata/hooks/transactions, browser/Desk, SDK and authority remain unverified.

## Offline evidence

Only `test_csr_draft.py` joins the fixed manifest. Tests use fictional declarations,
ephemeral test keys and mock ERP/saves/HTTP only: owner/environment combinations,
invalid context/config/required/duplicate keys before generation, private faults,
cancellation, material binding/canonicality/privacy/transport, and distinct local
test keys. Six Company/device/environment cases compare exact CSR TBS bytes
against the legacy adapter, not nondeterministic ECDSA signature bytes. Three
independent literal OID/order/value/label/SHA256 goldens do not reuse the template
to build expectations. Populated synthetic active records are not even loaded
during preparation. Prior guards and CSID defect characterization remain intact.

Final guarded combined verification: **13,264 local + 1,800 private SQL =
15,064 passed in 147.59 seconds**, across twelve owned-private SQL suites,
including **142 new synthetic cases**. The first combined run passed **15,061
in 146.25 seconds** before adding the three independent literal goldens.
All nine standalone Node VM scripts passed **1,444 cases**. No offline resource,
ordinary permission, existing crypto or transport assertion was waived. This is
not installed v15/v16, SDK, browser/Desk or authority acceptance.
