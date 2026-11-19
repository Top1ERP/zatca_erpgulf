# Existing XML admission to native delivery

Workstream2 source development,2026-11-19. No authority request, live app/site/
schema/service operation, native activation or installed ERP rehearsal occurred.
This adopts existing native originals, not an unowned-XML migration operation.

## Eight actual callsites

| Module | Wrapper | API | Saved device required |
| --- | --- | --- | --- |
| submit_xml_qr_notmultiple | submit_sales_invoice_simplifeid | reporting_api_xml_sales_invoice_simplified | No |
| submit_poswithqr_notmultiple | submit_pos_invoice_simplifeid | reporting_api_xml_sales_invoice_simplified | No |
| sales_invoice_with_xmlqr | submit_sales_invoice_withxmlqr | reporting_api_xml_sales_invoice | Yes |
| pos_submit_with_xml_qr | submit_pos_withxmlqr | reporting_api_machine | Yes |

All four wrappers defer submit-hook work first and consult `native_existing_xml`
before legacy extraction/response writers. All four APIs consult it before their
legacy API body. None selects legacy only for unmarked owners or the current
owned preparation's exact-payload handoff. A native result returns immediately;
it cannot reach the old HTTP/progress/status/PIH/File writers. The common last
transport fence still blocks standalone legacy transport for native ownership.

Inside owned preparation, each API captures its bound payload before old progress
publication. Thus the captured request can be committed by the coordinator before
any native transport; adding the adapter does not create a Redis/legacy-response
side effect inside generation. Debug/Compliance retain their separate entrypoints.

## Admission contract

The saved Source identity is authoritative; a conflicting supplied DocType/name
is rejected. Caller Company, credentials, state or other document values cannot
select the issuer. Normal Source READ+WRITE and Company READ precede decryption.
The source must be submitted and have current native custody. Current fiscal
data/identity must match under the existing publication projection; historical
NULL evidence keeps the full original source comparison. No missing artifact,
legacy UUID or newly uploaded XML can establish a new issuance/zero counter.

Only this site's private local attachment is eligible. Supported input forms are
the private URL, the legacy current-site concatenation, and the current private
folder's local path. A caller path is never opened/resolved/fetched. Metadata is
looked up for the saved source and local URL with a limit of2; exactly one record,
matching File identity/URL and normal File READ are required. Raw/encoded local
URL forms are supported; ambiguous results are reviewed. Cross-source metadata,
public/Debug files, traversal, remote URLs, missing/changed/symlink/nonregular/
oversized files fail. The shared bounded attachment reader selects the actual
local bytes. Site and actor remain pinned through admission.

Those bytes must equal the authenticated retained original exactly. UUID/hash
arguments on raw API calls must also equal its protected metadata. Leading
whitespace/newline/format/signature changes are not silently normalized or
re-signed. Cleared/Debug output is not reinterpreted as the original request.
The transport always uses the custody request; later changes to the attachment
cannot change its payload. Admission is neither signature/CA/SDK certification
nor a grant to import unowned or legacy history.

## Version, type and delivery policy

The verified issuance ID is checked again by the facade and under chain/source
reservation locks, and by accepted-status projection, including its read-only
cached path. Missing/changed custody cannot generate another original, dispatch
a newer version or repair another source version as a side effect of this file.

Delivery uses the normal `entry` policy: Simplified Batches/Background stays
prepared; Live dispatches; the existing explicit manual/scheduled facades retain
their own policy. Rejected/unknown/in-flight/review outcomes cannot be blindly
resent by reattaching an otherwise matching file. Verified cached acceptance can
be reused with disabled rollout/current signing-key loss, without another send.
Current normal source/Company permissions and current company delivery policy
remain enforced.

For retained PREPARED originals, classification comes from the authenticated XML,
not a later Customer B2C flag. The same retained bytes are used in the shared-lock
policy recheck, and the exact supplying issuance is fenced through reservation.
Simplified batching cannot become immediate merely because a Customer changed;
Standard cannot become deferred. New generation still pins current Customer
classification. This applies to the common native facade as well as XML adapters.
The stored request endpoint remains authoritative; an API's historical name does
not fabricate a clearance303 or authorize a different body/endpoint transition.

One shared provider boundary logs a static English diagnostic and displays one
translated review. Schema discovery/authorization/file/parser/driver failures
cannot spill raw data into child popup cascades. No document/credential/callback
is queued, no public RPC/import flag is added, and no source accounting field or
financial expectation is changed.

## Evidence and remaining release work

Local evidence:691 cases across6 suites in4.72s, including complete parent-stable
legacy behavior and new fixed-callsite admission/denial/identity/path/context/
policy/version tests. The fixed81-suite issuer-binding regression passes20,751
in114.45s.138 cases across4 private SQL suites pass in21.63s and cover all eight
actual entries for eligible Company/
device/linked owners; Batches/Live, cached key loss, no extra original/ICV/File,
owned handoff before progress, expected-version reservation/projection, actual
mocked401/400 holds, and retained type after Customer changes, including Standard303.
Focused/private/fixed regression sets overlap and are not additive release totals.

Logs: `/tmp/zatca-axis2-existing-xml-local-final.log`,
`/tmp/zatca-axis2-existing-xml-private-final.log`,
`/tmp/zatca-axis2-existing-xml-regression-final.log`.
Manifest230 local/66 private suites was not run in full. Private active registration
is preseeded, framework loaders are doubles and a synthetic UBL/signing builder
supplies generation. There is no installed ERP, genuine authority, full canonical
financial, CA or SDK acceptance. Original240 comparison91/117/32 is unchanged.

Workstream2 remains open: actual initial/cutover activation with complete legacy
consumer inventory/drain; explicit unchanged retry/corrected-clock operator flow;
draft handoff/durable recovery and source lifecycle; frozen master/print data and
saved File/external print publication; whole runtime qualification. Legacy/unowned
XML and pending legacy consumption cannot be adopted by this exact-original
adapter; they belong to reviewed continuity/cutover. Installed15/16 and specifically
approved fictional-site acceptance remain separately gated.
