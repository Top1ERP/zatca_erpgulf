# Exact archived-attempt advance source choice — increment 32

## What is implemented

`advance_source_selection.ArchivedAdvanceSource` is a pure, frozen derived
observation. It consumes ONE explicit `DispatchJournal` and explicit expected
`PreparationContext`, canonical UUID, positive integer ICV and exact journal
revision fingerprint. It does not discover records, files, connections or a site.

The selection rule is deliberately endpoint-specific:

- Reporting: preserve the **original exact request XML**. An optional returned
  reported XML is checked for contradictions but cannot replace the request.
- Clearance: use the **exact returned cleared XML**. Its absence, malformed
  content or disagreement cannot fall back to the original request.

The selector reconstructs journal observations and recomputes the existing
`ResponseAssessment`. It does not accept caller-supplied assessment/outcome
dictionaries. HTTP 200/202 alone, saved status, a filename or an attachment's
creation time cannot select a source. Unconfirmed/rejected/auth-failed/unknown
attempts fail closed; a late response requires an explicitly pinned later journal
revision, not an automatic latest-record lookup.

The candidate must have a matching full preparation context, UUID and ICV and
must be a type-386 **Sales Invoice**, matching the current direct allocation
schema's source Doctype. This is not a universal legal restriction on POS.
The complete context comparison pins declared Company/environment/chain/source
version/unit, credential owner/version, route and source snapshot. No current
settings or legacy certificate field is consulted.

## Reference consistency beyond generic response assessment

Increment 15's generic response assessment compares declared invoice identity,
ICV, seller, digest/previous-hash and classification metadata. It does NOT compare
IssueDate/IssueTime. Thus a response can satisfy that generic local assessment
while containing a changed clock.

Increment 32 independently applies increment 31's bounded original-reference
reader to the request and, if present, the response. Their issue date/time must
match **lexically**. Changed dates, seconds, offsets or fractions are rejected;
even equivalent instants with different text fail closed pending a separately
reviewed comparison policy. It never applies today's timezone to either artifact.
Other exact bytes may differ legitimately: source choice preserves the full
selected artifact without reserialization, indentation or signature rewriting.

This stricter check is local adapter policy, not a claim that every real ZATCA
response has been tested or that every rejected lexical variation is prohibited
by the authority. Supported clock limits remain in [ADVANCE_REFERENCE.md](ADVANCE_REFERENCE.md).

## Trust and permission boundaries remain gates

This primitive is **not** a permissioned ERP service and is not adopted by the
runtime builders. It never reads a File row and must not be exposed as a
whitelisted JSON method, hook, queue job, button or fallback generator.

All supplied objects and expected fingerprints remain declarations. Shape and
hash consistency do not establish a trustworthy namespace, committed database
record, saved source, actor permission, credential epoch or real transport origin.
The diagnostic projection includes fingerprints/size/source-kind/warnings only;
all provenance, permission, persistence, remote acceptance, signature,
invoice-hash/business-data verification and settlement/dispatch/replay authority
flags remain **false**. A consistent fabricated journal can pass this model.

Before runtime adoption, implement and audit:

1. A server-owned site/namespace/chain/issuance-version mapping and exact source
   identity lookup; user input cannot select storage namespaces or credential
   versions. Existing artifacts without journal records require a separate
   reviewed reconciliation path, not inferred or fabricated journals.
2. A permissioned saved Sales Invoice/Company/issuing-unit boundary, checking
   the current actor before storage acquisition and again before disclosure.
   Permission to read an invoice is not permission to export archive bytes.
3. An owned committed-record storage read with pinned revision/context, bounded
   decoding, transaction/closure handling and concurrency policy. Do not borrow
   the active Frappe transaction or mark an uncommitted observation durable.
4. Authenticated capture/remote-flow provenance, cryptographic and accounting
   verification of exact source artifacts, including changed clearance output.
5. Explicit missing-source policy for Phase-1 QR-only advances and retired legacy
   documents. No invented date/time/UUID, latest-file scan or remote fetch.
6. Golden reference/allocation/GL/VAT tests and separately approved isolated
   installed ERPNext 15/16 acceptance before any builder replacement.

## Evidence from this increment

The selected local tests use generated public certificates, synthetic invoice
metadata and fabricated response bodies. They deliberately do not have valid
ZATCA signatures, accounting or genuine remote receipts.

The additional owned-private MariaDB suite reconstructs committed request/receipt
journals and verifies exact endpoint-specific source choice across three declared
environments. It also proves namespace separation and late-revision rejection.
An explicit rollback case demonstrates that a same-connection uncommitted receipt
can satisfy structural selection and then disappear: **selection does not attest
commit**. Persistence flags remain false throughout.

Only a new temporary server with TCP disabled is used through the guarded runner;
no tenant database, authority API, real invoice, schema migration, live source or
worker was touched. This does not complete the broader unification, genuine
authority acceptance, installed v16, crypto or advance-accounting work.

Increment 33 adds [permissioned metadata-only saved-source access](ADVANCE_SOURCE_ACCESS.md).
It does not export selected XML or attest provider/remote origin. Those gates,
Phase-1/legacy missing-source policy and runtime settlement adoption remain open.
