# Read-only attached-XML evidence preflight — increment 9

Development only. No tenant inventory was executed, invoice identity/counter/PIH
was changed, worker restarted, schema migrated, or remote request performed.
The tool is opt-in and is not connected to submission, onboarding, or Debug UI.

## Purpose and scope

`artifact_evidence.py` supplies a site-free immutable metadata projection and
saved-identity comparison. `artifact_inventory.py` supplies an internal,
non-whitelisted Frappe bridge for one explicitly named Sales or POS Invoice.
This implements the attached-XML portion of the evidence inventory proposed in
[RETRY_IDENTITY.md](RETRY_IDENTITY.md); it is not the complete migration inventory.

The bridge requires read permission on the invoice, its saved Company, and each
File. It discovers attachments for that exact DocType/name, excludes non-XML and
`DEBUG_` files, reloads each candidate's ownership/privacy metadata, and reads
only bounded regular files directly under the site's private files directory.
Public/remote URLs, traversal, stale attachment ownership, symlinks, directories,
FIFOs, missing files, and oversized input do not become usable evidence. Failed
candidates remain in the report; a good file does not hide a bad one.

No content is rewritten or normalized. SHA-256 fingerprints refer to the exact
file bytes, including XML encoding and whitespace, **not** the transformed
invoice hash used in the submission payload. The parser accepts bytes with their
encoding declaration and uses explicit namespace-aware paths for root ID/UUID,
the ICV reference, and VAT CompanyID under AccountingSupplierParty. Buyer VAT,
nested reference UUIDs, and the SignedProperties digest are not substitutes.

The inspector rejects ambiguous required values/containers, malformed UUID/ICV,
wrong roots, invalid declared SHA-256 digest encoding/length, and malformed PIH
binary data. It records presence of QR without validating its TLV/signature.
Diagnostic ICV parsing is bounded to 64 decimal digits to avoid expensive integer
conversion; this does not change or define the live counter's allowed range.
PIH is not constrained to 32 decoded bytes because its cryptographic format is
outside this evidence step, including legacy initial-seed representation.

DTD/entity loading, parser recovery, and large-tree relaxation are disabled.
DTDs/entities are rejected; a custom resolver rejects external resource access.
Static failure codes avoid exposing parser snippets, private XML, or local paths.
These settings follow the primary [lxml parser documentation](https://lxml.de/parsing.html#parser-options),
[safe-parsing guidance](https://lxml.de/FAQ.html#how-do-i-use-lxml-safely-as-a-web-service-endpoint),
and [resolver API](https://lxml.de/resolvers.html#uri-resolvers).

## Report interpretation

| State | Meaning, limited to this inventory scope |
| --- | --- |
| `NO_ATTACHED_XML` | No non-Debug XML candidate; not proof that no invoice was issued |
| `RECONCILIATION_REQUIRED` | A candidate is unreadable/invalid or conflicts with saved ID/UUID/ICV/seller/environment; missing saved identity is not repaired |
| `CONFLICT` | Multiple successfully parsed candidates have different exact bytes; neither newest filename nor stored status selects a winner |
| `IDENTITY_CONSISTENT` | All candidates parse, match the inspected saved identity, and have identical bytes; not acceptance, signing verification, or replay permission |

An original standard XML and its later cleared XML can legitimately differ.
The inventory still reports different bytes: resolving their provenance and
authority requires the response/issuance ledger, not automatic deletion or an
assumption that a conflict itself means ZATCA rejection. Identical copies remain
listed; no file is selected, moved, deleted, or treated as authoritative.

Outputs include saved identity/status/environment/unit and per-file metadata,
byte fingerprint, and static reconciliation codes. Company keys, auth tokens,
certificate contents, XML bodies, and binary QR values are not returned.
All reports explicitly set `signature_verified`, `remote_acceptance_verified`,
and `replay_authorized` to false. The three fatal diagnostic messages have Arabic
translations; report codes are machine-readable, not a new UI dialog.

## Verification and next work

145 new local tests use synthetic metadata XML, mocked Frappe records/permissions,
and pytest temporary files. Cases include UTF-8/UTF-16 bytes, explicit seller
selection, duplicate/missing fields and containers, declared digest checks,
DTD/resolver rejection, exact-byte conflicts, saved-field mismatches, Sales/POS
parity, permission/privacy guards, URL/path/symlink/FIFO checks, failures alongside
good candidates, and absence of writes or exposed credentials. No fixture is a
golden signed invoice or proof of ZATCA validity.

The wider selected regression suite passes 1,393 cases in the existing Python
3.10/Frappe 15 environment. The bridge's Linux file flags match this Bench; a
different OS and a real ERPNext 16 runtime were not verified.

Remaining inventory sources include loose generated XML, stored accepted
responses, counters and their historical identity mapping, and credential-version
provenance. This checker does not compare line items, tax/discount totals,
issue timestamps, reference invoices, key/certificate binding, environment in
the certificate, or current PIH. It provides no concurrent-worker/file snapshot
lock. Identity consistency alone cannot authorize regeneration or exact replay.
Those are separate ledger/service and integration gates before any live retry
policy changes.
