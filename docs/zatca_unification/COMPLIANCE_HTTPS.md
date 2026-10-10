# Explicit Compliance HTTPS adapter — increment 25

## Delivered scope and limits

`compliance_https.py` implements an opt-in callable for increment 24's coordinator,
not a registered/default transport, operator endpoint, button or deployed caller.
It uses real Requests preparation/HTTPAdapter behavior and bounded urllib3 entity
reads. Tests replace the HTTP pool; no TCP connection, TLS handshake, OTP/CSID or
ZATCA request was made. Existing legacy submission/Compliance/Debug paths remain
unchanged and do not adopt this module.

A server must supply `ComplianceHttpsPolicy` and an explicit trusted monotonic
timer. Policy creation is not proof of tenant permission, source snapshot, issuing
unit, active epoch or approval to send. Use the adapter behind permissioned source
acquisition and the committed single-use reservation, not directly from UI data.
No archive/source/remote/CSR provenance or activation authority is upgraded.

## Destination policy

The immutable policy accepts 1–3 distinct explicitly approved environment routes
using the application's existing standard mapping. There is no environment/URL
fallback, caller URL concatenation, generic origin allowlist or custom gateway.

| Environment | Required path under https://gw-fatoora.zatca.gov.sa |
| --- | --- |
| Sandbox | /e-invoicing/developer-portal/compliance/invoices |
| Simulation | /e-invoicing/simulation/compliance/invoices |
| Production | /e-invoicing/core/compliance/invoices |

Only exact canonical HTTPS routes, Compliance purpose and matching saved base
field names are accepted. No alternate hostname, explicit port, userinfo, query,
fragment, redirected path, reporting/clearance or final-CSID operation is allowed.
Production onboarding is not forced to Sandbox: it is usable only if its exact
route is explicitly approved and material matches that route. This does not
establish remote credential eligibility or a completed compliance step.

Custom gateways already supported by legacy routing remain unchanged there.
They are deliberately unsupported in this NEW adapter until reviewed destination/
DNS/egress policy and tests exist. Do not silently substitute another route to
make an unapproved configuration pass. Network/platform policy still must protect
DNS and egress; a Python URL check is not a workload isolation boundary.

## Request preparation and one-send behavior

- Require the exact protected `ComplianceTransportRequest` class and revalidate
  its start/material binding before releasing authorization to the HTTP layer.
- Prepare one POST with original bytes via `data`, not JSON serialization. Derive
  headers from the staged snapshot; no caller auth, cookies or header override.
- Match method, destination, exact body, all headers and computed Content-Length
  before and after sending and after reading. No hooks or extra prepared headers.
- Use a fresh owned HTTPAdapter with zero retries, direct streaming send,
  `verify=True`, `cert=None`, and an explicit empty proxy map. No Session, netrc,
  ambient proxy/auth/CA override merge, cookie persistence or redirect resolution.
- Close response and adapter on success/failure; cleanup uncertainty is a static
  unconfirmed error, never a reason to send again.

The [Requests adapter API](https://requests.readthedocs.io/en/latest/api/#requests.adapters.HTTPAdapter.send)
supports prepared requests and explicit stream/TLS/proxy/timeout parameters.
Local Requests 2.32.5 source inspection found that Session.send's no-redirect path
can still consume a redirect body while creating Response.next. The direct adapter
avoids that path; synthetic 302 tests verify no second request or eager .content
consumption. This is a local implementation observation, not a claim about every
future Requests release. Rehearse the actual dependency versions before adoption.

Zero application-level retries does not mean zero TCP retransmissions or DNS/IP
connection attempts. A 3xx response is captured from the original destination,
never followed or counted as a successful Compliance validation. HTTP 401/400
remain ordinary rejection observations under the existing strict assessment.

## Bounded response entity reads

The request asks for identity content encoding. Accept only absent/identity
Content-Encoding and absent/chunked Transfer-Encoding. Reject simultaneous
Content-Length/Transfer-Encoding, malformed/noncanonical or duplicate-joined
lengths, unsupported encodings and advertised bodies over 8 MiB.

Check parsed headers for 100 fields/32 KiB aggregate. This is AFTER the native HTTP
parser reads headers, not a hard cap on every lower-level header buffer. Then read
at most 16 KiB per call through `raw.read1(..., decode_content=False)`, with one
overflow probe byte at the exact 8 MiB boundary. No .content/.text/read-all, JSON
repair, decompression or arbitrary legacy reader fallback. Reject over-bound or
non-byte chunks, missing reader support, truncation and declared-length mismatch.
Empty bodies are preserved, not converted into validation success.

The [urllib3 read1 API](https://urllib3.readthedocs.io/en/stable/reference/urllib3.response.html#urllib3.response.HTTPResponse.read1)
provides bounded reads with an explicit decoding switch. The archived bytes here
are the returned HTTP entity body after HTTP transfer framing, NOT TLS records,
HTTP chunk delimiters or a complete original packet capture. Response headers,
peer certificate, socket identity and actual TLS/source attestations are not
persisted by the existing response/archive contract.

## Time and dependency bounds

Server policy sets finite positive connect/read/elapsed values, capped at 10/30/60
seconds respectively; defaults are 5/15/30. Initial connect/read timeouts are
limited by the elapsed budget. Trusted monotonic checks before/after I/O and
cleanup reject elapsed or backwards/nonfinite/bad timer values without retry.

These checks are NOT a hard wall deadline or guaranteed cancellation. As the
[Requests timeout contract](https://requests.readthedocs.io/en/latest/user/advanced/#timeouts)
explains, connect/read timeouts concern connection or inactivity intervals rather
than total duration. DNS, native calls, multiple addresses and trickled protocol
framing can exceed an elapsed budget while an operation is blocked. Do not market
this as a hard execution deadline; a reviewed process deadline/cancellation policy
would be required separately, without authorizing replay after termination.

The tested stack is Requests 2.32.5 + urllib3 2.6.3 in the existing Python 3.10
environment. Packaging constraints remain unchanged; no library was installed or
upgraded. A missing HTTPResponse.read1 feature is rejected BEFORE adapter creation/
credential release. A missing reader on a returned raw object also fails closed.
Broader supported-version/ERPNext 15/16 dependency matrices remain release gates.

## Privacy and authority

Policy/transport repr excludes routes and secret material; pickle is refused.
Requests/prepared/raw-response objects and provider exceptions must never be
logged, queued or rendered. The adapter emits only static internal error codes
outside exception handlers so secret-bearing request/driver exceptions are not
chained. Future operator adapters must translate and safely display those errors.
There is no new UI string/catalog entry or browser endpoint in this increment.

TLS uses the library's verified public CA trust store, not the ZATCA signing key,
site encryption key, custom CA discovery or disabled verification. Actual hostname/
certificate validation was NOT exercised against a real TLS peer in these tests.
Audit platform CA custody, DNS/egress, HTTP debug/TLS key logging and workload
isolation before approval. Python memory erasure, trust/revocation of the invoice
certificate and protection from a privileged process holding keys are not provided.

The collector still exposes only supplied-observation diagnostics. A matching
success-shaped body returned by a synthetic pool is not verified ZATCA acceptance.
Source/credential epoch/remote receipt/CSR issuance/completion/activation/dispatch/
replay authority remains false. Never activate or bypass remote checks from it.

## Verification and next gate

191 new local cases cover all six types and three environments, exact preparation/
auth/body, 200/202/406/401/400/302, no redirects/eager body read, zero retries,
explicit TLS/proxy configuration, env isolation, allowed destinations, empty/exact/
over-bound bodies, malformed framing/encoding/headers, monotonic/time policy,
transport/binding/close errors, privacy and unsupported-reader fail-closed behavior.
The real HTTPAdapter operates against synthetic urllib3 pools with socket/DNS and
ambient Session access forbidden. This exercises configuration, not a TLS handshake.

Four private SQL cases compose the real preparation/adapter pipeline with the
owned MariaDB reservation/archive and a synthetic HTTP pool: success, redirect,
TLS-shaped failure and oversized response. Committed start visibility and closed
SQL resources precede pool invocation; duplicate collection never invokes it again.
Only owned private Unix SQL sockets are allowed; the urllib3 TCP path is blocked.

The selected regression suite passes **3,615 local + 110 private SQL = 3,725 cases**.
Private split: 25 journal, 30 bundle/service, 34 archive/service, 17 capture, 4 HTTPS.
Commands are in [STATUS.md](STATUS.md) and [COMPLIANCE_ARCHIVE.md](COMPLIANCE_ARCHIVE.md).
No actual TLS/HTTP/OTP/CSID, SDK/golden signing run, full restored Frappe boot,
browser or ERPNext 16 runtime was tested.

Increment 26 adds an [internal permissioned saved-source service](COMPLIANCE_CAPTURE_ACCESS.md)
that composes with this adapter in synthetic-pool/private SQL tests. Guarded calls
check exact saved revisions/ACL before reservation and in a closed preflight
transaction, then repeat saved ACL before releasing the request to this transport.
Current selected total: **3,839 + 118 = 3,957 cases**. No runtime adoption or real
TLS/source/CSR provenance is established by that service.

Next: audited tenant/key/owned-connection acquisition and installed-schema/ACL
rehearsal of the new guarded source boundary, durable source/epoch evidence,
trusted transport/CSR issuance attestation and explicit unknown-outcome recovery.
Rehearse real TLS and the v15/v16 dependency/site matrix in an approved isolated
harness; do not contact ZATCA or enable a tenant button without the required pilot/
deployment authority. Key/schema/off-host recovery review and prior notice before
any live source/configuration/schema change, installation or Bench restart remain.
