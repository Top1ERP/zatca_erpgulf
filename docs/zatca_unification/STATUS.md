# Implementation status — 2026-10-09

## Scope delivered in this increment

Safety preparation and the first Compliance outcome fix are complete locally.
The broader [unification plan](PLAN.md) is not complete. No change in this branch
has been deployed to the running application or sent to ZATCA.

### Recovery evidence

- Backed up all 33 sites found with this app installed: SQL, public/private files,
  original site configurations, five dependent app source/Git trees, a ZATCA Git
  bundle, bench configuration, and runtime package inventory.
- Verified archive integrity, SQL completion/table counts, and checksums.
- Restored two representative sites' databases and files into an isolated
  MariaDB instance without network access or Frappe workers. Verified encrypted
  password recovery where encrypted rows existed. The test server was stopped.
- Backups are owner-only local recovery material, not additionally encrypted and
  not off-host. Online file copying/MyISAM auxiliary tables are not a coordinated
  maintenance-window snapshot. Full Frappe boot was not tested.
- Detailed manifests and restore reports remain in the private operations backup
  directory, outside Git. No customer backup/configuration is part of this change.

### Git evidence

- Deployed branch stays at `2e97708e115e31c675182647d10829d6175e7449`.
- Development base: origin/main `2c38ff1b984f8b8f961fa7bc8d028576d2195cab`.
- The two revisions have the same tree:
  `529d3cb16fbc6ba3687397ba0adfc60688564fc8`.
- Local main was fast-forwarded, safety tags created, and two stale local
  remote-tracking references removed after archiving. No GitHub branch was
  deleted, no history forced, and no deployed source file changed.
- Development is in an independent worktree on
  `codex/zatca-unification-v15-v16-20261009`.

## Compliance fix

Previously, `compliance_api_call` caught network exceptions and returned an error
tuple. Both all-type buttons counted any return without an exception as PASS.
The HTTP 406 detector also filtered out malformed entries before `all`, allowing
an empty iterator to appear successful. HTTP 200/202 with no confirmed validation
could also pass through.

Changes:

- Added the pure `compliance_result.py` contract.
- Transport failures now raise a translated failure; no success-shaped tuple.
- HTTP 200/202 require explicit PASS/WARNING validation without errors.
- Previous completion requires HTTP 406, a validation ERROR, and a nonempty list
  consisting entirely of `Submitted before` errors. Summaries distinguish this
  as `compliance_status: ALREADY_COMPLETED` without claiming new clearance.
- Both aggregators reject unconfirmed return values, independently of the HTTP
  boundary. Existing PASS/FAIL UI fields remain compatible.
- Added Arabic translations and English explanations of the new invariants.

This does **not** change endpoint routing, credentials, signing, QR payloads,
discounts, GL/VAT reporting, or the server's final-CSID requirements. In particular,
it does not claim to fix a cryptographic digest error or incomplete remote tests.
Company validation-type mutation and debug/counter side effects remain queued
for subsequent increments.

## Verification

The initial regression suite reproduced **19 failures and 12 passes** on the
unchanged implementation (after isolating the Frappe HTTP decorator). The first
fix passed all 31 cases; the expanded suite plus baseline now passes **160 tests**:

| Suite | Scope |
| --- | --- |
| `test_compliance_result.py` | Pure result classification and malformed payloads |
| `test_compliance_api_outcomes.py` | Mocked real API/button functions, failures, previous completion, translations |
| `test_tax_details_compat.py`, `test_tax_details_regression.py` | Tax adapter regressions |
| `test_qr_tlv_compliance.py` | Existing QR/TLV regressions |
| `test_zatca_response.py` | Existing response handling |
| `test_compatibility_hardening.py` | Existing mocked runtime/advance compatibility regressions |

All HTTP/Frappe I/O in the new boundary tests is mocked. Run them against the
development worktree, not the installed production package. From the worktree:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  ../../env/bin/python -m pytest -q -p no:cacheprovider \
  zatca_erpgulf/zatca_erpgulf/tests/test_compliance_result.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_compliance_api_outcomes.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_tax_details_compat.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_tax_details_regression.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_qr_tlv_compliance.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_zatca_response.py \
  zatca_erpgulf/zatca_erpgulf/tests/test_compatibility_hardening.py
```

Tested with the existing Python 3.10/Frappe 15 environment. No real v16 runtime,
full site integration, browser language switch, ZATCA SDK run, remote Compliance
request, or production invoice submission was performed in this increment.

## Next gate

Inventory and test the shared endpoint/credential/settings context, then isolate
Compliance/Debug from live invoice UUID/ICV/PIH changes. Prepare a separately
pinned v16 bench and golden XML fixtures before consolidating cryptography or
advance-payment calculations. Obtain a suitable off-host backup destination and
choose the pilot/rollout window before any production deployment.
