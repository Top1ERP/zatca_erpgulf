# Permissioned pending CSR staging — increment 87 (development only)

## Internal boundary, not runtime adoption

Increment 92 preserves the same binding/error types via reexports from a shared
codec and adds optional [exact original source-history storage](PENDING_CSR_SOURCE_HISTORY.md).
No existing lookup/provider is automatically replaced; source/ACL/provenance and
owned committed-lookup integration remain gates.

Increment 90 adds a protected completion handoff used only by an optional
[owned transaction coordinator](PENDING_CSR_TRANSACTION.md). Ordinary `stage` and
`inspect` still own no commit/rollback/close and return observations only; there
is no runtime button/provider installation or arbitrary RPC completion callback.

Increment 89 adds required explicit Password schema/backing-state comparison,
without decrypting records or claiming an authoritative epoch. Source fingerprints
are now schema 2; old bindings are not recalculated automatically. See
[PENDING_CSR_PASSWORD_STATE.md](PENDING_CSR_PASSWORD_STATE.md).

Increment 88 adds a separate [explicit pinned resource lease](PENDING_CSR_PROVIDER.md)
without installing it or connecting any runtime button. Resource/transaction
ownership and independent provenance limits below still apply.

`SavedPendingCSRService` adds saved-source authorization and metadata-only
`stage`/`inspect` over increment 86's encrypted pending-draft repository. It is
**not whitelisted or connected to a button, wizard, worker, signer, transport,
installed schema or provider**. It generates no key, re-seals no envelope, exports
no plaintext/ciphertext, changes no active credential, and sends no request.

The server constructs a service with a site/namespace scope, an exact historical
binding lookup and a protected resource provider. These dependencies are not
request parameters. Provider origin, key custody and historical lookup provenance
still require independent provisioning/audit. A callback is a trusted dependency,
not a sandbox against arbitrary side effects.

## Access and exact source policy

Every operation requires the configured site and a non-Guest Administrator or
System Manager. Administrator does not bypass ordinary row ACL checks. The
shared credential-write loader requires target READ and WRITE, and related routing
Company READ for a device. It ignores supplied credential values/flags and uses
saved doctype/name only. Both inspected v15/v16 quiet permission signatures use
the shared adapter, with literal `True` required; unknown signatures/faults fail
closed without a second engine invocation.

The new boundary accepts explicit identity dictionaries for Company or ZATCA
Multiple Setting, not invoice/abbreviation-based source fallback. A device must
explicitly use its own keys. Linked-company/unknown flags are refused: select
the actual Company explicitly with its WRITE permission instead. No taxpayer,
alias-priority or signing-owner shortcut turns device access into Company WRITE.
This is a conservative staging limitation, not a change to legacy signing rules.

The saved observation includes canonical naive modified markers, physical field
presence, exact CSR configuration, defined legacy key/CSR/certificate/auth/reference
fields, and relevant Company routing/tax/abbreviation or device link/flag fields.
Required fields must exist. Optional absent aliases are recorded by omission;
adding/removing one changes the fingerprint rather than being treated as an empty
present column. Fields/identifiers come only from app constants, never request SQL.
Text is bounded and not coerced; unknown flag/value types are rejected.

The protected row aggregate SHA256 is compared with `PendingCSRSourceBinding`.
The binding also pins the entire canonical manifest and selected storage key ID.
Manifest owner, Company, source kind, draft ID, revision, environment and exact
configuration fingerprint must match saved observations. It is not enough to
supply any valid encrypted draft or reuse a draft ID. No latest draft, alternative
environment, credential owner, namespace or storage key is guessed.

## Ordering and transaction ownership

```text
actor + exact saved target READ/WRITE + related Company READ
  -> freeze and recheck protected source observations
  -> exact server binding lookup and source/manifest match
  -> recheck -> scoped protected resources -> recheck
  -> bounded locked source reads in the staging transaction -> recheck
  -> exact encrypted repository stage/load
  -> locked source reads + fresh actor/ACL/source recheck
  -> metadata-only observation, still not a commit confirmation
```

Actor continuity is checked before/after each actual ACL call. Source/ACL reads
are repeated around callbacks and SQL work. Resource acquisition happens only
after initial ACL and binding checks. Recognizable ambient `frappe.db` and its
raw parent handle are rejected without cleanup. Arbitrary connection origin or
ownership is **not** proven by that identity check or the resource object.

The supplied non-autocommit connection performs bounded exact source reads with
`FOR UPDATE` before and after repository work. Source locks and pending material
remain in the **same caller-owned transaction**. The service never begins,
commits, rolls back, closes, retries or compensates that transaction. No runtime
DDL exists. The caller must retain its original envelope independently of the
service/result and explicitly decide commit/rollback after all required checks.

Any ordinary failure, source drift, denied ACL, interruption or reentrant attempt
poisons the service. The caller must roll back **the whole transaction** and
discard service/resources, not try another operation on the failed handle. A late
denial after staging leaves pending SQL work for that caller; it does not claim
that nothing was staged or silently clear the caller's earlier work. Cancellation
propagates without a popup, automatic cleanup or resource reacquisition. Successful
calls still require the caller's transaction decision; do not share a service
across threads or treat its in-memory guard as a durable hold.

## Results, messages and privacy

Successful stage returns `PENDING_CSR_STAGED_UNCOMMITTED`; inspection returns
`PENDING_CSR_INSPECTION_OBSERVATION`. Only the manifest diagnostic projection and
current-source/current-permission observation flags are returned. Raw rows,
fingerprint of legacy private state, config/key/CSR, ciphertext, owner names,
providers and connections are not exported. Source/epoch/storage/remote/
activation/dispatch/renewal verification/authority flags remain false.

Child popups are muted in the request scope and flags restored. One static
comprehensive failure is presented outside child catches; Arabic is applied
only at display time using `ar.csv`. App-owned contract codes/states/message keys
stay English. No new log, secret-bearing raw diagnostic, driver string or child
exception context is retained in the public failure. Repr/pickle guards cover
protected dependencies; raw Python fields/trace locals remain disclosure risks.

## What is not established

Locked source comparisons cover defined visible fields only. They do not lock
permission tables, turn Frappe reloads into an independent committed historical
snapshot, prove database/tenant origin, or establish an authoritative credential
epoch. Increment 89 separately compares bounded encrypted Password backing rows;
it does not decrypt them or prove validity/history/absence of ABA. Out-of-band
writers, unknown commit outcomes and after-return ACL/source changes remain
limitations. Lookup declarations/hashes cannot attest their own provenance.
Ordinary row ACL checks do not establish field-level secret/export/log custody.
Those controls require separate review before any real-credential integration.

Staging a separate draft beside populated credentials does not authorize replacing
them, issuing/renewing a certificate or activating the draft. Existing CSR/CSID
preservation guards and known initial shared-certificate/device-alias defects are
unchanged. No real Company, schema, credential, asset, worker/Bench or authority
operation occurs. Installed ERPNext/Frappe 15/16, browser/Desk, SDK and authority
acceptance remain unverified.

Next provision/audit narrowly scoped transaction and independent storage-key
resources, bind a trustworthy issuance source/credential epoch and exact retained
draft to future request/receipt handling, then review coherent activation and all
writers. Nonce/volume/rotation/backup/recovery and abandoned-draft policy remain
release gates. Full development precedes separately approved fictional-Company
rehearsal and later adoption/cancellation or gradual active-client decisions.

## Offline verification

Only `pending_csr_access` joins the fixed local manifest. The existing private
pending-CSR suite adds synthetic Company/device tables inside its owned temporary
TCP-disabled MariaDB database; no app installer or tenant SQL is used. Tests
combine actual cipher/repository/SQL behavior with explicitly mocked Frappe saved
rows and permissions, not an installed v15/v16 Desk session.

The first local-only run passed **13,495 cases in 82.37 seconds**, including the
first 151 new boundary cases, before additional role/input/message tests and
native SQL composition were added. Existing guards/assertions were not relaxed.

Final guarded combined verification: **13,543 local + 1,844 private SQL =
15,387 passed in 157.30 seconds**, across thirteen owned-private SQL suites.
Increment 87 adds **216 cases: 199 local and 17 native SQL**. Native composition
checks Company/device source drift, pending parent visibility, explicit caller
commit/rollback, post-insert permission/revision denial, metadata-only inspection
and source-lock contention/release. All nine standalone Node VM scripts passed
**1,444 cases**. No offline/normal-permission/crypto/transport assertion was waived;
no installed v15/v16, Desk/browser, SDK or authority acceptance is claimed.
