# Saved-source permissioned capture — increment 26

## Delivered scope, not deployment

`compliance_capture_access.py` supplies an internal staged Compliance operator
boundary. It resolves saved Company/source/device/linked-owner identities without
reading legacy credential secrets. It authorizes all selected rows before calling
a server-supplied resource provider, checks exact row revisions inside the same
owned transaction as the bundle/request reservation, and repeats that check in a
separate closed preflight transaction before transport.

There is NO whitelist, button/worker/hook adoption, connection/key discovery,
schema installer, active credential selector, customer/invoice creation or live
ZATCA call. The provider and body/CSR/requirements are trusted SERVER inputs,
not a client API for arbitrary bodies, keys, URLs or namespaces. The provider
returns protected dependencies/factories, not an already borrowed connection.

The source SQL reader and service are optional. Existing low-level coordinator
callers retain two transactions. Guarded calls use three: source/bundle/reservation,
source preflight, then immutable receipt persistence. All owned connections must
commit AND close before the next stage. No owned lock survives HTTP.

## Saved selection and row coverage

The shared owner resolver accepts Company, Sales Invoice, POS Invoice or ZATCA
Multiple Setting identity only. Caller-supplied field values are ignored; saved
links and the explicit Use Company Certificate and Keys flag determine the owner.
Source Company, selected owner/source kind, environment and CSR Tax ID must match
the exact staged manifest/requirements. There is no latest/version/env override,
Production-credential fallback or implicit Sandbox switch.

| Saved row | Compared non-secret columns, in addition to modified |
| --- | --- |
| Company | abbr, tax_id, custom_select, all three configured environment URLs |
| Sales Invoice | company, custom_zatca_pos_name |
| POS Invoice | company, custom_zatca_pos_name |
| ZATCA Multiple Setting | custom_linked_doctype, custom__use_company_certificate__keys |

One to four distinct rows are locked in deterministic doctype/name order before
bundle/archive locks. SQL identifiers come only from the server allowlist. Names
are bound parameters; text retrieval is bounded to 4,097 characters and rejects
values exceeding 4,096. Missing rows/columns, malformed timestamps/flags, wrong
types and autocommit connections fail closed without schema repair or fallback.
The installed custom-field schema must be rehearsed before runtime adoption.
The reviewed provider must target MariaDB/InnoDB tables with the required lock
semantics. This reader does not attest database/table origin or storage engines;
no PostgreSQL/MyISAM compatibility or automatic engine repair is provided.

The naive MariaDB/Frappe modified DATETIME is normalized only for exact revision
comparison; it is not UTC capture time or a credential epoch. This projection is
NOT a complete invoice/child-table or signing-material snapshot. Frappe permits
updates without changing modified; those changes are detectable here only when
they affect a projected field. The [Frappe database API](https://docs.frappe.io/framework/user/en/api/database)
documents that option and the checks bypassed by raw SQL. This adapter performs
no ORM writes; explicit ACL precedes its narrow read-only SQL locking check.

## Permission policy and Frappe 15/16 compatibility

The conservative new operator policy requires the bound site, a non-Guest System
Manager (or Administrator), and direct permission-engine read AND write checks
on EVERY selected saved source/device/linked-owner row. It does not call Document
check_permission/has_permission, whose ignore_permissions shortcut is not accepted
at this boundary. Linked Company write permission may be more restrictive than
some current operator roles; review the deployment policy, never silently weaken it.

`permission_compat.py` is shared with the existing metadata-only staged inspection
service. It examines the explicit trusted permission-engine signature and invokes
that engine ONCE. Frappe 15's raise_exception=False suppresses diagnostic output;
the inspected [Frappe 16 permission source](https://raw.githubusercontent.com/frappe/frappe/version-16/frappe/permissions.py)
uses print_logs=False. Unknown signatures fail closed. An internal TypeError does
NOT trigger a second attempt or another permission path. Literal True is required.
This is signature compatibility, NOT a booted ERPNext 16 or permission-policy proof.

Site/user/role and saved ACL/revisions are rechecked around each source SQL check.
After preflight commit/close and fresh material/time validation, a final guarded
transport wrapper reloads saved ACL/revisions before giving the request to the
actual transport dependency. No flags.in_test/ignore_permissions bypass, shared
Frappe commit/rollback or permission-cache invalidation is performed.

These repeated checks use the AMBIENT Frappe permission engine/cache/transaction.
They do NOT atomically lock User/Role/User Permission/DocPerm tables in the owned
SQL transaction. They cannot establish globally fresh revocation or prevent a
change immediately after the last check. Direct SQL verifies projected saved rows
against that transaction, not complete ACL/source/XML/epoch provenance. Provider
database/site/namespace origin remains a separately reviewed deployment duty.

## Failure, receipt and privacy boundaries

- Initial actor/ACL/input/source mismatch stops before storage-key provider access.
- Reservation source/bundle/SQL/commit/close failure returns
  PREPARATION_UNCONFIRMED_NO_SEND, with no underlying transport invocation.
- Fresh SQL source/ACL or preflight commit/close failure returns
  DISPATCH_PREFLIGHT_FAILED_NO_SEND; the initial reservation remains spent.
- A final wrapper ACL/revision failure does not invoke the actual sender, but the
  generic coordinator conservatively returns TRANSPORT_UNKNOWN_NO_REPLAY. The
  coordinator cannot attest arbitrary callback behavior or authorize another try.
- Once a response exists, receipt persistence continues independently of later
  source edits: losing operator access must not discard already received evidence.
- Duplicate identity, unknown exchange or persistence outcome never permits
  automatic resend. Another explicit exchange identity is still another attempt;
  cross-attempt onboarding policy/outbox/leases remain unfinished.

Protected results retain the exact recovery envelopes for trusted internal
reconciliation. They are not operator JSON. Only existing redacted diagnostics may
be rendered; every source/epoch/remote/completion/activation/replay authority flag
remains false. The ephemeral source rows are NOT durably archived in this increment.

Row/resource/service repr hides names, Tax IDs, URLs, ciphers and callbacks, and
pickle is forbidden. Do not queue/log/export them via asdict/vars/custom serializers.
Static translated operator errors are raised outside provider/parser/SQL exception
handlers. Both English source messages have Arabic CSV translations; framework
language resolution selects them. No secure memory erasure or key custody is proven.

## Verification and next gate

206 new local source-service cases cover all six types/three environments and
Company/implicit/own-device/Sales/POS/linked-owner selection, read/write ACL before
provider access, exact saved/SQL mismatch even with stale ambient document reads,
three closed transactions, guard literal-True policy, ambiguous preflight commits,
actor/ACL/revision drift during SQL and after closure, source interruption cleanup,
duplicate/no-replay, bounded parameterized SQL, static privacy and translations.
18 permission signature cases cover both version-shaped/decorated engines,
non-boolean denial, unsupported signatures and no internal-TypeError retry.

Eight owned-private MariaDB cases exercise the real locked-row comparison with
reservation/archive and Requests/urllib3 against synthetic HTTP pools. Source
edits before reservation/before preflight and unknown preflight commit stop sends;
duplicate collection cannot invoke the pool again. A concurrent writer is blocked
until the guarded row locks are released. Reduced synthetic row tables and fake
Frappe ACL are not full restored application integration. TCP HTTP is forbidden;
only the fixture-owned SQL Unix socket is used.

Selected regression result: **3,839 local + 118 private SQL = 3,957 cases**.
Commands are in [STATUS.md](STATUS.md) and [COMPLIANCE_ARCHIVE.md](COMPLIANCE_ARCHIVE.md).
No real ZATCA/OTP/CSID/TLS, tenant reads/writes, browser, full restored Frappe boot,
SDK/golden signatures or ERPNext 16 runtime was exercised.

Next: audited tenant/namespace/owned-connection and protected-key providers,
durable source/credential epoch and CSR issuance evidence, actual reviewed
transport attestation/deadline/TLS harness, and explicit unknown-outcome recovery.
Rehearse restored v15/v16 schemas/permissions and six-type signed fixtures before
choosing runtime adoption. Schema/key/off-host recovery review, pilot approval and
prior notice before ANY live source/config/schema change or Bench restart remain.
