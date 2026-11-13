"""Frozen reconciliation classifier from 7906adf; test data only."""

def _is_tax_account(account_name, cache=None, default=True):
    """Return whether an Account is a tax account.

    An explicitly configured ``Tax`` account is always treated as a tax
    account. Some ERPNext sites leave ``account_type`` empty for retention,
    deduction, and other linked accounts; for those accounts, only a
    ``Liability`` root is considered a tax account. Existing accounts with
    any other root (for example ``Asset``) are non-tax rows and must not be
    included in VAT reconciliation. Unknown accounts retain the caller's
    fallback for backwards compatibility.
    """
    account_name = _safe_str(account_name)
    if not account_name:
        return False

    if cache is not None and account_name in cache:
        return cache[account_name]

    try:
        account_meta = frappe.db.get_value(
            "Account",
            account_name,
            ["account_type", "root_type"],
            as_dict=True,
        )
    except Exception:
        account_meta = None

    if not account_meta:
        # Preserve the existing conservative fallback only when the account
        # itself cannot be resolved. Existing accounts with a blank
        # account_type are classified using root_type below.
        result = default
    else:
        account_type = _safe_str(account_meta.get("account_type"))
        root_type = _safe_str(account_meta.get("root_type"))
        if account_type:
            result = account_type.casefold() == "tax"
        else:
            result = root_type.casefold() == "liability"

    if cache is not None:
        cache[account_name] = result
    return result
