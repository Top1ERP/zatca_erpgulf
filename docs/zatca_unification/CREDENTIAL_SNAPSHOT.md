# Ephemeral credential material snapshot — development increment 17

This is a local material-binding boundary, not deployment, certificate renewal,
remote authentication, or a verified credential epoch. No existing generator,
button, HTTP adapter, scheduler, or tenant calls the new capture function.

## Implemented contract

`credential_snapshot.CredentialSnapshot` copies the selected private key and the
one purpose-specific authorization field from a declared owner. It pins the
validated route, selected certificate text, parsed certificate/key, and explicit
UTC observation time in one frozen, secret-bearing object. The pure constructor
does not read SQL/files/the clock, sign XML, send HTTP, or change credentials.

`credential_settings.capture_credential_snapshot` is an internal, unwhitelisted,
read-only adapter for a future service. It reads the requested saved Company
once, freezes that row's relevant fields before source/device reloads, then reuses
the existing saved-source owner policy and certificate alias policy. Caller
objects supply document identity only. It performs no save, commit, field repair,
certificate issuance, or request. This is **not a cross-row atomic database
snapshot**: source, device, and linked Company records may be separate reads.

| Operation | Required authorization |
| --- | --- |
| `compliance/invoices` | Compliance CSID field of the selected owner |
| `invoices/reporting/single` | Production-purpose field of the selected owner |
| `invoices/clearance/single` | Production-purpose field of the selected owner |

All three configured environments remain explicit. Production-purpose credentials
do not force the Production environment. OTP/CSR/final-CSID operations are outside
this snapshot's scope. Missing credentials cannot fall back to another purpose.

The Basic username carries the certificate token and the password carries the
secret, consistent with the authorization construction described in the official
[Developer Portal manual](https://zatca.gov.sa/en/E-Invoicing/Introduction/Guidelines/Documents/DEVELOPER-PORTAL-MANUAL.pdf).
The new parser bounds sizes and recognizes three explicit compatibility encodings:
the app's Base64-of-Base64-DER token, a direct DER token, or a single PEM token.
These are local compatibility choices, not a claim that the API guarantees every
format. No recursive guessing or fallback to today's certificate is allowed.

The decoded authentication certificate must equal the signing certificate's exact
DER bytes. A renewed certificate sharing the same key is not interchangeable.
The private key must match the certificate's public key, and both must use
secp256k1, as used in ZATCA's key-generation instructions in the
[detailed technical guideline](https://zatca.gov.sa/en/E-Invoicing/Introduction/Guidelines/Documents/E-invoicing-Detailed-Technical-Guideline.pdf).
The explicit UTC time must fall within the certificate's local validity interval.
These checks do not prove that the password is valid remotely, the credential is
authorized in this environment, or that the certificate is trusted/not revoked.

## Reuse and privacy

- Authorization field selection is factored from the existing policy; old
  helpers retain their purpose separation and legacy normalization behavior.
- Bounded public certificate parsing is shared with embedded-certificate
  diagnostics. No certificate digest, SignedProperties, XML canonicalization,
  ECDSA serialization, QR, tax, advance, or counter algorithm is changed.
- The snapshot retains only the consumed purpose's authorization and private
  key in its copied owner values. Secret/material fields are excluded from
  `repr`; errors are static codes rather than raw parser/authentication text.
- Pickle is refused. Never log, persist, queue, call `asdict` on, or send this
  object to a diagnostic endpoint. A frozen Python object is not a security
  boundary, and no secure memory erasure is claimed.
- `diagnostic_projection` exposes identities, operation/purpose, UTC time, and
  public fingerprints only. It explicitly marks database snapshot, credential
  epoch, trust, revocation, taxpayer, remote authorization, dispatch and replay
  verification/authority as false.
- Adapter failures have an English translation key and Arabic catalog entry.
  Existing alias conflicts retain their translated failure; no certificate is
  selected automatically to resolve a Compliance/Production transition.

## Verification

`test_credential_snapshot.py` adds 100 cases: three environments/operations/owner
types, saved Sales/POS/device and linked-owner resolution, caller injection,
known token encodings, same-key renewal mismatch, validity/curve checks, malformed
and bounded material, frozen copies, blocked pickle, safe errors/diagnostics,
Arabic catalog lookup, unsupported operations before SQL, and no writes/HTTP.
A local signature verifies with the captured public key; this is not a golden
ZATCA XML/signature or SDK test. A simulated Company rotation during source reload
proves that the one copied Company projection is retained, not database atomicity.

The combined selected local suite passes 2,538 cases. The separate owned private
MariaDB rehearsal passes 25 cases after the shared parser refactor (2,563 total).
Only synthetic keys/records and the test's private database are used. No tenant,
ERPNext 16 runtime, browser language switch, SDK, remote Compliance, or production
invoice is involved. See [STATUS.md](STATUS.md) for the reproducible commands.

## Remaining adoption gates

1. Separate Compliance and Production certificate lifecycle storage and reconcile
   the two machine certificate aliases with an approved migration. Do not copy
   or discard conflicting historical certificates blindly.
2. Capture authoritative source/settings/credential provenance in an explicit
   transaction; verify taxpayer/issuing-unit/environment authorization and define
   a durable credential epoch. Fingerprints alone cannot manufacture that epoch.
3. Wire one captured material object through preparation/signing/request services
   only after those gates. Existing legacy helpers still reload records between
   calls, so their complete pipeline rotation race is not yet fixed.
4. Integrate the durable journal with an approved Frappe storage service,
   cross-attempt policy, chain allocation/fencing and outbox/leases. Rehearse on
   restored v15/v16 sites before authorizing dispatch or changing retry identity.
5. Complete SDK/golden XML/QR/advance fixtures and notify the user before any live
   source edit, schema/configuration migration, deployment or bench restart.
