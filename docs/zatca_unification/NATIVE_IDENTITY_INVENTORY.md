# Saved owner identity inventory

Workstream2 prerequisite, implemented in the isolated development source only.
This is not chain activation, a complete legacy-history review or authority
acceptance. FINAL_READY remains inactive.

## Adopted behavior

Before creating an initial native key/CSR, `native_onboarding.prepare_new_unit`
now calls `require_distinct_new_declaration`. It inventories saved Company and
ZATCA Multiple Setting rows across the selected site. Another owner's matching
environment/VAT/full-CSR-serial claim, backed by material or a local history
pointer, stops preparation before key generation, owner writes or intent commit.
Certificate and authorization-token claims work without a saved CSR config.
An invalid alias cannot conceal an independently valid certificate/claim.

An unused shared configuration template is visible but has no key/history yet.
It does not by itself block preparation. The existing unique native declared-EGS
reservation arbitrates first use; a later owner cannot create another initial
intent for the already reserved identity. Neither a new key nor a new token is
treated as proof of a new EGS. Existing owned CSR recovery does not run another
initial-key inventory or replace the key. Ordinary invoice generation, Phase1
QR, legacy/unselected CSR operation and financial calculations are unchanged.

## Transaction and permissions

The internal inventory requires an already-owned clean transaction. It checks
MariaDB's actual session isolation (REPEATABLE-READ or SERIALIZABLE) and requires
both physical owner tables to be InnoDB. Each fixed PRIMARY range is exhausted
under `LOCK IN SHARE MODE NOWAIT`; overflow above1024 owners per table is review,
not a partial result. Locks cover existing rows and insertion/rename gaps until
the caller commits or rolls back. No HTTP occurs while holding these locks.

Every saved row must pass the actor's ordinary READ ACL, using the inspected
Frappe15/16 quiet permission signatures. Inaccessible or missing rows cannot be
silently omitted. The locking SELECT's current scalar identity fields must equal
the saved ORM projection: an older consistent-read snapshot cannot hide a copied
key or changed link. Site/actor/physical transaction ownership is rechecked during
and after discovery. The actual initial CSR writer retains its existing selected
owner READ+WRITE, Company READ and System Manager requirements.

## Evidence and limits

The immutable, non-queue inventory contains owner references, public-key and
declared-unit fingerprints, routing/delegation observations, unparsed field names
and a material/history-presence flag. Its v2 observation also contains the exact
legacy logical unit hash and saved counter reference for known-consumer discovery.
The old token/name hash is not a stable native EGS identity. No raw key, certificate, authorization or
CSR configuration is returned. Material has a bounded per-owner byte budget.
The digest describes identity observations; it is not a saved-material epoch,
private credential digest, complete-history proof or activation approval.

Devices use their saved linked Company's environment. Unknown/missing routing
checks claims in all three environment namespaces conservatively, without a
Production default. A device's Use Company Certificate and Keys flag records
delegation separately; it does not erase independently copied material. Malformed
material remains explicitly visible by field name. A parseable public key need
not contain a usable unit claim. Thus no match cannot authorize genesis.

Still required before activation/cutover: the full legacy counter/source/XML and
consumer inventory, evidence of drained old dispatchers, authenticated activation
evidence and atomic transition. This service neither retires counters nor changes
PIH/ICV, imports historical XML, sends an onboarding request or activates a chain.
Unknown external software/fleets cannot be excluded by a local owner-table scan.

The actual inactive legacy review now uses this owner inventory to discover
known copied/delegated/declared-unit consumers and contradictory saved counters:
[NATIVE_LEGACY_CONSUMERS.md](NATIVE_LEGACY_CONSUMERS.md). It still cannot turn an
empty known match into complete historical coverage, drain or activation evidence.

## Offline qualification

The private fixtures exercise both Company/device initial writers, legacy key,
PIH/counter/chain collisions, ordinary ACL refusal, independent-unit preservation,
concurrent key-copy/insert-before/insert-after/rename and engine-DDL blocking, release on rollback,
READ-COMMITTED refusal and an intentionally stale ORM frame. The existing initial
CSR/enrollment/legacy-review/storage suites run alongside them. All SQL belongs
to temporary TCP-disabled fixture servers; all authority clients remain mocked.
These are framework doubles, not installed ERP15/16 or a live Company rehearsal.

Final selection/log counts are recorded in STATUS.md. Original financial
comparison remains240 cases:91 identical /117 review /32 blocked, unchanged.
