# Draft collection operation and scheduled waiting — workstream2

Development only: no installed schema, live source, site/company, worker/service
or authority request was changed. The native activation and installed15/16 gates
remain open. Financial references and the original240 comparison91/117/32 remain
unchanged; this change does not recalculate invoice data or XML/QR values.

## Fixed callers and preserved operation

The two manual Sales/POS collections and the shared scheduled draft collector now
call one `submit_draft` helper around the ordinary ERP `Document.submit()`.
Their existing Company auto-submit option, B2C tests and ERP validators stay in
place. A private synchronous scope retains only site, original actor, exact saved
doctype/name and the server-selected manual/scheduled operation. It stores no
Document, credentials or caller-selected method. The later
[borrowed draft isolation](NATIVE_DRAFT_ISOLATION.md) owns only a private local
savepoint and operation callbacks, never enclosing ERP commit/rollback.
A nested identical scope preserves its outer lifetime; a conflicting, cross-source,
actor/site-changed or retained closed scope cannot select another operation.

The native submit-hook producer copies this operation into the already protected
parent intent header. An ordinary submit with no scope still means submit.
Unmarked legacy callbacks retain their existing queue method/policy. The source
intent, not a form flag or RPC bypass argument, selects the eventual native action.

| Request | Previous development behavior for a draft | Current native behavior after ERP commit |
| --- | --- | --- |
| Manual send, Batches/Background Company | Lost manual origin and prepared only through submit policy | Retains manual intent and dispatches through the existing owned manual policy |
| Scheduled Background send inside its window | Lost scheduled origin and prepared only | Retains scheduled intent and dispatches after fresh source/settings/ACL checks |
| Scheduled worker starts outside the window | No durable distinct waiting state | WAITING, without allocating identity, signing or invoking transport in that check |
| Normal submit, Batches/Background Company | PREPARE | PREPARE, unchanged |

The actual Sales external-ID Background submit branch previously returned before
any generator's shared deferral. A native-only admission now registers the same
parent intent at that return, after the existing parent validators. It is inert
outside the ERP hook and does not turn an unmarked legacy early return into an
immediate send. Tests exercise actual parent branch selection and the real
storage bridge separately; complete installed canonical submission remains a gate.

## WAITING is not an unknown delivery retry

Only the provider's exact scheduled `SKIPPED / accepted=False /
outside_company_window` result can become WAITING. That result is produced before
preparation/reservation/transport, with the Company still enabled in Phase2 and
using Background. A changed method, phase, disabled rollout, lost permission,
changed fiscal source/chain, unknown result or exception remains REVIEW. The
provider checks rejected/uncertain retained originals before window policy, so a
closed window cannot conceal an existing OUTCOME_UNKNOWN attempt as harmless waiting.

READY and WAITING are rediscovered in bounded batches by last state modification.
Each worker claim has a new fence and repeats the original enabled actor and
fiscal source/chain checks. A previous fence cannot finish a later claim. A wait
preserves the immutable header/ciphertext and does not advance the issuance chain.
A later valid window enters the ordinary native provider exactly once; unknown
attempts still require explicit recovery. RUNNING/REVIEW are never automatically
reclaimed. No issue timestamp is rewritten to the next window.

Discovery authenticates the whole selected batch before any administrative hold.
Disabled/missing original Users become REVIEW with `actor_disabled`, without
changing the original actor or source. This prevents disabled discoverable rows
from permanently occupying the batch. It commits only its owned service-row
transaction, then queues enabled original actors with the existing session restore
boundary. No invoice or authority outcome is inferred from this hold.

## Evidence and remaining lifecycle work

Local tests run the actual manual collection callers, shared scheduled caller,
Sales parent external-ID branch and context failure boundaries. Private SQL tests
use actual native parent custody, all three owner forms across Sales/POS, repeated
waiting, next-day window entry, policy/source/account drift, late fences and a
competing mocked manual timeout leaving OUTCOME_UNKNOWN. The fixture replaces ERP
submit itself and canonical financial metadata/signing inputs; it is not installed
ERP accounting, CA/SDK acceptance, genuine HTTP delivery or process supervision.

Borrowed native draft rollback/callback isolation is now adopted in the shared
helper; whole canonical/installed accounting, physical File cleanup and mixed
legacy/native submitted-invoice coordination remain open. The older
collector still has its24-hour discovery horizon and established commit behavior;
later native PREPARED discovery, started/uncertain handoff resolution, explicit
retry/corrected-clock adoption, source cancel/delete/rename, frozen publication,
legacy history/drain and activation remain workstream2 requirements. This change
does not close workstream2 or authorize workstream3, installation or a pilot.
