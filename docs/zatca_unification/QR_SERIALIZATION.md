# Shared QR serialization — increment198

Development only, with no live installation or authority requests. This bundle
continues [signing consolidation](SIGNING_PIPELINE.md) by sharing serialization
between ordinary Phase-1 Sales/POS QR and the eligible initial-advance print hook.
It does not unify their amount, seller-selection or eligibility policies.

## Caller and policy map

| Caller | Values prepared by caller | Shared serializer | Existing final boundary |
| --- | --- | --- | --- |
| `create_qr.create_qr_code` for Sales/POS | Existing Arabic-name selection, VAT lookup and issue timestamp; `str(base_grand_total)` and `str(total_taxes_and_charges)` | `qr_encoding.encode_phase1_qr` | Existing image/File creation and caller-owned QR/status staging |
| `advance_deduction.ensure_final_sales_invoice_qr_for_print` | Existing name fallback, timestamp, deducted taxable/discount/SAR/base calculations and two-decimal amount strings | `qr_encoding.encode_phase1_qr` | Existing initial-advance image/File/QR-link update |
| Shared signing sequence and synthetic Company onboarding | Existing selected Phase-2 tags and legacy text/binary tag encoder | `qr_encoding.encode_qr_payload` | Existing QR embedding, formatting and artifact policy |

The Phase-2 `encode_qr_payload` implementation moved unchanged from
`signed_xml_pipeline`; its former import path remains an alias to the same
function. Its caller-supplied tag encoder and producer order remain intact.
Phase-1's one-byte text lengths do not replace Phase-2's existing long-string or
binary tag behavior. The pure module imports only `base64`; it reads no Company,
credential, database, clock, file or image and performs no signing or sending.

## Wire behavior and error presentation

`encode_phase1_qr` serializes exactly five caller-formatted UTF-8 strings in tag
order 1–5. It preserves whitespace, signs, decimal scale and empty strings. It
does not coerce numbers, calculate amounts or validate taxpayer/date semantics.
The adapters retain their own required-field and formatting rules.

Each field must fit the existing single-byte length representation. Strings over
255 characters are refused before allocating an encoded copy. Remaining strings
are encoded and checked against 255 **bytes**, allowing multibyte boundaries to
be checked correctly. No truncation, modulo-length wrapping, new normalization
or invented replacement characters is used. Total payload size is not confused
with a per-field bound.

The ordinary generator previously used character count for VAT text while
writing UTF-8 bytes. For non-ASCII text that produced an inconsistent tag length.
The shared serializer fixes that wire error. An Arabic-digit VAT test demonstrates
the byte length; this does not declare that Tax ID valid or replace taxpayer
validation. For the ordinary ASCII VAT domain, previous QR bytes are preserved.

Oversized, non-text or invalid UTF-8 values have the English internal code
`phase1_qr_encoding` and a numeric tag only. Rejected content and the original
Unicode exception are not included in the error message/context. The two adapters
display one static translated message with that tag before image/File writes.
The Arabic catalog includes this message. No new logger or popup cascade is
introduced; surrounding handlers retain their existing logging/display policy.
Required-field/time preparation precedes the shared encoding call; this bundle
does not promise the former error priority when several inputs are invalid.

## Accounting and artifact boundaries

Existing ordinary and advance amount formulas are deliberately distinct. In
particular, ordinary QR still uses base grand total with the existing tax-total
field; the advance hook still selects its existing SAR/base formulas and formats
two decimals. Preserving these values is **not** fiscal approval of FX, discount,
return or prepayment semantics. GL/VAT/XML/QR reconciliation remains a release
gate; no monetary correction is silently bundled with serialization cleanup.

Seller alias/fallback differences also remain: ordinary requires its configured
Arabic name, while the advance hook retains its existing fallback. Effective
settings/alias review remains in [ENGINEERING_QUALITY.md](ENGINEERING_QUALITY.md).

Existing-link preservation, unresolved-reference review, Phase-2 early exits,
schema/submission/initial-advance gates, filenames, File options, notifications
and transaction ownership are unchanged. There is no advance lookup, relink,
settlement, UUID/ICV allocation, endpoint or credential change. No stored artifact
is rewritten or repaired. SQL rollback tests use synthetic tables and mocked
image/File operations; they do not establish physical-file rollback behavior.

## Evidence

- **133 new local cases** cover known wire bytes; every tag's empty/ASCII/Arabic/
  emoji boundaries; invalid types/UTF-8; no eager encoding of oversized text;
  per-field versus whole-payload limits; exact strings/order; 24 real mocked
  adapter parity combinations across Sales/POS/advance, SAR/foreign, discount
  and sign; 36 one-message English/Arabic failure combinations; non-ASCII VAT
  serialization; compatibility alias identity and the pure dependency boundary.
- **12 new private SQL cases** verify that encoding rejection leaves unrelated
  pending work visible only to the owning transaction and preserves the caller's
  eventual commit/rollback choice, with no new File or QR metadata.
- Final reviewed selection: **4,815 local + 52 private SQL = 4,867 distinct
  passing cases**, including those 145 new cases. The 32 local suites cover
  previous real signing/QR parity, all six sample types, issuer modes, Debug/
  Compliance, routing/settings, scheduling, Phase-1/Phase-2 artifacts, advance
  preservation, recovery, messages and guard behavior. The private selection
  additionally covers ordinary QR commit/rollback, propagated File/metadata
  failure, scoped reference preservation and Phase-2 artifact preservation.
- The fixed manifest is 168 local/57 private suites. Only the reviewed selection
  ran; private SQL used one NEW fixture-owned TCP-disabled MariaDB per run and
  never a tenant database. Final logs are
  `/tmp/zatca-qr-wire-regression-final-198.log` and
  `/tmp/zatca-qr-wire-private-final-198.log`. Initial overlapping runs are not
  added to the final count.
- An AST comparison against `7f378fad597a0e9f054559ada032392cfd14c8df` normalized
  only the replaced encoding spans/imports in both adapters. Other module nodes,
  including amount assignments, gates, public signatures and writers, matched.
  The moved Phase-2 encoder function's AST matched exactly, and the rest of its
  former module matched after removing only that definition/import. Review tool
  `/tmp/zatca_qr_structure_198.py` produced `/tmp/zatca-qr-structure-198.json`.

No installed ERPNext/Frappe 15/16 lifecycle, complete invoice accounting, SDK,
optical QR decoding or authority acceptance is established by this selection.
No runtime performance percentage is claimed. Full development and separate
approval still precede isolated fictional-client rehearsal and any later rollout.
