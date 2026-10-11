# Original advance reference observations — increment 31

## Scope and current defects

This increment is offline development only. It adds a read-only metadata contract
and synthetic tests, not a runtime replacement or an accounting migration.

The local audit found three reference assembly branches in
`create_xml_final_part.py`:

| Branch | Source today | Unresolved issue |
| --- | --- | --- |
| `_append_direct_advance_reference_lines`, shared by item builders | Current Sales Invoice posting fields; child-row date fallback; optional current UUID | No original-issued XML binding. Valid zero `timedelta` is rejected as missing. |
| `item_data_advance_invoice` legacy `custom_advances_copy` branch | First copied legacy row's date/time/UUID | `get_time_string` catches every exception and invents midnight. |
| `item_data_with_template_advance_invoice` legacy branch | First copied legacy row's date/time/UUID | Missing/falsy time becomes midnight; separate parsing logic. |

`get_time_string` also wraps a day-plus duration via the installed Frappe 15
`get_time` helper and drops explicit timezone offsets during `strftime`. Tests
characterize these defects; they do NOT assert that this is desired behavior.
Both legacy branches depend on `claudion4saudi`. This app reads copied rows but
does not establish the external writer's immutable source/timezone provenance.
The current direct allocation validation reads accepted/submitted/marked source
status and refreshes `advance_invoice_date` from posting fields; that alone does
not bind a reference to original artifact bytes. No customer data was inspected.

## New local contract

`advance_reference.inspect_advance_reference` takes supplied XML **bytes** and
explicit expected invoice ID, UUID and seller VAT ID. It observes:

- Exactly one direct, namespace-qualified invoice ID, UUID, IssueDate, IssueTime
  and InvoiceTypeCode. The latter must be `386`.
- Exactly one supplier, Party, VAT tax scheme and seller ID, matching the
  explicit expected seller. The expected VAT ID is a 15-ASCII-digit projection;
  this is not a registry/ownership check. UUID equality is case-insensitive, but
  the original text is retained. ID/seller matching is exact.
- A bounded conservative calendar/clock subset: `YYYY-MM-DD`, two-digit
  `HH:MM:SS`, optional 1..6 fractional digits, optional `Z` or offset up to
  `+/-14:00`. Invalid dates, missing values, unsupported `24:00:00` or larger
  fractional precision fail closed. These adapter limits are not a complete
  statement of XSD's lexical language.
- An immutable observation with **original date/time text unchanged**, exact-byte
  SHA256 fingerprint and byte length. Fingerprint is NOT ZATCA invoice hashing.

It reuses the bounded diagnostic XML parser: maximum 5 MiB, no DTD/entities,
no external-resource resolution, no recovery or huge-tree option. UTF-8 and
UTF-16 declarations remain bytes. Errors carry static codes, with parser
exception context removed; the observation's repr omits identities and clock.
It does not serialize or rewrite XML, load files, look up ERP/site settings,
allocate UUID/ICV, read keys, change status or make requests.

For example, original `2026-09-27` / `00:05:42+03:00` stays that exact pair; it
does not become the prior UTC calendar day. Offsetless original XML remains
offsetless, not localized under today's Company/system timezone. The new-issue
normalization in increment 30 serves a DIFFERENT purpose. Neither contract
permits rewriting a previously issued artifact.

## Trust boundaries and adoption gates

Caller-provided expected identities and XML are declarations, **not trusted
provenance**. Even unsigned, fabricated metadata can satisfy this local check.
An observation is not an acceptance capability. No signature, invoice digest,
certificate, QR, XSD, invoice subtype, totals, buyer, currency, allocation,
remote acceptance or legal/SDK rule validation is performed here.

Before any of the three builders adopts this contract:

1. Supply an audited, permissioned Company/device/environment-bound selector for
   immutable original-issued bytes and saved source identity, distinguishing
   clearance-returned, reporting-issued, rejected, debug and temporary artifacts.
   Resolve attachment/version ambiguity; never pick the newest arbitrary file.
2. Bind acceptance and cryptographic evidence to the selected bytes and saved
   identity; retain original UUID/date/time without current-setting conversion.
   Reconcile existing copied rows without silently writing new values.
3. Define an explicit missing-original policy, including Phase-1 advances whose
   only issuance artifact may be a stored QR, and retired legacy advance records.
   No midnight/current-date/current-UUID/default-timezone repair is authorized.
4. Golden-test both item-template branches and partial/multiple/return allocation,
   quantities, tax categories, FX/rounding, prepaid totals and GL/VAT balances.
   These accounting and SDK gates remain unfinished.
5. Test installed ERPNext 15/16 on separately approved isolated fictional benches
   after completed development. Do not deploy this scaffold or run authority API
   tests on a customer bench. The authority-send ban remains unchanged.

The new primitive is intentionally **not called by runtime assembly** yet. Thus
the characterized legacy issues remain until trusted-source adoption is complete.
No schema/button/translation or runtime dependency change is introduced; static
internal codes are not new user-facing untranslated messages.

Increment 32 adds [exact archived-attempt source choice](ADVANCE_SOURCE_SELECTION.md)
on top of this primitive. It is still an observation; permissioned committed-source
acquisition, authenticated acceptance and legacy/Phase-1 reconciliation remain gates.
