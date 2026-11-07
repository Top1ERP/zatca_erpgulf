# Consumed POS Profile and default-payment source — batch173–174

The post-balance comparison previously accepted supplied profile/default-query
answers. This checkpoint adds an internal native reader for those consumed
dependencies. It neither installs that reader nor changes a controller or route.

## Separate lookup scopes

`MariaDBPosProfileReader` borrows one explicitly authorized transaction and an
existing `LockedInvoiceFinancialRead`. Require ordinary saved invoice, related
POS Profile, selected child/field READ and owned-connection provenance before
using it. A permissioned acquisition facade and complete controller assembly
are still required. This object cannot authorize a source by itself.

Both purposes bind the exact saved `pos_profile` Link target and Company Link,
the profile's Company, applied metadata/customizations, native descriptors,
source revisions and original financial rows. Blank/missing links, a missing
master, a wrong Company or changed metadata require review. They do not become
an implicit zero limit or a missing-default success. This is a conservative
source gate, not a claim that the primary controller rejects every such case.

The new metadata profiles do not enlarge any older projection or payload:

| Purpose | Consumed master fields | Child selection |
| --- | --- | --- |
| `limit` | Company, write-off limit | None; no payment table/query/metadata dependency |
| `default` | Company and payments table declaration | Mode, default and allow-in-returns for the actual bounded payment rows |

Native Decimal/NULL limits retain scale and sign. `limit_observation()` supplies
the existing `PosLimitObservation`; its later precision-free conversion remains
in the existing comparison. A default read does not inspect the write-off limit.
Unused setting changes therefore do not create artificial source conflicts.

## Exact default filter and ambiguity

The primary ERPNext15/16 return helper queries `POS Payment Method` using only
`parent=pos_profile` and `default=1`. It does not filter by parenttype, parentfield
or allow-in-returns. Reading only well-formed profile children would miss an
orphan row that the primary query could select.

The reader therefore acquires both the bounded real profile table and a separate
parent/default probe. Two matching names suffice to prove ambiguity. It refuses
multiple defaults instead of inventing which first row an unordered get_value
would return. A unique candidate must be an actual child of this profile's
payments table. Orphan/case/identity/Check/schema conflicts are not ignored.

No default is distinct from a found default with a blank/NULL mode. The latter
remains an explicit observation; it is not proof of a valid payment account.
`default_observation()` feeds the existing redistribution comparison without
filtering allow-in-returns, changing signs, applying FX or recalculating totals.
No row, account, Currency or payment document is saved or selected implicitly.

## Transaction and concurrency boundaries

Reuse the shared native financial and selected-metadata readers rather than a
second ORM/cache loader. Reads use bounded projections, native type signatures,
length preflight, masked value projection and `FOR UPDATE`. No private master
columns are selected. Metadata and invoice evidence are rechecked on the same
handle. Failures poison this reader without committing, rolling back, closing,
retrying or cleaning the caller's pending work. Interruptions propagate.

The caller must retain its transaction and call `require_unchanged` at completion.
In READ COMMITTED, a noncooperating writer can insert a new orphan default after
the first probe because Frappe child tables have no parent foreign key enforcing
the master lock. The independent-writer test verifies that the completion
recheck refuses this now-ambiguous result. This reader does not provide a durable
graph lock, committed source provenance or a general serializable transaction.

## Primary evidence and remaining work

Installed ERPNext15 and pinned ERPNext16
`ade850bbd6a7412e9994a9637d2c5c713771632a` declare the selected fields as Company
Link, Currency limit, payments Table, Mode of Payment Link and two Checks.
The pinned16 public JSON files were inspected from the official repository:

- [POS Profile](https://github.com/frappe/erpnext/blob/ade850bbd6a7412e9994a9637d2c5c713771632a/erpnext/accounts/doctype/pos_profile/pos_profile.json),
  SHA256 `66ec247ba994661563c09ffa3bf3ae5707015324c452c515aaef742f5b3c1d3a`.
- [POS Payment Method](https://github.com/frappe/erpnext/blob/ade850bbd6a7412e9994a9637d2c5c713771632a/erpnext/accounts/doctype/pos_payment_method/pos_payment_method.json),
  SHA256 `ed8da5c4563a2169e643e4626caa1100a4afbe70a881bd40b6179e68ea9dac22`.

Local tests bind these declared types to the existing calculation contracts.
Native tests use only NEW guard-owned TCP-disabled MariaDB, synthetic masters,
invoices and children. They exercise ambiguity/orphans, NULL/default distinction,
same-handle changes, pending-work privacy, retained master/payment locks and the
READ COMMITTED late-insert limitation. Counts are in [STATUS.md](STATUS.md).

Permissioned source acquisition, blank/missing profile policy for the primary
return helper, Mode/account/company/currency/return eligibility, full saved guard/
rounding/balance/write-off/paid composition, installed15/16 lifecycle and GL/VAT/
XML/SDK acceptance remain before the separately approved fictional-Company
rehearsal. No live code/data/schema/configuration, Bench/workers, counter behavior
or authority endpoint is changed. Separately authorized manual corrections do
not activate an automatic decrement/delete feature in this development.
