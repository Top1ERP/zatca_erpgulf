# Bounded historical attached-XML probe

Workstream2. The actual inactive legacy review now probes otherwise unattributed
old counters after its known-owner/counter checks. A structurally bound embedded
key or declared full-unit identity that overlaps the possible owner group stops
review with `registration_history_counter_related`. It does not merge counters,
adopt a maximum, change PIH/ICV, certify a signature or activate an issuer.

## Evidence binding and access

The probe uses the saved counter's last Sales/POS reference. Saved Source,
Company and File identities are reloaded with current locking reads and ordinary
READ permissions. Missing names/rows, noncanonical UUID/ICV, draft/unknown status,
different Company/unit, or counter/source ICV disagreement remain unresolved.
The XML's invoice ID/UUID/ICV/seller must match those saved observations before
an embedded declaration can require owner-group review.

Only attached XML File records are queried. The existing local private-file
reader still rejects public/remote paths, traversal, Debug names, nonregular
files, leaf symlinks and missing/oversized bodies. No directory scan, caller path,
URL fetch, current signing-key read or authority request is performed. Private
fixture tests change an archived File URL after the initial ORM read view and
require the actual review to see the current attached body.

The existing embedded-certificate inspector was factored without changing its
fingerprint result/API or structural validation. A separate projection adds only
hashed environment/VAT/full-serial declarations. An old counter purpose does not
identify its gateway, so potential declarations are compared conservatively in
all three environment namespaces. Missing/malformed unit claims cannot conceal
an independently observed public key. No DN, certificate, token or key is
returned by that projection.

## Limits and unresolved states

Each invocation attempts at most32 counter references, four attached XMLs per
source and4MiB of successful XML reads. The existing file reader gained an
optional lower byte ceiling; its default global bound/behavior is unchanged.
It checks the remaining limit before reading, including the usual one overflow
guard byte for a file-growth race. Read bytes are charged before parsing, so a
malformed body cannot reset the global budget. A size failure exhausts this
probe's remaining budget. More counters/files or evidence beyond budget remain
unresolved/unprobed, never a truncated complete result. Root source/child ORM
loading and SQL work are not bounded by that XML byte limit; installed acceptance
must assess administrative scan/lock cost separately.

The consumer result retains its total unattributed counter count and adds counts
of historical references probed, structurally unresolved and unprobed. A different
embedded declaration is only inspectable metadata, not verified independence.
Zero unresolved/unprobed counts do not establish complete history, acceptance or
an activation authorization. The immutable original review envelope is unchanged;
future cutover must revalidate and prove its own historical/fleet/activation gates.

Optional does not mean infrastructure failures can be swallowed. SQL/ORM/engine,
permission-engine and transaction-owner failures propagate to abort the parent
review. In particular a possible InnoDB deadlock/implicit rollback cannot be
classified as a missing file and followed by a commit with lost locks. Literal
READ refusal, missing data and bounded XML/file validation failures instead keep
the historical reference unresolved. Existing English redacted review errors and
ordinary selected-owner WRITE/source/counter/File READ requirements remain.

## Offline qualification

Tests use temporary private files, synthetic XML/certificates and fixture-owned
TCP-disabled MariaDB. Some historical fixture signatures are deliberately invalid:
their declarations may HOLD review, never prove a trusted history link. Cases
cover same keys after a token alias disappears, fresh keys with the same declared
serial, Sales/POS references, missing/denied/public/Debug/remote/symlink/invalid
files, source mismatches, byte/counter limits, malformed-input budget charging,
v15/v16 quiet ACL signatures, current File reads, context changes and fatal SQL
failure propagation. Existing certificate/file inventories and native existing-XML
delivery remain in the regression selection.

No installed ERP15/16, real fictional Company, live source/schema/service,
authority operation, complete archived XML/PIH/rotated-unit ancestry or drained
worker/fleet acceptance is claimed. Financial references and signing/hash/money
algorithms are unchanged. See STATUS.md for exact selections and logs.
