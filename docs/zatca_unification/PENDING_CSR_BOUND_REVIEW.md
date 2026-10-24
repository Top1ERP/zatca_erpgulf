# Owned read-only original-pair review — increment 94 (development only)

## Scope and non-activation

`PendingCSRStagingTransaction.observe_bound` reviews an independently retained
original envelope and its stored source-binding pair through a **separately
supplied fresh owned lease**. It reuses the shared permissioned source engine,
pinned Unix provider and read-transaction rollback/close lifecycle. It never
invokes the external historical lookup callback, stages, captures a new historical
binding, commits, reseals, generates IDs/material, activates or sends HTTP.

The method is internal and uninstalled: no Company button, whitelist, scheduler,
runtime provider/schema or active-credential caller is switched. Existing initial
creation, ordinary caller-owned stage/inspection, save and envelope-only review
remain unchanged. A failed or consumed owner cannot be reused as a writer/reviewer.

## Exact input and normal access before SQL

The existing constructor retains its trusted server dependencies for compatibility;
its lookup callback is not used by this pair-review operation. Scope, keys and
connections are not request-selected. The original namespace, manifest, key ID,
nonce and ciphertext must be retained unchanged after an unknown initial save.

Normal site/role/actor, saved target READ+WRITE and related Company READ checks
precede resource acquisition. Both quiet permission signatures and no-bypass
policy remain shared. Explicit Company or own-key device selection is required;
there is no invoice/abbreviation/latest/linked-owner fallback. The retained
manifest must match current saved owner/Company/source kind/revision/environment/
configuration, and the resource must match the exact scope and pinned key ID.
Current source rows are rechecked under locks before any stored pair is read.

## Bounded authenticated pair observation

The repository authenticates the original even when storage is empty, then reads
both exact namespace/draft-ID rows using bounded locked SELECTs. Existing envelope
authentication, canonical binding decoding and redundant-column checks are reused.
The internal return is `(classification, restricted_binding_or_None)`, never an
RPC result or log. A binding is handed to the service **only for an exact pair**.

| Classification | Checked transaction observation | Historical binding adopted? |
| --- | --- | --- |
| `PAIR_EXACT_OBSERVED` | Complete internally matching pair and every envelope field equals the retained original | Exact stored declaration only |
| `PAIR_ABSENT_OBSERVED` | Both exact SELECTs returned no row | No |
| `ENVELOPE_ONLY_OBSERVED` | Valid authenticated envelope exists without a source-binding row | No |
| `BINDING_ONLY_OBSERVED` | Valid canonical binding row exists without its envelope | No |
| `PAIR_CONFLICT_OBSERVED` | Complete internally matching authenticated pair differs from the original | No |

A resealed identical plaintext is a conflict, not exact storage. Corrupt rows,
unknown keys/tags, invalid schemas, wrong site/namespace, mismatched pair digests,
SQL failures and lock timeouts yield **no observation**, not absence or conflict.
The repository is poisoned on failure; caller cleanup remains mandatory.

For an exact pair, the service requires the **stored original** source/backing
hashes, manifest, scope and key to match current authorized observations. Drift
fails closed; current settings never replace that historical declaration.

For absent/half/conflicting pairs, no historical binding is manufactured, adopted
or exported. A private digest is taken only to observe **current** Password backing
stability across this review. It is not saved or labelled as historical agreement.
`original_source_binding_observed` and `password_backing_state_match_observed` are
false for these states. `current_source_match_observed` refers to the retained
manifest/current saved rows, not proof of an unavailable original aggregate.
`current_password_backing_stable_observed` is a current transaction observation.

## Recheck, rollback/close and disclosure

The same owned completion guard rechecks current source/normal ACLs and locked
source/backing state, rereads both pair rows, and compares the classification and
exact binding (if any) with the first result. Then source/backing/permissions are
rechecked before one rollback of the read transaction and one close. Post-close
visible source/actor/permissions are checked before returning metadata; no SQL,
borrowed connection or external lookup is used after closure.

Only then is `PENDING_CSR_BOUND_REVIEW_OBSERVATION` returned with
`local_read_transaction_closed=True`, `pair_observation` and observation flags.
It never returns `local_transaction_completed`, raw binding/source/backing digests,
stored metadata, config, key/CSR or ciphertext. All source/epoch/storage/remote/
activation/dispatch/renewal proof/authority flags remain false.

Classification stability for nonexact states is not identity of a different
conflicting/half artifact. Exact comparison always uses the retained original;
the exact stored declaration must remain identical. No classification authorizes
repair, replacement, new IDs, redelivery, retry, renewal, issuance or activation.

Cleanup ambiguity, post-close denial/source drift, reentry or interruption withholds
metadata. Only newly owned resources are cleaned; rollback/close are not retried
after an uncertain attempt. Existing interruption priority and comprehensive
single-popup/display-only Arabic failure are reused. English states/keys remain;
no new log, raw diagnostic or active credential/ambient transaction write occurs.

## Limits and next gate

These are present local observations, not proof of a prior commit's outcome,
permanent absence, capture authenticity, atomic permissions or an authoritative
credential epoch. An earlier transaction may still be in flight; a lock timeout
is unconfirmed. Missing-row/isolation/ABA, caches, trusted callback side effects,
out-of-band writers and post-close source/backing changes remain limitations.
Canonical hashes do not independently detect coherent record/hash tampering.
Restricted binding data, keys, trace locals, field/log/backup custody and SQL
account/tenant provisioning still require separate audit, not Python guardrails.

This closes the owned exact-original read-only pair-review link after initial
capture without fabricated historical lookup or automatic retry. Next review
protected prepared-draft intake and independent source/key/tenant/epoch provenance
before issuance/receipt/activation integration. Installed ERPNext/Frappe 15/16,
Desk/browser, SDK and authority acceptance remain unverified. Finish development
before the separately approved isolated fictional-Company rehearsal and later
adoption/cancellation or active-client decisions. No live/authority operation occurs.

## Offline evidence

Only the reviewed `pending_csr_bound_review` suite joins the fixed local manifest.
The existing owned temporary TCP-disabled private SQL suite adds native pair-state,
corruption/source/backing drift, classification recheck and cleanup ambiguity
cases, and extends four actual initial-save ambiguity cases with a fresh owned
review. All staging methods and commit are trapped during native review; the
external lookup is trapped in every pair-review fixture. Synthetic coverage
includes both owner/permission signatures, Password profiles, environment
declarations, cleanup/interruption/reentry, redaction and Arabic display.

The local-only guarded run passed **14,024 in 85.55 seconds**, adding 83 local
cases. Final guarded combined: **14,024 local + 2,006 private SQL = 16,030 passed
in 174.79 seconds**, across thirteen private suites, adding **115 cases**
(83 local + 32 native SQL). All nine Node VM scripts passed **1,444 cases**. No resource/
ordinary-ACL/crypto/transport assertion was waived. These tests do not establish
installed or remote acceptance.
