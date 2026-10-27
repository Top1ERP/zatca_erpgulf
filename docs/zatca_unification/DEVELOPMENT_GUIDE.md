# Development guide: current architecture and closing gates

Start here for source navigation. PLAN.md explains the target and STATUS.md
records historical increments/test results; neither test volume nor historical
README feature claims establish a completed or deployed unified release.

## Safety and execution scope

Work only in the isolated development worktree. Read
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md) before implementation.
Do not touch an installed app/site/configuration/schema, restart Bench/workers,
create a fictional Company on a working bench or request any authority API.
Sandbox/Simulation, OTP/CSID and Compliance are included in that prohibition.
A DEV branch source push is not deployment or permission to send.

## Functional map

| Layer | Source anchors | Current status |
| --- | --- | --- |
| Installed-style entry points in DEV | hooks.py; public/js/company.js, our_sales_invoice.js, our_pos_invoice.js | Existing Sales/POS callbacks and frontends remain; not a new installed release |
| Legacy runtime orchestration | sign_invoice.py, pos_sign.py and existing/without-XML adapters | Partially shared internals; whole-writer/transaction integration still open |
| Routing and declarations | api_routing.py, credential_material.py, credential_settings.py, scheduling.py | Reuse these policies; do not invent parallel environment/owner/window selectors |
| Field compatibility | ksa_compliance/field_alias_registry.py and field_compat.py | One registry; pure names separated from Frappe schema/lookup operations |
| Financial observations | financial_source_observation.py, tax_dependency_observation.py, issuing_settings_observation.py | Pure PARTIAL immutable declarations, not complete committed source guards |
| Invoice-owned native SQL | financial_source_sql.py | Caller-owned selected header/child reads, exact metadata, bounded length/value passes, native type/scale and child revision binding; no ORM coercion or complete preparation proof |
| Party/address graph | party_address_observation.py | Pins settings/financial parent; exact records/current links and declared candidate order, NOT an address resolver or complete-query proof |
| Calculation declarations | calculation_settings_observation.py | Explicit Singleton/Currency/POS/profile-tax records; not effective precision, timezone interpretation or fiscal validity |
| Applied metadata adapter | source_metadata.py | Explicit base/default fields plus immutable applied properties; narrow read view, not physical schema, raw Setter provenance or committed values |
| Declared customization matching | metadata_reconciliation.py | Explicit baseline/raw/applied equality using bounded installed Frappe casts; no committed query/completeness proof or defaults resolver |
| Scoped calculation defaults SQL | calculation_defaults.py | Fixed three-key locking reads/rechecks and explicit cache equality on a caller-owned transaction; not a provider, committed-origin proof or effective precision resolver |
| Permissioned calculation acquisition | calculation_defaults_access.py; archive_source_access.py saved-record mechanism | Defaults-only, invoice/Company metadata or native invoice/child financial composition in one owned transaction; shared ACL/cleanup/display, no installed provider or complete preparation proof |
| Explicit field precision | calculation_precision.py; SavedCalculationFinancialRead.resolve_precision | Fresh v15/v16 declaration resolution, explicit v16 locale/currency context and stale cache comparison; no amount rounding, locale SQL provider or full installed ERP16 proof |
| Format source acquisition | currency_format_source.py; source_metadata.py FORMAT_PROFILE | Caller-owned bounded Language/Currency/tabSingles reads and shared metadata matching; no saved ACL/provider or field-currency discovery |
| Permissioned invoice-currency formats | calculation_format_access.py; SavedCalculationDefaultsService.capture_currency_context | Shared normal related READ and owned transaction, explicit locale/invoice currency/cache/revision binding; missing Check needs nonempty storage witness; no base/child currency or runtime activation |
| Company/parent child-field currency | company_currency_source.py; capture_base_currency_context; SavedFieldCurrencyRead | Native Company link/revision/metadata on the same owned pipeline; explicit parentfield precision and field-currency cache comparison; direct child-document currency remains separate |
| Selected metadata SQL | metadata_source.py | Bounded DocType/DocField/customization preflight/full reads, guarded defaults, raw membership rechecks and applied-declaration matching; caller supplies ACL/owned transaction/provenance |
| Original preparation/history | issuance_candidate.py, issuance_preparation.py, issuing_chain*.py, preparation_hold.py | Explicit identity/chain contracts and local durable holds; not integrated issuance authorization |
| Protected recovery | preparation_review_access.py, preparation_recovery_access.py, preparation_custody*.py | Opt-in source/ACL/evidence boundaries; no default trusted provider/runtime caller |
| Primary receipt/outcome scaffolds | primary_capture*.py, primary_receipt*.py, response_assessment.py, dispatch_journal.py | Local observations/recovery, not automatic acceptance/replay authority |
| Offline evidence | tests/rehearsal_selection.py, tools/run_unification_rehearsal.py, tests/offline_rehearsal_plugin.py | Reviewed synthetic/owned-private SQL selection; no site discovery |
| Private fixture SQL | docs/zatca_unification/*rehearsal.sql | Test schema ONLY, never an installer or migration |

Python module names above are under zatca_erpgulf/zatca_erpgulf unless qualified.
Frontend/registry/hooks paths are under the top-level zatca_erpgulf package.
This is a functional map, not a completed file-by-file dead-code audit.

## Design and change rules

Target responsibility order: ERP adapters, complete source/effective settings,
pure amounts/tax/XML/signing/QR core, explicit output-mode services.
Do not combine that target with a claim that every legacy path already uses it.

- Keep Frappe/SQL/files/HTTP in explicit owned services, not new pure profiles.
- Keep the source metadata adapter above profile definitions; profiles must not
  import it back and introduce a circular dependency. Acquisition services can
  compose the explicit metadata/read views before calling the pure profiles.
- Keep framework cast matching outside pure profiles. Defaults are API/user/scope
  dependent; use the characterized behavior in METADATA_RECONCILIATION.md before
  designing a committed reader. Cache hits do not prove current stored rows.
- Compose the scoped SQL reader in CALCULATION_DEFAULTS.md with an audited
  authorized transaction. Its own writes remain visible; READ COMMITTED admits
  insertions between checks. Do not claim a complete source lock from row locks.
- Preserve exact originals and identity; unknown results never grant rebuilding,
  resetting a chain, releasing holds or automatic resend.
- A hash/HTTP status/saved field alone does not prove source, signature or remote
  acceptance. Keep observation/provenance/authorization distinct.
- Field presence is separate from NULL/zero/blank. Use the shared alias registry;
  an observation records alternatives without silently choosing their meaning.
- Financial-policy changes need explicit expected XML/accounting fixtures:
  discounts, mixed taxes/FX/rounding, returns and advance allocations.
- English docstrings explain purpose, invariants, dependencies and side effects.
  User summaries translate for display; retained internal states stay English.
  Never translate or expose raw authority/credential payloads.
- Version persistent contracts explicitly. Preserve golden bytes/fingerprints
  when refactoring helpers; do not regenerate goldens merely to pass a test.
- Each file needs a clear purpose, known callers or an explicit staging reason
  and integration/removal gate. Lack of an import is NOT evidence of dead code:
  Frappe hooks, RPC paths, JS, fixtures and external customizations use strings.
- Final cleanup includes a caller inventory, duplication/unused/static checks
  and documented compatibility wrappers. That complete audit is still pending.

## Tests and evidence

From the DEV worktree, local-only:
PYTHONDONTWRITEBYTECODE=1 ../../env/bin/python tools/run_unification_rehearsal.py

Add --private-sql for the reviewed owned temporary MariaDB suites. The active
guard is mandatory. Never replace the command with bench --site tests or point
fixtures at an existing database. Node VM frontend scripts use synthetic forms,
not an installed browser session. Report separately: unit mocks, native private
SQL, installed ERP integration, SDK and remote acceptance.

## Closing sequence before adoption

1. Complete dependencies: party/address/Company/device/POS profile/time/precision,
   tax templates and linked/archived advance evidence.
2. Capture effective field precision/default scopes and implement authorized
   committed capture with fixed columns, Singleton storage, stable locks,
   child membership/order checks and physical v15/v16 normalization.
3. Resolve the documented invoice/template priority discrepancy and establish
   amount/XML/GL/VAT parity without changing snapshot formats accidentally.
4. Integrate one actual pipeline behind existing entry points; finish whole-worker
   identity/transactions/custody/security and legacy continuity.
5. Finish file/dependency/quality audit, offline golden/SDK tests and performance
   evidence; freeze a candidate with install/upgrade/backup/rollback instructions.
6. Obtain separate approval for isolated installed v15/v16 fictional-data rehearsal
   with egress blocked; test the full documented success/failure matrix.
7. Present evidence and remaining risks for adoption/cancellation. Any customer
   pilot, deployment, migration and authority sending require their own approval.

Do not turn a generic 'continue' into permission to skip these gates.
