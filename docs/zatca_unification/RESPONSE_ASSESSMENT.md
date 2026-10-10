# Endpoint-bound response assessment — increment 15

Development branch only, 2026-10-10. No installed source, schema, settings,
credentials, invoices, counters or PIH were changed. No invoice was submitted
and no bench/worker was restarted. Notify the user before any live application
change; this increment does not authorize deployment or automatic retries.

## Regulatory semantics versus defensive application checks

A genuine expected ZATCA response **200 means success**; **202 means success
with warnings**. Warnings must be reviewed, not relabelled as rejection. The
official table distinguishes 303 (clearance disabled), 400 (rejection), and
401 (authentication failure).
[Detailed Guidelines, version 2, May 2023, printed pages 53–55](https://www.zatca.gov.sa/en/E-Invoicing/Introduction/Guidelines/Documents/E-Invoicing_Detailed__Guideline.pdf)

The official developer manual's successful clearance example includes validation
PASS, no errors, clearanceStatus CLEARED and clearedInvoice.
[Developer Portal Manual, printed page 61](https://zatca.gov.sa/en/E-Invoicing/Introduction/Guidelines/Documents/DEVELOPER-PORTAL-MANUAL.pdf)

These references support response semantics, not the assertion that any local
caller-supplied bytes came from ZATCA. The checks below are an **application
consistency policy**, not new ZATCA rules. Invalid HTML/proxy/display responses,
wrong operation, contradictions and another invoice's returned XML must not
silently update live status or PIH.

## Implemented pure boundary

`ResponseAssessment(DispatchJournal)` derives immutable observations from the
receipt already bound to an unchanged prepared candidate and attempt. Outcomes
cannot be supplied as constructor claims. The model reads no settings, clock,
database, credential, file or HTTP service. No runtime adapter consumes it yet.

| Local observation | Assessment | What it does not authorize |
| --- | --- | --- |
| 200/202, coherent PASS/WARNING, explicit errors=[], matching REPORTED | REPORTING_ACCEPTANCE_MATCHED | Live status/PIH writes without verified receipt provenance and transactional service |
| 200/202, coherent PASS/WARNING, explicit errors=[], matching CLEARED and returned XML metadata | CLEARANCE_ACCEPTANCE_MATCHED | Trust in signature, computed invoice hash, QR or accounting parity |
| 400, coherent ERROR with nonempty structured errors, no accepted outcome or wrong-operation status | VALIDATION_REJECTION_MATCHED | New UUID/ICV, corrected reissuance or replay |
| Other 400 | HTTP_REJECTION_OBSERVED | Inventing the validation cause from a bare status |
| 401/403 | AUTHORIZATION_FAILED | Changing credentials or reissuing |
| 409 | DUPLICATE_UNCONFIRMED | Treating every duplicate as accepted |
| 303 on clearance | CLEARANCE_DISABLED_OBSERVED | Silently switching route or sending a second request |
| 5xx | HTTP_FAILURE_OBSERVED | Declaring invoice validation failure or acceptance |
| No receipt / unknown transport | NO_RESPONSE / TRANSPORT_UNKNOWN | Automatic replay or identity reset |
| Malformed/inconsistent success receipt or unexpected status | UNCONFIRMED | Acceptance inferred from status alone or historic display text |

An observed 202 always sets has_warnings, including an omitted/empty warning
list. A declared WARNING or nonempty warning list also sets it. Structured
warning_count is retained; raw messages and request ID remain in the protected
receipt instead of a second mutable response dictionary. Optional info/warning
lists may be absent; errorMessages must be explicit. Supplied message type/status
must agree with the containing list, and textual fields must be strings.

Non-null outcomes belonging to the other operation are rejected. Both accepted
statuses, unknown values, fatal errors under PASS/WARNING, or ERROR without
errors remain unconfirmed. An optional returned invoiceHash must exactly match
the prepared artifact's declared digest. That comparison does not recompute it.

## Wire decoding and returned XML

`response_json.py` centralizes the existing duplicate-key and bounded/finite
number decoder. Historical diagnostics reuse those primitives, but retain their
known label/HTML wrapper handling unchanged. HTTP receipt decoding instead
requires bounded immutable bytes, strict UTF-8, exactly one JSON object, and
ASCII JSON outer whitespace only. It rejects display labels, HTML suffixes,
multiple objects, duplicate keys, nonfinite/unbounded numbers and bad encoding.
The exact receipt bytes/hash in the journal are never rewritten.

Reporting need not return XML. If reportedInvoice is supplied, it is checked.
Clearance requires clearedInvoice. Non-null XML for the wrong operation fails.
Strict Base64 decoding allows ASCII whitespace only, with a 5 MiB decoded XML
bound. The existing no-DTD/no-entity/no-external-resource inspector is reused.

Returned root invoice ID, UUID, ICV, seller VAT identity, type code/indicator,
declared invoice digest and PIH must match the prepared artifact unambiguously.
Only a completely matching assessment exposes exact returned bytes privately,
with a SHA-256 diagnostic fingerprint. Failed assessments retain raw evidence
in the protected journal, not an apparently accepted returned artifact.

Clearance can change serialization, XML encoding, signature, certificate and QR;
requiring byte equality with the submitted artifact would be incorrect. The
submitted candidate remains immutable. Neither metadata agreement nor matching
declared digests proves business-data parity, signature validity or recomputed
invoice hash. A deliberate test changes monetary data while leaving declared
digests untouched to demonstrate this boundary. Do not interpret MATCHED as a
cryptographic verification or a persisted live CLEARED/REPORTED status.

## Verification, privacy and next gate

278 new local tests cover Sales/POS, three declared environments, four type
codes, reporting/clearance, success/warning/rejection/auth/duplicate/303 states,
malformed JSON, returned-XML identity and bounds, changed signature/QR/encoding,
late responses, safe diagnostics, immutability and no I/O. Synthetic fixtures
contain invalid signatures and do not establish any remote acceptance.
Combined selected suite: **2,326 passing cases**, Python 3.10/Frappe 15 locally.
No actual ERPNext 16, site integration, browser or ZATCA SDK was exercised.

Bodies/messages/XML/raw URLs are excluded from repr and diagnostic projections.
Do not use generic dataclass serialization in logs/UI. Returned bytes require
the same protected durable artifact storage as submitted bytes in a future
service. Static internal issue codes need translated messages at that boundary;
no untranslated UI was introduced here.

Every assessment keeps remote_acceptance_verified, network_provenance_verified,
signature_verified, invoice_hash_verified, business_data_verified,
persistence_verified, dispatch_authorized and replay_authorized false.

Next: bind signing and HTTP to a verified atomic credential/source/chain snapshot;
implement durable repository/outbox/leases and cross-attempt reconciliation;
verify authoritative receipt capture and artifact integrity before transactional
status/PIH updates. Rehearse interruption/concurrency on restored sites and run
pinned SDK/ERPNext 16 acceptance before connecting this boundary to live paths.
