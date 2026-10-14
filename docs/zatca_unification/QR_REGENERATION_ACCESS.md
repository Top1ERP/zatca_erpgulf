# Saved-row access for QR recovery endpoints — increment 38

## Development-only boundary

`qr_regeneration.get_qr_regeneration_state` and `regenerate_qr` formerly loaded
Sales Invoice without an explicit saved-row ACL check. File metadata came from
unbounded `get_all`; recovery could read XML content or save a File with ignored
permissions without checking that saved File's access. Global URL existence
could also influence eligibility without same-invoice ownership.

This increment adds a bounded access boundary, NOT a complete repair service:

- A non-Guest actor and exact nonempty string invoice name are required before
  any saved-row load. Names/users are bounded to 140 characters, with no leading/
  trailing whitespace or control characters. Request documents/filter objects
  cannot serve as the saved source.
- Both endpoints load the exact Sales Invoice and saved Company through
  `get_doc`, not a Company cache used as an authorization subject. Preview needs
  read permission on both; mutation additionally needs Invoice write permission
  before attachment lookup. The mutation's preview reuses that authorized context
  instead of loading a second invoice revision.
- Direct `has_permission` calls use [the existing signature adapter](../../zatca_erpgulf/zatca_erpgulf/permission_compat.py)
  with quiet v15/v16 keyword selection and literal-True results. No Document
  `check_permission`/`ignore_permissions` shortcut, role-name shortcut, keyword
  retry or permission-cache mutation is introduced.
- File metadata is scoped by both owner Doctype and invoice name, limited to
  129 observations with at most 128 accepted. Every projected saved File must
  pass read permission and exact owner/projection comparison before artifact
  use or physical content reads. Unreadable, malformed, mismatched or over-limit
  observations stop the operation; they are not silently filtered so a different
  candidate can win. This can also block a recovery when an unrelated attachment
  is unreadable; no automatic fallback is intended.
- Existing-file re-linking additionally checks saved File write permission,
  then reloads/rechecks File read/write and owner/URL before its save. Global
  URL-existence reuse is removed; a preview's linked URL observation must match
  an authorized same-invoice File row.
- Actor identity is checked across row/ACL boundaries, before return and before
  the remaining explicit commits. Permission denial is outside the legacy XML
  parser fallback; parser failure cannot swallow an actor-change denial.
- Mutation is registered for POST only. The existing `frappe.call` uses POST;
  no guest access is enabled. This is registration evidence, not a browser/
  HTTP/CSRF integration acceptance test.

Missing/mismatched rows, ACL faults, unsupported engine signatures and denied
permissions emit one static translated PermissionError. Internal loader/engine
exceptions are not chained into that error. This does not prove redaction of
every third-party hook log or the entire installed HTTP response envelope.

## Important unchanged risks — do not adopt yet

This section describes the increment 38 baseline. Increment 39 separately
[removes speculative repair/content IO/commits](QR_RECOVERY_PRESERVATION.md)
and exposes preservation/review only until a verified source provider exists.
Its current endpoint no longer re-links files or needs File write permission.

Authorization is NOT provenance. Filename hints, creation order, saved acceptance
labels and current Company phase do not establish the original artifact/epoch,
signature validity or authority acceptance. The legacy newest/first QR/XML
selection, implicit re-linking, possible Debug XML use and unbounded content
read remain. An authorized operation can still choose the wrong artifact or
replace an existing QR. The ordinary/advance preservation policies do NOT yet
govern this button's selection branches.

The legacy explicit commits, Phase-1 link clearing/rebuild and Phase-2 image
attachment path remain, as does the truthiness-based time-presence check. A
midnight represented as a zero duration still needs the shared time contract
in the subsequent selection/generation change. Do not interpret this access
increment as approving those behaviors.

The generated-File branch still calls legacy `save_file` before reloading and
checking that resulting File for re-linking. Parent Invoice write permission is
checked first, but no new File-create ACL policy or proven physical rollback
was added. Failure can leave staged work; callers/framework must handle rollback.
The existing `ignore_permissions=True` File save is now preceded by direct
saved File read/write checks; it is not removed in this increment.

No serializable source/Company/settings/permission snapshot or unique artifact
reservation is claimed. ACL/source changes between observations remain a race;
actor checks alone do not lock permission tables or source epochs. Physical File
lifecycle/deduplication and installed ERPNext 15/16 behavior remain gates.

Next: replace legacy selection with explicit artifact provenance/preservation/
review decisions and remove helper-owned commits under caller-owned transactions.
Never substitute a guessed QR/XML or an authority request for missing evidence.

## Offline evidence

179 new local cases execute the actual endpoint bodies with synthetic saved rows,
signature-shaped v15/v16 ACL fakes and mocked ERP/image/File methods. The normal
typing decorator is unwrapped in unit tests so no Frappe site/request is booted;
POST/guest registration is checked separately against the imported v15 registry.
These are not installed-v16 or complete HTTP authorization tests.

Cases cover Guest/malformed input, source/Company/File denial and identity drift,
truthy non-True permissions, private loader/engine exceptions, unsupported
signatures, bounded/complete File projections, File write revocation, actor drift,
Arabic and no global URL fallback. The XML-read test uses only `BytesIO` and a
mocked parser; no physical file or real invoice XML is opened. One authorized
re-link case explicitly characterizes the remaining commit; all ERP/File writes
in that case are mocks, not an approved transaction policy.

No private SQL suite is added; the existing eleven guarded synthetic SQL suites
are regression checks, not proof of this new endpoint's installed SQL lifecycle.
The final guarded run passed **5,063 local + 200 private SQL = 5,263 cases**
in **47.83 seconds**. Initial unit runs stopped the 172 then-selected new cases at
the request-local typing decorator (`flags` unavailable); the unit fixture now
unwraps that decorator without initializing a site. The subsequent 172-case
local addition passed, followed by seven more cases and the full guarded run.
No customer site, worker, schema, credential or authority API is touched. Finish
development before separately approved isolated fictional-client rehearsal and
the user's whole-change adoption/cancellation decision.
