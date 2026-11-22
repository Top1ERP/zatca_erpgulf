# CSID counter epochs and retained EGS identity

Decision reviewed2026-11-22 after the user's request. This corrects the earlier
unqualified assumption that an EGS must always continue its ICV across CSID
renewal. It changes the development plan, not installed counters or credentials.

## Primary developer evidence

- [ZATCA Detailed Technical Guidelines, section3.2.2 and3.3.5](https://zatca.gov.sa/en/E-Invoicing/Introduction/Guidelines/Documents/E-invoicing-Detailed-Technical-Guideline.pdf)
  describe renewal as revocation of the existing CSID and issuance of a new CSID.
  Those sections do not themselves give an explicit ICV restart instruction.
- [Invoice counter value reset, Ankit.K.Tiwari,2024-11-06](https://zatca1.discourse.group/t/invoice-counter-value-reset/659/5)
  explicitly says the new CSID's ICV starts from1 after revocation or renewal.
  This is developer-community clarification; do not misattribute its exact
  instruction to a numbered requirement in the PDF.
- [Onboarding an EGS multiple times,2025-03-13](https://zatca1.discourse.group/t/onboarding-an-egs-multiple-times/6151/5)
  explains that each CSID has a sequence starting1,2,3,...; identical numerical
  counters across different CSIDs are not inherently duplicates. The same thread's
  [2025-05-11 reply](https://zatca1.discourse.group/t/onboarding-an-egs-multiple-times/6151/9)
  requires one ICV/PIH series per CSID, even with several invoice-number series.
- [New software, ICV, EGS,2025-06-01](https://zatca1.discourse.group/t/new-software-icv-egs/7201/2)
  confirms a genuinely new registered EGS has its own counter starting1.
  [The subsequent PIH clarification](https://zatca1.discourse.group/t/new-software-icv-egs/7201/7)
  describes a default initial PIH for a new EGS. Do not copy the old EGS's last
  invoice hash into a genuinely new EGS by inference.

Older community replies emphasize never resetting a sequence within the same
active EGS. Read that together with the explicit later per-new-CSID clarification,
rather than using it to deny the renewal case. Community clarifications are not
proof of remote issuance, current certificate validity or SDK acceptance.

## Implementation contract

The following is the application's design derived from that evidence:

1. Preserve a stable logical EGS/owner/environment/taxpayer identity and its
   historical relationships. A credential change does not erase that identity.
2. A positively admitted new Production CSID establishes a separate issuance
   epoch. Its next generated document starts with ICV1. Retain the old epoch's
   last ICV/PIH, originals, requests, receipts and credentials; never UPDATE the
   old generated ledger back to0 or overwrite an old invoice's identity.
3. Renewal and revoke/re-onboard need authenticated old/new linkage and exact
   server-retained issuance/renewal evidence. Re-saving a certificate, a new
   private key/CSR, changed secret/Basic token spelling, an expired certificate,
   Compliance CSID or FINAL_READY projection alone cannot authorize a reset.
4. One selected active epoch serves the intended shared owner/delegates. Normal
   Sales/POS, credit/debit notes and all delivery modes share that epoch's counter.
   Invoice IRN/naming-series policy remains independent of ICV.
5. Freeze/drain/fence the old issuer and inspect outstanding custody before
   switching epochs. Unknown deliveries and unsent old signed originals retain
   their identity/bytes/old epoch; never relabel them with the new CSID or treat a
   later renewal as proof that they were rejected or unreceived.
6. Make the epoch selection/activation and initial head durable and atomic.
   A replay or unknown commit acknowledgment must recover the same epoch, never
   open another sequence. No caller `reset=True`/`approved=True` is sufficient.
7. A genuinely new EGS uses the established default initial PIH. Renewal-specific
   first-PIH rules must be pinned to appropriate evidence before implementing
   renewal activation; the ICV instruction alone is not proof of PIH behavior.

## Current source and remaining development

`DispatchStore` already scopes native issuance uniqueness and ICV to an opaque
chain record, with historical readers resolving the original recorded chain.
Its `owner_key` identifies the selected owner/environment; certificate/public-key
fingerprints are separately bound. The implementation does not yet have the
complete stable-EGS versus successive-CSID-epoch mapping or renewal activation.
Do not assume existing chain records automatically implement this full contract.

Initial `native_onboarding`/`native_enrollment` deliberately reject populated
material/history and remain inactive at FINAL_READY. They must not be loosened
into a renewal shortcut. Legacy `icv._issuing_unit` currently hashes auth text;
that is a historical namespace observation, not a reliable certificate identity
or a renewal proof, and must not define the new native epoch boundary.

Separate owned encrypted pending old/new key/CSR custody is now implemented:
[NATIVE_RENEWAL_PREPARATION.md](NATIVE_RENEWAL_PREPARATION.md). It makes no request,
credential replacement or counter change. Next development must add authenticated
remote renewal custody, stable logical-EGS mapping, CSID-specific immutable ledger epochs, explicit activation
and drain/recovery semantics. Qualify renewal using the same private SQL/offline
runtime matrix; actual installed15/16, authentic SDK and dummy-company rehearsal
remain separately gated. No working-site counter, credential or API was touched
for this decision. Workstream2 stays open.
