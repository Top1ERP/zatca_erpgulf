# Known legacy consumer and counter inventory

Workstream2, adopted by `review_legacy_registration` after exact original/
counter/source/certificate verification. It strengthens an inactive candidate;
it does not freeze an issuer, activate a chain, merge counters or contact ZATCA.

## Owner relations and legacy aliases

The saved owner inventory now also observes each owner's current legacy logical
counter alias and saved counter reference. Its in-memory digest uses
`zatca-owner-inventory/v2`. No earlier inventory was a persisted activation proof;
original artifact/registration/onboarding envelopes and cipher domains are
unchanged. Raw private keys, certificates, tokens and CSR configuration are not
returned or logged by the inventory.

The logical alias deliberately matches the existing old Production-purpose
allocator: Company uses its production authorization or saved name; a setting
uses its own Final authorization, Compliance authorization or saved name, even
when signing delegates to Company. Exact saved whitespace/encoding is retained
in the old hash. This token/name hash is a legacy counter reference, not the
stable native EGS identity or proof that a counter was used.

`native_legacy_consumers` starts from the verified signing owner/key. It follows
shared public keys, shared declared environment/VAT/full-serial identities and
explicit Company-key delegation links transitively. Each identity bucket is
expanded once. A matching taxpayer alone does not join independent units. A
device with its own credentials is not joined merely because it links to the
same Company. Missing links in the reached group require review.

These are possible consumer relations, not proof that every unused legacy alias
represents the same physical EGS. Conflicting/stale fields can conservatively
connect additional rows. They cannot conceal a known copy or justify silently
merging its counter. Malformed material remains visible in the owner inventory;
unparsed/retired identities still require full historical review before cutover.

## Counter contradictions

The full saved counter catalog is read under an exhausted PRIMARY shared NOWAIT
range, bounded to4096 rows. Overflow, inaccessible rows, changed ORM projections,
missing references or nontransactional storage hold instead of truncating the
result. Existing actor/site/physical transaction and InnoDB/isolation checks
remain. Every counter, including an unrelated candidate, requires ordinary READ;
the service cannot claim a complete catalog while omitting an unreadable row.

Matched rows include the already-verified source unit/counter, current logical
aliases of possible consumers and their saved counter references. A stale token
alias can therefore remain attributable through its saved pointer. The known
Production-purpose set must contain exactly the reviewed anchor's counter.
Another matching Production counter holds even when inactive or at zero. No
maximum seed, zero-use inference, automatic pointer repair or historical
renumbering occurs. Compliance/Debug rows are reported separately; a saved owner
pointer to such a counter is a configuration contradiction. The legacy purpose
field is not the API gateway environment.

Other historical counters remain explicitly unattributed. Their existence does
not merge them into this owner group; their absence from the known group does
not prove no historical issuer/token relation. The non-queue result is a current
negative inventory, not a stored credential epoch or activation approval. Exact
review recovery reruns all checks; future activation must revalidate/fence under
its own cutover transaction and prove old-worker drain separately.

## Current issuer observations

Before signing-material admission, the review now compares every captured
credential/routing record with a current locking ORM read, normal READ ACL,
field-presence checks and the existing typed observation codec. This includes
a delegated device's link/flag, actual credential owner and routing Company.
The selected owner still requires WRITE through the existing admission.

An earlier ordinary invoice SELECT may create an older REPEATABLE-READ view.
Ordinary scope drift reads alone do not upgrade that view. Thus a current token,
environment or delegate flag cannot be substituted underneath a stale captured
issuer projection, even when the public signing key is unchanged. No ordinary
invoice generator, QR/money calculation or Source write was changed.

## Qualification and remaining gates

Private cases exercise actual inactive review, three owner-selection policies,
Sales/POS and Standard/Simplified anchors, copied keys, fresh keys with the same
declared serial, explicit delegates, independent same-taxpayer units, retired
counter pointers, test-purpose counters, unreadable rows, inactive/zero counters,
current issuer/owner/counter drift and insert/update locks until rollback. They
use fixture-owned TCP-disabled temporary SQL, explicit framework doubles and
mocked authority clients. The old shared module key fixture would itself create
real cross-case copy/counter conflicts; each independent case now has fresh test
keys, with no financial reference changes. Credential mutation tests now update
their actual fixture SQL rows rather than an in-memory prototype only.

Catalog scans/locks are administrative review work. Their index/maintenance and
full-site ACL requirements need separately authorized installed ERP15/16
acceptance. No installed schema/index, live site, service restart, real fictional
Company rehearsal or authority API operation was performed. Full old XML/PIH/
rotated-identity and external-consumer history, durable cutover/drain, atomic
activation, retry/correction/lifecycle adoption and whole runtime qualification
remain open. Counts and exact log selections are in STATUS.md.
