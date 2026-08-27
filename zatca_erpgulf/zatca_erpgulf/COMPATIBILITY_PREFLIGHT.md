# ZATCA Compatibility Preflight

## Purpose

`compatibility_preflight.py` is the read-only deployment gate for ZATCA releases on a multi-Site Bench. It compares the active Frappe metadata with physical SQL tables and columns without changing Site data or schema.

## Classification rules

- `SAFE_COMPLETE`: all marker, Payment Entry link, and advance-deduction capabilities are complete.
- `SAFE_PARTIAL`: only part of the optional schema is available; runtime guards disable unavailable behavior.
- `SAFE_LEGACY`: no new optional-schema footprint exists and legacy operation remains safe.
- `UNSAFE_STRUCTURAL`: metadata and SQL disagree in a way that can fail before runtime guards. Deployment is blocked.
- `NOT_APPLICABLE`: `zatca_erpgulf` is not installed on the Site.

Risk is reported independently: `CRITICAL` blocks deployment, `HIGH` means an optional feature is unavailable, `MEDIUM` means planned cleanup is recommended, and `INFO` identifies harmless state or residue.

## Deployment workflow

Run the module from the Bench environment before any release mutation and retain its JSON output as deployment evidence:

```bash
env/bin/python -m zatca_erpgulf.zatca_erpgulf.compatibility_preflight \
  --sites-path sites --format both
```

Exit code `1` means at least one Site is `UNSAFE_STRUCTURAL`: stop the deployment. Exit code `0` covers `SAFE_COMPLETE`, `SAFE_PARTIAL`, `SAFE_LEGACY`, and `NOT_APPLICABLE`. After any separately approved repair, rerun the gate and require exit code `0` before continuing the release.

## Interpreting results

Each Site result includes `classification`, `deployment_allowed`, `risk`, `runtime_capabilities`, `problems`, `root_causes`, and `repair_recommendations`. Problem `objects` and root-cause lists name every missing or mismatched field, column, DocType, and table. Recommendations are advisory only and include the reason, complexity, repair risk, and whether `reload-doc`, a patch, migration, or manual intervention may be required.

## Common repairs

- Missing child metadata field: use an approved targeted reload of the owning child DocType because the database metadata is older than the application JSON.
- Missing SQL table: use an approved DocType reload and schema migration path because document loading can reach the table before compatibility guards.
- Missing SQL column: reload the owning DocType/custom fields first; use a reviewed schema patch or migration only if normal synchronization does not create the column.
- Metadata present but SQL missing: treat this as an interrupted or incomplete schema synchronization; do not rely on runtime fallback.
- SQL present but metadata missing: treat it as orphan residue. Review it in a cleanup window and never drop it automatically from preflight output.
- Marker or Payment Entry mismatch: synchronize the exact authoritative field. The primary marker must not fall back to the legacy marker when primary metadata exists.

The preflight never performs repairs, reloads, patches, migrations, builds, or restarts.
