# Native printing before issuance

Workstream2 development,2026-11-21. This package changes only the isolated source
worktree. It neither installs schema nor operates a live invoice/site/worker or
authority endpoint. Installed15/16, actual dummy-company, browser/PDF/POS receipt
and SDK acceptance retain their separate authorization and qualification gates.

## Problem and resulting behavior

The print hook previously selected native custody only after the saved invoice
contained an egs: issuing-unit marker. Before an asynchronous preparation worker
saved that marker, an enabled Phase2 invoice belonging to a registered native
owner could return to ordinary rendering with an old persisted Phase1 QR/File.
UUID presence alone does not establish a saved generated document.

For a named saved Sales/POS source without that marker, before_print now checks
saved Company policy and resolves the actual certificate owner through the same
saved-source/device/delegate selector as processing. A registered native owner
requires a verified native document; until one is saved, the hook stops rendering
with one translated message. It does not claim a preparation request exists, is
queued, has run, or has authority acceptance. Operators review the saved request
and issuing unit and refresh after preparation. There is no polling delay.

The print selector needs Source/Company/selected-owner READ only. The selector's
processing default continues to require Source WRITE as well. Missing permissions,
invalid native registration IDs, missing selected devices and inconsistent saved
identity stop printing rather than permit a legacy fallback. Diagnostic text stays
static English and private exception/record values are not exported.

| Saved selection | Print behavior |
| --- | --- |
| Company schema predating native ownership | Existing legacy rendering |
| Unissued Phase1 or ZATCA disabled | Existing rendering, no added owner ACL gate |
| Enabled Phase2 and actual selected owner unregistered | Existing legacy rendering |
| Enabled Phase2 and actual selected owner registered native, no source marker | Hold with one unissued-document message |
| Registered native owner with rollout off or not yet active | Same hold; no silent legacy fallback |
| Saved egs: source marker | Existing strict custody reader, regardless of current phase, rollout or signing key |
| Unnamed unsaved draft | Existing draft rendering |

The Company's native registration does not override a separately selected legacy
device or certificate delegate. Conversely, an unregistered Company cannot hide a
registered selected device/delegate. Request print JSON cannot change the saved
Company/device selection to bypass admission.

Deliberate hold for adoption review: an older unmarked Phase2 invoice under an
owner now registered native is also held. No activation date or historical legacy
print grant is inferred from its ERP date, QR, UUID or display status. Reviewed
legacy adoption/print compatibility must resolve that case before rollout.

After preparation, the existing custody rules still govern: a generated Simplified
original can print without asserting Reporting acceptance; Standard requires
matched clearance or the bound accepted303 fallback. Print projects QR and frozen
party fields into render memory only. This package does not change those rules,
XML/money/taxes/currency, receipt classification, UUID/ICV/PIH or chain allocation.

## Side effects and limits

The new admission only reads saved policy/ownership and normal metadata/permissions.
It creates/finalizes no request, enqueues no worker and performs no build, signing,
File/source write, chain advance, commit or HTTP. In particular, attempting to
print during parent STAGED or committed READY does not promote or execute that
request. Framework error diagnostics use the existing log boundary.

This is the fixed application's before_print boundary, not an enforcement layer
for arbitrary privileged Python/SQL or external engines that bypass it. Owner
selection is a point-in-time read, not a perpetual render or rollout-change lease.
It does not invent a historical chain when source markers were manually removed.
Desk previews before issuance, Letter Head/custom direct master reads, other print
values, later overriding hooks, saved File/sidebar consumers and installed POS/
HTML/PDF qualification remain open. Do not infer whole print/workstream2 closure.

## Verification

The new local suite adds26 cases: Sales/POS, draft/submitted named sources,
rollout on/off, read-only printing, unchanged processing WRITE, actual device/
delegate selection, Phase1/disabled/legacy/older-schema preservation, alternative
phase-field fallback, identity/permission/registration failures and one Arabic
translation. Existing publication tests also cover hidden render markers,
unnamed drafts, historical read-only/key-loss access and Standard acceptance gates.

The new private SQL suite adds10 cases across all six actual native entries and
Company/device/delegate owners. It verifies hold before generation, successful
printing after retained custody, Phase1/rollout changes after issuance, and both
STAGED/READY parent handoffs. Counter, builds, mocked requests, transaction writes,
commits and enqueue state are unchanged by the print attempt.

Final qualification:603 local cases across14 reviewed suites in3.48s and162
private cases across5 suites in25.85s. Logs:
`/tmp/zatca-axis2-print-admission-local-final.log` and
`/tmp/zatca-axis2-print-admission-private-first.log`.
The private first run passed and remains the final private qualification; no
runtime/private-test change followed it. Only two extra local assertions followed.
Manifest251 local/85 private is not a full-run claim. HTTP/build/ERP inputs remain
synthetic and SQL is fixture-owned under /tmp, TCP disabled, private Unix only,
with the mandatory offline guard. No UI asset changed. The original240 financial
comparison remains91 identical/117 review/32 blocked; no reference was rebaselined.
