# Non-destructive advance QR print hook — increment 37

## Bounded development change

`advance_deduction.ensure_final_sales_invoice_qr_for_print` is registered on
Sales Invoice `on_submit` and `on_update_after_submit`. It is not an explicit
artifact-repair boundary. Before this change, the non-initial-advance branch
deleted `QR-ZATCA-Advance-Aware-*` File rows and sometimes linked a different
creation-ranked QR. Also, `force=True` bypassed the existing-link guard for an
initial advance and could generate a replacement.

Both behaviors are removed in DEVELOPMENT only:

- Final/subsequent/non-initial invoices return without File inspection, deletion,
  link clearing, replacement or repair. A suspicious historical filename does
  not authorize a hook to alter a stored artifact.
- Eligible initial advances use the same bounded, same-invoice metadata adapter
  and [pure preservation/review policy](QR_ATTACHMENT_PRESERVATION.md) as ordinary
  Sales/POS QR generation. A current owned reference is preserved even if
  `force=True`; unresolved/orphan/foreign/malformed/over-limit observations and
  missing links with REPORTED/CLEARED labels raise the existing translated review
  error before image/File creation or invoice writes.
- The `event` and `force` arguments remain accepted for call compatibility.
  `force` is no longer permission to replace an artifact. It does not perform
  repair or claim that any preserved QR is authentic or correct.

The shared adapter is internal, not a new public endpoint or a saved-row ACL
boundary. Parent invocation authorization still applies. It inspects File
metadata only: no file/image reads, directory scans or authority calls.

## Deliberately unchanged

Phase-2 Company early return, schema capability, submission state, QR-field
presence, initial-advance classification and positive deducted-taxable gates are
unchanged. Ineligible paths do not run the new File query. Current settings are
not proof of the historical invoice's phase; that provenance gate remains open.

First generation without a stored reference/candidate retains seller fallback,
VAT lookup, timestamp conversion, SAR/base-currency arithmetic, discount amount
selection, TLV formatting, filename, image options, public File save and single
QR-link metadata update. The hook still does not write acceptance status, save
the invoice recursively, commit or roll back. Errors propagate to the parent;
actual filesystem rollback and parent error handling are not established here.

No advance search, allocation, remaining amount, settlement eligibility, original
XML lookup, GL/VAT calculation or historical invoice data is changed. A synthetic
2020 date exercises this QR hook without an age cutoff; it does not validate the
entire historical settlement workflow. Tests characterize existing amounts, not
their regulatory correctness. No deployment, migration or customer repair ran.

## Evidence and remaining work

62 new local cases execute the hook with synthetic documents and mocked ERP,
image and File operations. They cover forced preservation, differing phase/name
hints, review states, non-initial invoices, existing early gates, old dates,
discounts/FX, Arabic review messages and propagated failures. Source assertions
also forbid deletion, transaction ownership and recursive invoice saves.

Four additional owned-private SQL cases exercise the advance hook's same-invoice
File projection for preserve/orphan/dangling/foreign-URL scenarios, extending the
existing eleventh suite. They prove unchanged synthetic database references and
attachment rows, not physical PNG/File-controller or installed-app behavior.

The explicit `qr_regeneration` endpoint is NOT fixed by this change: its saved-row
authorization, heuristic/latest XML/QR selection, implicit recovery and commits
still need a separate bounded audit. Phase-2 helpers, concurrent generation,
actual File deduplication/rollback, full ERPNext 15/16 installation and browser/
print acceptance remain gates. Increment 38 separately adds
[saved-row recovery access checks](QR_REGENERATION_ACCESS.md), without replacing
the button's legacy selection/implicit repair/commit behavior. Do not use an
unreviewed button to bypass REVIEW.

Finish offline development first, then seek separate approval for the new
isolated fictional-client rehearsal. The user still decides whole-change
adoption or cancellation afterward. No working environment or authority API
was touched or authorized.
