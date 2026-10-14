# Exact archived-attempt QR source observations — increment 40

## Internal consistency, not authenticated recovery

`qr_source_selection.ArchivedQRSource` consumes an explicit immutable dispatch
journal, expected preparation context, UUID, ICV and exact journal revision.
It derives the source XML and QR payload from those supplied observations only.
It does not discover a site, acquire SQL, scan Files, choose a latest attempt,
read physical content, load active credentials, generate an image or send HTTP.

The object is NOT an authorization/capability. A fabricated consistent journal
can satisfy this contract. All provenance, permission, persistence, signature,
invoice-hash, business-data, QR-validity, remote-acceptance and recovery/replay/
dispatch flags remain false. The class does not enable the recovery button.

## Exact source rule

The journal is reconstructed and its revision, context and source identity must
match the explicit expectations. Context equality includes the declared Company,
environment, chain, issuance revision, credential epoch, endpoint and source
snapshot. It does not prove those declarations came from an authorized server.

`ResponseAssessment` is derived from the exact journal, not an independently
supplied success dictionary. An unconfirmed/malformed/wrong-operation receipt,
transport-unknown state or HTTP rejection cannot provide an accepted-source
consistency match. Synthetic 200/202 matches preserve warning observations but
still do not prove authentic remote acceptance.

| Candidate operation | Selected QR source |
| --- | --- |
| Reporting | Exact prepared request XML, even when a returned XML is present |
| Clearance | Exact matching returned XML; never fall back to the request |

The existing response contract compares invoice ID/UUID/ICV/seller, declared
invoice/previous hashes and document classification. Original and any returned
IssueDate/IssueTime must additionally match their exact lexical values. The
shared pure clock parser validates supplied fields without timezone discovery or
normalization. Equivalent instants with different clock text require review;
this conservative policy is not a claim that such lexical differences violate
the whole XML standard.

The selected source must contain exactly one direct namespace-qualified QR
reference, ID, Attachment and EmbeddedDocumentBinaryObject. No local-name,
nested-reference or first-match fallback exists. Text must be nonempty, without
outer whitespace/child nodes, bounded to 16 KiB and canonical standard Base64.
Line-wrapped/noncanonical values fail closed pending a separately reviewed
adapter policy; this is NOT the complete regulatory/XSD Base64 language.

Base64 decoding checks only bounded lexical structure, NOT TLV tags, signatures,
certificate binding, seller/time/amount parity or scan validity. Exact original
XML bytes and payload text are preserved; no XML reserialization or signing
occurs. File/payload SHA-256 values are fingerprints, not ZATCA transformed
invoice digests. Encoding declarations remain byte input.

The object is frozen, redacted in repr and not pickleable. Diagnostics contain
hashes/lengths/source kind/warning flags only, not XML, payload, source identity,
clock, receipt body or URL. Generic dataclass serialization is still unsuitable
for logs because private fields intentionally hold caller-supplied bytes.

## Phase-2 writer audit — unresolved, NOT modified

This section records the increment 40 baseline. Increment 42 separately removes
[the automatic hook's speculative repair/deletion](PHASE2_ARTIFACT_PRESERVATION.md),
without modifying the shared extraction helper or primary submission adapters.

The current `phase2_artifacts` hook still:

- accepts a saved status/response field without exact request/identity/epoch
  binding and prefers `clearedInvoice` when both return fields exist;
- loosely decodes response Base64 and extracts the first nested local-name QR;
- reuses prefix-matching attachments by creation order, without comparing bytes;
- deletes QR-field files of another prefix and may change a saved QR/status.

Its extraction helper is also shared by Sales/POS clearance code. Replacing it
requires deliberate caller/fixture coverage; this increment does not claim the
new strict observer already protects those writers. No hook registration or
runtime adapter changes here. Missing reporting-return XML must not be invented
or substituted for the original request. Status/filename/current settings are
not an authenticated historical source.

## Offline evidence and next gate

Increment 41 adds a [permissioned metadata-only adapter](QR_SOURCE_ACCESS.md)
and shared saved-row/owned-cleanup engine. It does not install a provider,
authenticate receipt/storage origin, export source XML/QR or activate recovery.

Local cases use generated certificates and fabricated candidates/receipts, NOT
valid ZATCA signatures/TLV or genuine 200/202 responses. The matrix covers declared
Sales/POS candidate modes, invoice/credit/debit/advance codes, all three declared
environments and both operation classes. It is not regulatory approval of every
ERP/type combination. Negative cases cover exact expectation/response/clock
drift, missing receipt/QR, ambiguity/namespaces/DTD/bounds, noncanonical Base64,
immutable/redacted observations and false authorization flags.

The final guarded run passed **5,271 local + 231 private SQL = 5,502 cases**
in **48.04 seconds**, including 158 new local cases. An initial test-helper
argument-name collision was fixed without changing the source-selection contract.

15 added private SQL cases extend the existing archived-source suite: 12 exact
source reconstructions plus namespace/revision mismatch and same-connection
uncommitted-receipt rollback. They use a new owned synthetic MariaDB server and
the existing journal repository/schema, not a tenant or an installed ORM. A
same-connection consistent observation can disappear on rollback and therefore
cannot attest committed provenance. Existing advance selection is unchanged.

Next bind the selector through a permissioned server-owned site/namespace/exact
committed-record provider with saved-source/owner and historical epoch checks,
authenticated receipt origin and crypto/QR validation. Only then design an exact
generation/attachment plan; do not hand this DTO directly to a file writer or
expose raw XML/payload through a public endpoint. The button remains REVIEW for
missing originals, with no recovery mutation.

No deployed code/configuration/schema/worker/customer data or authority request
changed. Complete development offline before separately approved isolated
fictional-client rehearsal and the user's whole-change adoption/cancellation.
