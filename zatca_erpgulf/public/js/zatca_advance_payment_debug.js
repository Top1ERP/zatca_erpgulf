(function () {
    function should_show_button(frm) {
        return !frm.is_new() && frm.doc.docstatus !== 2 && frm.doc.payment_type === "Receive";
    }

    frappe.ui.form.on("Payment Entry", {
        refresh: function (frm) {
            if (!should_show_button(frm)) {
                return;
            }

            frm.add_custom_button(
                __("Create ZATCA Advance XML for Debug"),
                function () {
                    frappe.call({
                        method: "zatca_erpgulf.zatca_erpgulf.advance_payment_debug.create_advance_xml_for_debug",
                        args: {
                            payment_entry_name: frm.doc.name,
                        },
                        freeze: true,
                        freeze_message: __("Creating ZATCA advance debug XML..."),
                        callback: function (r) {
                            if (!r.message) {
                                return;
                            }

                            frm.reload_doc();

                            frappe.msgprint({
                                title: __("ZATCA Advance XML Debug"),
                                indicator: "green",
                                message:
                                    __("Debug XML was created and attached successfully.") +
                                    "<br><br>" +
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
