# Corrected-version history and explicit XML clock adoption

Workstream2 source development,2026-11-21. Development and verification remain
offline in the isolated worktree. No authority API, live site/schema, actual ERP
invoice or service was changed. Installed ERP15/16 and actual dummy-company
rehearsals retain their separate authorization gates. The Desk/durable-command
correction workflow remains open; this package adopts its backend prerequisites.

## Prior uncertainty cannot be erased by the latest400

The existing explicit prepare_corrected_rejection backend previously required the
current original/attempt, exact encrypted matched400 validation rejection, source
WRITE and current issuer/chain. It did not review older attempts of that same
original. A later rejection therefore could coexist with an older unknown send
or matching acceptance without blocking this internal replacement operation.

Replacement now takes a bounded current locked attempt history before building.
Names/record IDs, contiguous positive attempt numbers, original request hashes
and the named latest attempt must match. Missing history/gaps, over100 attempts or
over16MiB of response bodies keep review. No missing row is inferred to mean the
first attempt. No unknown invocation becomes rejected because its lease expired.

Every attempt must have a retained response. The canonical native assessor opens
the exact original/response and, where needed, the protected303 fallback. Only
known validation rejections, authorization failures and clearance-disabled steps
may precede the named current validation rejection. A prior acceptance, technical/
unconfirmed/duplicate-review result, missing/corrupt receipt or unreceived attempt
holds replacement. Mutable outcome labels and absent assessment labels do not
grant or deny it by themselves. No receipt/outcome is rewritten just to pass review.
The current attempt still independently requires the existing exact matched400.

This guard applies to the existing correction backend with either clock mode,
not just a future Desk action. It does not change ordinary unchanged retries or
the separate late-acceptance review operation.

## Explicit current clock, without editing ERP fields

The [official Detailed Technical Guidelines](https://www.zatca.gov.sa/en/E-Invoicing/Introduction/Guidelines/Documents/E-invoicing-Detailed-Technical-Guideline.pdf)
pages71–72/77–78 distinguish replacement after rejection from unchanged retry:
retain generated originals and their chain positions; corrected documents use
new identifiers/counters and the current generated predecessor. The Reporting
FAQ retains the transaction date; the Standard clearance FAQ updates the issue
date. This public document was read on2026-11-21; no authority API was called.

The explicit internal backend now accepts use_current_issue_time=True. It requires
System Manager, native rollout, enabled Phase2 and ordinary source READ+WRITE/
Company READ under the owned preparation. It selects an aware server UTC clock
after validating the rejection/history. This is not a client date/time or actor
override, and no global timezone/clock is changed.

The implementation policy is explicit: a Reporting original retains its XML
calendar date and uses the generation UTC time of day; a Clearance original uses
the generation UTC date/time. This interprets the FAQ's retained date/new timestamp
combination; it is not a claim that the FAQ prescribes this exact clock algorithm.
The whole-second result must differ from the original instant. A same-second
collision holds locally rather than sleeping or inventing another second. The
retained original endpoint controls the policy, including Standard303 history;
this does not change the existing classification/endpoint rules.

The selected immutable IssueTimestamp is passed in the request-local preparation
ticket. Both real Sales/POS metadata adapters use it only for that production
ticket. XML and derived Phase2 QR use the same fields; posting_date/posting_time,
ledger, financial amounts and the source document are not assigned a new clock.
Normal, Phase1, Debug and Compliance formatting retain the original path. A
correction ticket cannot be used to override a nonproduction request.

Before custody/chain advancement, the backend requires the produced XML date/time
to equal the selected timestamp, along with the existing new UUID/hash/next ICV/
classification/predecessor rules. A builder ignoring or changing the selected
clock rolls back. The previous backend default remains False for existing trusted
callbacks supplying their own explicit distinct clock; its original checks remain.

The resulting linked version is PREPARED, accepted=False and has no automatic
delivery origin. It grants no send authorization. An old-version repeated request
cannot build again or advance the counter; after uncertain commit acknowledgement,
review the committed current original instead of attempting compensation. The
future fixed Desk command/worker must bind the reviewed rejected version/fence and
current fiscal data before calling this backend. This package does not adopt that
operator workflow or treat an old clock override as replay authority.

## Evidence and remaining work

Local tests cover prior-response semantics, explicit time policy and actual Sales/
POS metadata with no persistence. Private SQL covers Company/device/linked owners,
Standard303 history, selected-clock enforcement, current policy/role/permissions,
unchanged source fields, no extra transport, new linked custody/current PIH,
unknown/accepted/technical predecessor holds, safe unassessed older responses and
missing earlier rows. SQL is fixture-owned Unix MariaDB; signing, ERP financial
inputs and HTTP remain synthetic. Counts/logs are in STATUS.md. No financial
reference or original240 comparison (91/117/32) was changed.

Next complete correction Desk/durable-worker adoption, explicit operator messages
and its claim/crash/race policy. Wider history/activation, frozen printing/File
consumers, whole mixed runtime and installed/SDK acceptance remain open in2 and
later gated workstreams. Do not announce workstream3 from this backend package.
