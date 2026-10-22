# POS Debug: independent of live submission scheduling

Increment 70 fixes a local Debug failure in the development worktree only.
No installed source/assets/configuration, site, Bench, worker or authority call.

## Cause and bounded change

In `pos_debug_xml._debug_call`, the Phase-2/no-existing-artifact branch read
`bypass_background_check` when live scheduling was `Background`. This variable
was not defined in the POS module or its public signature, so Debug returned a
NameError before generating its local artifact. Increment 69 made that returned
error visible and characterized it; it did not repair generation.

The branch calculated `handle_b2c_simplified`, which was passed to the nested
generator but **never read there**. Removing that dead calculation and its
private argument fixes the failure without inventing another bypass field or
changing the actual POS invoice-type selector. Public parameters are unchanged.
The POS Debug path no longer reads live submission scheduling at all.

This is POS-specific: Sales Debug really uses its corresponding selector,
including existing Background behavior. It is not removed or changed here.
Unifying that financial type-selection policy needs separate fixtures/review.

## Preserved application behavior

These describe existing app behavior, not a statement of ZATCA regulations.

| Input / setting | Local POS Debug behavior |
| --- | --- |
| Normal type `0`, resolved customer B2C = 1 | Existing simplified XML adapter |
| Normal type `0`, customer not B2C | Existing rejection; Background cannot force B2C |
| Explicit sample types `1` through `6` | Existing compliance-type XML adapter, still local Debug only |
| POS electronic invoicing disabled | Existing skipped result, no generation |
| Same seller/customer VAT | Existing intra-company skip |
| Buyer ID without its type | Existing validation failure before generation |
| GPOS XML without QR data | Existing validation failure before generation |
| Phase 2 + schema supports unique ID + invoice has unique ID | Existing POS-name requirement and GPOS notice |
| Existing issued XML/QR | Existing notice, then separate Debug copy |
| Explicit tax-template adapter flag | Existing plain/template pipeline choice |

Live/Batches/Immediate/Background, blank or missing scheduling values cannot
override these selectors or schedule a request from Debug. Phase/schema, POS,
GPOS, alias lookups, signing/QR/hash, invoice amounts/discounts, and tax/advance
logic are not changed. No new request/credential/CSID/Compliance operation,
queue/job, retry, save of Company/invoice, commit or schema action is added.

The existing Debug File replacement behavior, ignored permissions and success
reload lifecycle are **not** hardened here. A newly working Background case can
now reach those existing attachment operations, so their independent review
remains required before adoption. This fix alone is not deployment readiness.

## Offline verification

The existing fixed-manifest `test_nonproduction_isolation.py` now replaces the
old expected-failure observation with a required local-success regression and
adds:

- 168 phase/scheduling/B2C/type cases, using the real Debug entry/body and mocked
  ERP/signing/tax/File/transport. Original synthetic signed XML/QR bytes and
  invoice fields remain unchanged; no HTTP, invoice/Company write or commit.
- Twelve schema/unique-ID/POS/GPOS/existing-artifact cases preserving existing
  preflight failures and notices, rather than bypassing checks to fix Background.
- Eight plain/template tax adapter selection cases; these verify dispatch,
  not numerical tax correctness or installed ERPNext tax structures.
- A saved-settings object that fails on live scheduling reads, with a check
  that the public signature gained no bypass argument.
- Buyer-ID and signing failures remaining failures after the Background fix.

The Python rehearsal's network/site guard and twelve owned temporary SQL suites
are unchanged. The existing 160 synthetic English/Arabic UI cases are rerun;
no UI/translation key is changed. Tests never invoke a real user button, submit
an authority request, create a Company on a working bench or read tenant data.

This is not real v15/v16 ORM/browser/physical-file-hook, SDK/cryptographic or
authority acceptance proof. Those gates remain separately approved and remote
requests remain prohibited.

Final evidence: **10,873 local + 1,800 private SQL = 12,673 guarded Python
cases passed in 143.43 seconds**, across the existing twelve owned-private SQL
suites. There are 191 new local cases; the prior expected-error observation now
requires successful local generation. The same **160 synthetic UI cases** also
pass (108 Company + 52 Debug). No test failure or guard relaxation was required.
