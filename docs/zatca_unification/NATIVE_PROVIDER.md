# Native entry, worker and delivery adoption

Workstream2 source development,2026-11-19. No live app/site/schema operation,
native activation or authority API call was performed. Default rollout is off.

## Adopted callsites

`native_provider.maybe_process_native_invoice` reloads the saved source and actual
Company/device/linked credential owner. Normal source READ+WRITE, Company READ
and selected-owner READ precede owned issuance. A source's native chain marker
also selects retained custody without requiring current owner credentials. A
native marker cannot fall back to legacy generation after rollout is disabled.
Unmarked legacy owners retain their existing path. Missing marker metadata is
inert; indeterminate/invalid native state is review, never a new registration.

The six production generator entries delegate to the facade after submit-hook
deferral and before their identity/party/counter pipeline:

| Module | Entry |
| --- | --- |
| sign_invoice | zatca_call |
| pos_sign | zatca_call |
| sales_invoice_withoutxml | zatca_call_withoutxml |
| zatca_background_sched | zatca_call_scheduler_background |
| pos_submit__without_xml | zatca_call_pos_without_xml |
| pos_schedule_background | zatca_call_pos_without_xml_background |

The callback is the entry's fixed server function. When called inside the owned
preparation ticket, the facade returns to its original canonical generator body;
it cannot recursively start another coordinator. Existing Compliance delegation
still happens first and Debug remains separate. No public callback/method-path,
credential, document object or caller acceptance flag is accepted or queued.

The deferred worker consults native custody before any legacy status-only skip.
Its native callback uses the original saved validator/route dispatcher with the
old Background early-return bypassed: delivery policy now owns that choice.
The unmarked legacy callback keeps its earlier behavior. Submitted background
collection entries now stage a fixed scheduled command for execution after
commit; eligible unmarked entries retain their original callback. Submitted
manual Sales/POS collections stage an explicit manual command and return
DEFERRED/accepted=False per invoice. Their fixed worker uses this same provider;
an earlier draft's ERP writes cannot trigger inline owned dispatch. Details:
[NATIVE_COLLECTION_REQUESTS.md](NATIVE_COLLECTION_REQUESTS.md).
The POS draft collection's incorrect Sales-variable reference was also corrected.

## One policy across generation and dispatch

| Document and intent | Result |
| --- | --- |
| Simplified, Live or empty legacy default | Prepare and dispatch |
| Simplified, Batches/Background, entry or deferred submit | Prepare only |
| Simplified, explicit submitted manual operation | Dispatch retained bytes |
| Standard, entry/submit/manual | Immediate configured operation; B2C method does not defer it |
| Scheduled operation | Current enabled Phase2 Company, Background method and current configured window required |

`native_delivery` holds a nonserializable, site/actor/source-bound execution
context. Its decision is recomputed from current saved Company/Customer rows
under shared NOWAIT locks before generation and attempt commits. The owned read
view downgrades FOR UPDATE to shared master reads. A changed mode/buyer/window
holds the operation; no DB row lock spans HTTP. The existing site-local inclusive/
overnight/two-window policy is reused. Unknown Simplified methods are review.
This is not another remote acceptance model or permission bypass.

```mermaid
flowchart TD
  Entry[Entry or committed worker identifiers] --> Select[Saved native source or owner]
  Select --> Retained[Read exact retained custody]
  Retained -->|Verified accepted| Cached[Recover status; no key, build or HTTP]
  Retained -->|No original| Policy[Current delivery policy]
  Policy --> Prepare[Original canonical builder in owned read-only scope]
  Prepare --> Commit[Commit exact original and next UUID ICV PIH]
  Commit -->|Prepare only| Pending[Local Not Submitted; accepted false]
  Commit -->|Dispatch allowed| Fence[Recheck policy and commit attempt]
  Fence --> HTTP[One exact-body transport; no row locks]
  HTTP --> Receipt[Retain response before assessment and projection]
  Retained -->|Rejected or unknown| Review[Explicit review; no blind resend or replacement]
```

Preparation now writes local `Not Submitted` and an empty response atomically
with first/replacement identity, after checking actual column capacity. Thus an
imported blank status can be discovered by the existing pending worker. This is
not an accepted status and changes no amount/tax/XML calculation. Verified
acceptance alone can subsequently project REPORTED/CLEARED. If projection fails,
the accepted receipt remains recoverable without rebuilding or sending again.

Before first native generation, an attached XML or Phase2 QR is an ambiguity
requiring review, not permission to infer zero or regenerate. Only the literal
DEBUG_ XML prefix is excluded, so Create XML for Debug output does not masquerade
as a historical fiscal original. No attachment is read/deleted/repaired here.
The selected owner marker must match the actual active chain; a different
active-owner slot cannot silently replace that pointer.

## Results and operator messages

The facade returns bounded English status/IDs/flags, never XML/token/key/raw
receipt. PREPARED means accepted=false. Rejected, stale, authentication and
unknown outcomes cannot become SUCCESS. An already verified accepted receipt
can recover despite an invalid current key or disabled rollout, without HTTP.
Rejected/in-flight/unknown/review custody is returned for explicit review;
ordinary/manual/background discovery cannot blindly retry it or mint a UUID.
The separate exact-retry/corrected-version services still need their operator
adoption; a generic resubmit button is not their authorization.

Child messages during owned work are muted request-locally and restored exactly.
A facade failure has one translated review and an English static-code diagnostic,
without stringifying raw child exceptions. Arabic display is in ar.csv. A failed
operator display is not evidence of remote rejection or permission to reissue.

## Evidence and acceptance still open

Focused local tests cover all six fixed-callsite handoffs, scheduled/manual
collection selection, policy windows/drift, contextual ownership, status
classification, retained recovery and message isolation. Private SQL tests
exercise six actual entry functions across Company/device/linked owners, their
actual API handoff, cryptographic custody, shared master locks, mode changes
before generation/reservation, cached key-loss recovery and bound303 fallback.
The two unit-specific non-background entries correctly reject a missing saved
device; they are not relabeled Company-capable to make a matrix pass.

Final evidence:314 focused local cases across5 suites in1.31s,188 private SQL
cases across6 suites in13.46s, and20,751 across the fixed81-suite issuer-binding
profile in115.06s. Logs are `/tmp/zatca-axis2-provider-local-final.log`,
`/tmp/zatca-axis2-provider-private-final.log` and
`/tmp/zatca-axis2-provider-regression-final.log`. The sets overlap. Manifest227
local/64 private suites was not run in full. The existing old-schema branch
fixture now declares its missing metadata explicitly instead of reaching an
uninitialized framework Meta loader. No financial expectation was rebaselined.

Private registration is explicitly preseeded active; no activation is proved or
performed. Their metadata stub supplies the existing synthetic UBL/signing builder
inside the actual entry's owned scope. This is not complete canonical ERP financial
generation, installed15/16, CA trust or SDK acceptance. Financial reference files
and the original240 comparison91/117/32 are unchanged.

Remaining workstream2 work includes actual initial/cutover activation and complete
legacy-consumer inventory/drain; publication
compatibility/frozen master and print data (first Desk/transient-print adoption
is described in [NATIVE_PUBLICATION.md](NATIVE_PUBLICATION.md), with authenticated
collection updates in [PUBLICATION_COLLECTION_STATE.md](PUBLICATION_COLLECTION_STATE.md));
explicit unchanged retry and corrected-clock adoption; source cancel/delete/rename
decisions; and whole runtime qualification. Manual and scheduled draft callers
now preserve their fixed operation through the parent intent; exact pre-transport
closed-window checks may wait, with uncertain originals retaining priority. See
[NATIVE_DRAFT_SUBMISSION.md](NATIVE_DRAFT_SUBMISSION.md). The
older submitted-invoice collector still has its24-hour horizon, while the native
Background PREPARED discovery is now age-independent. The later
[durable native submission intent](NATIVE_SUBMISSION_INTENT.md) replaces native
submit-hook callback-only handoff and adds age-independent READY/WAITING discovery;
started/uncertain recovery and later PREPARED discovery are still open.
Installed/dummy-site rehearsals
retain their specific authorization gates. Workstream2 is not closed.

Explicit untouched-PREPARED recovery now has its own readonly Issuance form action
which registers the same manual collection command and fixed worker. It handles
Standard/non-Background originals by deliberate operator authorization, not by
changing automatic schedule/actor policy. It never rebuilds or retries uncertain
custody. Automatic non-Background recovery remains open:
[PREPARED_ORIGINAL_RECOVERY.md](PREPARED_ORIGINAL_RECOVERY.md).

Origin-backed automatic first-send recovery is now adopted for newly captured
DISPATCH originals, preserving the original enabled actor/operation and current
method/window checks. Deferred Background has its existing distinct schedule
authorization; Batches PREPARE stays manual. NULL-origin old records no longer
receive current-policy-only automatic discovery, and retain explicit manual
recovery. No original header/XML/AAD or financial reference changed:
[ISSUANCE_ORIGIN_RECOVERY.md](ISSUANCE_ORIGIN_RECOVERY.md).

The explicit [exact retry operator](EXACT_RETRY_OPERATOR.md) now stages a separate
retry-v1 command through the same fixed worker. Only the exact current version/
prior attempt/fence can use that mode, with fresh lease and canonical retained
failure checks at reservation. Ordinary/manual/automatic first-send operations
still cannot resend unknown custody. No body, UUID/hash/ICV or financial reference
is replaced, and unchanged retry is distinct from corrected rejection issuance.

The four existing-XML wrapper/API pairs now use exact private attached-original
admission and the same owned facade. Retained PREPARED classification is frozen
from authenticated XML through the shared policy recheck, and version expectations
are fenced through reservation/projection. Details and qualification limits:
[NATIVE_EXISTING_XML.md](NATIVE_EXISTING_XML.md).
