# Permissioned archive inspection — increment 23

## Delivered scope

The existing internal `StagedCredentialInspectionService` now supports
`inspect_compliance_archive(company_abbr, source_doc, *, version_id, exchange_ids)`.
It composes increment 20's saved-source permissions, increment 22's authenticated
encrypted storage and increment 21's CSR-bound diagnostic assessment.

There is no whitelisted endpoint, new button, automatic archive scan, write,
dispatcher, active-version selector, key provider or tenant installation. The
existing live Compliance/Debug/issuance callers do not adopt this operation.
Historical manifest-only and supplied-check-set inspection remain compatible.

## Explicit resource and selection boundaries

The server supplies an exact site/namespace scope and a trusted resource provider.
`CredentialStorageResources` has an optional dedicated `archive_cipher`, defaulting
to None so existing three-argument construction remains compatible. Archive
inspection requires this cipher; it never discovers or substitutes a key. The
repository rejects key-material overlap between archive and bundle keyrings.
Constructing these objects is not proof of database origin or secure key custody.

The caller supplies one canonical version UUID and a tuple of 1–64 distinct
canonical exchange UUIDs. It cannot choose a storage namespace, connection, key,
route, authentication header, CSR, raw request or raw response. No latest-version,
all-attempts, inferred identity or missing-row fallback exists. Invalid selection
is rejected before resource acquisition; actor/site checks occur first.

The operation is deliberately an explicit selection, not a complete history
inventory. It does not prove that other attempts are absent, that a selected
success is the latest state, or that a credential remains usable today.

## Permission and evidence order

1. Require the configured site and an authenticated System Manager or Administrator.
2. Validate the bounded explicit identities.
3. Reload and check the saved Company/source/device/linked-owner rows required by
   the existing ownership policy, using the permission engine directly. Neither
   ignore_permissions nor the test flag bypasses these checks.
4. Resolve the saved Compliance environment, gateway and owner without projecting
   legacy credential fields. Request payload settings/secrets are not adopted.
5. Recheck the actor/site before and after invoking the trusted resource provider.
   Require matching server scope and the archive cipher before storage access.
6. Authenticate the exact staged Compliance bundle and match Company/source kind.
7. Load each explicit history through the real archive repository. Recheck actor,
   site and roles before/after each load. Match identity, namespace, exact manifest,
   archived CSR taxpayer and saved gateway. No unchecked history is returned.
8. Enforce a 32 MiB aggregate raw-material budget before retaining another history.
   Count both start and receipt request/response/CSR bytes, including repetition.
   A temporarily loaded record remains subject to individual archive bounds.
9. Build the existing check-set assessment from current observations, requiring a
   shared exact CSR/version/flow/gateway and consistent sample identities. Recheck
   actor/site before returning metadata only.

Required types come from the archived signature-valid CSR functionality profile,
not a new UI toggle or a universal six-type assumption. Standard-only and
simplified-only profiles each retain their existing three-type diagnostic rule;
the combined profile has six. Matching CSR key material does not prove exact
CSR-to-certificate issuance provenance.

Frappe row loading precedes document permission evaluation and can bring a full
row into memory. No denied row or legacy secret is projected to the caller. These
reads do not establish an atomic saved-settings/ACL snapshot with SQL storage;
actor rechecks do not make concurrent row permission revocation atomic. That
integration remains a release gate, especially before any dispatch/activation.

## Public report versus protected material

The report has:

- `state: AUTHENTICATED_ARCHIVED_OBSERVATIONS` — records were authenticated at rest.
- `selection_is_complete_history: false` — the IDs are a caller-selected subset.
- `checks` — the existing bounded CSR/type/result/fingerprint diagnostic projection.
- `histories` — each start/receipt state's existing metadata-only projection.

No CSR, certificate text, signing key, CSID token/secret, request ID, authorization,
invoice UUID, taxpayer, URL, raw body, nonce or ciphertext is returned. The internal
decrypting repository still handles protected material; never expose it directly.
Future UI adapters must translate diagnostic labels and escape rendered metadata.
This increment adds no UI messages or browser endpoint.

`COMPLETE_MATCHED_OBSERVATIONS` in the nested check report means that the selection
contains matching supplied observations for every required type. It is NOT proof
of successful ZATCA checks, trusted HTTP provenance, certificate validity today,
Production-CSID eligibility, permission to dispatch or permission to retry. All
remote/completion/CSR-issuance/activation/dispatch/replay authority stays false.
The method cannot upgrade previously supplied evidence into trusted evidence.

## Errors and transaction ownership

Any missing selected history, corruption, key/resource/source mismatch, budget
failure, conflicting CSR or later SQL failure aborts the entire report. No partial
success/truncation, missing-result skipping or automatic retry occurs. Existing
generic translated permission/failure messages are reused, including their Arabic
catalog entries. Provider/parser/SQL exceptions are not chained into public errors.
Browser language switching and actual Frappe permission evaluation remain untested.

The service performs SELECTs only. It never commits, rolls back, closes a shared
connection or writes a Company/invoice/CSID/status/counter. The trusted provider
owns cleanup if acquisition fails. The caller must release read locks explicitly
after success; after any failure, roll back the whole transaction, discard failed
repository handles and close acquired resources according to approved policy.
Never hold these locks while making an HTTP request.

## Verification

145 new local cases cover six types, three environments, received/absent responses,
200/202/406/401 assessment, saved Company/linked/device owners with Sales/POS
sources, all ACL layers, actor drift, exact/bounded/unique selections including
64 entries, source/route/CSR/identity mismatch, whole-selection failure, safe errors,
key-domain separation, Arabic translation hooks, legacy resource compatibility
and no file/HTTP discovery. Real codecs and repositories use synthetic SQL rows.

Seven new cases run the permissioned service on the owned private MariaDB fixture:
request-only, receipt, six-type selection, denied Company, wrong environment,
missing selected exchange and deliberately corrupted synthetic ciphertext. Only
the Frappe document/permission layer is mocked. The test caller releases locks.

The selected regression suite passes **3,287 local + 89 private SQL = 3,376 cases**.
The private split is 25 journal, 30 bundle/service and 34 archive/service cases.
Commands are in [STATUS.md](STATUS.md) and [COMPLIANCE_ARCHIVE.md](COMPLIANCE_ARCHIVE.md).
The fixture accepts only its owned TCP-disabled process/socket/datadir, never
a tenant or external host configuration. No live ZATCA call, actual OTP/CSID,
SDK, full restored Frappe boot, browser or ERPNext 16 runtime was tested.

## Next gate

Build and audit trusted resource acquisition, transactional source binding and
protected transport capture with actual credential/header/CSR issuance provenance.
Require a committed start before networking, no network under DB locks, durable
receipt reconciliation and no automatic replay after unknown transport/commit.
Do not activate from this report. Rehearse actual v15/v16 integration and complete
key/schema/off-host recovery review and pilot approval. Notify the user before
any live source/config/schema change, installation or worker/Bench restart.
