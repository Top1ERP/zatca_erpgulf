# Encrypted Password-state comparison — increment 89 (development only)

## Gap and bounded change

The pending-source comparison previously covered saved document values only.
A Password field can retain the same mask/modified marker while its encrypted
backing row changes. The inspected local Frappe 15 implementation stores encrypted
Password values separately in `__Auth`; the app's checked-in credential fixtures
normally use text fields. This is a defensive customized-schema boundary, **not
a diagnosis that a customer's current fields are Passwords**.

`pending_csr_password_state.capture_password_state` adds bounded read-only
observations of exact known credential-field backing records, without decrypting
them or accessing a site's encryption key. `SavedPendingCSRService` requires an
explicit expected backing-state digest and compares before and after repository
work in the same caller-owned transaction. No runtime button/provider/site,
schema, active credential, signing/request or authority operation is activated.

## Source/schema and binding

Saved schema capture now identifies Password fields among the existing nine
known config/key/CSR/certificate/auth/reference fields. Missing/unknown field
definitions or unsupported field types fail closed. Only explicit text-like or
Password types are supported; no arbitrary coercion or schema inference is used.
Optional absent aliases remain distinct from present columns. The protected row
fingerprint moves to `pending_csr_source_schema: 2`, including Password-field
identity. The encrypted draft's version-1 envelope/manifest format is unchanged.

`PendingCSRSourceBinding.password_state_sha256` is mandatory, not an optional
empty/fallback value. Existing schema-1 source fingerprints are not automatically
adopted/recalculated, and there is no tenant binding migration. The trusted server
lookup must retain the expected digest from an independently reviewed preparation/
custody flow; comparing a freshly invented expectation to itself proves nothing.
No production lookup/provisioner or authoritative epoch registry is supplied here.

## Locked bounded backing observations

After saved-source ACL/binding/resource checks and locked source-row comparison:

1. Require non-autocommit and an exact ordered selection of one or two authorized
   Company/device identities, with app-constant Password field names.
2. Read only those owners' known credential field names from `__Auth`, using
   bounded substrings, a bounded row limit and `FOR UPDATE`.
3. Require unique exact fields, integer `encrypted=1`, nonempty bounded UTF-8
   ciphertext text, and an explicit Password schema declaration for every row.
4. Compute only a protected namespace/source/schema-bound aggregate SHA256 of
   ciphertext fingerprints and explicit presence/absence observations.
5. Compare to the expected binding before storage and again after storage,
   alongside fresh ordinary source/actor/ACL checks.

The query includes **all nine known names**, even absent/non-Password aliases.
Unexpected historical/orphan backing rows are rejected rather than ignored,
selected as an alias, decrypted, cleared or repaired. Unrelated owners/Password
fields are not scanned. Missing rows are observed absence, not evidence that an
issuing unit was never enrolled. Hashed/plain (`encrypted=0`), malformed/unknown
flags, duplicate/oversized/non-text rows and SQL/schema errors fail closed.

Rotated, removed or added encrypted bytes change the digest even when the UI mask
and source modified value are unchanged. Re-encrypting the **same plaintext** also
changes the observation and requires review; this is exact stored-state comparison,
not semantic password equality. Opaque ciphertext is not decoded or validated as
a usable Fernet token, certificate, authority credential or real authorization.

## Ownership, privacy and limits

The helper never generates/decrypts/discovers keys, writes credentials, installs
DDL, commits, rolls back, closes or retries. Its caller owns failure cleanup.
The service poisons itself on failure; late mismatch may leave staged work which
the caller must roll back together with its parent transaction. Interruptions
propagate. Static English failures contain no raw SQL/ciphertext/parser context;
the existing single-popup/display-only Arabic boundary remains unchanged.

Only `password_backing_state_match_observed=True` is added to success metadata.
No raw backing row, ciphertext/digest, plaintext, owner identity or source-binding
fingerprint is returned. `credential_epoch_verified`, source/storage/remote proof
and activation/dispatch/renewal authority remain false. Protected repr/pickle
restrictions are not a memory/export/logging sandbox; encrypted bytes exist in
ordinary memory during reads, and trace locals/manual field serialization still
require restricted diagnostics and field-level secret custody.

Existing-record locks serialize ordinary competing updates until caller release.
Missing-row inserts, isolation/gap-lock differences, mutations after the final
check/return, restoration of identical bytes (ABA), out-of-band schema/writers,
lookup provenance and atomic permission/commit handling remain limitations. This
is **not a monotonic authoritative credential epoch**, remote validity check or
source/ACL-aware commit coordinator. Matching declarations cannot attest their
own historical origin, actual tenant or approved key/vault provenance.

The SQL profile is based on inspected local MariaDB/Frappe 15 code. Synthetic
tests cover both quiet permission signatures; installed ERPNext/Frappe 16 schema,
roles/hooks/transactions, PostgreSQL, Desk/browser, SDK and authority acceptance
are not established. No existing credential is cleared or reconstructed. Full
development and separately approved fictional-Company rehearsal still precede any
adoption/cancellation/pilot decision or change to the ban on authority requests.

## Offline evidence

Only `pending_csr_password_state` joins the fixed local manifest. The existing
owned-private pending suite adds a synthetic `__Auth`-shaped table to its temporary
TCP-disabled database. Test-only opaque encrypted strings are not customer
passwords and are not claimed to be valid authority credentials. Existing text
fixtures explicitly declare their schema and empty backing observations; no
ordinary permission, crypto or transport assertion is weakened.

The first local-only guarded run passed **13,707 cases in 84.10 seconds**, including
the first 81 new local cases. Tests cover strict schema/selection/row/bounds/error handling,
mask-preserving rotation/deletion, schema/orphan changes, related Company state,
post-repository drift and caller-owned failure behavior.

The first combined run passed **15,594 cases in 166.71 seconds** before adding
an explicit Password-field-count preflight bound and its regression case. Native
tests compose the pinned provider/service/cipher/repository with synthetic backing
rows: mask-preserving rotation/deletion/unknown flags, unchanged source revision,
orphan refusal without repair, post-insert same-transaction drift with caller
rollback, related Company drift, and existing-record lock contention under both
tested isolation selections. No tenant Password or encryption key was read.

Final guarded combined: **13,708 local + 1,887 private SQL = 15,595 passed in
163.91 seconds**, across thirteen owned-private SQL suites, including **107 new
cases** (82 local + 25 native SQL). All nine standalone Node VM scripts passed
**1,444 cases**. No offline resource, ordinary permission, crypto or transport
guard was waived. No installed v15/v16, Desk/browser, SDK or authority acceptance
is claimed.
