# Existing-XML adapters and ICV continuity audit — increment 6

This is development-only work. No production process, stored counter, customer
XML, certificate, or ZATCA state was changed. The ICV implementation is unchanged.

## Four more request adapters use the shared context

| Module | Request function | Saved issuing unit required |
| --- | --- | --- |
| `submit_xml_qr_notmultiple` | `reporting_api_xml_sales_invoice_simplified` | No |
| `submit_poswithqr_notmultiple` | `reporting_api_xml_sales_invoice_simplified` | No |
| `sales_invoice_with_xmlqr` | `reporting_api_xml_sales_invoice` | Yes |
| `pos_submit_with_xml_qr` | `reporting_api_machine` | Yes |

These four existing-XML reporting adapters now share the route/auth/owner context
introduced for the primary Sales/POS adapters. Eight duplicated PIH/notification
blocks now delegate to the request-pinned owner. This makes eight migrated live
request functions across the two increments; it does not cover every submission
or background path in the application.

The two machine-specific adapters keep their issuing-unit requirement. A new
optional context guard checks the **saved** invoice link, not caller-provided
fields; they cannot silently fall back to Company credentials. The general
adapters still support Company-only invoices. The new error has an Arabic catalog
entry. Existing URL/header compatibility helpers remain available. The two raw
token header helpers still take raw Basic tokens; the callers strip the single
normalized prefix before using them, avoiding a doubled `Basic` prefix.

The files are read and encoded by the existing readers; XML is not regenerated,
re-signed, attached again, or given a new UUID/hash/ICV. Request timeouts remain
480 seconds for the simplified Sales adapter and 300 seconds for the other three.
The existing 200/202/409 response handling, error/status persistence, and logging
are unchanged. These functions remain reporting-only; the refactor does not
choose a new reporting/clearance classification for a stored XML document.

`test_legacy_submission_context.py` adds 151 cases with actual temporary XML file
reads and mocked saved documents, HTTP, logs, and persistence. They cover three
environments, Company/device/linked ownership, accepted and rejected statuses,
timeout, missing auth/environment, taxpayer mismatch, caller-injected links,
owner changes during HTTP, the four real extraction/submission wrappers, and
unchanged XML/QR references. The test XML contains only synthetic data.

## ICV audit: why the key cannot simply be replaced

`test_icv_identity_contract.py` adds 22 read-only characterization cases against
the existing `_issuing_unit` and `_counter_key`. They intentionally document
legacy behavior, including unsafe edge cases, to force an explicit migration
decision before the implementation changes. They do not allocate or seed counters.

| Observed behavior | Continuity risk |
| --- | --- |
| Company fingerprint hashes the raw selected credential text | Prefix/whitespace cleanup or credential rotation can select a different counter |
| Device fingerprint prefers final auth, then Compliance auth, then device name | A missing/freshly issued credential can change identity; purpose is not part of field selection |
| Device fingerprint ignores the linked-company certificate flag | HTTP/signing may use a Company while ICV still identifies the device's stored token |
| Company uses Production auth only for the exact `Production` argument | Passing an API environment such as Simulation is not equivalent to the existing purpose convention |
| Company/device prefixes and Company name remain in counter identity | Equal credentials do not imply that historical counters can be merged |
| Counter key replaces `/` and truncates the whole string to 140 characters | Different names can collide; sufficiently long Company names can remove owner/purpose from the key |

The counter DocType offers `Production`, `Compliance`, and `Debug`. The Sales/POS
XML builders pass those **purpose-like labels**, not Company API selections
`Sandbox`, `Simulation`, and `Production`. Debug reads the Production counter;
dedicated Compliance allocates separately. Do not mechanically substitute API
environment names or the new authorization owner into existing keys.

These findings are from source and synthetic tests. They do not prove that any
tenant already has a collision or broken chain. No tenant counter values or
credential material were inspected for this increment.

## Required migration design before changing ICV

1. Build a read-only inventory of counters, saved invoice ICV/issuing-unit fields,
   issuing-unit links, credential epochs, and accepted XML references. Keep all
   raw credentials out of reports. Record ambiguities instead of guessing a chain.
2. Separate API environment, document purpose, issuer identity, and credential
   version in the proposed model. Define and verify rotation continuity explicitly;
   do not assume a newly issued CSID always means a new counter or the same counter.
3. Map each historical counter to a proposed stable chain identity without
   resetting it. Detect many-to-one mappings, slash/truncation collisions, shared
   certificates, linked-company switches, and conflicting invoice evidence. Block
   automatic migration for unresolved cases; a largest-value rule alone is not
   proof that two chains may be merged.
4. Prove monotonic allocation, concurrent-worker locking, stable retry identity,
   purpose/environment separation, and no regression of accepted evidence using
   restored v15/v16 integration fixtures before introducing any writes.
5. Prepare a forward migration journal and rollback procedure that never rewinds
   an already used ICV/PIH. Rehearse migration and interruption recovery on restored
   data, then obtain the pilot deployment window. No migration is run by this code.

## Next adapters and release gates

Increment 7 migrates `sales_invoice_withoutxml`, `zatca_background_sched`,
`pos_submit__without_xml`, and `pos_schedule_background`, and redirects the six
legacy generator sample paths. See
[GENERATION_AND_COMPLIANCE.md](GENERATION_AND_COMPLIANCE.md). Retry identity,
worker deferral, per-Company eligibility, and artifact transactions remain pending.
Final-CSID issuance, wizard auth, purpose-specific certificate storage/renewal,
and a single signing/request credential-version snapshot also remain pending.

Generic HTTP 409 acceptance, production response classification, SDK/golden XML,
advance accounting, site transaction behavior, and actual ERPNext 16 compatibility
are not resolved by this increment. The full selected suite passes 778 local
cases; this is neither SDK approval nor remote Compliance acceptance.
