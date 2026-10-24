"""Pure bounded field presence, not credential validity or rotation permission."""


def classify_saved_credential_presence(values, fields):
    """Inspect an exact app-owned projection without coercing private values.

    Only None/exact empty text is absent. Whitespace/masked/invalid text remains
    present. Unknown shape/types fail closed; never parse, stringify or export
    material. EMPTY is an observation, not proof of no previous remote issuance.
    """
    if (type(fields) is not tuple or not 1 <= len(fields) <= 16
            or any(type(name) is not str or not 1 <= len(name) <= 140
                   or not name.isascii() or not name.isidentifier() for name in fields)
            or len(set(fields)) != len(fields)):
        return "UNKNOWN"
    if (type(values) is not dict or len(values) != len(fields)
            or any(type(name) is not str for name in values) or set(values) != set(fields)):
        return "UNKNOWN"
    if any(value is not None and type(value) is not str for value in values.values()):
        return "UNKNOWN"
    return "PRESENT" if any(type(value) is str and value != "" for value in values.values()) else "EMPTY"
