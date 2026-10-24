# Shared-key preservation guard — increment 83 (development only)

## Observed issue and deliberate behavior change

The selected key/CSR paths could replace the shared private key while saved
certificate/authentication fields still referenced the old key. Row WRITE
permission and client consent are not safe renewal/activation authorization.

These paths now stop conservatively when their exact authorized saved target
contains any certificate, authentication or onboarding-reference data. This
intentionally disables using the legacy CSR/key operation for renewal of a
populated target. There is no force option, privileged-role exception, automatic
credential clearing, alias repair, expiry-based exception or environment bypass.
Do not clear saved credentials to make the button work. A separately reviewed
staged renewal workflow must preserve the active bundle first.

This is a presence guard, **not** proof that a certificate is active, valid,
trusted, accepted, correctly scoped or expired. Malformed, unrelated, historical,
whitespace-only and masked text all require preservation/review too.

## Fixed projection and outcomes

The pure `csr_key_preservation.require_unissued_key_target` accepts only an exact
app-owned dictionary projection. It never parses certificates, decrypts auth,
checks token validity, performs HTTP, writes, or exports input material. Arbitrary
objects are not stringified or truth-tested. Missing/extra projection keys and
unknown value types fail closed.

| Saved target fields | Treatment |
| --- | --- |
| `custom_certificate`, `custom_certficate` | Either populated spelling blocks replacement; no preferred-alias fallback |
| `custom_basic_auth_from_csid`, `custom_basic_auth_from_production`, `custom_final_auth_csid` | Any populated purpose's authentication blocks replacement |
| `custom_compliance_request_id_` | A populated onboarding reference blocks replacement even without a stored certificate/token |
| Private key, CSR, OTP alone | Outside this issued-material projection; pre-issuance key/CSR generation remains possible |

Only literal `None` and exact empty strings count as absent in the six protected
fields. Boolean/numeric/bytes/container/custom-object values are unknown, not
normalized to empty. Static results are `CSR_KEY_PRESERVATION_REQUIRED` for present
text and `CSR_CREDENTIAL_STATE_UNCONFIRMED` for unverifiable shape/type/read state.
The error constructor receives only a static classification selector, never a
source, field value, key, CSR, certificate, token or raw exception argument.
The public boundary throws outside the child catch, without its implicit context.

## Bounded integration

The shared operation boundary from increment 82 owns one final translated popup.
Before any key-save entry, it displays the static preservation message. If a
later check fails after a key save returned, it retains the partial-key stage
message and appends the preservation notice to the same popup. Unknown private
read errors are not stringified. Cancellation restores parent mute flags and
propagates without retry, cleanup, speculative restore, commit or rollback.

Checks occur after ordinary saved-source authorization:

1. At CSR entry, before reading/parsing its configuration.
2. In the shared key worker, on its reloaded authorized target before generation.
3. On that same loaded target again after generation/serialization, before key
   assignment/save, catching observed in-process changes during crypto callbacks.
4. On the fresh authorized target before final CSR assignment/save.

A device inspects/writes its own target only. A populated linked Company's
credentials do not become the device's write target, even when its signing policy
uses Company credentials. The existing linked Company READ-only dependency and
normal target READ/WRITE checks remain unchanged; this does not reconcile device
onboarding with linked signing ownership or authorize a separate device renewal.

Company/device confirmation now explicitly says this operation is for pre-issuance
settings only and that existing issued material blocks it. Its real Arabic CSV
entry is used only for display. Client payloads cannot clear server-side fields or
bypass the guard with `force`, rotation or ignored-permission flags. This does not
make manual settings edits impossible; the guard is not a durable tamperproof hold.

Successful pre-issuance API signatures/return shapes, curve, key encoding, subject,
OIDs/environment labels and signing stay unchanged. No new endpoint, role, schema,
storage activation, certificate, field migration, invoice/QR change, real request,
installed asset build, site operation or Bench/worker restart is introduced.

## Remaining custody and concurrency gates

The post-crypto recheck observes the **same loaded object**, not a locked/reloaded
database revision. Ordinary ORM timestamp/permission checks remain, but this guard
does not prove cross-request isolation, prevent every hook/commit race, bind a
durable epoch, detect prior remote issuance with missing local records, or preserve
key material from arbitrary other/manual writers. A later check can stop CSR save
after the key has already changed; it does not undo that effect. No automatic
rollback or another key is a safe repair for that situation.

Legacy Compliance/Final CSID writers can still change shared certificate/auth
fields. They are not protected by this local key/CSR guard. Secret field custody,
all other writers, complete hook/log/trace/read/export control, immutable staging,
remote/source/epoch provenance and atomic explicit activation remain separate gates.
Earlier encrypted staging primitives are still uninstalled/unactivated. Renewal
must stage the new key/CSR separately and bind returned material before an explicit
reviewed activation; do not infer that workflow from blank aliases.

## Offline evidence

The new fixed-manifest suite uses synthetic documents/ACLs/saves and ephemeral
in-memory test keys only. Allowed key/CSR fixtures explicitly model pre-issuance
settings by clearing **test objects**, never actual saved Company/device records.
Existing negative ACL fixtures stay populated. Two old lifecycle overwrite
characterizations are intentionally replaced with assertions that generation is
not called, key/auth remain unchanged, no save occurs and local token/key binding
remains intact. CSID overwrite characterization is not weakened or removed.

Coverage includes every protected field in Company/device key/CSR calls; English/
Arabic display; masked/whitespace/invalid material; unknown types/read errors;
client force/empty-field attempts; environment switches; crypto callback changes;
data appearing on the second source load or after key save; linked Company
preservation; invalid config ordering; cancellation; and alias-registry coverage.
Standalone UI tests check the updated translated consent without real RPCs.
Full installed ERPNext/Frappe 15/16, physical metadata/field masking, actual ORM/
timestamps/hooks/transactions, browser/Desk, SDK and authority acceptance remain
unverified. Development completion and a separately approved isolated fictional
Company rehearsal remain prerequisites before any adoption or gradual live pilot.

Final guarded combined verification: **12,853 local + 1,800 private SQL =
14,653 passed in 164.51 seconds**, across twelve owned-private SQL suites,
including **271 new synthetic preservation cases**. The earlier combined run
passed **14,652 in 148.40 seconds** before the additional alias-registry case
was collected. All nine standalone Node VM scripts passed **1,444 cases**,
including the updated English/Arabic consent checks. No offline resource guard,
normal source permission, successful crypto check or transport assertion was
relaxed. These timings describe test runs, not user-facing operation latency.
