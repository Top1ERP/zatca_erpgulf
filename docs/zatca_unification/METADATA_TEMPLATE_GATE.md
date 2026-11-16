# Template validation before canonical identity creation — increment227

Development only, 2026-11-16. No installed source, site/configuration/schema,
invoice, Bench or worker was changed. No tenant SQL or authority API was used.
Unit spies record write/commit arguments; they are not ORM durability evidence.

## Narrow problem and boundary

Increment226 selected template mode immediately after metadata in six ordinary
Sales/POS generators and both Debug adapters. Sales production metadata can
persist a missing UUID using the existing `db_set(..., commit=True)` before
returning. Therefore an initially mixed item-template table could be rejected
after that identity write. POS production generates its UUID without that Sales
write, and Debug produces only a preview, but their allocation still preceded
the same source check.

Canonical `createxml.salesinvoice_data` and `posxml.salesinvoice_data` now use:

1. The same single document-loader invocation and existing timestamp validation.
2. Source-owned plain/template/mixed validation for production and Debug.
3. The unchanged existing UUID provider/reuse/persistence rule for that purpose.
4. Another template-mode observation to detect observed change during callbacks.
5. The unchanged metadata append and original three-value public result.

An initial mixed/invalid template table fails at step2: the UUID provider is not
called, no metadata nodes are appended and no new identity write is performed
by these canonical functions. Existing saved UUID is retained. Timestamp errors
still take priority, as before. This is not a complete fiscal/preflight gate:
later customer, VAT-account, reference, credential, signing or storage checks can
still fail after identity creation.

The Sales `_get_or_create_sales_invoice_uuid` body is unchanged, including retry
reuse and its existing `commit=True` argument. POS production's UUID rule and
the shared preview UUID functions are unchanged. No UUID is erased/replaced to
repair an error, no counter is rewound, and no existing UUID implies acceptance.

## Callback drift and retained writes

Inspected local Frappe15 `frappe/model/document.py`, commit
`7b430f5eec8c0537f2f0cde9d30e175ae9068647`, SHA256
`8178edc26b565bfb7dbb0a01a45e772f9bfc42d4f0f5784b2a419be2b84e4ac6`:
its `db_set` invokes `before_change` and `on_change` around the write and can
commit afterward. This is a read-only source finding, not a live hook execution
or proof that an installed16 behaves identically.

The post-identity observation calls the same current mode reader. An all-plain
to all-template change (or the reverse) receives static code
`metadata_item_template_changed`; newly mixed/invalid rows receive the existing
source code. Both use the existing English canonical review/diagnostic and
Arabic display key, without another wrapper/popup. The check precedes XML append.

A UUID already written by the provider/hook is **retained** when this second
check fails. There is no rollback or side-effect erasure promise. The scalar
check observes only mode: same-mode template-ID, rate, money, Company or revision
changes are not frozen or authenticated. Master/credential/transaction custody
and atomic issuance remain separate release gates.

## Shared generation entry and integration compatibility

`invoice_generation_data.prepare_invoice_generation` is adopted by the six
ordinary Sales/POS generators and both Debug implementations. It returns the
root, UUID, loaded document and checked mode to their unchanged later sequence.

The public metadata functions still return three values by default. The new
private `_include_template_mode` option returns the fourth value only for
production/Debug composition. A code-reference identity check plus matching
runtime, translator and mode-reader bindings permits this internal path. The
stored canonical reference is code only: it contains no document, site,
credential, permission grant or source snapshot.

Imported metadata replacements receive their exact original two-argument call,
plus `purpose="debug"` only where Debug already supplied it. They never receive
the new private keyword. Their returned root/document are preserved, and the
caller's current mode reader checks the returned document afterward. Distinct
runtime/translator/reader bindings also retain this compatibility path.
Replacement code can perform earlier writes: the adapter cannot certify or undo
them. A replacement wrapping canonical metadata can still benefit from its early
check, but arbitrary replacements do not gain the canonical no-initial-write
guarantee merely by being callable.

The default path performs two intentional row-mode observations around identity
callbacks, without a third caller scan or another invoice-loader invocation.
The compatibility path can add a caller observation; there is no universal read
count, SQL query count or latency benchmark claim. Attribute-only partial legacy
metadata records remain supported by the mode reader; absent/empty rows select
plain mode, not proof of a valid invoice.

## Deliberately retained Compliance boundary

Dedicated Compliance keeps its existing three-value metadata call and subsequent
Company-mismatch check, then the increment226 template check. Canonical metadata
does not inspect template rows for purpose `compliance`; the private four-value
option is not supported for it. This avoids moving a template decision ahead of
the existing Company binding. Compliance preview, separate counter, temporary
file and authority route remain unchanged; no such request was actually sent.

## Evidence and remaining work

`tests/fixtures/metadata_gate_d9c87a4.py` freezes both metadata functions and all
eight generator bodies from226. SHA256:
`4fddb950aa2d7c889d94cc45ee1fb7b0c401f764c84002f96307ccedeb78839d`.
Tests execute the real metadata and UUID-provider functions under controlled
UUID factories and synthetic runtime/write spies. Actual SQL/Frappe hooks,
genuine signing, SDK, scanner, GL and installed16 lifecycle are not executed.

269 new cases include32 initial mixed-source comparisons,48 public metadata
byte/write-contract comparisons,8 canonical return/read checks,12 distinct-binding
fallbacks,8 metadata override contracts,1 override side-effect example,8 simulated
Sales `db_set` drift cases,6 partial-record compatibility checks,2 Compliance
boundary checks,128 complete-parent generator comparisons with imported metadata
and16 native eight-route early-stop cases. Synthetic15/16 row shapes are distinct
from actual installed16 acceptance. Random preview UUIDs are fixed only in tests
to compare deterministic metadata bytes; production factories are unchanged.

Structural restoration reconstructs the eight exact parent generator bodies and
both metadata functions after removing only the documented composition/gate
changes. Existing financial/type/reference/UUID-provider/ICV/signing/QR/API/artifact/
permission algorithms remain. Original financial differences retain their review
status. Final regression/UI counts and logs are recorded in STATUS.md.

The final guarded run passes17,109 cases across68 reviewed suites, including269
new. Focused269 and1,208 browser cases pass.349 other tracked runtime files and
28 earlier Python reference fixtures are unchanged. Original240 remains91
identical/117 changed/32 blocked, independent of the new parent comparisons.
No private SQL or whole-manifest run is included, and repeated runs are not
summed as independent validation evidence.

Complete saved-source/settings/phase/credential custody, full fiscal/GL/precision/
settlement and identity transaction integration, installed15/16 and SDK/scanner
before separately approved isolated fictional-client rehearsal. No test success
authorizes this branch on working sites or permits an authority API request.
