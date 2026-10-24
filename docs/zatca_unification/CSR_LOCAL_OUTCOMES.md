# Local key/CSR outcomes — increment 82 (development only)

Increment 83 adds a conservative saved-material preservation guard to these
paths. The original no-blocker limitation below describes increment 82; see
[CSR_KEY_PRESERVATION.md](CSR_KEY_PRESERVATION.md) for current guard scope and
remaining non-atomic renewal/custody limitations.

## Scope and contracts

The selected local `create_csr` and internal `create_private_keys` paths now
have one error owner, `_run_csr_operation`. CSR calls the shared key worker,
not another public boundary which could add a second popup. Authorization is
still exact saved-row READ/WRITE, with related Company READ for devices; ordinary
saves and all previous source/abbreviation checks remain in place.

Success contracts remain an opaque base64 CSR string and internal PEM bytes,
respectively. The key helper is not whitelisted. No new success popup, endpoint,
HTTP request, certificate, log write, automatic retry, restore, commit, rollback,
cleanup, schema change or live installation is introduced.

Keep the existing EC SECP256K1 key generation, TraditionalOpenSSL unencrypted
in-memory PEM representation, subject/alternative-name attributes, extension
OIDs, environment labels, SHA256 signing and key-before-CSR save ordering.
This refactoring does not certify these legacy choices as authority-compliant,
strengthen unknown environment handling, or consolidate signing/hash code.

## Observations, not transaction evidence

`CSRProgress` holds only four request-local literal boolean observations. The
pure `csr_local_failure` returns static English status/purpose/code/message,
never an exception, key, CSR, certificate, source name or request data.

| Observed failure boundary | Classification | Required interpretation |
| --- | --- | --- |
| Before key-save entry | `CSR_PREPARATION_FAILED` | Review saved permissions/configuration; no key/CSR save was started by this worker |
| Key assignment/save entered, did not return | `CSR_KEY_STORAGE_UNCONFIRMED` | Changes may already exist; inspect before another operation |
| Key save returned, CSR processing/final source load failed | `CSR_BUILD_UNCONFIRMED` | The key may differ while CSR/certificate fields remain old |
| CSR assignment/save entered, did not return | `CSR_STORAGE_UNCONFIRMED` | Both saves may have partial effects; inspect without retry |
| Expected save returned but local completion failed | `CSR_LOCAL_COMPLETION_UNCONFIRMED` | A returning save still does not prove commit or usable credentials |

Source failures before key-save entry use `CSR_SOURCE_ACCESS_DENIED` or
`CSR_SOURCE_UNCONFIRMED`. Later source failures keep the stage-specific review
message and append one static access notice in the same popup. Explicit row
denial retains native Frappe PermissionError even after a key save. Ordinary
save/hook failures remain storage-unconfirmed ValidationError, not a claim that
the operation was rejected before effects. They never grant retry permission.

## Display and diagnostic custody

Child popups are muted only within this operation. Parent mute flags are restored
exactly, queued parent messages are not cleared, and BaseException cancellation
propagates without a replacement popup or speculative cleanup. The final throw
occurs outside the caught child exception context. Static metadata remains English;
only the final display keys use the user's translation, including Arabic CSV keys.

Raw crypto/ORM exception text is deliberately neither stringified nor logged by
this boundary: it can contain private material. No raw diagnostic is retained or
exported here. This is a scoped redaction policy, not certification of full
Frappe hook output, logs/tracebacks/locals, request decorators, browser/wizard
saves, read/export permissions or application-wide error reporting.

## Active credentials: unresolved activation gate

Existing settings still share a private-key field with active certificate/auth
fields. Successful row authorization is not authority to rotate an active bundle.
The legacy helper can still replace that key, leaving existing certificate/CSR/auth
incompatible. This increment makes partial outcomes visible; it does **not** add
an active-material blocker, stage/activate a new credential epoch, migrate fields,
restore old keys or solve concurrency. The encrypted staging work from earlier
increments remains uninstalled and unactivated.

Before runtime adoption, design a separate authorized renewal/onboarding workflow
which preserves the active bundle, stages a new key/CSR privately, binds issuance
to that exact source/epoch/environment, validates the returned certificate against
the staged public key, and activates only under explicit reviewed transaction and
rotation policy. Do not infer a safe path merely from populated or empty legacy
aliases. This needs its own review and isolated v15/v16 rehearsal, not an automatic
compatibility fallback in this error refactor.

## Offline verification boundary

`test_csr_local_outcomes.py` is explicitly added to the fixed offline manifest.
It uses synthetic saved documents/ACLs, ephemeral in-memory test EC material,
mocked saves and blocked/mock HTTP only. Faults cover configuration, generation,
serialization, key save, key loading, CSR construction, late permission/source
loss and final CSR save. Tests check one English/Arabic popup, parent muting and
message preservation, unstringifiable private exceptions, cancellation, progress
validation, no retry/transaction cleanup, unchanged successful return shapes and
signature/key/OID observations. No real customer source, file, key or authority
request is used. Full installed Frappe/ERPNext 15/16, SDK, concurrent transactions
and authority acceptance remain unverified and are not claimed by these mocks.

Final guarded verification: **12,582 local + 1,800 private SQL = 14,382 passed
in 150.68 seconds**, including **282 new synthetic cases**, across twelve
owned-private SQL suites. Nine standalone Node VM checks passed **1,444 cases**.
The first local run caught four missing late source notices; those assertions
were retained and the source adapter corrected. The first combined run passed
all local cases but could not ready its temporary MariaDB process. The same
fixed command passed after reviewed subprocess execution permission, with all
offline guards still active; no tenant fallback was used.
