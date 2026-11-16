"""Choose item-template mode from invoice rows, never a request-side hint.

Presence retains native truthiness: no trimming, template/account discovery or
rate/category inference. This only selects an existing XML builder family.
"""


REVIEW = "The item tax template selection could not be verified. Use an Item Tax Template on every item or leave it blank on every item, then save and retry."


class ItemTemplateModeError(ValueError):
    """Static source code only; do not retain item names or template values."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def item_template_mode(rows):
    """Read a native list once; stop on the first mixed presence observation.

    Empty/absent tables select plain mode, not proof of a valid invoice. Linked
    template existence, rates, accounts, categories and money remain downstream.
    """
    if rows is None:
        return False
    if not isinstance(rows, (list, tuple)):
        raise ItemTemplateModeError("item_template_rows")
    selected = None
    for row in rows:
        if row is None or isinstance(row, (str, bytes, bool, int, float)):
            raise ItemTemplateModeError("item_template_row")
        value = row.get("item_tax_template") if isinstance(row, dict) else getattr(row, "item_tax_template", None)
        present = bool(value)
        if selected is not None and selected != present:
            raise ItemTemplateModeError("item_template_mixed")
        selected = present
    return bool(selected)
