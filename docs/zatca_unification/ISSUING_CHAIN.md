# Explicit new-EGS chain and exact-artifact transaction

Increment 97 — 2026-10-25. OFFLINE development only: no installed schema,
Company field, active CSID/PIH/counter change, client-script edit, Bench/worker,
fictional Company on a working site, or authority API call. No UI reset or
"first invoice" checkbox is added. This is an uninstalled internal component,
not completion of runtime first-invoice or onboarding integration.

## Source decisions

- The [official XML standard v1.2, BR-KSA-26, page 54](https://www.zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/20230519_ZATCA_Electronic_Invoice_XML_Implementation_Standard_%20vF.pdf)
  supplies the initial PIH. `INITIAL_PREVIOUS_HASH` encodes the ASCII hexadecimal
  SHA-256 digest of the ASCII character `0` as Base64, matching the published
  literal. It is not an empty-string hash, literal zero, a random invoice-ID
  hash or the Base64 of the 32-byte binary zero-character digest.
- The [official detailed guideline, sections 5.5/6.5](https://www.zatca.gov.sa/en/e-invoicing/introduction/guidelines/documents/e-invoicing_detailed__guideline.pdf)
  prohibits a user counter-reset function and multiple concurrent sequences for
  one unit. Registering a genuinely new unit is not resetting its predecessor.
- [Developer-community new-software discussion](https://zatca1.discourse.group/t/new-software-icv-egs/7201),
  including the 2025-06-24 clarification, distinguishes new EGS/new PCSID from
  old-unit history: its first ICV is 1 and PIH uses the default, not another
  unit's last invoice. An old Company may therefore have prior invoices while
  its new registered unit legitimately starts a new independent series.
- Renewal remains separate: the [2023 discussion](https://zatca1.discourse.group/t/renewal-of-csid/658)
  says no reset, while the [2024 clarification](https://zatca1.discourse.group/t/invoice-counter-value-reset/659)
  says start from 1 after revocation/renewal. The official technical guideline
  describes renewal as revoking/replacing CSID but does not, in the reviewed
  passage, settle all local continuity mapping. Do not infer genesis/continuity
  from a changed certificate, cleaned Basic header or rotated password alone.
  `RENEWAL`, migration and restore origins are refused by this new-only contract.
- The [official technical guideline, FAQ pages 71/77/78](https://zatca.gov.sa/en/E-Invoicing/Introduction/Guidelines/Documents/E-invoicing-Detailed-Technical-Guideline.pdf)
  distinguishes generation order from upload order and includes rejected
  documents in the hash sequence. The new ledger records a generated original
  before any observed HTTP result. It does not wait for acceptance to move its
  head. This does NOT retrofit the legacy accepted-response PIH writers yet.

Community answers supplement the published specification, not universal proof
of onboarding/renewal policy. The code makes no HTTP calls to verify a registration.

## Model and transaction

`issuing_chain.py` defines an explicit `DeclaredChainRegistration` with separate
opaque chain/registration references, Company/seller/environment, public epoch
fingerprints and a retained-enrollment-evidence fingerprint. There are no tokens,
keys or credential text. These are declarations, not authenticated evidence;
diagnostics keep all provenance/persistence/signature/dispatch claims false.

`IssuingChainState` starts at last ICV **0** plus the published initial PIH.
`record_generated_candidate` binds the immutable candidate's source, environment
and epoch; requires exactly the next ICV and exact predecessor PIH; and derives
the next head from the candidate's declared digest. It never creates/replaces an
invoice UUID, signs or normalizes XML, looks up old invoices, observes HTTP, or
proves a signature/hash. The 64-digit ICV cap is an internal parser/storage bound,
not a regulatory maximum; exhaustion refuses issuance instead of resetting.

`MariaDBIssuingChainRepository` uses the caller's explicit transactional
connection and namespace. It reuses `MariaDBJournalRepository` to store the
exact original XML/context, rather than implementing a second artifact codec.

1. `create(registration)` inserts explicit genesis once. Exact redelivery returns
   the existing head, even after issuance; it never rewinds it. Registration-ID
   uniqueness and per-environment certificate uniqueness prevent accidental
   duplicate chains for the same declared enrollment/certificate in a namespace.
2. `record(expected_state, candidate)` locks the head, validates its stored tail,
   stages the exact immutable original and updates head/ICV with compare-and-swap
   inside the SAME caller transaction. A competing different first original
   cannot obtain the same position. Caller commit is still required.
3. Exact already-bound original redelivery returns the current head without
   advancing again, even after later documents. Changed bytes/context conflict.
   A staged artifact with no bound chain position is refused, never adopted or
   repaired automatically as genesis.
4. Any failed/ambiguous/interrupted operation poisons this handle. Caller must
   roll back the whole transaction and discard it. The repository never begins,
   commits, rolls back, closes connections, sends HTTP or retries. A lost commit
   acknowledgment requires fresh exact-original review, not regenerated identity.

Row rehydration checks schema/types, declared context, indexed fields, state
fingerprint and latest original binding. It is not tamper-proof storage or an
exhaustive cryptographic audit of all earlier artifacts. No native provider,
vault/encryption, authoritative tenant/connection/epoch or normal ACL facade is
installed. Do not export payload bytes as a UI/log projection.

## Small existing-path correction

Increment 99 adds [durable pre-build holds](DURABLE_PREPARATION.md) and makes the
previous internal entry points honor recorded pending/permanent source holds.
That opt-in owner commits the hold before a local builder and completes it with
the exact original/head later; no live generator or schema is installed.

Increment 98 adds the uninstalled [one-shot preparation coordinator](ISSUANCE_PREPARATION.md)
on top of this repository. It pins UUID/context/next ICV/PIH and refuses an
existing logical key before building, with explicit local custody/source guards.
It does not authenticate enrollment, install a durable pre-build hold, migrate
legacy workers or change the live issuance path.

Automatic onboarding's EMPTY-Company-PIH fallback now uses the shared published
seed instead of a hash of a random sample ID. It still creates no ERP invoice or
customer and writes no Company PIH. Nonempty configured values, timestamp-based
sample ICV and other sample construction stay unchanged. This is not full sample
chain consolidation or authority validation. Ordinary Sales/POS blank PIH still
requires review; it must not silently enter the new-registration path.

## Verification and adoption gates

Local cases cover published seed bytes, first/second candidates, Sales/POS,
standard/simplified/credit/debit/advance types, all API environments, missing
history, independent new units, epoch/source/predecessor drift, no migration or
renewal inference, frozen/bounded codecs, static errors and transaction ownership.
Sample cases exercise all six types with empty and configured saved PIH.

Owned-private InnoDB cases cover parent/head/original atomic visibility and
rollback; duplicate initialization; exact versus competing first originals under
READ COMMITTED and REPEATABLE READ; namespace/certificate binding; unbound partial
artifacts; lost commit acknowledgment; changed original conflicts; independent
units; header/tail corruption; autocommit refusal and owned-server crash recovery.
Synthetic 200/202/400/401/500 observations do not roll back the generated chain.
No test establishes authenticated enrollment, valid signatures, SDK acceptance,
installed ERPNext 15/16 or remote acceptance.

Increment 97 guarded verification: **14,399 local + 2,049 private SQL = 16,448 passed
in 177.33 seconds**, across fourteen owned-private SQL suites. The increment adds
174 cases; all nine Node VM scripts also passed **1,444 cases**. One initial
native assertion held an observer lock across a different connection's read;
the test now reuses the observer and releases its transaction explicitly. No
timeout/assertion was weakened, and no customer/site or authority I/O occurred.
Increment 98 preparation verification extends the combined result to **16,558
passing Python/SQL cases** and the same **1,444 Node VM cases**; see its linked
preparation notes for the exact scope and remaining custody/worker gates.
Increment 99 durable preparation extends the combined result to **16,650 passing
Python/SQL cases**, with the same **1,444 Node VM cases**. Its separate notes
explain committed pending holds, exact reconciliation and missing-original gates.

Before runtime adoption: authenticate the exact enrollment record and owned
site/namespace/connection; implement normal source/settings ACL and revision
guards; bind protected credential versions and artifact custody; coordinate
generation/UUID/ICV/PIH with worker/caller transaction ownership; exclude every
legacy independent writer; and explicitly map migration/renewal/restore history.
No locks may be held while calling an authority. Preserve the user's order:
finished development, separately approved isolated fictional-company rehearsal,
then adoption/cancellation and any gradual rollout. Authority sending is still
prohibited regardless of deployment/rehearsal approval.
