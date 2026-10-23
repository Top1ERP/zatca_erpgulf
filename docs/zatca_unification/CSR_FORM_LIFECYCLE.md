# CSR form lifecycle — increment 77 (development only)

## Inspected behavior and bounded change

Both Company/device `custom_create_csr` buttons previously saved the open form
after `create_csr` had saved private-key and CSR fields on the server. Device
also fetched the entire Company and wrote Company/CSR responses to the browser
console. These two handlers now use the same credential-form runner as the four
CSID buttons, without automatic save, reload, model sync or console output.

The server is deliberately unchanged: `create_private_keys` replaces the shared
private key before CSR construction and a later save stores CSR data. Existing
certificates/auth are not rotated with that key. Errors after key generation can
leave partial local effects; a client response is not a commit/activation receipt.
The legacy encoded-CSR return is retained for compatibility, not copied, parsed,
logged, displayed or returned by the new form runner. No actual key generation or
CSR RPC is used by the offline UI tests.

## Consent, input and UI policy

Require an active saved explicitly clean form with observed revision and valid
identity/routing fields. Before even the device metadata read, obtain translated
confirmation that generating CSR replaces the saved private key and can make
existing certificates unusable. Decline/close cancels without a credential call
or review mark. Consent failure has a static preparation message; it cannot
authorize issuance or establish that renewal is safe.

Recheck form object, source identity/revision/link/environment, CSR configuration,
active route/form and clean state after confirmation and device lookup. Device
reads only the linked Company's abbreviation/environment through ordinary
`frappe.client.get_value`, never the full Company or its credentials. This is
an observed UI snapshot, not atomic linked-Company revision/source pinning.

One per-form pending promise coalesces CSR and both CSID actions, including while
consent or metadata lookup waits. Entering either credential RPC marks the
original document object for review across all three actions, even after a
failure or unknown result. Review precedes any dirty-form save guidance. A
metadata-only failure/declined consent allows a later explicit attempt, not an
automatic retry. Shared guards remain in-memory only: no durable/cross-tab lock,
API authorization, manual-save protection or server-side rotation policy.

After a non-exception response, show a single static orange **returned-call and
review** notice, not a green PASS, certificate-issued claim or CSR-validity claim.
Even an empty/malformed return cannot become an issuance success. Framework
exceptions retain their existing owner; unknown delivery gets static guidance
that the private key may have changed. Raw response/error content is not
stringified. Navigation/edits while waiting cause no automatic form write/reload.
Display notices/consent use the real Arabic CSV; no stored value is translated
and no logger is added. This does not sanitize the legacy backend's exceptions,
framework traceback/local snapshots, custom-hook output or broader logging.

## Separate configuration and server gates

`get_csr_config` was inspected: it builds and returns text and prints a raw HTML
configuration popup but does **not** save the Company. Its Company handler
assigns `custom_csr_config` and automatically saves. It is a distinct draft-input
workflow, **unchanged** here; do not apply a server-writer reload strategy to it.
It still needs escaped/translated single-message presentation, deliberate draft
staging, source/dirty-change checks and coordination with pending/review guards.
It can still save a stale form, as can other manual/programmatic writers.

Device single Compliance, other forms/wizards, backend permissions (including
`ignore_permissions=True` writes), active-key protection and versioned credential
activation, protected logs/read/export/retention, transaction/hook behavior and
installed v15/v16 Desk tests remain gates. The two-handler change does not solve
key rotation or make production onboarding ready. No schema, credential data,
cryptography, backend return signature, API route or acceptance policy changes.

## Offline verification

`test_csr_form_lifecycle.js` evaluates actual Company/device handlers with mocked
ERP/HTTP calls in a network-free Node VM. **176 cases** cover both languages,
new/dirty/inactive/incomplete settings, consent decline/failure, edits while
consent/lookup/request waits, limited metadata reads, cross-action coalescing and
review, unchanged source data, framework/unknown failures, malformed replies,
read-only failures followed by explicit attempts, and no save/reload/console leak.
All twelve new display keys are required in the actual Arabic catalog.
All six standalone Node scripts passed **900 cases** in total. The unchanged
guarded Python selection passed **11,664 local + 1,800 private SQL = 13,464 cases
in 143.64 seconds**, across twelve owned-private SQL suites. No Python suite or
manifest change was needed for this client-only increment.

```sh
node zatca_erpgulf/zatca_erpgulf/tests/test_csr_form_lifecycle.js
node zatca_erpgulf/zatca_erpgulf/tests/test_csid_form_lifecycle.js
PYTHONDONTWRITEBYTECODE=1 ../../env/bin/python tools/run_unification_rehearsal.py --private-sql
```

No installed source/assets/config/schema/worker/site/credentials change and no
authority request is authorized. Full isolated fictional-company rehearsal is
still a separately approved later gate, followed by the user's adoption decision.
