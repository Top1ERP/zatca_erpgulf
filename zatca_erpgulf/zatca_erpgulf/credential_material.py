"""Pure credential field policies; no database, HTTP, or secret-bearing errors."""

from dataclasses import dataclass, field
from collections.abc import Mapping, Sequence


class CredentialConfigurationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class CredentialOwner:
    """Read-only projection of one saved credential owner; secrets stay out of repr."""

    company_name: str
    doctype: str
    name: str
    source_kind: str
    values: Mapping[str, object] = field(repr=False, compare=False)


@dataclass(frozen=True)
class ApiAuthorization:
    """Safe provenance and purpose, with a deliberately hidden header value."""

    owner_doctype: str
    owner_name: str
    source_kind: str
    purpose: str
    fieldname: str
    header: str = field(repr=False)


def use_linked_company(value) -> bool:
    """Respect an explicit false checkbox; never coerce arbitrary strings true."""
    if value is None or value is False or value == 0:
        return False
    if value is True or value == 1:
        return True
    if isinstance(value, str):
        if value.strip() in ("", "0"):
            return False
        if value.strip() == "1":
            return True
    raise CredentialConfigurationError("link_flag")


def certificate_value(values: Mapping, aliases: Sequence[str]) -> str:
    """Read registered spellings without silently choosing conflicting certificates.

    Whitespace-only differences may be equivalent, but do not rewrite the chosen
    text: the legacy digest code hashes those exact stored characters.
    """
    candidates = []
    for fieldname in aliases:
        value = values.get(fieldname)
        if value is None or value == "":
            continue
        if not isinstance(value, str):
            raise CredentialConfigurationError("certificate")
        if value.strip():
            candidates.append(value.strip())
    if not candidates:
        raise CredentialConfigurationError("certificate")
    if len({"".join(value.split()) for value in candidates}) != 1:
        raise CredentialConfigurationError("certificate_conflict")
    return candidates[0]


def authorization_for_owner(owner: CredentialOwner, purpose: str) -> ApiAuthorization:
    """Select one purpose-specific field; never fall back across credential types."""
    if purpose == "compliance":
        fieldname = "custom_basic_auth_from_csid"
    elif purpose == "production":
        fieldname = (
            "custom_final_auth_csid" if owner.doctype == "ZATCA Multiple Setting"
            else "custom_basic_auth_from_production"
        )
    else:
        raise CredentialConfigurationError("purpose")
    value = owner.values.get(fieldname)
    if not isinstance(value, str) or not value.strip():
        raise CredentialConfigurationError("authorization")
    value = value.strip()
    parts = value.split(None, 1)
    if parts[0].lower() == "basic":
        value = parts[1] if len(parts) == 2 else ""
    token = "".join(value.split())
    if not token:
        raise CredentialConfigurationError("authorization")
    return ApiAuthorization(
        owner.doctype, owner.name, owner.source_kind, purpose, fieldname, "Basic " + token,
    )
