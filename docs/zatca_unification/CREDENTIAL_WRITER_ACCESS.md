# Credential writer access — increment 81, 2026-10-24 (development only)

Increment 82 supersedes the legacy CSR failure-wrapper descriptions below with
one stage-aware owner; see [CSR_LOCAL_OUTCOMES.md](CSR_LOCAL_OUTCOMES.md).
The source guard/save ordering and unresolved active-key risks remain.

Increment 83 additionally blocks observed populated/unknown credential targets
in the local key/CSR paths; it does not protect all CSID/other writers or establish
atomic renewal. See [CSR_KEY_PRESERVATION.md](CSR_KEY_PRESERVATION.md).

## Observed issue and bounded change

`create_csr`, `create_csid`, `production_csid` and internal `create_private_keys`
loaded selected records without explicit row authorization and saved with
`ignore_permissions=True`. Company branches then looked up a potentially
different write target by the supplied abbreviation. UI guards could not protect
direct calls or that identity mismatch.

These four paths now share `credential_write_access.load_credential_write_source`.
Only saved Company/device identity is trusted from dictionary/JSON input. Dictionary
subclasses remain compatible; JSON is bounded to 16,384 characters. Caller keys,
certificates, CSR/auth, linked Company and permission flags are ignored, not used
to construct a Document. Unsupported doctypes/malformed identities and Guest/
missing actors stop before generation, HTTP or saves.

Load the exact saved target and verify returned identity. Require ordinary READ
and WRITE using the existing quiet v15/v16-signature permission helper, with
literal-True results and no unknown-signature fallback. A device additionally
loads and READ-checks its saved linked Company; Company WRITE is not required for
this read-only dependency. Require that Company's abbreviation to match exactly.
No alternate Company lookup, same-VAT bridge, case/trim repair or client flag
bypass is added. Case-mismatched external callers need review before adoption.

## Writes, returns and partial outcomes

Use ordinary `save()` in the selected writers, retaining Frappe's later ORM
permission/timestamp/validation/hooks rather than bypassing them. No explicit
commit/rollback, ignore-version flag, retry, schema or role change is added.
CSR reads configuration from its authorized saved target, not another Company
selected by abbreviation. Its key helper now receives the real abbreviation,
not the old device-document argument quirk. Recheck access before key generation
and before final CSR save. That final guard/save is outside the crypto exception
wrapper so its denial is not wrapped into a second CSR message there.

Public signatures and return contracts remain: encoded CSR, internal PEM bytes,
and auth-free English CSID JSON-string metadata. The key helper remains private,
not a new key-export API. OID/environment/route/timeout, cryptography, credential
field selection and CSID processing/acceptance are otherwise unchanged.

Key replacement still precedes completed CSR. Later access/save failure can leave
a replaced key without new CSR; do not speculate about rollback, restore material
or generate another key. Initial row access does not authorize safe rotation.
Existing active-key/certificate/auth field conflicts remain unresolved.

Source guards preserve parent popup flags/messages and translate only static
final display keys. Unknown ACL exceptions are not stringified by that boundary.
CSID preflight permission denial has local `CSID_SOURCE_ACCESS_DENIED` and native
Frappe PermissionError, not remote ZATCA HTTP 403/401 or issuance success. Other
unverified/malformed sources retain preparation-failure classification. Ordinary
save denial after a reply retains storage-unconfirmed, never an unsent/retry claim.
Interrupts propagate with exact child-state restoration. No logger is introduced.

## Remaining gates

The source holder contains mutable ORM records, not a credential epoch/transaction
lock. Row ACLs, links and abbreviation are observations; related routing, source
and credentials can change during crypto/HTTP. Field-level custody preflight,
active-key preservation, protected receipts, durable idempotency and epoch/
rotation activation remain gates. Ordinary saves can fail after remote issuance;
the answer is review/receipt custody, not weaker permissions or resending.

Legacy CSR crypto/local error wrappers and full framework hooks/logs/tracebacks/
locals/read/export/retention are not certified as one-dialog or secret-redacted.
Other cache/direct writers are not implicitly protected: the legacy explicit
public-key cache writer still has ignored-permission saves/commit. Read-only QR
consumers must keep using their non-writing key helper. Wizard saves and other
legacy APIs/diagnostics require separate review.

No installed/live source/assets/config/schema/site/customer credential/worker
or authority operation is performed. Actual v15/v16 request decorators, ORM
permission/field-role/timestamp/hooks, SDK and authority acceptance remain
unverified. Full development then separately approved isolated fictional-Company
rehearsal remains mandatory before adoption and gradual live pilots.

## Offline evidence

The fixed-manifest suite exercises actual public CSR/CSID bodies/private key
helper with synthetic records, explicit ACL engines, test-only in-memory keys,
mocked saves and mocked HTTP. Only HTTP type decorators are unwrapped without
site initialization. No customer key/file or real HTTP is used.

Coverage includes all source/related row denials; malformed/redirected identities;
abbreviation/link/actor binding; ignored supplied credentials/flags; dictionary
subclasses; ordinary save arguments; English/Arabic denial; unknown ACL/signature
errors; cancellation; CSR access loss after key save; and save permission failure
after a reply. Existing lifecycle tests still characterize key/certificate
conflicts but now assert ordinary saves. Routing fixtures explicitly authorize
their synthetic records: seven old route cases initially stopped at the new guard;
their existing URL/transport assertions are retained, not weakened.

Final guarded Python: **12,300 local + 1,800 private SQL = 14,100 passed in
148.48 seconds**, including **231 new synthetic cases**, across the same twelve
owned-private SQL suites. All nine Node VM scripts passed **1,444 cases**.
No network/site/SQL ownership guard or normal permission/acceptance rule is waived.

```sh
PYTHONDONTWRITEBYTECODE=1 ../../env/bin/python tools/run_unification_rehearsal.py --private-sql
```
