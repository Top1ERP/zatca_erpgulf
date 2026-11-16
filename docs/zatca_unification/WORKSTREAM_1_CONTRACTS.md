# Source and issuer contracts — workstream 1

Development only. The active local contract is an execution-scoped observation,
not a database snapshot/epoch, installed lifecycle acceptance or permission to
submit to the authority. No site, schema, Company, invoice, worker or service was
changed. The reviewed release scope is described below; the next workstreams
own the explicitly identified remaining acceptance and transaction work.

## Adopted entry contracts

| Entry family | Source and purpose | Scope boundary / artifact |
| --- | --- | --- |
| Ordinary Sales / POS | Saved invoice; Production purpose | Authorize invoice READ/WRITE and Company READ; require enabled Phase-2; capture issuer and prime the canonical signing material before native UUID/ICV preparation. |
| Sales / POS generated and scheduled variants | Same saved invoice, ignoring request issuer hints | Same early scope as ordinary generation. Scheduling eligibility remains the worker's responsibility. |
| Single-invoice Compliance | Saved invoice rendered separately from selected saved Company/device authentication source; Compliance purpose | One source/issuer scope around builders/signing/temp sample/request. Does not allocate production invoice identity. |
| All / automatic Company Compliance | One saved Company and Compliance selection for all six checks | Recheck captured settings before each check; no per-type credential reselection. Synthetic samples remain temporary, with no Customer/invoice insert. |
| Sales / POS Debug | Saved invoice; local Debug purpose | Preview identity and one scope around local preparation/signing/attachment. No auth token required; no request or scheduling decision. |
| Four pre-signed XML wrappers | Saved invoice and existing imported extractor | Same issuer scope; seal extractor-observed bytes; existing metadata gate checks request UUID/hash; transport fence checks same-content digest even if UUID/hash did not change. This is not signature authentication. |
| Clearance fallback | Original scope/source/purpose and captured request value | The existing internal fallback must keep the selected issuer. Response/409/receipt/PIH policy is workstream2. |
| Standalone request helpers / explicit replacements | Existing imported callback contract | Keep request-only/lazy XML behavior. No producer seal or native signing proof is claimed when no native writer/scope ran. These internal functions are not new public capabilities. |

The six native production generators use `invoice_issuing_attempt` before their
metadata operation. Thin imported metadata/signing replacements remain explicit
extension points: their private side effects cannot be certified or undone by a
post-return check. Replaced signing callbacks do not obtain a claim of native
material verification. The compatibility surface must be inventoried again in
workstream4 before removing an adapter.

## Observed values and boundaries

- Company selection: saved invoice Company, then its saved abbreviation. The
  route and purpose authorization use one frozen saved Company projection.
- Owner: existing Company/device/linked-Company declaration policy, including
  explicit false versus true linked-key flags and same-taxpayer validation.
  A request payload is not an editable owner/key/Company source.
- Phase: metadata presence decides preferred `custom_phase_1_or_2` versus legacy
  `phase_1_or_2`; a blank preferred field does not fall through to Phase-2.
  Phase-1 issuance remains in the existing local QR flow.
- Environment: selected Company and its configured URL; Compliance stays in that
  environment and uses Compliance material. It is not forced to Sandbox. Normal
  reporting/clearance uses Production-purpose credentials in its selected
  environment. URL suffix/purpose checks retain the established routing policy.
- Credential material: select this purpose's token certificate; require its
  exact certificate DER, key/curve/time consistency and Company taxpayer claim.
  Recognize explicit organizationIdentifier and the app CSR's DirectoryName UID;
  never infer VAT identity from free-text CN/organization. Preserve generic
  certificate bytes only when they describe that same token certificate. Do not
  overwrite aliases, copy tokens between purposes or select a different owner.
- Saved invoice: raw business values/children, including v16 item tax details;
  native `as_dict` selects keys, but `get` supplies original values so Decimal
  precision is not hidden by export-time conversion. Original modified is only
  provenance. Framework metadata and derived issuance outputs are excluded.
- Consumed masters/discovery: scoped saved reads and selected query adapters
  re-observe address/customer/template/account/source inputs, including empty
  and reordered discovery results. Minimal test records have only the declared
  scalar profile; they cannot demonstrate an installed full-record observation.
- XML: seal final canonical-writer/temp/extractor content after the established
  formatting and compare the actual captured request value. Match existing
  UTF-8/lstrip behavior only. No new fiscal rounding, invoice-hash algorithm,
  SignedProperties hashing or QR financial rule is introduced.

Recheck at signing/file boundaries and immediately before all thirteen existing
HTTP invocation sites. A retained child context is invalid after scope exit;
wrong site/source/purpose is rejected. Nothing is queued, pickled or held in a
cross-request/site cache. The fence does not lock database rows or make later
concurrent changes impossible. Counter/PIH transaction ownership, historical
identity changes and partial commits belong to workstream2.

## Explicit credential storage decision

The current release does **not** activate the previously staged encrypted,
versioned credential tables/provider/activation APIs or migrate legacy fields.
Existing legacy CSR/key preservation guards prohibit overwriting an observed
issued target; no force/expiry/role bypass or automatic credential clearing is
added. Existing Final-CSID preservation continues. A populated target requiring
renewal receives review rather than a destructive key replacement.

This release supports initial onboarding and purpose-correct consumption of the
saved bundle. It does not claim a complete automatic renewal/multi-key activation
workflow. A future renewal feature requires its own trusted source/custody,
old/new bundle retention and explicit atomic activation design. The staged
components stay unregistered and documented; they are not an implicit runtime
fallback or install-time migration. See [CSR_KEY_PRESERVATION.md](CSR_KEY_PRESERVATION.md)
and [CSID_PRESERVATION.md](CSID_PRESERVATION.md).

## Evidence and remaining acceptance

One typed review crosses the legacy failure writers without an extra invoice
error save. Display uses the user's translation; explicit diagnostics and error
string remain English. Once a transport invocation has started, context failure
uses an unknown-outcome notice and does not assert that no request was sent.
This marker proves neither socket delivery nor a received/accepted response.

Tests use synthetic saved records, real ephemeral EC keys/certificates, native
formatting/signature/QR helpers, temporary files and mocked HTTP under the offline
guard. The native-signing integration verifies all six types for Sales/POS and
Company/device/linked owners, including the actual Compliance HTTP adapter.
Self-signed test certificates are not trusted ZATCA certificates. Installed15/16,
CA/environment-origin/revocation evidence, stored XML signature/source-file
custody, local SDK/scanner and fictional-Company acceptance remain later gates.
Existing file-path/ownership and duplicated extractor cleanup are workstream4;
full pre-signed crypto authentication is workstream6. No extra authority lookup
is allowed by this local identity comparison.

Public reference: [ZATCA Security Features Implementation Standards v1.2](https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/20230519_ZATCA_Electronic_Invoice_Security_Features_Implementation_Standards_vF.pdf),
section2.2.2 organizationIdentifier profile, and the app's existing CSR template.
This does not establish revocation or remote account authorization.
