# Saved-owner admission for Desk previews

Workstream2 development,2026-11-21. This adopts the unissued print decision in the
existing Sales/POS Desk preview. Source/assets/tests only in the isolated worktree;
no live schema/site/service, actual invoice or authority API operation. Installed
ERP15/16 and actual dummy-company/browser/POS/PDF/SDK acceptance remain gated.

## Server classification and side effects

Before this package the Desk asset required a source egs: marker and otherwise
left the old QR field visible. The server preview always attempted native custody.
That did not represent a selected native owner waiting for its first saved original.

The existing GET preview still accepts saved doctype/name only. It verifies exact
saved identity and Source READ before classifying. The print and preview decisions
share _unissued_native_selected, which observes saved Company phase/enablement and
the actual device/delegate certificate owner through the shared owner selector.
Preview exposes no owner/chain identifier, secret, request or document input.

| Result | Meaning and payload |
| --- | --- |
| LEGACY | Existing display path selected; status only, no acceptance assertion |
| UNISSUED | Enabled Phase2 and a registered selected native owner, no saved source issuance marker; one translated waiting message, no QR/issuance/acceptance |
| READY | Existing strict saved custody/receipt reader and exact QR selection |
| REVIEW | Unresolved identity/permission/policy/custody; one static translated review, never a legacy restore |

Ordinary UNISSUED/LEGACY reads do not log an Error Log. They require no native
storage namespace/encryption key, builder, request creation/finalization, queue,
counter, File/source write, signing, commit or HTTP. The print hold still uses its
existing error boundary when printing is actually attempted. Native custody READ
and receipt matching remain unchanged, including historical key/phase/rollout loss.

Older-schema, Phase1 and disabled sources receive LEGACY without imposing Company/
owner READ. An enabled Phase2 owner selection retains its existing Source/Company/
selected-owner READ checks; unresolved permissions are REVIEW. No WRITE is needed
for viewing. Processing still requires WRITE by default. A Phase2 legacy device
or delegate is not overridden by its Company's native registration, or vice versa.

## Form lifecycle

Each refresh of a named saved form performs one fixed local GET, with no timer or
polling. Until the result arrives the old QR field is hidden, because an absent
egs: marker does not prove legacy ownership. A confirmed LEGACY result restores
the field's exact previous visibility, removes our panel/buttons and detaches our
dirty listener. Request failure/unknown status keeps it hidden with one review.
This additional classification read and temporary hiding also apply to Phase1/
legacy saved forms. Unsaved unnamed/local ordinary drafts keep their old path.

UNISSUED displays one waiting panel and a manual refresh action, with no image or
XML download. It does not claim a request is queued/running or remotely accepted.
The client uses fixed catalog messages; arbitrary server message HTML/text is
ignored. English/Arabic display paths are tested against the actual CSV catalog.

If custody appeared after an unmarked form loaded, a READY response asks the
operator to refresh the invoice. Its QR/downloads are not placed beside that old
form's fields and the model is not rewritten. An already marked form cannot use
a contradictory LEGACY/UNISSUED response to restore an old QR. Dirty native forms
require save/discard; unknown dirty forms may complete only classification so a
confirmed legacy form can restore its normal field without a model write.

Tokens bind form object, route, source identity/revision, UUID/ICV/issuing unit
and Company/device selection. Dirty events or late responses cannot install an
older image or overwrite a newer form view. The handler owns only its namespaced
listener, panel, buttons and temporary field visibility. No reload/save/set_value,
private File URL or authority operation is introduced by this asset.

## Compatibility limits

The earlier deliberate hold for older unmarked Phase2 invoices under a newly
native registered owner still applies; no historical print grant is inferred.
Known legacy owners, however, receive their ordinary existing display. This is
not proof that legacy artifacts or statuses satisfy authority acceptance.

The preview is a point-in-time saved view. Custom/external print engines, Letter
Head/direct master reads, other dynamic print data, later overriding hooks,
saved File/sidebar consumers and real installed browser/PDF/POS behavior remain
open. The read is not a perpetual lease or remote crypto/SDK/acceptance evidence.
This does not activate native registrations, import history or close workstream2.

## Verification

17 new local cases cover both saved source types/draft states, rollout off/on,
Phase1/disabled/old-schema/legacy without native key requirements, Source/Company
read denial, exact source identity and redacted policy/driver failures. Waiting
and legacy cases make no publication/issuance calls and do not log normal waits.

10 new private cases cover all six actual entries and Company/device/delegate
owners, before/after generation and during parent STAGED/committed READY. They
verify no write, head/build/mocked-HTTP/commit change and no request promotion or
enqueue. Subsequent explicit fixture worker execution makes retained READY
publication available even after current phase/rollout changes. SQL/runtime/UBL/
HTTP inputs are fixture doubles, not installed ERP or authority requests.

Final evidence:620 local cases across15 reviewed suites in3.27s;172 private SQL
cases across6 suites in28.67s;172 preview UI cases and108 Company message cases
in two Node synthetic VM scripts. Sets are not additive release coverage. Logs:
`/tmp/zatca-axis2-preview-admission-local-final.log`,
`/tmp/zatca-axis2-preview-admission-private-first.log`,
`/tmp/zatca-axis2-preview-admission-ui-final.log`,
`/tmp/zatca-axis2-preview-admission-company-ui.log`.
The passing private first run is final private evidence. The mandatory offline
guard denies external/site access and allows fixture-owned Unix SQL only, under
/tmp with --no-defaults and TCP disabled. Manifest252 local/86 private was not run
in full. Financial/golden references are unchanged; original240 remains91/117/32.
