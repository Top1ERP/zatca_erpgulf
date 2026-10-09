# Shared API routing — increment 3

## Implemented boundary

`api_routing.resolve_api_route` is a framework-independent resolver returning a
frozen `ApiRoute`. `api_settings.get_company_api_route` reads Company routing
fields and translates configuration errors. All six old `get_api_url` entry
points delegate to it; their names and arguments remain available to importers.
The dedicated `get_compliance_api_url` additionally permits onboarding only.

The route records environment, endpoint, base URL field, and required credential
purpose. It **does not load, select, verify, or rotate the actual credentials**.
Cryptographic/key ownership unification is the next increment, not a completed
property of this route object.

| Existing operation | Required credential purpose | Permitted through onboarding helper |
| --- | --- | --- |
| `compliance` | OTP | Yes |
| `compliance/invoices` | Compliance CSID | Yes |
| `production/csids` | Compliance CSID | Yes |
| `invoices/reporting/single` | Production CSID | No |
| `invoices/clearance/single` | Production CSID | No |

These mappings preserve the application's existing operations. Every operation
can be resolved in the explicitly selected Sandbox, Simulation, or Production
environment; the name `production/csids` does not itself force an environment
switch. Normal Production onboarding remains supported without switching Company
to Sandbox. These are routing contracts, not proof of remote API authorization.

## Intentional configuration behavior changes

- A missing, blank, misspelled, or unknown environment is an error, not an
  implicit Production selection. Environment names are case-sensitive Select
  values; surrounding whitespace is removed.
- An omitted onboarding override uses Company selection. An explicitly empty
  override is rejected. A valid override does not save or change Company.
- Base URLs require HTTPS, a host, and an unambiguous path. User information,
  queries, fragments, controls, path traversal, and malformed ports are rejected.
- Surrounding whitespace and the joining slash are normalized consistently,
  including the leading space in the historical Production URL fixture.
- For `gw-fatoora.zatca.gov.sa`, the selected base must match the existing app
  fixture mapping: developer-portal for Sandbox, simulation for Simulation, core
  for Production. This catches swapped base URL fields before an HTTP request.
- Custom HTTPS gateways are retained for compatibility. Their internal routing,
  trustworthiness, and environment mapping cannot be verified from a URL alone;
  an administrator must review them before deployment. This is not a host
  allowlist, network reachability check, or certificate-environment validator.
- Unknown operation paths cannot be passed through as arbitrary URL suffixes.
  Add new operations explicitly with their credential-purpose tests.

No Company fields, fixtures, schema, or credential values are automatically
rewritten. There is no silent migration from blank selection to Production.

## Verification and release gate

The initial legacy-boundary run had 38 failing cases and 18 passing cases:
unknown/blank selections, inconsistent whitespace joining, and onboarding helpers
accepting live invoice endpoints. The new pure and mocked-boundary tests cover
all existing operations/environments, override behavior, invalid bases, swapped
gateway paths, safe error messages, and route immutability.

Mocked Company CSR creation, Compliance checks, and final-CSID requests verify
the actual URL/header boundary. Invalid configuration prevents requests; it is
checked before displaying the CSR/final-CSID loading indicator. No actual OTP,
certificate, API request, or tenant was used in these tests.

Before deployment, run a read-only per-Company preflight for Phase-2/onboarding
users: explicit valid selection, selected URL, custom gateway trust, and required
credential provenance. Blank legacy configurations will now block requests and
must be reviewed by the operator, not auto-filled. Inspect external integrations
that call these internal helpers with nonstandard suffixes or HTTP proxy URLs.

The generic compatibility helpers still accept all five known operations. Only
the dedicated onboarding helper enforces the onboarding-only subset. Legacy
nonzero-compliance branches, credential aliases, signing identity, HTTP response
handling outside Compliance, and v16 transaction behavior remain separately gated.
In existing live flows, route resolution can occur after XML preparation and
identity allocation. This increment blocks an invalid HTTP destination; moving
the full preflight ahead of all live side effects requires the service/context
integration and transaction tests planned next.
