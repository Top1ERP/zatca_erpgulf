# Permissioned QR archive metadata — increment 41

## Internal service, not recovery activation

`qr_source_access.ArchivedQRInspectionService` binds the exact QR source
selector to saved-row authorization and owned local source/archive inspection.
It returns only the selector's redacted hashes/lengths/source-kind diagnostics.
No XML, QR payload, historical clock, certificate, key, token or receipt body is
exported. No whitelist, hook, button call or installed provider is added.

The server supplies `CredentialStorageScope`, a historical lookup callback and
a NEW OWNED connection factory. `inspect(invoice_name, doctype=...)` accepts
Sales Invoice or POS Invoice only. The caller cannot choose an SQL connection,
namespace, source version, identity or credential epoch through those arguments.
These dependencies are declarations, NOT proof of their origin or ownership.

## Shared access/transaction engine

`archive_source_access` now owns the common bounded source projection, quiet
direct saved-row ACL checks, source locks, exact journal read, rechecks and owned
handle cleanup. Advance and QR adapters supply fixed domain binding/row/selector
classes and their runtime/translator/ACL/repository dependencies. Request input
cannot select an adapter or substitute these classes.

The advance adapter retains its public class/import entry points, Sales-only
restriction, marker precedence, messages and type-386 selector. The standard
advance marker still wins even when zero; missing schema or a false marker does
not fall back to a truthy alias. QR projection requires NO advance marker/schema.
Existing advance local and owned SQL regressions run against the extracted
engine unchanged. This is not adoption of either observer in settlement.

No advance search, allocation, remaining balance, accounting eligibility, age
cutoff, historical reference repair, GL/VAT amount or actual settlement builder
was changed. Private shared projection failures use generic internal error codes;
operator-facing advance denials/failures remain unchanged and redacted.

## Order and safeguards

1. Require the exact configured site and a non-Guest System Manager or
   Administrator, then direct read ACL on saved source and Company. This is a
   restricted metadata operator service, not the public recovery POST.
2. Resolve the saved Company/device/linked-Company credential OWNER only,
   with read ACL on each encountered row and `include_secrets=False`. Do not
   inspect current keys/certificates/authentication values to infer old issuance.
3. Capture bounded non-secret fields and `modified` revisions. Recheck actor,
   saved ACL and these projections before/after lookup, acquisition, source/
   journal reads, cleanup and disclosure. Document permission bypass flags are
   never authority; explicit quiet v15/v16 signature selection remains shared.
4. Require exact QR binding type/scope and saved Doctype/name/Company/Tax ID,
   UUID/ICV/issuing-unit, submitted status, environment, route and owner identity.
   Current CLEARED/REPORTED labels are consistency guards, NOT acceptance proof.
   A changed current configuration requires review, not automatic historical
   fallback or credential rotation.
5. Reject recognizable ambient Frappe/raw handles BEFORE cleanup. On the declared
   owned handle, roll back prior uncommitted observations, require autocommit
   off, then lock bounded exact source projections and load the explicit journal
   key/revision from its declared namespace. SQL comparisons detect actual stale
   identities/revisions even when ambient saved-document fakes/cache look valid.
6. Derive the exact request/returned QR source observation, verify source rows
   again, then attempt BOTH rollback and close. No commit or shared transaction
   rollback/close occurs. Interruption cleanup preserves interruption priority.
   Denials/provider/parser/SQL failures return static translated messages outside
   handlers, not private exception context.

All `_verified`/`_authorized` report flags, including permission, persistence and
recovery, remain false. The service checks ambient access and SQL observations;
it does not provide a serializable ACL snapshot or authenticated source capability.

## Unfinished gates

A connection factory can still lie about its site/database/namespace or return
an unrecognized borrowed wrapper. The service recognizes direct ambient identity,
not every possible proxy. No production provider acquisition, database-origin
attestation, committed-record lookup protocol, historical credential fingerprint/
epoch provenance, authentic receipt origin, cryptographic invoice/QR validation
or full issuance snapshot is established here. Projections omit monetary data
and current QR links; they cannot authorize a future recovery write/replacement.

Owned initial rollback discards detectable uncommitted work. It is not global
proof that every supplied historical observation was committed/authentic. SQL
source locks do not atomically lock permission tables or every application epoch.
Current ownership/settings are checked conservatively; migrated old records are
not automatically repaired, rejected for age or substituted with current values.

The recovery button remains PRESERVE/REVIEW only. The audited Phase-2 prefix
deletion/reuse helpers are NOT changed by this increment and need separate
preservation/source-policy integration. No metadata diagnostic may be passed
directly to a file writer as recovery permission.

## Offline verification

Local cases exercise Sales/POS, all three declared environments, both operation
classes, Company/device/linked owners, two signature-shaped ACL engines, per-row
denial, revoked access/source edits, borrowed/proxy failures, cleanup/interruption,
domain/scope/owner mismatch, malformed source input and Arabic errors. Actual
framework data loads, credentials and requests remain mocked; no v16 app boots.

The twelfth owned-private SQL suite covers actual source/archive locks, both
invoice Doctypes and owner paths, stale modified/UUID/case/Tax-ID observations,
and initial rollback of uncommitted source/receipt work. Saved Frappe/ACL remains
mocked. The previous advance SQL suite is regression evidence, not an installed
ERP/physical-File/provider lifecycle rehearsal.

192 new local and 48 new native SQL cases bring the final guarded selection to
**5,463 local + 279 private SQL = 5,742 passing cases**, in **48.92 seconds**.
No prior advance access test assertion was changed for the extraction.

Finish development offline, then separately approved new isolated fictional-client
rehearsal, followed by the user's whole-change adoption/cancellation decision.
No customer source/configuration/schema/worker/data or authority API was touched.
