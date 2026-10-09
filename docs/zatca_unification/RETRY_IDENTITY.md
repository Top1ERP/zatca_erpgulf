# Retry identity characterization and consolidation order

Read-only source/mock audit following increment 8. No live invoice, UUID, signed
file, counter, PIH, or credential was changed. These are observed implementation
behaviors, not a regulatory endorsement or a completed retry-safety fix.

## Evidence from the actual paths

`test_retry_identity_contract.py` adds 61 site-free cases. Metadata tests call
the actual Sales/POS builders; HTTP tests exercise all twelve production-purpose
adapters using mocked saved documents/responses and temporary XML. Existing-XML
tests call the actual extraction/submission wrappers.

| Boundary | Observed behavior | Consequence for unification |
| --- | --- | --- |
| Sales `createxml.salesinvoice_data` | Reuses any non-placeholder saved value; otherwise creates and commits UUID before sending | More durable than POS, but the guard is not a UUID syntax validator |
| POS `posxml.salesinvoice_data` | Always generates a new live UUID; does not persist it in metadata | Regeneration after an unknown outcome can change identity even when saved UUID exists |
| Primary Sales reporting/clearance HTTP 400/401/503 | Retain a non-placeholder saved UUID | This policy is not shared by the other adapters |
| Other ten audited HTTP adapters at those statuses | Replace saved UUID with `Not Submitted` | A valid prior identity can be discarded on auth/server failure as well as validation rejection |
| All twelve at mocked HTTP failures | Existing invoice ICV/issuing-unit remain; PIH does not advance | A subsequent regeneration may combine a fresh UUID with the old saved ICV |
| All twelve at a direct Requests timeout | Saved UUID/ICV remain at this boundary; no PIH success update | This alone does not preserve later regeneration identity or prove remote rejection |
| Four existing-XML wrappers | Extract UUID/hash from artifact, without reconciliation against saved UUID, then overwrite saved UUID after mocked acceptance | Choosing either the field or file blindly can conceal conflicting historical evidence |

The POS regeneration test executes metadata twice with the same saved invoice
and existing ICV. The two UUIDs differ, with no metadata UUID write. Sales's
placeholder filter accepts an arbitrary non-UUID string; this is explicitly
characterized rather than strengthened in this audit. Tightening it without
artifact reconciliation could replace a historical identity unexpectedly.

HTTP tests use a valid saved UUID and retain a source XML file byte-for-byte. They
do not establish that the test's synthetic UUID/hash/XML are mutually valid or
would be accepted by ZATCA. An HTTP mock cannot prove invoice-hash correctness.

## Why a UUID-only patch is insufficient

Metadata UUID, assigned ICV/issuing unit, previous-invoice hash, issuer credentials,
signed XML bytes, QR, and payload UUID/hash must describe one issuance attempt.
Reusing a UUID while recomputing XML with changed invoice values, current PIH,
signing time, or renewed credentials does not preserve the issued artifact.
Conversely, sending the existing file while resetting saved fields obscures its
relationship to the invoice. Existing file-name queries are not an immutable
artifact ledger or a concurrency lock.

The foreground Background preparation path also creates signed artifacts before
the worker submits them. The shared writer uses an invoice-name-based file path;
it does not independently distinguish Sales/POS documents with identical names
or concurrent generations. Unique temporary Compliance files do not solve this
live artifact problem. The accepted-response artifact hook is Sales-only and
cannot substitute for an issuance ledger spanning POS and unknown outcomes.

## Required implementation order

1. Build an explicit read-only evidence inventory of saved UUID/ICV/unit/status,
   linked issuing unit, counters, accepted responses, and attached/generated XML.
   Parse namespace-qualified root invoice ID/UUID and the issuer party, not the
   first arbitrary `CompanyID` in the file. Report conflicts without exposing
   credentials or automatically repairing tenant records.
2. Define a durable issuance record keyed to invoice DocType/name, environment,
   issuing unit, and issuance version. Store exact signed bytes, payload hash,
   UUID, ICV, previous hash, credential-version reference, QR, and provenance.
   Keep historical accepted/unknown artifacts immutable and access-controlled.
3. Serialize allocation and dispatch by the actual chain owner, not raw auth
   string formatting. Reconcile historical counter identities using the mapping
   gates in [LEGACY_XML_AND_ICV.md](LEGACY_XML_AND_ICV.md). Do not reset, merge,
   or lower counters automatically when credentials rotate.
4. Separate preparation, dispatch, and response recording. Transport-unknown,
   auth failure, validation rejection, and confirmed acceptance must be distinct
   states, with an explicit correction/version policy instead of a generic
   `Not Submitted` identity reset. A transport retry replays exact stored bytes;
   it does not rerun XML/signing. Remote outcomes need the appropriate confirmed
   response contract before status or PIH is advanced.
5. Migrate Sales/POS and all existing-XML/without-XML/background adapters together
   to that artifact contract. Validate source ownership and payload/artifact
   metadata before HTTP; preserve explicit manual/batch authority and Company
   eligibility for automatic workers.
6. Verify concurrent workers, interruption after allocation/signing/HTTP, delayed
   responses, credential rotation, corrected rejected invoices, source/file
   conflicts, equal Sales/POS names, and v15/v16 transaction boundaries on isolated
   restored sites. Golden XML/SDK and remote test evidence remain independent
   acceptance gates.

This sequence avoids treating one retained field as a complete retry-safety
solution. No runtime identity migration is part of this audit.

Increment 9 adds an opt-in saved-identity/attached-XML evidence inspector, without
changing any generation or HTTP adapter. Its scope and reconciliation states are
documented in [ARTIFACT_EVIDENCE.md](ARTIFACT_EVIDENCE.md). Loose generated files,
accepted responses, counters, and credential-version provenance remain pending.

Increment 10 extends that diagnostic with stored response XML/declarations and
the saved unit's historical counter, explicitly separating API environment from
counter purpose. See [HISTORY_EVIDENCE.md](HISTORY_EVIDENCE.md). Loose generated
files, complete historical mapping, provenance/credential epochs, and actual
restored-site rehearsal remain pending before any identity migration.

Increment 11 adds a separately permission-gated known generated-file location,
including same-name Sales/POS ambiguity; see [GENERATED_EVIDENCE.md](GENERATED_EVIDENCE.md).
Increment 12 adds embedded certificate/key fingerprints across all requested XML
sources; see [CERTIFICATE_EVIDENCE.md](CERTIFICATE_EVIDENCE.md). This is observed
public evidence, not a verified credential epoch. The durable issuance/version
contract, complete historical mapping, atomic provenance and restored-site
rehearsal still precede any live identity or retry migration.
