# One XML observation per request adapter — increment228

Increment229 adds embedded metadata matching to four existing-XML APIs and typed
review propagation. The other nine request-capture contracts remain unchanged.
The evidence and limits below describe increment228; see
[EXISTING_XML_BINDING.md](EXISTING_XML_BINDING.md) for current adoption.

Development only, 2026-11-16. No installed application, tenant, invoice, schema,
settings, Bench or worker was changed. No authority API was used. Every request
in the tests is a mock under the offline network/site guard.

## Problem and resulting behavior

The primary POS Reporting adapter read the same signed XML twice: once for its
local File and again for the request. Four legacy generated Sales/POS Reporting
adapters read once for the request and again for their File. Primary Sales
Reporting read for the request, then reread after the response for its File and
parsed the path again for QR. A changed, replaced or deleted file could therefore
produce inconsistent artifacts or a local failure after a response was received.

`invoice_payload.read_invoice_payload` calls the caller's current imported XML
reader once and retains that returned value with the original UUID and hash.
`InvoicePayload.as_payload()` returns a fresh dictionary with the original key
order and native values. `xml_text()` decodes lazily using the former permissive
Base64 decoder and strict UTF-8 behavior; opaque test/replacement values are not
validated or coerced at construction. The representation does not print XML,
UUID or hash. The frozen container is not a deep freeze of caller-supplied mutable
identity/hash values; native readers return immutable Base64 strings.

Thirteen existing API functions adopt the shared composition:

| Family | Functions | Local content behavior |
| --- | ---: | --- |
| Primary Sales/POS Reporting | 2 | Existing File uses the captured XML; Sales QR uses that XML too |
| Primary Sales/POS Clearance | 2 | Request only; returned cleared XML remains the response source |
| Generated legacy Sales/POS Reporting and schedulers | 4 | Existing pre-request File uses the captured XML |
| Existing-XML Sales/POS adapters | 4 | Request only; existing artifacts remain untouched |
| Compliance samples | 1 | Same `json.dumps` text and `requests.request(data=...)` contract |

For stable input the serialized request and existing writes remain the same.
There is no new financial calculation, XML transformation, signing operation,
UUID/ICV/PIH allocation, URL selection, credential fallback, timeout, permission
rule, response interpretation or schema field. This composition is framework-free
and adds no ERPNext-version API dependency; installed 15/16 verification remains
separate from these mocked adapter tests.

## Changed-file example

For the old generated Reporting adapter, reader results A then B could send A
and attach B. Old primary POS could attach A and send B. Old primary Sales could
send A, then attach B and save QR-B after its mock POST changed the file. New
canonical consumers use A throughout the corresponding request operation, even
when that file is deleted after the mock POST. Tests demonstrate each difference.

This is an intentional local artifact change in a race/failure scenario. Normal
stable-file invoice amounts, XML, headers, ownership and persistence arguments
are compared against the full previous API functions, not a recreated payload
formula. Removing the second read also removes failures/side effects that would
have arisen only from that second invocation of a custom reader.

## Compatibility and retained boundaries

Private Sales `_attach_reported_xml(path, invoice)` and `_extract_qr_payload(path)`
retain standalone positional calls and their previous reader/parser behavior.
Canonical composition supplies captured text through an internal keyword. Code
reference checks preserve old positional arguments for replaced helpers; those
replacements can still reread or introduce side effects. No new endpoint, public
request option or permission capability is added.

The QR parse receives in-memory UTF-8 bytes with the same XPath/first-match/strip
rule. It does not reopen the source path or carry its filesystem base URI. This
bundle does not introduce a new DTD/entity validation or arbitrary-encoding
contract; valid signed UTF-8 UBL remains the relevant input. Existing default
readers retain their own path, UTF-8/newline and leading-whitespace behavior.

This is one file observation, not an atomic file-write transaction, signed source
revision, durable receipt repository or authenticated network transcript. A file
can still be modified during a read. Wrapper UUID/hash reads performed before the
API remain separate observations; this helper does not recompute or verify them,
or certify that presigned QR/signatures match those arguments. Another layer can
mutate an outbound dictionary, and an arbitrary replacement callback is outside
the canonical content guarantee.

Legacy pre-request File creation in POS/generated routes, deferred-mode writes,
partial commits, post-response review behavior and generic status branches remain.
The existing POS Clearance rejection of 409 is retained as well.
In particular, preserving existing 200/202/409 handling does not certify acceptance
from the HTTP code alone. No retry, resubmission or real authority connection was
performed. Debug and Phase1 have no request adapter adoption in this bundle.

## Evidence and release gates

The SHA256-frozen increment227 source is
`tests/fixtures/invoice_payload_f524d06.py`, digest
`45aa2515cbdeda2a99f17e27374f21a801c38d54e0a002c2f0d9c6ca9dd3b175`.
All 13 API bodies and both private helpers are exercised. The 541 new tests include:

- 432 complete-parent comparisons across 12 ordinary API functions, three owners,
  three configured environments and four mocked response statuses.
- 18 deferred/foreground side-effect comparisons and36 first-read failures.
- 12 one-read checks, five frozen two-read inconsistencies, six post-response
  changed/deleted-file cases and three frozen Sales artifact/QR differences.
- 15 Compliance JSON/auth/result comparisons, one replacement-helper contract,
  and13 lazy/native/standalone compatibility cases.

Focused 541 pass in 4.92s. Structural AST restoration recreates all 15 existing
function bodies and complete affected modules after reversing only the documented
composition/helper changes and removing four now-unused `base64` imports.
350 other tracked runtime files and 29 earlier Python reference fixtures are
byte-identical to increment227. The original pre-development 240-case oracle is
still 91 identical/117 observed differences awaiting review/32 blocked ambiguous
cases; increment228 changes no financial builder or original expectations.

The final guarded broad run passes 18,781 cases across 71 reviewed suites in
113.95s, including the existing post-response error suites. Six browser suites
pass 1,208 cases. Manifest selection is 200 local/57 private; only the explicit
71-suite local selection ran, with no private SQL. See [STATUS.md](STATUS.md).
Local evidence:
`/tmp/zatca-payload-228-focused-final.log`,
`/tmp/zatca-payload-228-regression-verified.log`,
`/tmp/zatca-payload-228-structure.json`.

Next investigate producer/wrapper UUID/hash/content binding and source/settings/
credential custody before any proposal for stricter validation or retry behavior.
Fiscal/GL/precision/settlement review, installed ERPNext15/16 lifecycle tests,
SDK/scanner checks and a separately approved isolated fictional-client rehearsal
remain release gates. This bundle is not approval to deploy or contact ZATCA.
