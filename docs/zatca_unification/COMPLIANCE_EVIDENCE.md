# Version-bound Compliance observations — increment 21

## Purpose and limits

`compliance_evidence.py` checks exact supplied CSR/request/response observations
against **one** staged Compliance version. It does not dispatch HTTP, issue CSIDs,
persist receipts, activate credentials or change existing buttons. This is local
contract matching, **not verified remote acceptance**. A hand-crafted valid-looking
response can match; every transport/completion/activation authority flag remains
false until trusted capture, protected storage and issuance provenance exist.

The new internal `inspect_compliance_checks` service composes those observations
with increment 20's saved source/owner permissions and authenticated staged
repository load. It is not whitelisted or adopted by live preparation/submission.

## Requirements come from CSR bytes, not a UI label

The official [ZATCA detailed technical guideline](https://zatca.gov.sa/en/E-Invoicing/Introduction/Guidelines/Documents/E-invoicing-Detailed-Technical-Guideline.pdf),
sections 3.3.3–3.3.5, defines the functionality map and ties onboarding checks to
the submitted CSR: standard-only and simplified-only each require their invoice,
credit and debit samples; combined functionality covers both groups. Integration
onboarding checks precede Production CSID issuance. This model implements that
mapping, not a blanket six-step requirement for every unit.

| CSR functionality | Required observations |
| --- | --- |
| `1000` | Standard invoice, credit note and debit note |
| `0100` | Simplified invoice, credit note and debit note |
| `1100` | Both groups, six distinct types |

`ComplianceRequirements` accepts bounded DER CSR bytes with a valid CSR signature,
the staged certificate's public-key fingerprint, one SAN DirectoryName and one
unambiguous Title functionality map. Unknown/reserved maps do not fall back to
Production or all types. One UID must use the guideline's 15-digit VAT identifier
format (ASCII digits, first/last digit 3). The service also matches that identifier
to the saved Company Tax ID. This is **not** a full CSR business/template validator.

Matching a public key does not prove this exact CSR caused the certificate to be
issued. Renewals can reuse keys. A future trusted issuance receipt must bind the
exact CSR hash, environment, taxpayer/unit and flow/request/version; today's mutable
`custom_csr_config` and caller-provided requirement objects cannot supply that proof.
The local requirement object cannot reduce ZATCA's server-side requirements.

## Exchange binding

`ComplianceExchangeObservation` preserves exact immutable request/response bytes,
explicit UTC timestamps and an exchange identity. It enforces:

- Exact Compliance purpose/environment and a validated `compliance/invoices`
  route, never a reporting, clearance, OTP or final-CSID request.
- Strict bounded wire JSON with only `invoiceHash`, `uuid` and Base64 `invoice`
  in the request. No response display-text repair, duplicate keys or trailing JSON.
- Request UUID and declared digest matching XML, embedded certificate DER/SPKI
  matching the staged manifest, and seller Tax ID matching the CSR UID.
- Type derived from the actual XML `InvoiceTypeCode` and indicator; the existing
  application's six label/code mappings are reused. Advances (`386`) are not
  silently substituted for ordinary onboarding invoice samples.
- Ordered explicit times: preparation, attempt, receipt. Unknown transport has
  no status/body/receipt time and never completes a step.
- Shared strict validation-message checks from the response assessment module.
  HTTP 200/202 need consistent PASS/WARNING validation without errors; HTTP 401,
  403 or other rejection cannot become successful from a success-shaped body.
- HTTP 406 is separate: only the existing `Submitted before` code plus the exact
  type-specific `Compliance-Check` message matches a previous-completion observation.
  Mixed errors, another type, warnings/info mixed into that response, or a local
  `_zatca_compliance_status` marker never substitute for raw matching wire evidence.

Matching a declared digest is not recomputing the transformed invoice hash.
Embedded DER equality is not verification of SignedProperties, signature, QR,
trust/revocation or certificate provenance. No actual Authorization header or
password is retained; binding the actual sent header to the staged material is
part of the future trusted transport capture, not something this parser proves.
Reporting/clearance response labels in a Compliance body do not grant real invoice
reporting/clearance authority.

## Aggregation and permissioned inspection

`ComplianceCheckSet` requires one namespace, exact manifest/flow/request/version,
exact CSR and gateway for all exchanges. Identical exchange redelivery is
deduplicated. Reusing an exchange identity with different bytes/status/times is a
conflict. A sample UUID cannot represent two different XML artifacts. Observing
another attempt for the same exact artifact does **not** authorize replay.

Each required type needs its own matching observation; six copies of one success
cannot satisfy six types. Successful observations and previous-completion
observations remain distinct in the report. Historical matches are not erased by
later unsuccessful observations. Rejections/unknown results remain visible.
The set is bounded to 64 exchanges and 32 MiB of unique request/response bytes;
CSR, individual request/XML and response bounds also apply.

The permissioned service checks the authenticated stored manifest bytes, server
namespace, saved Company Tax ID and today's effective Compliance route before
returning the check-set projection. It inherits role/site/document ACL checks,
generic unchained English/Arabic failures and explicit caller transaction cleanup.
It returns fingerprints/types/outcomes only, never CSR/request/response bytes or
credential material. Existing manifest-only inspection is unchanged.

`COMPLETE_MATCHED_OBSERVATIONS` describes a complete **local matching set**. It is
not `compliance_completion_verified`, does not enable a final-CSID button, and does
not replace the gateway's mandatory validation. Increment 21 did not store this
evidence durably or invoke the operator method from a browser/API. Increment 22 adds
an isolated [encrypted observation archive](COMPLIANCE_ARCHIVE.md), not live runtime
capture, an operator endpoint or verified remote provenance.

## Verification

The new local suite adds **136 cases**, using generated in-memory CSRs/certificates
and deliberately unsigned synthetic XML. It covers all three environments, three
functionality profiles, six types, 200/202/406, wrong/mixed previous-completion
responses, scope/identity conflicts, CSR signatures/keys/UIDs, request/body bindings,
timeouts/rejections, bounds/privacy and permissioned service integration.

Four added owned-private-MariaDB cases exercise complete, previous-completion,
incomplete and wrong Compliance-request-ID observations against actual authenticated
encrypted version rows. The Frappe documents/ACL layer remains mocked; no tenant
or external connection is accepted by the private fixture.

Increment 21 passed **2,993 local + 55 private SQL = 3,048 cases**. Increment 22 adds
147 archive-local cases, two net empty-body cases and 27 private SQL cases; the
increment 22 selection passes **3,142 local + 82 private SQL = 3,224 cases**.
Increment 23's [permissioned archive selection](COMPLIANCE_ARCHIVE_ACCESS.md) adds
145 local and seven private SQL cases, reaching **3,287 + 89 = 3,376 cases**. Commands
are in [STATUS.md](STATUS.md) and [CREDENTIAL_BUNDLE_STORAGE.md](CREDENTIAL_BUNDLE_STORAGE.md).
No SDK, real CSR/OTP, remote Compliance/Production request, invoice submission,
browser, restored Frappe application or ERPNext 16 runtime was tested.

## Next gates

Capture protected exact issuance/HTTP evidence from a trusted server transport,
including the actual credential/header binding and source/settings transaction;
store it durably without plaintext credential leaks or caller verification flags.
Verify CSR-to-certificate/flow provenance and current source/unit/environment,
then design controlled transactional epoch activation and rejection/rollback
policy. Preserve the previous active Production version on failure. Rehearse on
restored v15/v16 sites and notify the user before any live change. Never activate
from this local report or repurpose it as a way to bypass the remote checks.
