# Missing original advance sources and five-tag QR — increment 34

## Scope

This increment adds bounded local QR observations and explicit review outcomes
for source gaps. It does not replace the three reference builders, change advance
accounting eligibility, install fields/buttons or deploy any code. All supplied
facts remain declarations; the model does not establish that a file is absent.

The current `advance_lifecycle.is_accepted_advance_sales_invoice` accepts submitted,
marked Sales Invoices with REPORTED, CLEARED or the two recognized Phase-1 QR
statuses. This eligibility remains unchanged. It is different from having an
authoritative original reference artifact for a subsequent Phase-2 document.

## What the five-tag payload actually contains

The inspected ordinary Sales/POS and initial-advance Phase-1 builders encode:

1. Seller name.
2. Seller VAT ID.
3. Timestamp.
4. Invoice amount text.
5. VAT amount text.

Those fields do not supply invoice ID, UUID, ICV, document type or original XML.
They cannot, on their own, identify an original type-386 invoice. Nor does their
presence prove Phase-1 provenance or genuine issuance: any caller can manufacture
five matching tags. A stored QR image/file name, invoice status or copied legacy
row does not fill these gaps automatically.

`FiveTagQRObservation` takes an explicitly supplied Base64 payload and expected
seller VAT ID. It never scans an image, reads files or contacts a service. The
one-byte TLV subset requires exactly tags 1..5 in order, UTF-8, nonzero bounded
lengths and no trailing/extra/duplicate tags. Canonical strict Base64 is bounded
to 1,716 encoded bytes / 1,285 TLV bytes. Paths, data URLs, invalid UTF-8 and
truncated values fail with static codes. A Phase-2 payload with additional tags
is not silently reduced to its first five fields.

Timestamp text uses the same conservative calendar/clock subset as original
reference inspection, preserving offsets/fractions and accepting a naive clock
as an observation, NOT assuming UTC or today's timezone. An offset-presence flag
does not attest time provenance. Amounts are preserved signed ASCII decimal text
(up to 24 integer and 6 fraction digits), never floats/calculated/rounded totals.
This is not monetary reconciliation, VAT-rule, signature, QR/XSD or legal proof;
unsupported lexical forms require review, not invoice invalidation or repair.

The frozen object hides raw fields in repr. Its diagnostic projection exposes
only byte fingerprints/sizes, format, offset presence, missing field labels and
false verification/authorization flags. Generic dataclass serialization is not
suitable for logs. The hash describes supplied encoded bytes, not invoice hashing.

## Missing-source review policy

`MissingAdvanceSourcePlan` accepts an explicit origin and target phase, optionally
the five-tag observation for the Phase-1 QR-only origin. It is a diagnostic plan,
not a permissioned source selector or an eligibility guard installed in hooks.

- **Phase-1 QR-only, target Phase-1:** keep the existing Phase-1 workflow unchanged.
  No Phase-2 XML/UUID/ICV is required by this diagnostic, and no new authorization
  is granted. Existing business/permission/amount checks continue to apply.
- **Phase-1 QR-only, target Phase-2:** require explicit historical reconciliation.
  Do not create a fictional UUID, infer a type from a filename or convert the
  old clock with current settings to fabricate an original XML.
- **Legacy copied reference:** copied fields are review inputs, not authenticated
  original-artifact provenance. Resolve original source identity and ownership;
  do not replace absent times with midnight or pick the first/newest file.
- **Missing Phase-2 archive:** recover exact committed evidence through an audited
  source path. Do not regenerate/re-sign historical invoices or fetch remotely.
- **Ambiguous original:** resolve versions/artifacts explicitly; do not choose the
  latest candidate or silently discard conflicts.

Every outcome remains `SOURCE_GAP_REVIEW_REQUIRED`. Missing-source verification,
Phase-2 reference readiness, settlement, reconstruction, migration, dispatch and
remote acceptance flags remain false. Accounting eligibility is NOT changed.
The policy does not declare that mixed Phase-1/Phase-2 references are legally
impossible; an actual bridge requires official rule/SDK evidence, source identity,
permissioned historical provenance and a reviewed migration/reconciliation design.
It cannot be inferred from these five QR fields alone.

## Additional lifecycle finding

The ordinary `create_qr.create_qr_code` path still performs `doc.db_set`,
`doc.save(ignore_permissions=True)` and an explicit `frappe.db.commit` after QR
attachment creation. New mocked characterization confirms one legacy commit for
Sales/POS versus no explicit commit in the tested initial-advance QR path.
The observation/plan itself performs NONE of these operations. The old behavior
was not changed here. QR attachment cleanup, re-entrancy and transaction ownership
need a separate bounded migration before claiming clean v15/v16 lifecycle parity.

## Evidence and remaining gates

Tests cover bounds, malformed/extra tags, UTF-8/Arabic seller text, explicit seller
matching, original clock/amount preservation, immutable private projections,
all gap/phase review outcomes, actual mocked Sales/POS/advance builders and
unchanged legacy accounting eligibility. They use synthetic data only.

No PNG decoding, actual saved source lookup, tenant/database repair, authority
request, SDK acceptance, full ERPNext 16 installation or source recovery occurred.
Increment 33's metadata service remains separate; this plan cannot bypass it or
authorize raw XML export. Full bridge/accounting and cryptographic unification,
audited provider origin and installed integration remain unfinished.

Next audit QR lifecycle side effects and transaction ownership, preserving
existing issued artifacts and non-production isolation. Continue offline before
the separately approved fictional-client rehearsal and whole-change decision.
