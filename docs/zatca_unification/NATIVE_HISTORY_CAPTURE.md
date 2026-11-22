# Durable encrypted legacy XML page capture

Workstream2 development,2026-11-22. Implemented inside the owned unchanged legacy
review service. Source/schema declarations and fixture-owned SQL only: no live
site/schema/source/service, actual invoice, authority endpoint or installation.
Installed15/16 and dummy-company rehearsals still require their separate gates.

## Command and atomic progress

The existing internal review service accepts history_capture=True only with a
valid history_review_id/history_page_after pair. It retains all existing System
Manager, Source/Company/counter/File and selected-owner admission, current issuer/
consumer/tail checks and exact authenticated unchanged-review binding. It is not
a public RPC or UI action. Ordinary review/read-page defaults are unchanged.

New capture starts at0. Continuation must start at the current protected head;
skipping positions cannot append a disconnected page. An exact already-captured
start returns its saved page before the XML producer runs. It neither rereads
mutable older XML paths nor writes another page/commit. current_cursor and
head_page_number describe the protected current head, even for an earlier page's
replay; history_page describes that specific saved partial read.
The outer review remains reused=True; capture.reused distinguishes a new page
from recovery of existing page custody.

Each new page and its protected current-head update share one owned transaction.
The parent review/counter/chain locks serialize callers; a unique page key binds
review ID and exact start. The head update also compares its earlier header/
ciphertext and current inactive review slot. Compare failure rolls back the page.
Unknown COMMIT acknowledgment stays uncertain; repeating the command recovers
the same committed ciphertext/head without generating a replacement. No ERP
source, accounting entry, ICV/PIH, active slot or signing credential is changed.

## Exact bytes and authenticated domains

A page payload frames a bounded canonical manifest plus length-prefixed exact
XML bytes. Each manifest source preserves its saved DocType/name/Company/status/
UUID/ICV/unit and permitted File IDs, including an explicit unresolved state.
Successful copies must agree on declared chain/key data. Invalid/missing XML is
not silently converted into valid data; its source remains unresolved with no
unchecked raw body. The verified selected anchor is reused from the parent.

The common site/namespace/key/record/header-bound cipher adds three separate
domains: legacy-history-page for XML, legacy-history-access for its small access
manifest, and legacy-history-head for current progress. Previous formats/AAD are
unchanged. A protected page header contains exact payload/access hashes and the
previous page ID/header digest. The authenticated head pins the latest page/header
digest and cumulative captured/unresolved counts. Captured means retained evidence,
not successful compliance or accepted/qualified invoices.

The access manifest is authenticated separately under the same page header.
Current saved Source/File READ and source/attachment identity are checked before
large XML decryption. Ciphertext is never treated as a read grant. Source fields
are fixed metadata only; no credentials, private keys or caller callbacks are
added to page data. No raw XML/path/token enters an exception or log. The internal
result exposes metadata and page identity, never decrypted XML.

Each capture-specific page uses at most64 new sources plus its reread boundary,
four candidates per source, the existing5MiB single-file limit and15MiB total
captured XML. The anchor also consumes this XML budget even though its bytes are
reused. The canonical manifest is capped at512KiB and access metadata at256KiB;
framing fits the existing16MiB encrypted-payload bound. XML is not resigned,
serialized, normalized or Base64-expanded inside this historical frame.

## Stable capture scope and correction

Continuation retains the initial known-position count. A changed census holds
instead of silently adopting new slots. A page's current boundary must match
the saved previous source identity and unresolved state, and an observed boundary
must retain at least one exact XML copy. Current whitespace/body substitution,
missing formerly observed XML, or newly fixed previously unresolved evidence
requires review; it cannot rewrite an earlier capture.

Correcting such an input can explicitly supersede the inactive review with a
fresh reason and start a new capture under that new review ID. Existing review,
head and XML pages stay retained. It does not reset or merge a counter, activate
a unit or replace an issued invoice. Cumulative counts exclude repeated boundary
observations. Exhausting a suffix still does not imply all inputs were unambiguous:
unresolved, PIH/genesis/key and gap observations remain in the captured pages.

## Source-only schema and remaining release work

ZATCA Legacy History Page is a new read-only System Manager DocType with unique
record/page slots and a review index. Generic insert/update/delete/rename/import
are denied by the existing service-owned controller. Two nullable hidden Long
Text fields on Issuing Chain hold its head. All authenticated identities are Data,
not mutable ERP Links. Hidden ciphertext/header fields are no-copy/print-hidden;
new visible metadata labels have Arabic catalog entries. Capture checks current
InnoDB, full unique/index semantics and physical column types before writing.

Cold namespace initialization now includes the page table in its orphan census.
It creates no schema, table, key or site config. These new declarations must be
installed only during the separately approved isolated acceptance stage. Existing
valid namespaces and non-capture paths do not initialize missing history storage.

This pins immutable captured declarations and append progress, not a trusted
database epoch, global archived/rotated-owner census, whole ledger availability,
computed invoice-hash/signature/CA/SDK validation, worker drain or activation.
Current append admission verifies the protected head/latest page and boundary;
a complete backward header/body/coverage audit is still required before any
qualification/adoption decision. There is no overall accepted/complete/active
flag. Privileged complete DB/key rollback is outside this local epoch guarantee.
General archive publication/operator presentation and installed/pilot acceptance
remain open; workstream2 is not closed by this capture primitive.

## Evidence

20 new local framing/domain/schema cases and23 new private capture cases cover
exact bytes, shape/size rejection, privacy and purpose separation, three owner
policies, replay after mutable files change, lost COMMIT acknowledgment, denied
READ before XML decryption, corrupt/orphan/index/head data, atomic compare rollback,
unresolved retention, stable boundaries/census and explicit corrected review.
Corrupt100k-character head fields are bounded by SQL before parsing/decryption.
Existing schema guards additionally cover the seventh read-only service DocType.
The first focused local run found a test expecting the wrong static exception
family for a rejected noncanonical counter; runtime validation already rejected it.
The expectation was corrected without weakening source/counter validation.

Final:569 local cases across16 suites in2.11s and294 private cases across9 suites
in44.33s. Logs: `/tmp/zatca-axis2-capture-local-final2.log`,
`/tmp/zatca-axis2-capture-private-final2.log`. Initial focused16 private cases and
the expanded67 private set also passed. Sets overlap and are not release totals.
Manifest255 local/89 private was not run in full. The mandatory offline guard
admits fixture-owned /tmp Unix SQL only, with --no-defaults/TCP disabled, and
denies site/network access. ERP/signed-XML/HTTP data remain fixture input;
altered declaration fixtures are not asserted cryptographically valid. No monetary
or golden fixture changed; original240 remains91 identical/117 review/32 blocked.
