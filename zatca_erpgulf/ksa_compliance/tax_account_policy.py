"""Legacy account eligibility for tax reconciliation, not exclusive VAT identity."""

# Cache an unresolved observation, rather than a caller's chosen fallback.
# This marker is private to an in-process, caller-owned cache; never persist it.
_UNRESOLVED_ACCOUNT = object()


def _text(value):
    return "" if value is None else str(value).strip()


def is_reconciliation_tax_account(account_name, *, read_account, cache=None, default=True):
    """Apply the existing Account type/root policy through an injected reader.

    Explicit Tax accounts qualify. A blank account_type uses Liability root;
    any other known account is excluded. This conservative reconciliation rule
    does not establish that a qualifying account contains VAT exclusively.

    Missing/unreadable records use each call's default. An optional local cache
    avoids rereading them without freezing that default. Existing prepopulated
    cache values remain authoritative. No cache is created or retained globally.
    Reader failures retain the legacy fallback; malformed truthy metadata still
    propagates its access error, rather than silently becoming an unknown account.
    """
    account_name = _text(account_name)
    if not account_name:
        return False

    if cache is not None and account_name in cache:
        observation = cache[account_name]
    else:
        try:
            account_meta = read_account(account_name)
        except Exception:
            account_meta = None

        if not account_meta:
            observation = _UNRESOLVED_ACCOUNT
        else:
            account_type = _text(account_meta.get("account_type"))
            root_type = _text(account_meta.get("root_type"))
            observation = (
                account_type.casefold() == "tax"
                if account_type else root_type.casefold() == "liability"
            )
        if cache is not None:
            cache[account_name] = observation

    return default if observation is _UNRESOLVED_ACCOUNT else observation
