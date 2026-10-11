# Shared invoice issue-time contract — increment 30

## Delivered scope, not deployment or signature acceptance

`issue_timestamp.py` parses explicit date/clock fields without Frappe, a site,
database, network or current-clock dependency. A frozen UTC instant produces
QR Tag 3 and XML IssueDate/IssueTime at the same whole-second precision.
`qr_timestamp.py` preserves both legacy function names as thin ERP adapters.
Local timezone rules come from the existing pytz package, not a remote service.
No package/version upgrade or running-site timezone configuration is changed.

This is time normalization, not immutable full invoice/settings provenance,
signature/hash verification, legal amount/accounting acceptance or a completed
onboarding flow. The [no-working-environment/no-authority-send restriction](SAFETY_AND_REHEARSAL.md)
still applies. All adapter tests use synthetic documents and mocked persistence,
QR image rendering, keys and translations; no real tenant or authority is called.

## Supported fields and deliberate failure policy

- Accept exact `date` and `time` objects, ISO calendar-date text, bounded clock
  text, or a MariaDB-style `timedelta` from zero through less than one day.
  `timedelta(0)` is valid midnight, not a missing field. Durations outside the
  same day are rejected; never wrap them, infer today or invent midnight.
- Text permits one-digit hours (`9:05:42`), minute-only legacy clocks, optional
  seconds/microseconds, and explicit `Z` or `+/-HH:MM` offsets. Reject malformed
  offset minutes, compact/week dates, negative/24-hour clock values, extra
  precision and unsupported types before timezone/settings discovery.
- Naive fields require an explicit valid IANA timezone in the core. DST gaps
  and folds fail rather than silently choosing an offset. An already aware
  value or explicit offset determines the instant without a fallback lookup.
- Preserve microseconds in memory but TRUNCATE, not round, when serializing.
  UTC date rollover and four-digit low-year formatting are deterministic.
  QR value always equals `xml_date + 'T' + xml_time` for the same instant.
- Invalid field/timezone/DST errors are static, translated outside exception
  handlers and have no raw input/parser/provider exception context. New English
  keys have Arabic CSV translations; browser/full-site language tests remain gates.

## Adapter mapping and side-effect boundaries

| Path | Time source after this increment | What remains unchanged |
| --- | --- | --- |
| Ordinary Phase-1 Sales/POS QR | Shared adapter over document posting fields | Existing amount fields, attachment cleanup and hook persistence |
| Sales/POS XML metadata, including debug/compliance | SAME loaded invoice record; validate time BEFORE UUID persistence | Existing production UUID policy and non-production UUID isolation |
| Name-based `get_issue_time` / `get_issue_timestamp` wrappers | Shared adapter after their one legacy lookup | Public names/arguments and UTC string semantics |
| Phase-2 QR generation | One nonempty direct IssueDate/IssueTime pair from supplied XML | Tag 4/5 choices, signature/certificate extraction and XML signing |
| Six synthetic onboarding types | Explicit aware UTC clock or internal aware deterministic instant | Sample business data, temporary files, no customer/invoice creation |
| Initial advance Phase-1 QR | Shared adapter; no missing-time midnight default | All existing amount/FX/arithmetic and invoice selection rules |
| Advance Phase-2 printing | Existing early guard retains the stored authoritative QR | No rebuild or rewrite of accepted XML/QR, even with force |
| Phase-2 QR regeneration | Existing extraction of stored QR payload | No time recalculation, re-signing or authority request |

Sales/POS metadata no longer calls `get_doc` again merely to obtain issue time.
The timestamp is validated before XML metadata append/UUID persistence, so an
invalid clock cannot commit a newly assigned Sales UUID at this stage. This is
one loaded-record consistency, not cross-row transactional settings/child-table
or complete source-snapshot attestation. Existing valid legacy UTC serialization
is preserved; issued/accepted artifacts are not migrated or rewritten.

The synthetic builder previously used naive `datetime.utcnow()` and emitted
an IssueTime without an offset. QR's legacy formatter interpreted that value
as system-local time and could shift it AGAIN. The builder now uses
`datetime.now(timezone.utc)`, emits the shared `Z` time and derives its synthetic
ICV from that aware instant. Its optional private `issue_instant` argument accepts
an aware datetime only; it is not exposed as a new button/client clock override.

Phase-2 generation rejects duplicate, missing, blank or nested issue fields
instead of selecting the first or passing a placeholder. Explicit XML offsets
avoid system settings lookup and double conversion. Offsetless legacy XML still
uses the existing ERP adapter policy; this does NOT prove its timezone provenance.
The XML parser, digest/canonicalization/signature rules and amount validation
are not consolidated by these date/time checks.

## Settings/defaults and advance-payment gaps

The ERP adapter deliberately retains Frappe's `get_system_timezone()` behavior
for naive posting fields; it does not add a Company/device timezone or assume
all tenants use Riyadh. The inspected local Frappe 15 source returns
`get_system_settings('time_zone') or 'Asia/Kolkata'`. Therefore this adapter alone
does NOT prove that a timezone was explicitly configured. Capture a verified
timezone/settings epoch and review blank-setting behavior before future strict
selection/migration. Do not silently change running tenants or reinterpret
historical posting times during a credential/route change.

The initial advance Phase-1 Tag 3 now uses the shared conversion, but advance
amounts/GL/VAT and references remain unfinished. In particular,
`create_xml_final_part.py:get_time_string` and the settlement reference builder
still format posting times locally and can default invalid/missing values to
midnight. Audit their original issued-artifact/date-time/UUID binding before
consolidating them; do not rewrite historical references or claim full advance
compliance. The current Tag 4/5 formulas were characterized, not approved as
regulatory amount sources. SDK/golden comparison is still required.

## Verification and rehearsal hardening

119 core cases cover supported ERP types, single-digit hours, explicit offsets,
midnight/duration bounds, fractions, date rollover/overflow, DST rejection,
bounded inputs, static privacy and the frozen UTC contract.
93 adapter cases exercise real metadata/Phase-1/Phase-2/synthetic builders with
mocked side effects, six sample types, type 386 time extraction, unchanged legacy
amount formulas, Phase-2 advance protection, XML ambiguity, no second invoice
lookup, invalid time before UUID persistence, Arabic errors and aware UTC clocks.

Initial negative adapter cases exposed an unmocked framework translation path:
without an initialized translation cache, Frappe tried its logger fallback at a
missing worktree log path. No log was created and no tenant site was initialized.
The fixtures now mock translations explicitly, and the offline guard additionally
blocks `frappe.logger` BEFORE log discovery; one guard denial case covers it.
This is still an accidental-I/O guard, NOT an OS/hostile-code/global file sandbox.

Measured totals and guarded commands are in [STATUS.md](STATUS.md). No remote
Compliance/CSID, ZATCA SDK/golden signature, browser/print rendering, actual v16
boot, restored application acceptance, deployment or historical digest fix is
demonstrated. Next audit: advance reference/time bindings and verified settings
snapshots, followed by broader amount/cryptography/QR artifact unification gates.
