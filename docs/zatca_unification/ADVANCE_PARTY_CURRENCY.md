# Standard direct-advance party currency — batch155–157

This DEV checkpoint closes the saved/native `party_account_currency` source gap
in the preceding advance context for standard saved invoices with a nonempty
parent party currency. It remains an optional read/comparison operation, without
runtime provider installation, saved controller execution, XML changes or sends.

## 155: optional native row party links

The new `source-advance-party-currency-metadata/v1` profile selects only optional
`Sales Invoice Advance.party_account_currency`, constrained to Link -> Currency.
`LockedAdvancePartyRead` and `MariaDBAdvancePartyReader` reuse the existing child
projection/metadata/physical-column/failed-session engine through fixed class
configuration. Only the advances parentfield is admitted. No arbitrary field,
table, transaction, cleanup or SQL transport is added.

Preserve existing financial and currency/Company profile fields, canonical
payloads and domains. The new party profile has its own domain. Physical column
presence must agree with applied metadata, including an absent field; a hidden
physical party column cannot silently become an absent/NULL declaration. Native
row identity/order/index/revision stays bound to the original financial read.
No customer schema is altered by this reader.

## 156: ordinary READ and exact fallback order

`AdvancePartyAcquisition` borrows the existing authorized numeric graph and owned
handle. Inspect initial direct/reference party values and fresh normal saved
loads, selected child field levels, and root table READ. Pin the child's applied
party definition, retaining absent/NULL/blank distinctions.

A nonempty own party link wins. Only when at least one row needs parent fallback,
reuse `OwnerCurrencyAcquisition` for the saved parent's **party-account** currency:
normal root/field READ, exact definition/level/getter, native link/revision and
metadata binding. Do not use transaction currency, row `currency`, Company
default currency or an in-memory `parent_doc` as a substitute.

The new trusted constructor dependency `advance_party_metadata_reader` supplies
the narrow child profile. Existing `owner_currency_metadata_reader` supplies the
parent profile when needed. Providers are server constructor dependencies, never
caller-selected request values. The seventeen capture method bodies remain
unchanged; callers still use `capture_advance_rounding_context`.

Authorize all selected party fields and Currency/Language/System records before
new party/parent/format metadata callbacks. The initial same-owned financial/
defaults/method read necessarily precedes the lazy dependency decision. All-own-
party rows need no parent source/provider. Configured precision, version15 and
empty-table paths acquire no new party evidence or related format sources.

Reuse direct-child plain-link fallback and cache semantics: the framework treats
`currency` and `party_account_currency` as field names in the same algorithm.
Here its generic inputs are explicitly bound to native PARTY columns, not to
transaction currency. A shared exact cache comparator preserves row precedence,
parent keys and blocked NULL/blank `setdefault` behavior without filling slots.
Sample every consumed original slot before providers, and recheck through close.

## 157: protected group and aggregate comparison

`SavedAdvancePartyRead` binds the saved financial/default context, optional native
row links, conditional parent link, complete original cache samples, and ordered
native format/related-record evidence. Validate each row's resolved currency and
fresh precision. Keep original root/child precision semantics separate.

`SavedAdvanceRoundingRead.party` is optional and protected. On the standard unset16
branch it supplies per-row resolutions instead of the older currency/Company
field proofs. Require the same financial/default source, exact row order,
document/container observations and precision slots. Existing group calls and
`AdvanceAggregateCalculation` reuse the same interface and arithmetic. Missing
new trusted dependencies continue to fail closed, rather than guessing a value.

Actual pinned16 `get_field_currency` and `get_field_precision` are compared with
the bound source on synthetic documents. A fresh excerpt namespace prevents the
precision oracle's dependency injection from leaking into later probes. The
actual ERP controller prefix and numeric helpers are also executed synthetically,
stopping at `total_advance` assignment. No saved invoice/controller constructor,
site initialization, Redis or authority endpoint is involved.

## Boundaries and next steps

Batch158–160 builds an explicit ceiling/FX/write-off-input comparison on this
same-owned group; downstream settlement recursion remains separate. See
[ADVANCE_LIMIT.md](ADVANCE_LIMIT.md).

Supported: absent own party field/column, present NULL/blank own link, nonempty
own link, mixed own/parent rows, different transaction versus party currencies,
and Sales/POS graphs with a present standard advances table. Parent fallback
requires a saved, nonempty Link -> Currency source. Missing/NULL/blank parent
party currency and unproved `parent_doc` fallback remain refused. This is not a
complete model of every modified ERP schema or unsaved controller state.

Normal permissions, provider/cache/namespace provenance and post-cleanup staleness
are not atomically frozen. These observations do not attest committed/durable
origin or grant permission to mutate/submit an invoice. Complete invoice limits,
FX, paid/outstanding/write-off, advance matching/settlement, tax/GL/VAT/XML parity,
worker/custody/dead-code/performance review, installed15/16 and SDK acceptance
remain before separately approved fictional-Company rehearsal and rollout.

LIVE remains at the independent Phase-1 address hotfix. No installed code/site/
schema/data/Company/credential/worker change or authority request is authorized
by this checkpoint. SQL tests use NEW guard-owned TCP-disabled temporary servers
only. Executed counts and compatibility checks are recorded in [STATUS.md](STATUS.md).

See [ADVANCE_ROUNDING_CONTEXT.md](ADVANCE_ROUNDING_CONTEXT.md),
[CALCULATED_TOTALS.md](CALCULATED_TOTALS.md) and [PLAN.md](PLAN.md).
