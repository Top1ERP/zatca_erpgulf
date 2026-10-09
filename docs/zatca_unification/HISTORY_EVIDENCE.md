# Opt-in stored response and counter observations — increment 10

Development only: no tenant inventory, counter allocation/seed, identity repair,
schema migration, deployment, worker restart, or remote request was executed.
The existing submission/response persistence and cryptographic paths are unchanged.

## Compatibility and scope

`inspect_saved_invoice_artifacts(doctype, invoice_name)` keeps increment 9's
attached-XML scope. Only explicit `include_history=True` adds stored response and
saved-unit counter observations. Non-boolean option values are rejected with an
Arabic-translated diagnostic; there is no new UI or whitelisted endpoint.

The extended scope is `saved_identity_attached_xml_response_and_counter`.
`history_complete`, `signature_verified`, `remote_acceptance_verified`, and
`replay_authorized` remain false. This is evidence for a later reconciliation
decision, not an authorization to retry or a complete issuance ledger.

## Stored response handling

`history_evidence.py` parses bounded UTF-8 stored text/bytes using a strict JSON
decoder. Duplicate keys (including nested duplicates), invalid/nonfinite or very
large numbers, malformed/deep JSON, multiple objects, and arbitrary trailing
text do not silently select the first JSON object. Known English/Arabic
`ZATCA Response:` display wrappers with whitespace/BR markup are supported;
unknown or ambiguous wrappers remain visible failures. Arbitrary HTML is neither
unescaped nor rendered. The stored response field is never normalized or saved.

The UTF-8 stored-text fingerprint is not a reconstruction of original HTTP wire
bytes. Neither a display status code nor the saved REPORTED/CLEARED field proves
endpoint, HTTP outcome, environment, taxpayer, or credential-version provenance.
Reports intentionally omit raw bodies, messages, certificate values, and auth.

| Observation | Diagnostic condition |
| --- | --- |
| `OBSERVED_REPORTED` | One REPORTED declaration plus explicit PASS/WARNING validation with a well-formed empty error list |
| `OBSERVED_CLEARED` | One CLEARED declaration plus the same explicit validation contract |
| `OBSERVED_REJECTED` | ERROR validation with a nonempty object error list and no accepted outcome declaration |
| `UNCONFIRMED` | Missing/invalid/incomplete/contradictory declarations or validation |

These names deliberately do not say verified acceptance. Saved-status mismatch,
missing required cleared XML, or malformed embedded XML remain reconciliation
issues. Compliance PASS/previous-completion bodies do not imply live acceptance.
Nullable optional XML is absent evidence; it is not automatically malformed.
Reporting without a returned XML does not manufacture a signed artifact.

Present `clearedInvoice`/`reportedInvoice` values are strictly Base64-decoded with
size limits and sent through the **same** immutable artifact inspector as local
attachments. Their invoice ID/UUID/ICV/seller and exact bytes are compared without
choosing a winner. An original and cleared XML may legitimately differ: a byte
conflict is provenance to resolve, not permission to delete either source.

## Counter handling

`counter_inventory.py` uses only saved Company/issuing-unit identity and the
characterized legacy key builder. It never reads current auth to derive a new
fingerprint and never calls allocation, creation, seeding, or mutation helpers.
It does not trust today's Company/device counter pointer for an older invoice.

The counter's legacy `environment=Production` column denotes document purpose.
Company API selection Sandbox/Simulation/Production is reported separately;
it is not substituted into the counter key or interpreted as a proven historical
API environment. Queries are scoped to the saved Company/unit/Production tuple.
Two matching rows suffice to flag ambiguity; the expected historical name is
also checked to expose key collisions with a different tuple. No largest-value
or newest/current-pointer rule resolves that ambiguity.

Schema absence, missing unit/counter, read permission denial, and disappearing
records remain report issues. Counter values are projected only after read
permission. Company/unit/purpose/key/active state, position, and last-invoice
metadata are checked. A position below the saved ICV is flagged; a greater
position is not reduced. At equal position, invoice name **and DocType** must
agree with the tail, distinguishing equal Sales/POS names. Missing saved ICV is
not inferred from the counter.

## Verification and remaining work

129 new local tests cover pure response/counter rules and the actual opt-in bridge
with mocked records and temporary XML. They exercise duplicate/ambiguous JSON,
size/encoding/number limits, nullable XML, validation/status conflicts, known
English/Arabic wrappers, source/file byte comparisons, Sales/POS parity, counter
purpose versus API selection, key/tuple collisions, inactive/regressed counters,
tail metadata, permissions, schema absence, and no-write/no-credential paths.
The selected suite passes 1,522 cases in the existing v15/Python 3.10 environment.

There is no actual site/SQL/SDK/HTTP or ERPNext 16 integration result. Inventory
still excludes loose generated files, success/event logs, full historical counter
enumeration/mapping, credential epochs, and chain-wide PIH/signature verification.
The legacy counter key can still collide; this step observes, not repairs it.
Queries and records are not an atomic concurrent-worker snapshot. Live response
normalization may already have discarded historical display evidence; the reader
cannot reconstruct information no longer present in the saved field.

Extend/rehearse that inventory on isolated restored data, then implement durable
issuance/version and exact-byte replay with explicit migration/transaction gates.
Do not connect diagnostic observations directly to submission success or automatic
UUID/counter repair.
