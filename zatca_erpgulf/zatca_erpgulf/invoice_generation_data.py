"""Share early template validation and checked metadata results.

Default metadata still returns three values. Only this internal composition
requests the fourth, already checked mode. Imported replacements keep their
original call contract and a post-return mode check; they are not trusted source
or transaction capabilities. No namespace or record is cached across calls.
"""

from . import createxml, posxml


def prepare_invoice_generation(invoice, invoice_number, *, namespace, doctype,
                               purpose="production"):
    """Return root, UUID, loaded document and source-owned template mode.

    Canonical fast-path requires the same current runtime, translator and mode
    reader. Never add a private keyword to an integration's replacement function
    or discard its returned root/document. A replacement may already perform
    writes: the post-return check cannot certify or undo its side effects.
    """
    if doctype not in ("Sales Invoice", "POS Invoice") or purpose not in ("production", "debug"):
        raise ValueError("invoice_generation_purpose")
    adapter = createxml if doctype == "Sales Invoice" else posxml
    metadata = namespace["salesinvoice_data"]
    if (
        metadata is adapter._CANONICAL_INVOICE_METADATA
        and adapter.frappe is namespace["frappe"]
        and adapter._ is namespace["_"]
        and adapter.resolve_invoice_template_mode is namespace["resolve_invoice_template_mode"]
    ):
        return metadata(invoice, invoice_number, purpose=purpose, _include_template_mode=True)
    if purpose == "production":
        root, uuid, doc = metadata(invoice, invoice_number)
    else:
        root, uuid, doc = metadata(invoice, invoice_number, purpose=purpose)
    mode = namespace["resolve_invoice_template_mode"](doc,
        runtime=namespace["frappe"], translate=namespace["_"])
    return root, uuid, doc, mode
