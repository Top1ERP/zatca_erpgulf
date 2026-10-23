# Company Compliance forms — increment 80 (development only)

## One saved-source facade, three retained workflows

Company `custom_check_compliance`, `custom_run_all_compliance` and
`custom_run_zatca_onboarding_checks` now delegate to one UI runner and one
`company_compliance.run_company_compliance_summary(company_name,
expected_modified, mode)` facade. The two invoice-based buttons previously sent
the current client sample number; the three buttons had independent request/
confirmation/freeze lifecycles without shared pending or dirty/source guards.
The legacy batch/automatic APIs also lacked the single wrapper's explicit source
READ preflight. Their direct compatibility APIs remain unchanged here.

The new authenticated facade accepts only exact Company identity, comparison
revision and one literal mode: `single`, `all`, `automatic`. It does not accept
an invoice identity, abbreviation, validation label, credentials or routing
override. Reject malformed identity/revision/mode and Guest/missing actor before
loading. Load the exact saved Company; require ordinary saved-row READ access
through the existing quiet v15/v16-signature adapter and compare its observed
naive DATETIME revision. Require a valid saved abbreviation before delegation.

`single` and `all` read `custom_sample_invoice_number_to_test` from that saved
Company, load the exact Sales Invoice, check ordinary READ and require its
Company to match. Automatic checks do **not** read or require a sample invoice.
Delegate exactly once to the corresponding existing workflow and return its
original English result contract unchanged. There is no new acceptance decision,
retry, save/commit, key generation/rotation, credential activation or local-preview
substitution. Existing single label/fallback, six-type batching, synthetic sample
construction, signing, temporary files, routing and transport are unchanged.

The facade mutes preparation/delegate popups request-locally, preserves parent
messages and restores the exact previous mute flag on success/failure/cancellation.
Static allowlisted preflight failures are translated only for final display;
unknown ERP/ACL exceptions are not stringified or implicitly chained into that
public error. Once delegation is entered, a failure escaping the legacy workflow
is conservatively **unconfirmed**, not a claim that no request happened. No new
logger or translated stored result is introduced.

## Shared form policy

All three buttons use the existing saved-form snapshot helper and credential/
configuration pending/review state. Require an active saved explicitly clean
Company with observed revision and abbreviation. Invoice modes require a sample
identity; automatic does not. A prior attempted CSR/CSID document is shown review
guidance before dirty-input save advice, avoiding an indirect stale-credential
save recommendation. There is no automatic pre/post-save or reload/model merge.

One pending promise coalesces clicks across all three checks, CSR, configuration
and both CSID actions. It covers the automatic consent dialog as well as RPC and
summary rendering; it does not queue a different action after completion.
Automatic decline/close starts no RPC or credential review hold. After consent,
recheck captured Company object/identity/revision/abbreviation/environment/label/
sample, active route/form and clean state before starting the RPC.

The confirmation now explicitly says the alternative sends temporary samples to
ZATCA Compliance in the saved Company environment and is **not** a local-only
preview. It creates no customer/sales invoice and issues no certificate. Users
choose it or Run All Compliance, not both. This clarification does not authorize
the agent to send: verification remains entirely mocked under the user's ban.

RPC args contain only saved-source identity/revision and mode. Frappe owns the
RPC `freeze`/unfreeze lifecycle; the old separate manual global freeze is removed.
After a response, changed/dirty/replaced/navigated forms get one static notice
that the request may have completed and the original Company's outcome needs
review, never an incorrect unsent/cancelled claim. Do not overwrite edits, reload,
rerun automatically or display a result against a different active form.

Unchanged forms use the existing localized single/batch/automatic summary.
Framework errors retain their owner; unknown client/consent failures get one
static localized notice. Raw diagnostics stay escaped/original under the existing
presenter contract. The formerly missing sample-number prompt now has an actual
Arabic catalog entry. New strings and actual translations are asserted by tests.

## Limits and adoption gates

Pending/review state is UI memory only, not cross-tab/server idempotency, durable
alternative-method selection, a remote receipt or a source/credential epoch lock.
Completion of a read/check does not mark a credential mutation. A later explicit
request remains possible; no stored field/schema or durable no-retry hold is added.

Only Company revision is compared at facade entry. The legacy workflows reload
Company/related data; concurrent Company, invoice, address or credential changes
are not pinned across generation/HTTP. Related Address/Customer/Item dependencies,
broader legacy direct-API permissions and complete key/read/export/log custody
remain gates. Existing collected technical details preserve legacy exceptions;
this is not a whole-framework secret/traceback/local-snapshot redaction guarantee.

No live source/assets/config/schema/sites/credentials/workers are changed. No
invoice is submitted and no real authority call is executed by development/tests.
Actual installed v15/v16 Desk/request decorators/ORM/hooks and SDK/authority
acceptance remain unverified. Full development, separately approved isolated
fictional-Company rehearsal, adoption and gradual pilot remain distinct gates.
Deployment approval cannot override the current authority-send prohibition.

## Offline evidence

The new fixed-manifest Python suite reuses only synthetic documents and mocks
all three delegates. It tests exact source/mode/revision checks, v15/v16 ACL
signatures, invoice ownership, automatic independence from sample fields,
unchanged results, parent messages/flags, private-error handling and cancellation.
Only the HTTP type decorator is unwrapped for a request-free harness; the real
facade body runs without site initialization or actual generator invocation.

The new Node VM script evaluates actual Company handlers in **292 cases**, both
languages: entry guards, cross-action pending/review, all three result modes,
malformed replies, source changes before/after consent/RPC, decline/close,
framework/unknown failures, no automatic writes/retry and later explicit actions.
All eight previous UI scripts also pass. Existing Company message tests now
assert the new limited args and framework-owned freeze rather than expecting a
manual global unfreeze; they still require reaching the RPC on error scenarios.

```sh
node zatca_erpgulf/zatca_erpgulf/tests/test_company_compliance_form.js
PYTHONDONTWRITEBYTECODE=1 ../../env/bin/python tools/run_unification_rehearsal.py --private-sql
```

Only the reviewed synthetic Company suite is added to the fixed manifest;
network/site/private-SQL ownership and ordinary permission/acceptance guards are
not relaxed. No off-host/authority/browser or ERPNext 16 runtime is exercised.
Final guarded Python: **12,069 local + 1,800 private SQL = 13,869 passed in
147.73 seconds**, across the same twelve owned-private SQL suites, including
**160 new synthetic Company cases**. All nine Node VM scripts passed **1,444
cases** (292 new form cases). This is offline evidence, not installed framework,
cryptographic material/SDK or remote acceptance evidence.
