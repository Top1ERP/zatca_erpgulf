# Saved POS source READ on the shared owned pipeline — batch175–176

This checkpoint adds `capture_pos_profile_context` to the existing uninstalled
`SavedCalculationDefaultsService`. The caller supplies only a saved invoice,
declared ERP major and consumed kind (`limit` or `default`). The profile name,
Company, table/row membership and metadata types come from authorized saved
documents. No requester chooses a master, SQL handle, field set or provider.

## 175: normal saved graph and related access

`PosProfileAcquisition` composes the existing financial graph, related saved-row
READ engine and bounded table membership helper. Document READ alone does not
grant higher-level field READ. Authorize the root Company/profile Links, selected
profile fields, table READ (including an empty table), every saved payment row
and selected payment fields before calling trusted metadata or SQL providers.
Child field levels use the saved parent's allowed levels, as in Frappe's field
filtering; they do not use an invented child role table.

The shared table helper now permits fixed internal subclasses to specify row
projection, child policy/type and row bound. Existing invoice financial tables
retain their original defaults. The POS subclass uses only ownership/revision
fields and the bounded128-row profile table. It does not copy that ACL engine.
The shared exact Link definition helper is also used by Currency-fraction
inspection; its earlier Link projection is unchanged.

Limit inspection never requests POS payment-table permission or metadata. Default
inspection validates membership and field definitions, without applying return
eligibility or inventing a valid Mode/account. Missing/blank profiles retain the
conservative review boundary from [POS_PROFILE_SOURCE.md](POS_PROFILE_SOURCE.md).

## 176: one owner, final rechecks and protected output

A constructor-only `pos_profile_metadata_reader(scope, kind, types)` supplies the
exact applied profile selected by the service. No cache or rounding-settings
callback is introduced. Defaults, Company/invoice metadata, native financial
rows and the native POS lookup use one newly owned connection with the existing
initial rollback, final source checks and rollback/close lifecycle.

The related normal documents supply identity/revision/access, not limit, mode or
default values. Those consumed values remain native SQL observations, retaining
the distinction between NULL and zero and between absent and found-null defaults.
Do not substitute an ORM float, document default or unverified cached API answer.

Initial document/reference objects are retained alongside fresh saved-document
loads. Each original/fresh child's own Meta must match the consumed global
definitions too; matching ownership alone cannot conceal stale field metadata.
Membership, definitions, allowed field levels and actor/READ access are
rechecked around callbacks and after connection close. Final native POS and
financial/default/metadata checks follow the last trusted callbacks. Ordinary
failures use the existing single localized financial-inspection popup; internal
diagnostic keys stay English. Interruptions retain the enclosing cleanup policy.

`SavedPosProfileContext` independently pins the financial/default context, native
lookup, financial-table membership, related master/payment identities and the
initial invoice object's ephemeral owner identity. It has a redacted repr and
cannot be serialized as a worker/RPC/log payload. Its native lookup can supply
the existing pure limit/default observations. It grants neither issuance nor
complete accounting/lookup authenticity.

## Verification and remaining boundaries

Local synthetic tests exercise v15/v16-shaped quiet READ calls, both root types,
early record/table/row/field denial, lazy limit-only dependencies, callback/close
drift, stale original objects, parent child-field levels and strict result/scope
binding. Native tests use only NEW guard-owned TCP-disabled MariaDB, including
same-owned financial/default/POS reads, late callback SQL drift, parent pending
work, refusal of borrowed ambient handles and initial pending-work exclusion.
Counts and limits are in [STATUS.md](STATUS.md).

Batch177–179 adds an internal [co-owned settlement comparison](SETTLEMENT_SEQUENCE.md)
using the same graph and original invoice object, with explicit consumed-lookup
and party/amount handoff checks. Neither inspection is installed in runtime.

This remains an internal explicit inspection. It does not choose active POS
branches, install trusted site/namespace/provider/cache provenance or eliminate
READ COMMITTED graph races after the final check. Complete paid/guard/balance/
POS/write-off assembly, Mode/account/company/currency/return eligibility, missing
profile policy, installed15/16 lifecycle and GL/VAT/XML/SDK acceptance remain
before the separately approved fictional-Company rehearsal. No runtime caller,
schema, invoice/counter write, scheduler, Bench/worker or authority request is
enabled by this development change.
