# Pending native certificate renewal preparation

Workstream2 development,2026-11-22. The active issuing-chain form now has a
**Prepare Certificate Renewal** action backed by the actual owned preparation
service. It retains pending material separately from active credentials. This
is local preparation, not complete renewal, issuer suspension or epoch activation.
No live site, schema, asset, worker, invoice, counter or authority API was changed.

## Why a separate path

The [official Developer Portal manual](https://www.zatca.gov.sa/en/E-Invoicing/SystemsDevelopers/ComplianceEnablementToolbox/Documents/Developer%20Portal%20User%20Manual.pdf)
describes `PATCH /production/csids` for renewal with OTP. The developer replies in
[How to renew expired PCSID](https://zatca1.discourse.group/t/how-to-renew-expired-pcsid/524)
describe old Production CSID authentication, new CSR, the renewed Compliance
certificate response and the subsequent compliance/Final-CSID steps.

The common route resolver now accepts an explicit method. POST to that path
retains Compliance-purpose authentication; PATCH requires Production-purpose
authentication and is permitted only on that path. Route metadata alone does not
prove the HTTP method, OTP, committed reservation or remote issuance. Existing
invoice/initial-onboarding transports still validate their own capabilities and
remain POST-only. This bundle adds no PATCH invocation or fallback.

The [per-new-CSID counter decision](CSID_COUNTER_EPOCHS.md) requires retained old
ledger custody and a separate new issuance epoch. Replacing owner fields early
would destroy the ability to reason about old signed/unknown requests. A pending
key/CSR therefore does not reset ICV, change PIH or create a new active chain.

## Admission and exact pending custody

The POST action accepts a recorded chain ID and bounded review reason only. It
requires the explicit native rollout setting, System Manager, current selected
owner READ+WRITE, routing Company READ and chain READ. Server-loaded owner links,
marker, environment, active slot and taxpayer must match the recorded active
chain. A device delegating to its Company's key cannot prepare a second renewal
as though it owned another issuer; operate on the actual owning chain instead.

Production-token certificate DER and the current private key must agree with
each other and the active chain's certificate/key fingerprints. Explicit taxpayer
and complete EGS serial claims must match the saved CSR configuration/environment.
The supplied browser cannot change key, CSR, serial, taxpayer, environment, old
counter or credential data. Generic old aliases are retained exactly, not silently
selected as a different purpose's certificate or rewritten.

One new secp256k1 key and CSR are generated using the shared existing template.
After cryptography, saved material/routing are checked again under the owned
transaction. Any observed drift aborts before retention. Payload admission also
checks the CSR signature, key equality, SHA256 algorithm, exact subject, both
expected noncritical extensions and environment signing label.

ZATCA CSID Renewal is a new read-only service DocType. A unique pending-owner slot
prevents concurrent preparations for the same owner/environment. Separate
`csid-renewal` AES-GCM custody binds site, namespace, record ID and exact header.
The header contains public IDs/fingerprints, method PATCH, actor and UTC clock;
the encrypted payload contains exact old credential/configuration text, new key/
CSR and review reason. It contains no OTP. Plaintext payloads are capped at4MiB;
header/ciphertext SQL reads and column/index/engine semantics are checked.
No new site encryption key is generated. Existing cipher formats/AAD are unchanged.

Repeat preparation requires the same current owner/old certificate/configuration/
route/reason and reopens the retained pending key/CSR. A lost COMMIT acknowledgment
remains uncertain; the next identical call recovers committed custody without
generating another key. Corrupt or changed custody holds instead of replacing it.
There is no generic edit/delete/rename/import or automatic abandonment/reset.

The old issuer may continue generating while preparation is only local. A later
old-epoch ICV does not invalidate the same pending CSR or cause a rewind. The
separate remote-renewal step must establish its old-issuer freeze/drain/fence
before PATCH, since renewal can revoke the old certificate. No `drained=True`
or client approval flag is introduced here.

## Expired material and presentation

Local preparation can retain a currently expired old certificate after verifying
the same key/token/taxpayer/EGS bindings; it reports expiration explicitly.
This does not prove the remote API will accept that credential. Future-dated old
certificates hold. The common material equality checks were extracted without
weakening ordinary `CredentialSnapshot`: invoice signing still requires current
certificate validity. No historical XML or digest/certificate text is rewritten.

The active-chain Desk action prompts for a reason and performs one explicit POST.
Refresh performs no work. Dirty/stale/new/inactive/unbound forms and duplicate
in-flight callbacks cannot start another preparation. A successful response shows
one translated aggregate notice and links to the pending metadata record. It
returns no private key, CSR, auth, reason or raw certificate. Arabic catalog
entries cover new display text/metadata labels; error diagnostics remain static
English codes. Unknown commit state survives the public error boundary.

## Source-only installation and remaining work

This adds the eighth read-only service DocType and the seventh native custody
table. Cold namespace setup includes it in the orphan census. Missing/incorrect
storage holds preparation; no table/schema/config/key is installed or repaired
by the action. Actual ERP15/16/dummy installation remains separately gated.

Remaining workstream2 work includes authenticated pending remote-request/response
custody, old-issuer freeze/drain/unknown-outcome policy, renewal428 and later
Compliance/Final-CSID admission using pending material, stable logical EGS versus
successive CSID ledger mapping, explicit atomic activation and original readers
across the transition. Initial onboarding buttons are not a renewal shortcut.
Real CA/SDK/remote account acceptance and installed/pilot behavior remain gates.
This preparation service does not close workstream2 or qualify a new CSID/ICV1.

## Verification scope

Tests cover exact old/new material, CSR/environment/header/route purpose binding,
permission and changed-source admission, replay after unknown commit, protected
corrupt/index/reason/route holds, old counter advancement, foreign parent writes/
callbacks and expired preparation versus strict invoice signing. Synthetic Desk
VM checks cover English/Arabic messages and stale/dirty/role/slot/duplicate/error
conditions. Private active-chain/CA responses are explicit fixture inputs, not
real activation/SDK/authority proof. Exact final selections/logs are in STATUS.
Financial/golden data and the original240 comparison91/117/32 remain unchanged.
