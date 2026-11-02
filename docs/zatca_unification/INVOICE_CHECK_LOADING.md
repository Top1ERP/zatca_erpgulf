# Saved Check loading and native NULL evidence — increment137, 2026-11-02

## Corrected stage assumption

Ordinary invoice loading and explicit numeric fixing are different operations.
The inspected15 and pinned16 regular document loaders retain returned numeric
scalars. Singleton loading calls numeric fixing; an explicit later numeric fix
also converts present NULL Check values to int0 and non-NULL Currency values to
float. Testing the numeric-fix helper alone does not establish ordinary saved-
invoice getter behavior. No numeric fix is introduced into product acquisition.

The earlier saved-control inspection required int0 for a present SQL NULL Check,
so an ordinary None getter could be rejected despite valid native evidence.
Accept that saved view only with native NULL proof, preserving both the observed
getter and the raw database value. This does not grant a default or fallback.

## Separate comparisons, unchanged native profile

`LockedInvoiceRoundingRead` now shares internal validation across two named APIs:

| Proved source | Saved getter accepted | Explicit numeric-fix getter accepted |
| --- | --- | --- |
| Metadata and physical column absent | None | None |
| Present SQL NULL | None or canonical int0 | canonical int0 |
| Present native int0 | canonical int0 | canonical int0 |
| Present native int1 | canonical int1 | canonical int1 |

`require_saved_check_match(mapping)` accepts the saved-view column.
`require_check_cache_match(mapping)` retains its exact old normalized-view
contract and error code. Both require precisely the two fixed keys, revalidate
the protected native parent and reject bool/text/float lookalikes. None cannot
mask a stored zero or one. Do not infer None from missing observations or coerce
an unknown getter into an expected value.

Reuse the new saved comparison in `InvoiceRoundingAcquisition` and protected
`SavedInvoiceRoundingContext` reconstruction. Present None is provisional until
the owned native read proves NULL; it is not accepted from the getter alone.
`checks` retains the exact original/fresh saved values while `normalized_checks`
keeps the separate numeric-fix projection. SQL selection, source metadata/profile
bytes, digests, amounts and versioned control plans are unchanged.

## Priority and drift

A present invoice disable Check with native NULL and observed None remains false
for controller guard selection. Its metadata presence still wins over Global
Defaults, even when the global value is one. No Global lookup is introduced.
Both independent controls and consumed-source inspections use this same binding.

Keep original/fresh getter equality checks through cleanup: None-to-zero and
zero-to-None are observable view changes even when both are false. A native
NULL-to-zero mutation is a distinct source change and must also be refused.
The saved result does not rewrite a getter, record, default or cache to hide it.
Normal record/field permissions, one owned transaction, rollback/close, ambient
pending-work ownership, interrupt priority and one translated summary remain.

## Reproducible framework evidence

`test_invoice_check_loading` executes the actual installed15 base Document load
method and bounded pinned16 load/init/update/get/set/column-initialization
excerpts. Metadata and DB returns are synthetic; child loading is empty/stubbed.
Ordinary15 uses get_value and ordinary16 uses its fast sql path. Both preserve
None/Decimal before an explicit fix; nonempty Singleton loading calls its fix.
Record dictionaries remain unchanged. Precision-free conversion consults no
System rounding setting. These probes do not execute a site or a full ERP16 app.

Observed actual15 file SHA256 values for reproduction:

- model/document.py: `8178edc26b565bfb7dbb0a01a45e772f9bfc42d4f0f5784b2a419be2b84e4ac6`
- model/base_document.py: `3ddaf655be1b12d4320b61760c5d87f0245a9b9ca9dff33d26a1768d5c92b049`

The new `saved_loading` peer section in `frappe16_precision_oracle.json` records
only the extra methods and their reserved/cached-property infrastructure. It
reuses the existing MIT notice/license and primary source identity at commit
`e8d41dd0061a32ee781caefe5d0b0d2bb7c15362`, model/document.py SHA256
`4c1bf95413517c7deed5ae2edd24a38cadf0e21869e0710c80ad62aaada459b3`.
The pinned primary [document source](https://github.com/frappe/frappe/blob/e8d41dd0061a32ee781caefe5d0b0d2bb7c15362/frappe/model/document.py#L489)
also contains the separately tested explicit numeric-fix method.
Old excerpts/license data are unchanged and the existing oracle loader ignores
the peer section. Match captured methods and constants to the pinned full file;
never import its complete newer-Python application into the v15 environment.

Known callers are the existing saved-control acquisition/result reconstruction,
and local/native control and consumed-selection suites. The new loader suite is
explicitly in the offline manifest; native tests extend existing NEW guard-owned
TCP-disabled SQL fixtures. No provider, RPC, hook, button or schema is installed.

## Remaining work

This closes only selected Check getter/native-source matching for these base
loading stages. It does not establish full controller override/setup behavior,
lazy/child loading, monetary normalization/equality, effective precision/cache,
FX/GL/VAT/advance/XML/QR/signature/browser parity or installed16 integration.
Finish those and provider/role/caller/dead-code/performance/SDK gates before any
separately approved fictional-Company rehearsal and adoption decision. Live
changes and authority requests remain prohibited. See [STATUS.md](STATUS.md),
[ROUNDED_TOTAL_ACCESS.md](ROUNDED_TOTAL_ACCESS.md) and
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md).
