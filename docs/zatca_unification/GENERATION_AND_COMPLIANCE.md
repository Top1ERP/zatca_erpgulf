# Generation request ownership and early Compliance dispatch — increment 7

Development-only source changes. No site migration, running-process restart,
customer document write, counter migration, or real ZATCA call was performed.

## Four additional reporting adapters

The reporting functions in `sales_invoice_withoutxml`, `zatca_background_sched`,
`pos_submit__without_xml`, and `pos_schedule_background` now consume the same
request route/auth/owner context as the eight previously migrated adapters.
Their eight repeated PIH/notification blocks use the request-pinned owner.
All twelve production-purpose HTTP request adapters identified in this audit now
share owner selection; CSID issuance and wizard Compliance auth remain separate.

The foreground without-XML Sales/POS paths keep their saved issuing-unit
requirement. The two background variants continue to support Company-only
invoices. Local route/auth/owner failures are checked before attaching the
reported XML; existing error handlers may still persist invoice error responses.
Valid requests retain their payload, private attachment, timeouts, logging,
response interpretation, and PIH success guards.

## Six generators divert samples before live identity generation

`compliance_dispatch.py` centralizes dispatch for the two main Sales/POS
`zatca_call` generators and the four without-XML/background generators. The
legacy `compliance_type` argument remains supported:

- String/integer zero selects ordinary generation.
- Codes 1–6 select the corresponding explicit Compliance document type.
- Unknown, empty, boolean, or malformed values raise a translated error before
  metadata generation; they do not select a live or sample workflow implicitly.

The dispatcher reads the saved invoice and its Company, checks an explicit
Company abbreviation when supplied, and invokes the dedicated Sales or POS
Compliance adapter. It passes an explicit label so Company default type cannot
override the caller's requested type. Caller source objects do not override the
saved issuer. Sales serializes only saved document identity; POS passes the saved
document. No credential values are placed in the serialized source.

The diversion happens before the legacy generator's catch-and-log block.
Exceptions and unconfirmed results therefore reach the caller as failures.
The dispatcher accepts only the existing confirmed PASS/WARNING or distinguished
previous-completion contract. It returns that actual result rather than a
success-shaped tuple or an empty return.

Twelve now-unreachable live/sample branches were removed from the six generator
bodies. Dedicated Compliance uses its disposable UUID and temporary XML, with its
separate Compliance counter. It does not write the source invoice's live
UUID/ICV/issuing unit, attach a replacement QR, or write a live submission file.
Compliance is still not fully write-free: its separate counter can advance.

For ordinary generation, signing/QR now receive the saved invoice returned by
the metadata builder, matching HTTP owner selection. The public `source_doc`
parameter remains for compatibility, but cannot select unrelated Company/device
credentials for a live invoice. The dedicated check defaults to its saved
invoice source when no explicit source is supplied; Company-oriented onboarding
can still pass an explicit Company source as before.

## Meaningful verification

`test_generation_routes.py` adds 241 cases covering the four real reporting
functions, three environments and owner modes, 200/202/409 behavior, rejection,
timeout, missing auth before attachments, current mode deferral, the six generators
and sample types, malformed selectors, explicit Company mismatch, unconfirmed
results, and exception propagation.

Bridge tests execute each generator through the actual dedicated adapter using
real temporary XML files and mocked crypto/HTTP boundaries. They assert sample
file cleanup on success/failure and preserved live invoice identity/attachments.
Ordinary-generation checks exercise the existing pipeline with stubbed XML/tax
operations and confirm that signing receives the invoice source and reporting is
called for both string and integer zero.

Frappe HTTP decorator wrappers are bypassed only in site-free tests. Actual
production functions keep their decorators. The full selected suite passes
1,019 local cases. No remote acceptance, SDK verification, real accounting
integration, or ERPNext 16 runtime result follows from these tests.

## Background caller trace (clarified in increment 8)

The current foreground without-XML adapters defer `Batches`. Their background
counterparts defer both `Batches` and `Background`. Caller tracing shows that the
Background variants prepare XML during foreground submission. The scheduled
worker then calls the main on_submit adapter with `bypass_background_check=True`,
which selects ordinary generation or an existing-XML adapter. The preparation
adapter's deferral is intentional; making it send Background immediately would
break that separation. Increment 8 preserves this behavior and tests the actual
parent branch selection, not just the flag on a mocked callback.

The old scheduler entry points used an any-Company time-window gate before
collecting invoices across Companies. Increment 8 replaces it with per-invoice
Company eligibility and enables both POS windows. Explicit manual/batch authority
is unaffected. See [BACKGROUND_SCHEDULING.md](BACKGROUND_SCHEDULING.md). No running
scheduler was changed by either development increment.

ICV continuity mapping, stable retry identity, certificate issuance/renewal,
atomic signing/request credential version, structured 409 acceptance, golden
XML/SDK validation, advance accounting, and real v15/v16 integration remain
the broader release gates in [PLAN.md](PLAN.md).
