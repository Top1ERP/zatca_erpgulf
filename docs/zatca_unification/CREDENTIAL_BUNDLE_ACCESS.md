# Staged credential access — increment 20

## Delivered boundary

`credential_bundle_access.py` adds an **internal metadata inspection service**,
not a whitelisted method, button, active-credential selector or migration.
Server-owned dependencies bind a Frappe site to a storage namespace, connection
and AES storage cipher. None is discovered from request data, Company credentials,
site encryption settings, filesystem or environment variables.

The selected certificate is not switched or activated. Existing issuance,
signing, QR, reporting and clearance callers do not use this service.

The operation order is deliberate:

1. Require the configured site and an authenticated System Manager (or
   Administrator). Guest is rejected even if an apparent role is supplied.
2. Validate an exact canonical version UUID and a known non-OTP operation.
3. Reload Company, source invoice, device and linked Company as required by the
   existing owner policy. Check **each** saved document's read permission using
   the permission engine directly, not `Document.ignore_permissions` or the
   test-mode bypass in `frappe.only_for`.
4. Resolve saved environment/purpose and owner; check Company membership,
   linked taxpayer and the existing checkbox interpretation. Legacy `None`,
   empty and zero checkbox values continue to mean false. Caller values provide
   source identity only, never credentials, links, flags or routing overrides.
5. Recheck actor/site before requesting protected resources. Require the returned
   server resource binding to match the configured scope exactly, and recheck
   actor/site before repository access.
6. Load exactly the owner/environment/purpose/version slot using the existing
   authenticated repository. Also match manifest Company and source kind:
   sharing a linked owner does not make another Company's declaration evidence
   for the requested source. Recheck actor/site before returning metadata.
7. Return only the manifest's diagnostic projection. No envelope, ciphertext,
   nonce, raw certificate, private key, authorization or request secret is returned.

Company/source documents are loaded server-side before their document permission
can be evaluated. Metadata capture does not project their legacy secret fields;
this is not a claim that loading a full Frappe row never brings them into memory.
No unchecked row is returned to the caller, and denied scope/ACL checks occur
before the resource provider can supply storage keys or a storage connection.

## Error and transaction behavior

Denied access uses a generic translated permission message. All other failures
(missing records, bad configuration, provider, SQL, cryptographic integrity or
declaration mismatch) use a generic translated failure message. Original exceptions
are not chained into the rendered error/traceback. Arabic catalog entries exist;
browser language switching has not been tested.

The trusted provider must not log material or render detailed errors itself. It
must clean up failed acquisitions. Its caller owns acquired resource cleanup:
after failure, roll back the **whole** transaction and discard repository handles;
after a successful inspection, explicitly release read locks with rollback or
the approved caller transaction policy. There is no implicit commit, rollback,
connection close, installation or retry inside this service.

## Key custody is a deployment decision, not an implemented vault

`CredentialStorageScope` and `CredentialStorageResources` are explicit dependency
contracts. Constructing them does not prove the namespace-to-tenant mapping,
database origin, key custody or authorization of a server process. They cannot
be client-selected payloads or whitelisted factory parameters. Production needs
a reviewed server registry/provider and approved migration before adoption.

Storage AES keys and ZATCA signing keys/CSIDs have different responsibilities:

| Material | Responsibility | Boundary here |
| --- | --- | --- |
| Storage AES key | Protect staged material at rest | Explicit trusted provider only; no signing-key/site-key fallback |
| ZATCA private key | Sign invoice material for an issuing unit | Encrypted bundle contents; never returned by inspection |
| Compliance/Production authentication | Purpose-specific gateway identity | Preserved inside staged contents; not activated or exported |
| Site/namespace mapping | Separate tenant storage and key access | Server-provisioned declaration, exact current-site guard; not auto-discovered |

Before choosing a provider, review tenant isolation and workload identity,
separate secret access from public operator metadata access, least privilege,
redacted audit logging, key-ID lifecycle and old-version recovery, nonce-volume
limits, rotation/re-encryption policy, protected off-host backups and restored
recovery. Never invent a key when one is missing or silently fall back to another
namespace/key ID. Immutable envelopes cannot be overwritten to rotate a key.
The underlying random-nonce primitive and collision guard do not replace global
key-volume and recovery policy. No file keyring, external vault, actual key
rotation/recovery, or production provider is installed by this increment.

## Verification and limits

The new local suite has **105 passing cases**. It uses generated in-memory
certificates/AES keys, mocked saved documents and the real cipher/repository
logic. It covers all three environments, four allowed operations, three owner
kinds, Company/invoice/device/linked ACL denial, test/ignore-permission flags,
actor drift, slot/source/provider mismatches, legacy checkbox semantics, caller
spoofing, safe errors and Arabic catalog entries. No HTTP or tenant SQL occurs.

Three additional cases run the service with the real repository on the owned
private MariaDB fixture: authorized metadata, denied Company and wrong environment.
Only the document/permission layer is mocked. The combined selection passes
**2,857 local + 51 private SQL = 2,908 cases** at increment 20. Increment 21 adds
[CSR/version-bound Compliance observations](COMPLIANCE_EVIDENCE.md) through the
same permissioned service without changing manifest-only inspection. Its current
combined suite passes 2,993 local + 55 private SQL cases. Use the commands in [STATUS.md](STATUS.md)
and [CREDENTIAL_BUNDLE_STORAGE.md](CREDENTIAL_BUNDLE_STORAGE.md).

Permissioned metadata still cannot establish transactional saved settings, remote
issuance provenance, certificate trust/revocation, current certificate usability,
six completed Compliance steps or a verified credential epoch. Repository audit
decryption uses historical preparation time, not a claim that a staged certificate
is valid today. All activation/dispatch/replay/remote-verification flags remain
false. No live CSID request, real invoice, full restored Frappe site, browser or
ERPNext 16 runtime was tested. Pilot approval and prior live-change notice remain
mandatory. Next: verified onboarding evidence tied to the exact flow/version,
then reviewed transactional activation; never activate from diagnostic flags.
