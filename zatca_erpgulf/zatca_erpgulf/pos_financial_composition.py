"""Compose POS financial XML once while preserving imported integrations.

Default adapters share one preparation and an immutable rendering projection.
An overridden builder/helper or distinct runtime/rate/translation binding keeps
the public two-argument composition contract. No global financial cache, site
discovery, write, signing or authority operation belongs in this selector.
"""

from . import pos_final, posxml
from .document_tax_xml import DocumentTaxTools, populate_document_tax
from .pos_financial_xml import render_pos_section


def _bindings(module):
    """Observe current adapter dependencies, never a cached site context."""
    return module.frappe, module._, module.get_item_tax_rate


def populate_pos_financials(invoice, doc, *, namespace, has_template, use_item_result=True):
    """Append totals and items using the selected public integration contract.

    The historical template Compliance route ignores a custom item's returned
    root. Its caller passes use_item_result=False; ordinary routes accept it.
    Captured canonical identities are code references only, not source data.
    """
    discount_name = "add_document_level_discount_with_tax_template" if has_template else "add_document_level_discount_with_tax"
    tax_name = "tax_data_with_template" if has_template else "tax_data"
    item_name = "item_data_with_template" if has_template else "item_data"
    tax_module = pos_final if has_template else posxml
    factory = namespace.get("DocumentTaxTools", DocumentTaxTools)
    composer = namespace.get("populate_document_tax", populate_document_tax)
    tools = factory.from_namespace(namespace, has_template=has_template)
    item = namespace.get(item_name)

    canonical = (
        factory is DocumentTaxTools and type(tools) is DocumentTaxTools
        and tools.discount is posxml._CANONICAL_POS_BUILDERS[discount_name]
        and tools.tax is tax_module._CANONICAL_POS_BUILDERS[tax_name]
        and item is pos_final._CANONICAL_POS_BUILDERS[item_name]
        and composer is populate_document_tax
    )
    if canonical:
        tax_bindings, item_bindings = _bindings(tax_module), _bindings(pos_final)
        if all(left is right for left, right in zip(tax_bindings, item_bindings)):
            runtime, translate, read_rate = tax_bindings
            return render_pos_section(invoice, doc, has_template=bool(has_template),
                section="complete", runtime=runtime, translate=translate, read_rate=read_rate)

    # Integrations retain their original imported functions, dependency reads,
    # returned-root handling and failure order. Never discard an override.
    invoice = composer(invoice, doc, tools=tools)
    result = namespace[item_name](invoice, doc)
    return result if use_item_result else invoice
