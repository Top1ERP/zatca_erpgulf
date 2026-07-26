(function () {
    function clear_copied_advance_fields(frm) {
        const fields = {
            custom_zatca_is_advance_payment: 0,
            custom_zatca_advance_tax_invoice: "",
            custom_zatca_advance_invoice_status: "Not Created",
            custom_zatca_advance_invoice_uuid: "",
            custom_zatca_advance_qr_code: "",
            custom_zatca_advance_xml: "",
            custom_zatca_advance_last_debug_at: "",
            custom_zatca_advance_full_response: "",
        };

        Object.keys(fields).forEach(function (fieldname) {
            if (frm.fields_dict[fieldname]) {
                frm.set_value(fieldname, fields[fieldname]);
            }
        });
    }

    function hide_technical_fields(frm) {
        [
            "custom_zatca_is_advance_payment",
            "custom_zatca_advance_xml",
            "custom_zatca_advance_last_debug_at",
            "custom_zatca_advance_full_response"
        ].forEach(function (fieldname) {
            if (frm.fields_dict[fieldname]) {
                frm.set_df_property(fieldname, "hidden", 1);
            }
        });
    }

    function should_show_issue_button(frm) {
        return (
            !frm.is_new()
            && frm.doc.docstatus === 1
            && frm.doc.payment_type === "Receive"
            && frm.doc.party_type === "Customer"
            && flt(frm.doc.unallocated_amount) > 0
            && !frm.doc.custom_zatca_advance_tax_invoice
        );
    }

    frappe.ui.form.on("Payment Entry", {
        onload: function (frm) {
            hide_technical_fields(frm);

            if (frm.is_new()) {
                clear_copied_advance_fields(frm);
            }
        },

        refresh: function (frm) {
            hide_technical_fields(frm);

            if (frm.doc.custom_zatca_advance_tax_invoice) {
                frm.add_custom_button(
                    __("Open ZATCA Advance Tax Invoice"),
                    function () {
                        frappe.set_route("Form", "ZATCA Advance Tax Invoice", frm.doc.custom_zatca_advance_tax_invoice);
                    },
                    __("ZATCA")
                );
            }

            if (!should_show_issue_button(frm)) {
                return;
            }

            frm.add_custom_button(
                __("Issue ZATCA Advance Tax Invoice"),
                function () {
                    frappe.confirm(
                        __("Issue a local Phase 1 ZATCA Advance Tax Invoice from this submitted Payment Entry?"),
                        function () {
                            frappe.call({
                                method: "zatca_erpgulf.zatca_erpgulf.advance_payment_debug.issue_advance_tax_invoice_from_payment_entry",
                                args: { payment_entry_name: frm.doc.name },
                                freeze: true,
                                freeze_message: __("Issuing ZATCA Advance Tax Invoice..."),
                                callback: function (r) {
                                    if (!r.message) return;

                                    frm.reload_doc();

                                    frappe.msgprint({
                                        title: __("ZATCA Advance Tax Invoice Issued"),
                                        indicator: "green",
                                        message:
                                            __("ZATCA Advance Tax Invoice was issued successfully.") +
                                            "<br><br>" +
                                            `<b>${__("Advance Tax Invoice")}:</b> ${r.message.advance_tax_invoice}` +
                                            "<br>" +
                                            `<a href="/app/zatca-advance-tax-invoice/${r.message.advance_tax_invoice}" target="_blank">${__("Open Advance Tax Invoice")}</a>`
                                    });
                                }
                            });
                        }
                    );
                },
                __("ZATCA")
            );
        },
    });
})();
