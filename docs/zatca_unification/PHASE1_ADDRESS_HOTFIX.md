# Authorized current-version Phase-1 address hotfix

2026-10-28. Explicit user exception to the otherwise offline-only mandate.

The user requested this specific correction in the installed CURRENT version
for ALL sites on the shared Bench, and separately in DEV. They explicitly did
not authorize deploying or merging the development version into working sites.
All authority requests remain forbidden.

## Change and deployed identity

`customer_address.validate_customer_address_for_zatca` now returns before loading
the buyer/address when the already enabled Company resolves to known `Phase-1`.
It reuses the existing phase resolver, including legacy field compatibility.
Phase-2 non-B2C missing-address validation, B2C exemption and successful address
resolution retain their behavior. Missing/unknown resolved phases retain the old
check; they do not silently acquire the Phase-1 exemption. Ordinary ERPNext
validation and detailed XML/signing checks were not changed.

This is an integration preflight correction, not a statement that every Phase-1
tax invoice is legally exempt from buyer-address requirements.

- Previous installed baseline: `2e97708e115e31c675182647d10829d6175e7449`.
- Independent live hotfix: `ba51f2587763a4e9db045f57e1b8ee2bc29ea77c`.
- Installed branch: `hotfix/phase1-address-preflight-20261028` (local branch).
- Exactly ONE changed file from that live baseline:
  `zatca_erpgulf/zatca_erpgulf/customer_address.py`.
- Installed/fixed DEV source SHA256:
  `d4360df7195ac4e3e63d74f005c000a3adadaa55caa7681cd1de1b058d4f7f01`.

The hotfix was prepared in a detached isolated checkout of the old baseline,
tested before deployment, and installed by selecting the independent hotfix
branch. No development commit, schema, provider, handler or cache service was
copied into the installed app. No per-site exception/configuration flag was added.

## Validation and activation

The fixed current-version and DEV address modules were byte-identical; the phase
and enablement helper ASTs also matched. Fourteen new synthetic policy cases plus
four existing address-resolution cases passed: **18 in 0.09 seconds**, under the
offline network/site-init guard. Cases cover Sales/POS, both phases, legacy
priority, disabled integration, unknown phase, B2C and address result preservation.

A protected source backup/manifest was created outside app Git before deployment:
`.operations/hotfix-backups/phase1-address-20261028T122350Z` under the Bench, with
private directory/file permissions. It contains code and baseline/hash information;
site configurations, credentials and customer data were not copied or modified.

Only the supervised Gunicorn web process received graceful HUP. The master stayed
RUNNING and logs recorded six new workers and old worker exits. Cold web/RQ
imports with site initialization blocked confirmed this app validator is lazy,
not preloaded by those imports. Queue workers, scheduler, Redis and Bench were
not restarted. No invoice was submitted, validated through live document events
or sent to an authority. A read-only `frappe.ping` on dar-ana returned HTTP200/pong.
That health check is not evidence of a successful real invoice issuance.

## Rollback and ongoing mandate

The prior baseline branch/commit and protected source backup remain available.
Any rollback must restore only this reviewed source change and reload web workers;
do not restore a customer database or merge DEV as a rollback shortcut.

The installed source is now intentionally pinned to this one-file hotfix rather
than the old frozen hash. Future generic "continue" instructions authorize DEV
work only, not further live fixes, migrations, cache/provider activation, restarts
or authority calls. Every other development/fictional-Company/pilot gate in
[SAFETY_AND_REHEARSAL.md](SAFETY_AND_REHEARSAL.md) remains in force.
