"""Exact pre-fix discount guard statements from c2de512; test data only."""

def zatca_background_discount_guards(sales_invoice_doc, tax_categories, base_discount_amount):
    if len(tax_categories) > 1 and base_discount_amount > 0:
        frappe.throw(_('As per ZATCA regulations, ZATCA does not respond for multiple items with multiple tax categories with doc-level discount. Please ensure all items have the same tax category.'))
    if base_discount_amount > 0 and sales_invoice_doc.apply_discount_on != 'Net Total' and (not _use_line_net_amounts_discount_model(sales_invoice_doc)):
        frappe.throw(_('As per ZATCA regulations,You cannot put discount on Grand total as the tax is already calculated. Please make sure your discount is in Net total field.'))

def zatca_background_on_submit_discount_guards(sales_invoice_doc, tax_categories, base_discount_amount):
    if len(tax_categories) > 1 and base_discount_amount > 0:
        frappe.throw(_('As per ZATCA regulations, ZATCA does not respond for multiple items with multiple tax categories and a document-level discount. Please ensure all items have the same tax category.'))
    if base_discount_amount > 0 and sales_invoice_doc.apply_discount_on != 'Net Total' and (not _use_line_net_amounts_discount_model(sales_invoice_doc)):
        frappe.throw(_('As per ZATCA regulations,You cannot apply a discount on the Grand Total as the tax is already calculated. Please apply your discount on the Net Total.'))
