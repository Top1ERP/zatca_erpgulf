# Primary live adapter context — development increment 5

This increment connects the four primary Sales/POS reporting and clearance
functions to the shared route and credential-owner policies. No deployed source,
tenant setting, invoice, certificate, counter, or remote ZATCA state was changed.

## Implemented scope

`submission_context.get_submission_context` validates the source invoice name
and expected adapter doctype, permits only reporting/clearance operations, and
resolves a route and Production-purpose authorization before preparing artifacts
or HTTP. The immutable result pins the URL, header, and owner identity for that
request. Authorization remains hidden from its printable representation.

Both `reporting_api` and `clearance_api` in `sign_invoice.py` and `pos_sign.py`
consume this context. Configured Sandbox, Simulation, or Production routing is
preserved. Production-purpose auth does not mean that the endpoint is forced to
Production: these are independent route properties.

Company, own-device, and explicitly linked Company use the same saved-owner
policy already used for signing and dedicated Compliance. A missing Production
token cannot fall back to Compliance. Source ownership, linked Tax-ID consistency,
explicit checkbox zero, and normalization of copied Basic prefixes/whitespace
are therefore consistent across these four request adapters.

Seven repeated success blocks now call `record_submission_owner_success`. It
loads the owner by the request's pinned identity, applies the existing owner's
notification preference, and delegates to the existing Phase-2 PIH updater. It
does not reevaluate the invoice/device link after HTTP returns. Existing Phase-1
and unchanged-hash PIH guards remain active; counter allocation is unchanged.

## Deliberately preserved behavior

- Request payload, operation-specific Clearance-Status header, timeout, response
  interpretation, accepted XML/QR attachment behavior, and invoice status writes
  are unchanged. This is not a unified HTTP transport or response classifier.
- Reporting remains deferred when configured for Batches. Route validation now
  also happens before that branch; incomplete URL/environment settings fail early.
- POS reporting still attaches its XML before HTTP for valid contexts. Its local
  configuration failures now occur before that attachment, but legacy exception
  handlers may still write an invoice error response and commit. This is **not**
  a fully write-free preflight or an overhaul of transaction boundaries.
- Sales reporting/clearance and POS reporting currently treat HTTP 409 as a
  duplicate success; POS clearance rejects it. Tests characterize this pre-existing
  difference, not approve it. Validate a structured accepted/duplicate outcome
  before unifying these branches; generic 409 must not be assumed to prove acceptance.
- Certificate selection, signing algorithms, Phase-1 QR, advance calculations,
  ICV keys, retries, and background scheduling are unchanged in this increment.

## Tests

`test_submission_context.py` adds 138 cases. They exercise the real four adapter
functions with mocked HTTP, saved documents, files, and events, and the actual PIH
helper against fake saved owners. Cases include three environments and ownership
modes, 200/202 payload/auth/PIH assertions, missing Production auth, 400/401/500,
timeout, owner-link changes during HTTP, deferred Batches, malformed environment,
cross-taxpayer rejection, target identity checks, Phase-1/unchanged-PIH guards,
notification settings, legacy 409 behavior, and Arabic catalog messages.

All 605 cases in the combined selected suite passed in the existing Python 3.10 /
Frappe 15 environment. No real invoice request, SDK validation, browser language
switch, full-site transaction test, or ERPNext 16 run occurred. See
[STATUS.md](STATUS.md) for the reproducible command.

## Remaining release gates

Increment 17 provides a local ephemeral material-binding contract, but these
existing HTTP adapters do not consume it yet. It does not fix their cross-pipeline
rotation races or establish database/epoch/environment provenance. See
[CREDENTIAL_SNAPSHOT.md](CREDENTIAL_SNAPSHOT.md) for the staged adoption gates.

1. Increment 6 migrates the four existing-XML adapters listed in
   [LEGACY_XML_AND_ICV.md](LEGACY_XML_AND_ICV.md). Increment 7 migrates the remaining
   four reporting adapters and redirects the six legacy generator Compliance paths
   in [GENERATION_AND_COMPLIANCE.md](GENERATION_AND_COMPLIANCE.md).
2. Reconcile ICV owner/environment fingerprinting with the selected owner, with
   an explicit continuity/migration policy. Never reset or merge existing chains
   merely because a resolver has changed.
3. Pin signing material, credential epoch, and request route together. The new
   context is created at the HTTP adapter, after signing; it does **not** prevent
   rotation races across the entire pipeline or certify CSID/certificate binding.
   Linked-owner environment provenance and certificate lifetime/Tax-ID checks
   remain pending as well.
4. Resolve conflicting certificate fields and issuance/renewal lifecycle before
   deployment; then prove retry identity, structured response acceptance, chain
   ordering, and transaction behavior in isolated v15/v16 site integrations.

The broader backup, golden-fixture, onboarding, advance-accounting, and pilot
requirements remain in [PLAN.md](PLAN.md).
