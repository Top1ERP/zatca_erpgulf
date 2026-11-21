# Native custody views and transient printing

Workstream2 development,2026-11-19. This is the first actual Desk/print adoption
of the retained reader, not publication/workstream2 closure. No live app/site/
schema/service operation, chain activation or authority API was used.

## Source of truth and authorization

`native_publication` exposes three authenticated GET-only methods: `preview`,
`download_xml` and `download_original`. Requests contain saved Sales/POS identity
only, plus an opaque issuance UUID for downloads. No document/credential/callback,
URL, acceptance flag or artifact body is accepted. Source READ and Company READ
precede custody decryption. Current signing-key expiry, disabled rollout or a
changed phase cannot prevent an authorized historical read. The authenticated
storage namespace/site encryption key remains required.

The latest source version must match its saved Company, chain, UUID and canonical
ICV. An old download ID cannot accidentally serve a newer version. Accepted states
require re-assessing the exact retained response against the original request,
including bound clearance303 for Standard Reporting. UUID/QR presence, HTTP
success or an ERP status alone never establish acceptance.

## Operation policy

| Custody and document type | QR preview / tax-print candidate | XML |
| --- | --- | --- |
| Simplified PREPARED, DISPATCHING or OUTCOME_UNKNOWN | Generated QR; explicitly unconfirmed acceptance | Exact original |
| Simplified matched REPORTED | Generated QR; accepted | Exact original |
| Standard matched CLEARED | Matched returned cleared QR | Exact returned cleared XML |
| Standard matched REPORTED after bound303 | Original QR; accepted fallback | Exact original |
| REJECTED, REVIEW_REQUIRED or unmatched fallback | Review; no QR or print fallback | Separate diagnostic original only |
| Standard without matched acceptance | Review; no original tax print | Separate diagnostic original only |

Diagnostic downloads use `ORIGINAL_<issuance UUID>.xml`; they do not grant print
permission or repair data/status. All XML bytes, including returned encoding/BOM,
are preserved without an invented HTTP charset. Responses are private/no-store
and nosniff. Raw XML/driver details never enter a display error or log message.

PNG generation encodes the retained canonical Base64 verbatim, error recovery L,
quiet zone4. It does not rebuild TLV, timestamps, money or currency. Capacity/
rendering failure stops instead of shortening a payload. `pypng`, already used by
legacy PNG creation, is now an explicit dependency. Image construction is not QR
scanning, signature verification or SDK acceptance.

## Actual integration

Sales and POS `before_print` reload the saved marker; supplied print JSON cannot
hide native ownership. Render UUID/ICV/chain must match the very same custody
view, rather than a source read preceding a version change. Render data must match
the whole current saved observation, whose fiscal projection is checked against
generation-time evidence. Old originals without that evidence keep the full
original comparison. Only the transient document receives
`ksa_einv_qr` as a PNG data URI and a receipt-derived accepted status, or `Not
Submitted`. No source/File save, status/ICV/PIH update, disk write, signing or
transport occurs. Failure stops native rendering without an old QR fallback.
Legacy fields and an ordinary unnamed unsaved draft retain their earlier path.

The shared Desk asset displays one QR/status section with issued/original XML
downloads and explicit refresh. It temporarily hides the old QR field and restores
its previous visibility when removed. No model write, reload/save or polling delay
occurs. It checks active form, document object, identity, revision and dirty state
before applying results or opening fixed local GET routes. Dirty events remove
old views/buttons; late responses cannot replace a newer/other invoice view.

Labels/messages have Arabic display translations. Child popups are muted only
within the server operation, with the previous flag restored. One static review
is displayed and diagnostic codes/messages remain English. Current source/child/
Company reads use shared NOWAIT locks inside the existing read-only owned boundary;
parent writes/callbacks are still rejected. Views are point-in-time, not perpetual
latest-version leases. Subsequent downloads recheck the current saved identity.

## Remaining release blockers

The first blanket post-payment hold has been replaced for newly captured native
originals by a generation-time authenticated collection-state projection. It
permits only the inspected header/schedule and POS consolidation fields; fiscal
and unknown fields remain exact. Rendered collection values must still match the
current saved source. Old originals are never silently relabeled or backfilled.
The full rule, compatibility boundaries and latest evidence are in
[PUBLICATION_COLLECTION_STATE.md](PUBLICATION_COLLECTION_STATE.md). No monetary
expectation was rebaselined.

Seller/buyer legal/VAT/address fields and their two link titles are now frozen in
the actual transient print hook from saved XML, with strict same-object reprint
observation: [ISSUED_PRINT_PARTIES.md](ISSUED_PRINT_PARTIES.md). Missing XML buyer
VAT/address remains empty rather than read from current masters. This is a
deliberate display change, not a source/financial edit or new print format.

Still open: Letter Head/custom direct master reads, other dynamic print values,
saved File/link and attachment-sidebar consumers; external integrations bypassing
`before_print`; actual browser/print/PDF/scanning, installed15/16 and authentic SDK
qualification. A native source before its issuance marker exists still needs its
handoff/lifecycle print decision. Installed/fictional-site rehearsals require their
separate authorization. On-demand views are not File compatibility closure.

## Evidence

Local policy covers Simplified388/381/383/386, uncertain/accepted/rejected states,
Standard cleared/fallback selection, saved/render/custom-field drift, custody
identity binding, read-only viewers/denials/key loss, returned UTF16 bytes, GET-only
no-store responses and English-log/translated-display separation.

Private SQL uses all six real entries with eligible Company/device/linked owners,
Simplified Batches/Live and Standard Live303 on the two capable primary entries.
The four secondary generators remain Simplified-only reporting adapters; two
unit-specific entries still require a device. Publication adds no chain position,
build/request/commit or File and persists no render QR/status edit. A competing
uncommitted source update causes NOWAIT review; cancelled sources remain readable
for diagnosis. Active registration is fixture input, and a synthetic metadata/UBL
signing builder supplies generation: this is not installed ERP/canonical financial
or genuine authority acceptance. Original240 comparison91/117/32 is unchanged.

Logs: `/tmp/zatca-axis2-publication-local-final.log`,
`/tmp/zatca-axis2-publication-private-final.log`,
`/tmp/zatca-axis2-publication-regression-final.log`.
`test_native_publication_ui.js` runs a synthetic VM, without a browser/site/network.
Focused, private and fixed81-suite sets overlap and are not additive release totals.
