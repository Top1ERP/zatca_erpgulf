(function () {

    function clear_copied_advance_fields(frm) {
        const fields = {
            custom_zatca_is_advance_payment: 0,
            custom_zatca_advance_tax_invoice: "",
            custom_zatca_advance_invoice_status: "Not Created",
            custom_zatca_advance_invoice_uuid: "",
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
            "custom_zatca_is_advance_payment"
        ].forEach(function (fieldname) {
            if (frm.fields_dict[fieldname]) {
                frm.set_df_property(fieldname, "hidden", 1);
            }
        });
    }

    function should_show_create_button(frm) {
        return !frm.is_new() && frm.doc.docstatus !== 2 && frm.doc.payment_type === "Receive";
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

            if (!should_show_create_button(frm)) {
                return;
            }

            frm.add_custom_button(
                __("Create ZATCA Advance XML for Debug"),
                function () {
                    frappe.call({
                        method: "zatca_erpgulf.zatca_erpgulf.advance_payment_debug.create_advance_xml_for_debug",
                        args: { payment_entry_name: frm.doc.name },
                        freeze: true,
                        freeze_message: __("Creating ZATCA advance debug XML..."),
                        callback: function (r) {
                            if (!r.message) return;

                            frm.reload_doc();

                            frappe.msgprint({
                                title: __("ZATCA Advance XML Debug"),
                                indicator: "green",
                                message:
                                    __("ZATCA Advance Tax Invoice was created/updated and debug XML was attached successfully.") +
                                    "<br><br>" +
                                    `<b>${__("Advance Tax Invoice")}:</b> ${r.message.advance_tax_invoice}` +
                                    "<br>" +
                                    `<a href="/app/zatca-advance-tax-invoice/${r.message.advance_tax_invoice}" target="_blank">${__("Open Advance Tax Invoice")}</a>` +
                                    "<br>" +
                                    `<a href="${r.message.file_url}" target="_blank">${__("Open XML")}</a>`,
                            });
                        },
                    });
                },
                __("ZATCA")
            );
        },
    });
})();
