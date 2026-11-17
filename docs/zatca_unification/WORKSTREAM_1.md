# Workstream 1 — source, settings and credential binding

Local development closure, 2026-11-16. This is the source/settings/material
contract milestone, not deployment, installed ERP15/16 acceptance, CA trust,
transaction/ICV safety, SDK acceptance or authority authorization. The precise
adopted routes, deliberately retained extensions and storage decision are in
[WORKSTREAM_1_CONTRACTS.md](WORKSTREAM_1_CONTRACTS.md).

## Closure checklist

- [x] One frozen saved Company/source/device selection supplies each adopted
  route and purpose authorization; no split Company-read credential selection.
- [x] Bind source identity, original modified provenance, business observations,
  phase and environment through the native preparation/signer/request lifetime.
  Detect observed drift; do not claim a database snapshot, trusted epoch or lock.
- [x] Native signing/QR use one purpose-token certificate and matching key/time/
  taxpayer context. Alias conflicts fail; no secret-field repair, owner fallback,
  key overwrite or purpose-token copying is performed.
- [x] Adopt ordinary Sales/POS, generated/scheduled, Debug, dedicated/synthetic
  Compliance, collection and existing-XML wrappers. Preserve explicit imported
  callback contracts without claiming native proof for replacement callbacks.
- [x] Explicitly keep versioned credential staging/activation outside this
  release. Existing CSR/key and Final-CSID preservation remain; initial onboarding
  is supported, destructive automatic renewal is not silently enabled.
- [x] Publish field/owner/purpose mapping, conflicts, evidence and limits.

Native production source READ/WRITE and Company READ, enabled Phase-2 and native
signing preflight precede UUID preparation. The metadata return is rebound before
party/counter builders. Debug uses no API auth and consumes no scheduling window.
One Company selection covers all six Compliance types. All thirteen invoice HTTP
invocation sites have a final observation fence. Final writer/temp/extractor
bytes are bound to the captured request, catching same-UUID/hash file replacement.

Before transport, review asserts no request was sent. After an invocation marker,
review explicitly treats delivery/acceptance as unknown. Display translates;
error strings and explicit diagnostics remain English. The marker is not a receipt.

## Reproducible closure verification

From this development worktree only:

```sh
PYTHONDONTWRITEBYTECODE=1 ../../env/bin/python tools/run_unification_rehearsal.py --profile issuer-binding
```

This fixed **81-suite local** profile retains the existing offline guard and
reviewed global allowlist. It cannot enable private SQL or accept an arbitrary
suite/host/site/command. The full default manifest remains205 local/57 private.

Final profile result: **20,747 passed in126.97 seconds**.
Six standalone browser suites pass1,208 synthetic cases. Nine read-adapter module
AST restorations match parent2d96f2c exactly, demonstrating that these wrappers
preserve their earlier financial/counter algorithms;13 HTTP sites are fenced.
No existing financial reference fixture or expected amount was rebaselined.
The original240-case comparison is still91 identical/117 differences requiring
review/32 ambiguous blocked. It is not a count of customer failures.

The final profile includes the earlier19,539-case76-suite integration selection,
new source-provenance/profile checks and1,202 credential-preservation cases.
Additional focused boundary checks passed691; the final scoped source/request/
material selection passed246. These are overlapping evidence, not additive totals.
Logs: `/tmp/zatca-axis1-profile-final.log`,
`/tmp/zatca-axis1-release-regression-final.log`,
`/tmp/zatca-axis1-scope-final-provenance.log`,
`/tmp/zatca-axis1-credential-preservation.log`,
`/tmp/zatca-axis1-browser.log`, `/tmp/zatca-axis1-read-audit.json`.

A separate frozen default-manifest qualification completed: **39,003 passed in
3017.23 seconds**,205 suites. The detached qualification commit b78fd24 pins
runtime44fdd50 plus only a retry-fixture correction: the input XML UUID now matches
the intended request. No runtime or expected financial result was changed there.
Log: `/tmp/zatca-axis1-frozen-qualification.log`. This broader local result includes
later-workstream primitives; it is not installed ERP15/16, SDK or live acceptance.

## Explicit remaining ownership

Workstream2 owns transaction/ICV/PIH/identity/response and retry coordination,
including uncertain results and legacy409 handling. Workstream3 owns native
financial/advance/GL acceptance and original baseline differences. Workstream4
owns file ownership/path validation, remaining duplicate extractors and runtime
cleanup. Installed15/16 and authentic signed XML/QR/local SDK remain5/6. A separately
approved isolated fictional-company rehearsal and adoption decision remain7.
No live/site/schema/invoice/tenant-SQL/restart or authority API action occurred.
