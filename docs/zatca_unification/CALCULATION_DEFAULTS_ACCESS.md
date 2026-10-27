# Saved-source permissioned calculation defaults acquisition

Increment 112 — 2026-10-27. Server-only development service; not installed.

Increment 114 adds `capture_context` to the same transaction/presentation service,
combining defaults with exactly invoice/Company metadata and their final SQL
rechecks. The original `capture` remains defaults-only. See
[CALCULATION_CONTEXT.md](CALCULATION_CONTEXT.md).

## Responsibility and composition

`calculation_defaults_access.py` composes the scoped defaults SQL reader with
saved-source READ, actor/site checks, an explicitly owned connection and an
explicit cache reader. It returns a protected server object, not UI/RPC/queue/log
data or authority acceptance. No callback, provider, hook, whitelist, schema,
certificate or environment switch is installed.

The common saved-record ACL/drift mechanism is extracted once as
`ArchiveInspectionEngine._saved_record_access`. Existing archive/review/recovery
callers retain their original owner graphs, READ/WRITE and status policies.
The new service chooses only invoice and Company, without certificate owner,
route, UUID, ICV or accepted-status prerequisites. Native fixtures deliberately
have no Phase-2 Company/device columns. This keeps the read usable as a staged
dependency for Phase-1 as well as Phase-2 sources without coupling it to CSIDs.

## Access and scope contract

`SavedCalculationDefaultsService.capture(invoice_name, doctype=...)` requires
the configured site, an authenticated Administrator/System Manager and ordinary
saved READ on that exact Sales Invoice/POS Invoice and its Company. It invokes
the shared direct permission engine with the inspected quiet v15/v16 keyword;
Document permission shortcuts and bypass flags are not consulted. Every saved
identity/revision/ownership check repeats around dependency acquisition and
before protected disclosure, including after cleanup.

The operator role is a conservative local staging policy, not a ZATCA rule or a
new requirement imposed on ordinary runtime POS/invoicing. Adopting a runtime
worker/user policy is still an integration gate. Draft/submitted/cancelled saved
sources are readable; this does not authorize submission, rebuilding or sending.

Parent selection is fixed by the SERVER constructor: `site` means `__default`,
`global` means `__global`, and `user` means the current authorized actor. A call
cannot select another user/parent. These are separate APIs/scopes, not a guessed
precedence chain or user-overlay implementation.

## Fresh transaction and consistency boundary

All normal saved ACL checks precede factory/cache access. The existing owned
connection acquisition helper rejects recognizable ambient DB/raw identities
without cleaning them, rolls back only the acquired owned connection to discard
pre-existing pending work, and rechecks permissions. Factory ownership/tenant/
registration/session provenance must still be audited; arbitrary wrappers or
hostile trusted callbacks are not sandboxed.

In the same owned transaction the service locks exact source projections, reads
all selected defaults rows, checks the supplied cache, repeats source/defaults
membership checks and checks the cache again. A final SQL recheck detects changes
made during the second cache callback too. Source projections contain invoice
company/docstatus and Company identity/revision only. Framework get_doc supplies
documents for ACL; this minimal projection is not a claim that ORM acquisition
reads only those physical columns or captures complete financial/settings data.

Cleanup always attempts both owned rollback and close, including cancellation;
no commit is performed. Failed acquisition/cleanup or late permission loss
denies disclosure. Ambient transaction state and prior pending parent work are
preserved. Native tests prove initial owned rollback, stale ambient-source
rejection, pending parent continuity, RC insertion detection and callback-owned
edit rollback. SQL is native, but ACL/documents are synthetic, not installed ERP.

This establishes the reviewed acquisition sequence under the explicit trusted
dependency contract. It does not prove provider origin, atomically freeze ACL/
cache tables, prevent RC phantoms after the final check or ensure freshness after
locks are released. A full preparation source guard must compose all dependencies
and its own complete transaction/isolation/index strategy.

## Protected result and one display message

`SavedCalculationDefaultsRead` independently validates/copies the declared
site/namespace, actor, minimal source rows and defaults observation. It accepts
only the two exact linked source rows and the configured/common/current-user
scope, with private repr and no pickle. There is no verified/authorized grant,
complete preparation fingerprint, fiscal resolver or persistence/export method.
Generic dataclass/raw-payload access is not a disclosure sandbox.

The existing `mute_operation_messages` context suppresses child popups and
restores the parent's flag exactly on success, error, nesting and interruption.
Existing parent messages and UI language remain intact. One final app-owned
failure is translated for display after restoration; internal codes/labels
remain English. The two Arabic translations are included in ar.csv. Tests cover
nested producer messages, not merely the number of throw calls. This introduces
no new UI button or live message behavior until separately adopted.

## Verification and remaining work

Synthetic tests cover both inspected permission signatures, Sales/POS, three
parent kinds, saved states, role/row denial, late actor/source/ACL drift, borrowed
handles, cleanup/interruption, cache/SQL changes, private result corruption and
Arabic/parent-message ownership. Native SQL runs only on a new guard-owned
TCP-disabled server with synthetic source/default tables. Counts are recorded
in [STATUS.md](STATUS.md).

Next implement committed metadata/Custom Field/Property Setter acquisition and
compose it with scoped defaults and the remaining source graph. Effective
precision, complete amount/XML/GL/VAT parity, pipeline adoption, installed v15/v16
and SDK acceptance remain gates. See [CALCULATION_DEFAULTS.md](CALCULATION_DEFAULTS.md),
[DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) and
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md). Working-environment changes
and all authority requests remain prohibited.
