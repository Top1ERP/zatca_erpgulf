"""Pure, fail-closed API routing shared by legacy submission entry points.

Environment and API operation are independent: onboarding can run in Production
without being a live invoice submission. This module identifies the required
credential purpose, but deliberately neither loads credentials nor sends HTTP.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit


ENVIRONMENT_FIELDS = {
    "Sandbox": "custom_sandbox_url",
    "Simulation": "custom_simulation_url",
    "Production": "custom_production_url",
}

# Paths already used by this application. Unknown paths must be added with a
# deliberate purpose/credential contract instead of arbitrary URL concatenation.
OPERATION_CREDENTIALS = {
    "compliance": "otp",
    "compliance/invoices": "compliance",
    "production/csids": "compliance",
    "invoices/reporting/single": "production",
    "invoices/clearance/single": "production",
}

GATEWAY_PATHS = {
    "Sandbox": "/e-invoicing/developer-portal",
    "Simulation": "/e-invoicing/simulation",
    "Production": "/e-invoicing/core",
}


class ApiConfigurationError(ValueError):
    """A safe error code; never include configured URLs or credential material."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ApiRoute:
    """Immutable routing decision, not a loaded or validated credential bundle."""

    environment: str
    endpoint: str
    base_url_field: str
    required_credential: str
    url: str


def resolve_api_route(
    settings: Mapping[str, object],
    endpoint: str,
    *,
    environment: str | None = None,
    onboarding_only: bool = False,
) -> ApiRoute:
    """Resolve explicit settings without treating blank/unknown values as live.

    An omitted override uses Company settings; an explicitly blank override is
    invalid. HTTPS custom gateways remain supported, but their environment
    mapping cannot be inferred here. The standard gateway paths are checked
    against the selected environment so swapped Company URL fields fail closed.
    """
    selected = settings.get("custom_select") if environment is None else environment
    selected = selected.strip() if isinstance(selected, str) else ""
    if selected not in ENVIRONMENT_FIELDS:
        raise ApiConfigurationError("environment")

    operation = endpoint.strip().strip("/") if isinstance(endpoint, str) else ""
    if operation not in OPERATION_CREDENTIALS:
        raise ApiConfigurationError("operation")
    credential = OPERATION_CREDENTIALS[operation]
    if onboarding_only and credential == "production":
        raise ApiConfigurationError("onboarding_operation")

    field = ENVIRONMENT_FIELDS[selected]
    raw_base = settings.get(field)
    base = raw_base.strip() if isinstance(raw_base, str) else ""
    if not base or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in base):
        raise ApiConfigurationError("base_url")
    try:
        parsed = urlsplit(base)
        port = parsed.port
    except ValueError:
        raise ApiConfigurationError("base_url") from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or any(char in base for char in ("?", "#", "\\"))
        or "%" in parsed.path
        or "%" in parsed.hostname
        or "//" in parsed.path
        or any(part in (".", "..") for part in parsed.path.split("/"))
        or port == 0
    ):
        raise ApiConfigurationError("base_url")

    if parsed.hostname.lower().rstrip(".") == "gw-fatoora.zatca.gov.sa":
        if parsed.path.rstrip("/") != GATEWAY_PATHS[selected] or port not in (None, 443):
            raise ApiConfigurationError("environment_url")

    return ApiRoute(
        environment=selected,
        endpoint=operation,
        base_url_field=field,
        required_credential=credential,
        url=base.rstrip("/") + "/" + operation,
    )
