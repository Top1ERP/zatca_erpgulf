# Invoice-owned native SQL reads and ordered child evidence

Increment 115 — 2026-10-27. Uninstalled caller-owned dependency reader.

## Delivered boundary

`financial_source_sql.py` reads a selected saved Sales/POS invoice header and
its present items/taxes/payments/advances/ZATCA-deduction tables. It composes the
existing metadata SQL reader and pure financial observation contract without
altering their wire formats or choosing fiscal/alias/discount policy.

The caller supplies an authorized exact connection, invoice identity, declared
ERP major and exact applied metadata for the invoice plus present child types.
Items/taxes are mandatory under the existing observation contract; optional
tables remain absent or present independently of whether they contain rows.
Present empty tables still require metadata. Table types/options and required
columns must match the explicit profile. No Company/customer/template/ledger/
archive lookup, provider installation, source write, ORM/controller execution,
UUID/counter allocation, XML/QR generation or authority request is performed.

## Native scalars rather than a guessed ORM conversion

Local installed Frappe source uses NEWDECIMAL-to-float in its MariaDB conversion
map. Its numeric-fixing helper is explicitly used for Singles; ordinary document
loading also has different base/docstatus behavior. It would be incorrect to
silently treat native PyMySQL Decimal data as the same bytes as an ORM float or
to apply a universal field-type cast/default coercion.

This reader records `native-sql-no-orm-coercion/v1`. Result type signatures bind
type code, reported precision/scale and nullable flag for every selected value
column, including empty tables/NULL values. Values must match supported metadata
and native driver families: exact Decimal for DECIMAL, float for SQL real types,
integer for integer types, strings for text and native date/datetime/timedelta
for temporal types. Returned Decimal exponents must preserve reported SQL scale.
Unexpected float/normalized-Decimal decoders fail; NULL remains NULL, with no
zero/empty/date fallback. Supported physical real columns retain their floats;
this is not a claim that every source value is decimal money.

Tests compare CASE-projected values to direct native queries and verify that the
actual installed Frappe conversion map is rejected on non-NULL DECIMAL values.
No connection/decoder provenance is proved merely by compatible returned values.
Projection descriptors are not a complete physical DDL/charset/index attestation;
CASE can affect reported nullability. A reviewed ERP15/16 normalization/bridge
and installed accounting/XML parity remain separate requirements.

The existing Decimal codec is preserved: zero at scale nine is `0E-9`, not a new
fixed-format rewrite. Both native precision and this canonical representation
remain distinct from integer/blank/NULL values. Subcent values are captured
without quantization or recalculation.

## Bounded two-pass data projection

For each group, a locked identity/revision/length preflight runs before value
projection. It limits selected scalar byte lengths and the aggregate scalar/
identity budget. The following SQL CASE returns NULL for an oversized concurrent
value, then its length/membership witness forces failure. Native RC insertion
tests prove oversized text is not returned before drift is rejected.

Only fixed source-profile identifiers are used; identity/scope/limits are bound
parameters. Child selection uses parent AND parenttype AND parentfield. A
legitimate same-name invoice of another type is ignored; returned collation/case
variants are refused. Rows use idx/binary-name order, contiguous integer indices,
unique identity and exact parent binding through the shared observation validator.
Each child's nullable revision is retained separately from its parent timestamp.

Limits reuse the existing 64 KiB UTF-8 scalar, 2 MiB canonical object and 4,096
children across ALL tables. SQL uses one-row overflow probes and explicit value
masking, never silent truncation. Preflight bounds returned value content, not
total memory, scan work or transaction duration; metadata/descriptors/encoding
overhead have their own canonical bound and may cause earlier rejection.

## Transaction, result and rechecks

`MariaDBInvoiceFinancialReader.load_for_update` requires autocommit off. It reads
and matches all required metadata, locks exact data groups, captures native
values and rechecks metadata before returning. It never commits, cleans up,
changes session options or retries. Errors poison the reader; interruptions
propagate. The caller owns all rollback/close and authorization/provenance.

`LockedInvoiceFinancialRead` independently pins the PARTIAL financial observation,
exact metadata family, physical result signatures and child revisions. Direct
reconstruction revalidates type/schema/presence/identity/revision bindings.
Repr is protected and pickle refused; generic dataclass/raw access is not a
disclosure sandbox or permitted UI/log/queue/RPC export. Neither digest replaces
the required complete preparation source fingerprint or grants issuance.

`require_unchanged` repeats metadata and financial reads on the same connection.
Native tests detect child value/insert/delete/order/revision changes without
changing the parent timestamp, and physical decimal scale changes with a NULL
value. Existing row locks survive until explicit caller cleanup. Own pending
writes remain visible and are never implicitly saved. RC phantoms after a last
boundary, complete graph consistency and actual index/isolation/provisioning
remain gates; this is not a committed-origin or complete atomic snapshot claim.

## Advance/payment scope and remaining work

The read preserves invoice-owned payment amounts, advance references and deduction
rows, including old synthetic references and zero allocations. It does not search
historical source invoices, decide settlement eligibility, allocate available
balances, validate archived XML authenticity or change legacy settlement behavior.

All tests use synthetic metadata/data on a NEW guard-owned TCP-disabled server.
Declared v15/v16 labels are not installed-version, GL/VAT, SDK or authority proof.
Executed totals are in [STATUS.md](STATUS.md). Next compose permissioned financial
acquisition with the remaining linked/settings graph and an explicit ORM bridge,
then establish effective precision and amount/XML/GL/VAT parity before adoption.
See [FINANCIAL_SOURCE_OBSERVATION.md](FINANCIAL_SOURCE_OBSERVATION.md),
[CALCULATION_CONTEXT.md](CALCULATION_CONTEXT.md), [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md)
and [SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md). Working-environment changes
and all authority requests remain prohibited.
