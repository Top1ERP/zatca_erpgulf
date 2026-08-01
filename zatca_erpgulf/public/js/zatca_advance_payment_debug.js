(function () {
    function should_show_create_button(frm) {
        return (
            !frm.is_new()
            && frm.doc.docstatus === 1
            && frm.doc.payment_type === "Receive"
            && frm.doc.party_type === "Customer"
            && flt(frm.doc.paid_amount) > 0
            && flt(frm.doc.total_allocated_amount) === 0
            && flt(frm.doc.unallocated_amount) === flt(frm.doc.paid_amount)
            && flt(frm.doc.total_taxes_and_charges) === 0
        );
    }

    function open_unsaved_sales_invoice(invoice) {
        if (!invoice) return;

        frappe.model.sync(invoice);
        frappe.set_route("Form", "Sales Invoice", invoice.name);
    }

    frappe.ui.form.on("Payment Entry", {
        refresh: function (frm) {
            if (!should_show_create_button(frm)) return;

            frm.add_custom_button(
                __("Create Advance Payment Invoice"),
                function () {
                    frappe.call({
                        method: "zatca_erpgulf.zatca_erpgulf.advance_payment_entry.create_advance_sales_invoice_from_payment_entry",
                        args: { payment_entry_name: frm.doc.name },
                        freeze: true,
                        freeze_message: __("Preparing Advance Payment Invoice..."),
                        callback: function (r) {
                            open_unsaved_sales_invoice(r.message);
                        }
                    });
                },
                __("Create")
            );
        }
    });
})();
