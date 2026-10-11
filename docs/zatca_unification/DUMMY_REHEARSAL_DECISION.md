# Fictional-client rehearsal and whole-change decision

## User decision recorded — 2026-10-11

The user reiterated: complete development, test with a fictional client, THEN
decide whether to adopt **all changes** or cancel them. A generic "continue"
authorizes development within the existing scope, not adoption or deployment.

The working application remains untouched. Authority sending remains prohibited
in every environment, including Sandbox/Simulation, OTP/CSID and Compliance.
The fictional-client rehearsal is future work, not already executed or an
extra Company permitted on a working customer's bench.

## Before the rehearsal

- Finish the documented development gates, including amount/advance/GL/VAT
  reconciliation, exact signature/QR artifacts, identity/retry coordination,
  settings/credential/source provenance and installed version acceptance.
- Freeze the candidate Git commit and record package/runtime versions, offline
  test/SDK evidence, unresolved limitations and baseline/recovery references.
- Obtain separate scope approval for NEW isolated v15/v16 benches and purely
  fictional data. Contain outgoing authority HTTP, mail, webhooks and automatic
  jobs without modifying any working service. Never copy active customer secrets
  into the dummy fixtures or label fabricated results as genuine authority PASS.

## Rehearsal report

Record the exact tested commit and outcome for Sales Invoice/is_pos/POS Invoice,
Phase-1/2, six invoice/note types, synthetic/single/all Compliance, XML for Debug,
English/Arabic, discounts/inclusive taxes/FX/rounding, initial/multiple/partial/
returned advances, GL/VAT/outstanding balances and concurrent/failure recovery.
Preserve local evidence and distinguish mocks, SDK checks, installed integration
and **UNVERIFIED remote acceptance**. No real request may substitute for this ban.

Present failures and remaining risks before asking for the user's decision:

- **Adopt all changes:** approve the tested candidate as a whole. This alone does
  not deploy it, merge main, restart workers, migrate schemas, replay invoices,
  rotate credentials or revoke the authority-send ban. An explicitly named
  gradual pilot/rollout scope and recovery review are still required.
- **Cancel the changes:** leave working applications/main at their untouched
  baseline and preserve the development branch/evidence for recoverability.
  If removal of isolated dummy resources is later requested, resolve the exact
  owned targets and get the appropriate deletion approval. Never reset or restore
  a customer's working database to "undo" development that was never deployed.

No automatic partial adoption, client pilot or fleet deployment follows the
rehearsal. If tests fail or the user requests revisions, return to offline
development and freeze/retest a new candidate before another decision.
