# Frozen party fields in native print rendering

Workstream2 source development,2026-11-21. Source and verification remain offline
in the isolated worktree. No live site/schema/source/service, actual invoice or
authority API was changed or invoked. Installed ERP15/16, actual dummy-company,
browser/PDF/scanning and authentic SDK acceptance retain their separate gates.

## Saved XML is the source for these presentation fields

Before this package, native printing selected the retained QR/accepted status but
left party display data to the render document and current master/title lookups.
New print-only artifact selection projects seller/buyer legal names, alternative
names, identification schemes/values, VAT registration and postal address from
the exact saved original. Standard cleared XML must project the same values as
that original; matching UUID/hash metadata alone cannot waive party drift here.

The parser uses bounded bytes, the existing no-DTD/no-external-resource XML reader
and fixed namespace-aware paths. It refuses duplicate/ambiguous parties, legal/
VAT/address nodes, nested text and excessive list/text values. Seller identity/
postal structure is required. An optional absent buyer remains empty; no current
Customer/Company/Address/Country lookup invents missing values. The projection
preserves literal names/IDs/ISO country codes and performs no money, timezone,
country-name or signature calculation. This is not a replacement XSD/SDK validator.

The existing Sales/POS before_print hook verifies current saved identity/render
data, then changes only its transient render copy:

| Render field | Retained XML value |
| --- | --- |
| company_name | Seller legal registration name |
| company_tax_id | Seller VAT registration |
| company_address_display | Escaped seller postal components |
| customer_name | Buyer legal registration name, or empty |
| tax_id | Buyer VAT registration, or empty |
| address_display | Escaped buyer postal components, or empty |

ERP company/customer link IDs stay unchanged. Their transient __link_titles entries
use the issued legal names; other links are retained. The structured immutable
doc.zatca_issued_parties also exposes alternative names, identification scheme/
value tuples and raw address components for compatible templates. Names/IDs are
plain data; custom HTML templates must escape text normally. The generated address
HTML escapes every component and supplies only fixed br separators. No XML is
serialized, resigned, repaired or rewritten.

**Deliberate display changes for review:** XML names can differ from ERP display
aliases; address order follows the retained components and country remains its
ISO code. Buyer VAT/address absent in the saved XML is displayed empty rather than
copied from current masters. Other identifiers, including foreign/TIN schemes,
remain separate in the structured projection and are not substituted for VAT.
No customer/invoice record, ERP posting date, amount, ICV or PIH is edited.

## Strict same-object rendering without a fiscal exception

A private nonserializable stamp binds these presentation overrides to the exact
render object, site, actor and issuance. Printing that same object again first
verifies the projection/titles/stamp, reloads canonical custody and compares its
other fields to the current saved observation. Only our known presentation fields
are observed through their original pre-render values; app-added presentation
attributes and reserved link-title metadata are excluded from that local adapter.
The persisted fiscal/publication profiles are unchanged.

The adapter preserves native as_dict/raw-get observation and the earlier minimal
test adapter separately. It never omits arbitrary unknown fiscal fields or changes
numeric/date types. Changed money, unknown fields, projected names, frozen data,
actor, titles or copied/JSON-forged stamps remain blocked. A new issuance cannot
reuse an old object's stamp. There is no process-wide cache or Frappe monkeypatch.
Missing/malformed/conflicting parties stop native print through the same single
translated review boundary; an old QR/File is not a fallback. QR-only previews and
diagnostic downloads do not acquire this print-party grant.

## Actual adoption and remaining limits

This updates the existing before_print path rather than adding another print
store or forcing a new template. The inspected local Frappe15 printview establishes
link titles before before_print and excludes arbitrary presentation properties
from native as_dict; the hook freezes the two party titles afterward. Ordinary
legacy/Phase1 printing and unsigned draft behavior retain their previous selection.
Historical native reads still require saved Source/Company READ, not WRITE or a
currently usable signing key/rollout setting.

This is not complete print-master provenance: Letter Head content/scripts,
arbitrary direct master/address lookups in custom templates, other dynamic link
titles, external engines, later overriding hooks, saved File/link/sidebar consumers
remain open. Named saved native sources now also receive an unissued print hold:
[NATIVE_PRINT_ADMISSION.md](NATIVE_PRINT_ADMISSION.md). Compatible templates should
consume these frozen fields/projection rather than reload current party masters.
There is no perpetual render lease after the hook; complete installed/canonical
HTML/PDF and mixed-runtime qualification is still required before release.

## Verification

Local tests exercise literal/absent data, duplicate/nested identities, escaping,
UTF8/UTF16, rejected XML/XXE, actual hook field/link overrides, same-object reprint,
actor/name/title/stamp/money tampering and changed cleared-party rejection.
Private SQL covers all six native entries, Company/device/delegate owners,
Standard303, key/rollout loss and changed current Company values. It verifies
unchanged source/financial values, counter/head, commits, write count, build/HTTP
count and fresh saved records, including same-object native reprint. Source-print
evidence fixtures gained only missing legal/address metadata; no monetary/golden
reference was changed. ERP/financial/signing/HTTP inputs remain synthetic.
Counts/logs are in STATUS.md; original240 comparison remains91/117/32. This package
does not close workstream2 or authorize installed/dummy-company/authority actions.
