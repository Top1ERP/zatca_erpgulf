# Existing XML identity bound to its request observation — increment229

Development only, 2026-11-16. No tenant SQL, installed source/configuration/schema,
invoice modification, service restart or authority API action. HTTP is mocked
under the explicit offline test guard. Code upload is limited to the authorized
GitHub development branch; it is not deployment.

## Behavior and scope

Four existing-XML Sales/POS APIs previously trusted UUID/hash arguments extracted
by a wrapper before they read XML for the request. Increment228 captured the
request value once but did not verify that its embedded identity matched those
arguments. A file replacement between wrapper extraction and API read could send
UUID-A/hash-A alongside XML-B.

All four now call `existing_xml_submission.read_bound_invoice_payload`, after
existing authorization/context resolution and before HTTP. It captures once with
the caller's current reader, then invokes the shared framework-free
`existing_xml_binding.existing_xml_binding_issue` policy. The original Base64,
UUID, hash, dictionary order and request options are retained for an exact match.

The policy checks:

- Decodable standard Base64 and parseable XML bytes, with a fresh parser that
  disables entity substitution, DTD loading, recovery and external resources.
- The UBL Invoice root, exactly one direct CBC UUID and exactly one DS Reference
  with `Id="invoiceSignedData"`, containing exactly one direct DigestValue.
- Nonempty leaf values and exact equality with the request UUID and hash.
  No trimming, replacement, rate calculation, XML reserialization or repair.

A missing, ambiguous, malformed, DTD-bearing or mismatching source receives a
static issue code and one canonical review. A namespaced unrelated UUID or
SignedProperties digest is not substituted. This is metadata consistency only:
UUID syntax, digest recomputation, signature/certificate, QR, seller/Company,
amounts and remote acceptance are **not** certified by a match. Same-identity
content changes can still pass; the tests deliberately demonstrate this limit.

The four wrapper extractors keep their earlier interfaces and separate initial
read. Earlier extraction failures retain their old behavior. This bundle detects
observed metadata disagreement before transport; it does not make those reads
atomic or replace the extractors with a new file repository. Nine other primary,
generated and Compliance API functions retain increment228's unvalidated capture;
this new check is not silently imposed on their different source contracts.

## One review across parent and worker boundaries

`ExistingXmlSubmissionError` inherits Frappe ValidationError, whose app-defined
fields carry a static code and whether its diagnostic has already been logged. The bridge logs
an English review before invoking the caller's translator and `throw` with that
same error instance. It performs no invoice/File/counter/PIH save or commit for
this review. Existing first-read exceptions retain their old handler behavior.

Four API outer handlers and four wrappers preserve the typed review. Six actual
Sales/POS manual, on-submit and batch parent handlers also preserve it, avoiding
another generic throw or a Sales wrapper's generic failed-response write. The
background worker continues with the next pending invoice; it records the review
only if it was not already logged. Normal successful commits and unrelated
failure handling remain unchanged. A later scheduler run can encounter the same
source again: no durable review hold, automatic identity repair or retry policy
is introduced.

Frappe15's native `throw`/`msgprint` changes exception.args to the translated display
message. The error therefore supplies an English canonical `__str__`, while the
framework's message log retains Arabic display text for Arabic users. Pinned
native message-function tests verify one display (zero when muted), one English
diagnostic and exception propagation. The UI translation is one appended CSV
entry; no browser script or existing translation was rewritten.

Source evidence: Frappe15 `7b430f5eec8c0537f2f0cde9d30e175ae9068647`,
`frappe/__init__.py` SHA256
`91ff3bd9c46f554b3ced2fc025297c1e56348c67190135b8222b1980646918f3`.
The message functions run with in-memory message storage and injected globals;
this is not an initialized site, HTTP application lifecycle or installed16 test.

## Verification

515 new cases include 288 complete-parent stable API/wrapper comparisons, 128
bad-content language/adapter cases, 16 real wrapper-change cases, four frozen
counterexamples, 12 authorization-priority cases, 15 pure/read-contract cases,
32 native Frappe15 message cases, 12 actual public parent error-boundary cases
and eight worker continuation/log cases. The existing 541 payload tests also pass;
four one-read test inputs now supply matching pre-signed metadata rather than
identity-free XML. No original financial expected values or frozen sources changed.

The increment228 reference contains all 15 changed function bodies, SHA256
`66ccae53a75393cf23a4a46c5d987739353a48f01026acc404db587a71f77898`.
The separate native Frappe15 message reference SHA256 is
`99a0eb0f585e564bb430c30dd93f1d77961fa49b69d429ee7a5f985da1f268e5`.
AST restoration reproduces all seven affected module trees after reversing only
the new capture call/keywords, typed review handlers and documented imports.
354 other tracked runtime files and 30 previous Python reference fixtures remain
byte-identical. The original financial matrix remains 91 identical/117 differences
awaiting review/32 blocked out of 240, with no financial builder change here.

Focused 1,056 pass in 8.28s. The final guarded broad run passes 19,296 cases
across 72 reviewed suites in 108.12s. Six browser suites pass 1,208 cases.
Manifest201 local/57 private; no whole-manifest or private-SQL run. See
[STATUS.md](STATUS.md).
Local evidence: `/tmp/zatca-binding-229-focused-final.log`,
`/tmp/zatca-binding-229-regression.log`, `/tmp/zatca-binding-229-structure.json`.
Release priorities and acceptance criteria are consolidated in
[RELEASE_REMAINING.md](RELEASE_REMAINING.md).
