# CSR configuration draft — increment 78 (development only)

## Scope and saved-source boundary

The Company `custom_create_csr_configuration` button previously called the
abbreviation API, received a raw configuration popup, assigned the returned text,
printed a second success message and automatically saved the entire Company.
It now calls `prepare_csr_config(company_name, expected_modified)` and stages only
`custom_csr_config` for deliberate user review/manual save. No automatic save,
reload, credential/key generation, invoice creation or authority call is added.

The new non-guest API loads the exact named Company and checks ordinary saved-row
READ and WRITE ACL through the existing quiet v15/v16-signature compatibility
helper. Unknown/unsupported ACL engines fail closed without fallback. The
requested modified timestamp must match the observed naive saved DATETIME. No
abbreviation/company fallback or client-supplied company field values are used.
Both identity and requested revision are validated before loading the Company.

Four required saved values (Tax ID, Company name, location, category) must be
strings of at most 1,024 characters, without control characters or Unicode line
separators. This prevents injecting extra configuration lines into downstream
`splitlines()` parsing; it is **not** VAT, CSR, certificate or authority validation.
The shared builder preserves the existing nine-key format, TST defaults, invoice
type `1100`, uppercase city and serial generation. Those defaults/randomness and
regulatory suitability are unchanged and still need separate review.

Return only English `status: DRAFT`, exact Company identity, echoed comparison
revision and raw draft text. No private key/auth/OTP/certificate or complete
Company is returned. No configuration is persisted. Timestamp and ACL checks are
observations, not row locks or authoritative credential epochs; later concurrent
server edits remain possible and normal Frappe save timestamp checks are retained.

## Form lifecycle and messages

Use the same per-form pending promise and attempted-credential review state as
CSR/CSID. The new action is Company-only, requires a saved clean active form, and
captures identity/revision, routing metadata, old config and all four source
fields. After the read request, recheck this snapshot and active/clean state;
changed/dirty/replaced/navigated forms do not receive the draft. Environment/OTP
are not prerequisites for configuration preparation.

Require a structured DRAFT with exact source/revision and a bounded nine-key
single-line-value text shape before invoking `frm.set_value` once. This only
checks shape, never declares CSR validity. The returned draft is not HTML-rendered
or translated; the field contains the original text. The one orange summary says
it is **unsaved**, requires review/manual save, and generated no key/certificate.

The shared pending promise remains until async field staging finishes. Recheck
source/route and staged value after the setter, without restoring old values,
discarding edits or retrying. Setter/hook failure can leave a partially changed
field; static review guidance explicitly avoids claiming staging succeeded.
Subsequent ordinary credential actions require a clean saved form. Successful
read-only preparation does not itself mark a credential attempt. Metadata/read
failure permits a later explicit click, never automatic retry.

If a prior CSR/CSID call entered its credential RPC, configuration preparation
also refuses that old document object. Review guidance takes precedence over
dirty-input save guidance; the button cannot indirectly save stale credentials.
WeakMap/WeakSet policy is UI-only, not cross-tab/durable idempotency, source
provenance or access control. Manual/programmatic saves and other writers are
not intercepted. A replaced document/page reload is not proof of actual review.

The new server path emits no success popup. Child preparation messages are muted
request-locally with exact flag restoration; a static allowlisted failure is
translated only at presentation, outside the child exception scope. Unknown
exceptions are not stringified/chained into the public error. Parent messages
are preserved. Framework errors retain their owner; client unknown-read or local
staging failure has one static localized message. No logger or persisted
translated result is introduced. Arbitrary hooks/framework traceback/locals/log
retention remain separate gates, not an atomic one-dialog guarantee.

## Compatibility and remaining gates

The legacy `get_csr_config(company_abbr)` string API remains available and uses
the same builder; its popup now HTML-escapes the text. The new Company handler
does not call it. Legacy abbreviation lookup/access/error presentation remains a
compatibility surface to review, not a protected exact-source API. No schema or
installed asset/source/config/worker/site changes occur.

CSR/private-key backend permissions/rotation/activation, device single Compliance,
other wizard/manual writers, source concurrency, protected receipts and complete
log/read/export lifecycle remain gates. Normal form hooks, actual v15/v16 Desk,
HTTP decorators/permission behavior and installed CSR field types require later
separately approved isolated fictional-Company rehearsal. Full development is not
complete; adoption/pilot and authority-send permission remain separate decisions.

## Offline evidence

The new fixed-manifest Python suite mocks saved documents, ACL and ERP errors;
no site/HTTP/credential generation is performed. HTTP type decorators alone are
unwrapped for the request-free test harness; real endpoint bodies, validation,
quiet ACL calls and message boundaries are tested. The first harness run exposed
missing Frappe request-local context; the fixtures now explicitly unwrap that
decorator without initializing a site or weakening resource guards.

Cases cover exact source/revisions, inspected v15/v16 ACL signatures, required
permissions/fields, bounded/control/Unicode line injection, unexpected private
errors, cancellation, parent flags/messages, no credential export/writes and the
legacy unchanged string/escaped-popup contract. The new Node VM script covers
both languages, pending/review across all actions, stale/dirty/changed forms,
malformed/mismatched drafts, async setter hooks, manual-save workflow and no
automatic save/reload/credential mutation. All earlier UI scripts are retained.

```sh
node zatca_erpgulf/zatca_erpgulf/tests/test_company_compliance_messages.js
node zatca_erpgulf/zatca_erpgulf/tests/test_debug_messages.js
node zatca_erpgulf/zatca_erpgulf/tests/test_debug_ui_lifecycle.js
node zatca_erpgulf/zatca_erpgulf/tests/test_csid_messages.js
node zatca_erpgulf/zatca_erpgulf/tests/test_csid_form_lifecycle.js
node zatca_erpgulf/zatca_erpgulf/tests/test_csr_form_lifecycle.js
node zatca_erpgulf/zatca_erpgulf/tests/test_csr_configuration_form.js
PYTHONDONTWRITEBYTECODE=1 ../../env/bin/python tools/run_unification_rehearsal.py --private-sql
```

Only this specifically reviewed Python suite is added to the fixed manifest;
network/site/SQL ownership guards and ordinary permissions are not relaxed.
The added Python suite contains **102 cases**. All seven standalone UI scripts
passed **1,024 synthetic cases**, including **124 new configuration form cases**.
The final guarded selection passed **11,766 local + 1,800 private SQL = 13,566
cases in 147.74 seconds**, across the same twelve owned-private SQL suites.
No site/network/SQL ownership guard, normal permission or acceptance policy is
waived; installed HTTP/Desk/v15/v16 and authority acceptance are unverified.
