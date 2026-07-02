frappe.ui.form.on("ZATCA Advance Tax Invoice", {
    refresh: function (frm) {
        if (frm.is_new()) return;

        frm.dashboard.clear_headline();

        if (frm.doc.zatca_status) {
            const color = {
                "Cleared": "green",
                "Reported": "green",
                "Failed": "red",
                "Warning": "orange",
                "Debug XML Created": "blue",
                "Preflight Passed": "blue",
                "Not Submitted": "gray"
            }[frm.doc.zatca_status] || "gray";

            frm.dashboard.set_headline_alert(
                `<b>ZATCA Status:</b> ${frappe.utils.escape_html(frm.doc.zatca_status)}`,
                color
            );
        }

        if (frm.doc.payment_entry) {
            frm.add_custom_button(__("Open Payment Entry"), function () {
                frappe.set_route("Form", "Payment Entry", frm.doc.payment_entry);
            }, __("Connections"));
        }

        frm.add_custom_button(__("Validate for ZATCA"), function () {
            frappe.call({
                method: "zatca_erpgulf.zatca_erpgulf.advance_payment_debug.validate_advance_for_zatca",
                args: { advance_invoice_name: frm.doc.name },
                freeze: true,
                freeze_message: __("Validating ZATCA data..."),
                callback: function () {
                    frm.reload_doc();
                    frappe.show_alert({ message: __("Preflight validation passed."), indicator: "green" });
                }
            });
        }, __("ZATCA"));

        if (frm.doc.status === "Draft") {
            frm.add_custom_button(__("Finalize"), function () {
                frappe.confirm(__("Finalize this advance tax invoice?"), function () {
                    frappe.call({
                        method: "zatca_erpgulf.zatca_erpgulf.advance_payment_debug.finalize_advance_tax_invoice",
                        args: { advance_invoice_name: frm.doc.name },
                        freeze: true,
                        freeze_message: __("Finalizing..."),
                        callback: function () { frm.reload_doc(); }
                    });
                });
            }, __("ZATCA"));
        }

        if (frm.doc.status === "Final" && !["Cleared", "Reported"].includes(frm.doc.zatca_status)) {
            frm.add_custom_button(__("Send to ZATCA"), function () {
                frappe.call({
                    method: "zatca_erpgulf.zatca_erpgulf.advance_payment_debug.send_advance_to_zatca",
                    args: { advance_invoice_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __("Sending to ZATCA..."),
                    callback: function () { frm.reload_doc(); }
                });
            }, __("ZATCA"));
        }

        if (frm.doc.zatca_status === "Failed") {
            frm.add_custom_button(__("Retry Send"), function () {
                frappe.call({
                    method: "zatca_erpgulf.zatca_erpgulf.advance_payment_debug.retry_advance_zatca_submission",
                    args: { advance_invoice_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __("Retrying ZATCA submission..."),
                    callback: function () { frm.reload_doc(); }
                });
            }, __("ZATCA"));
        }

        const locked = frm.doc.status === "Final" || ["Submitted", "Cleared", "Reported"].includes(frm.doc.zatca_status);
        if (!locked || frappe.user.has_role("System Manager")) {
            frm.add_custom_button(__("Delete and Unlink Payment Entry"), function () {
                frappe.confirm(__("This will delete this ZATCA Advance Tax Invoice, remove its XML attachment, and clear the linked Payment Entry fields. Continue?"), function () {
                    frappe.call({
                        method: "zatca_erpgulf.zatca_erpgulf.advance_payment_debug.delete_advance_tax_invoice",
                        args: { advance_invoice_name: frm.doc.name },
                        freeze: true,
                        freeze_message: __("Deleting and unlinking..."),
                        callback: function (r) {
                            if (r.message && r.message.deleted) {
                                frappe.show_alert({ message: __("Deleted and unlinked successfully."), indicator: "green" });
                                frappe.set_route("List", "ZATCA Advance Tax Invoice");
                            }
                        }
                    });
                });
            }, __("ZATCA"));
        }
    },

    tc_name: function (frm) {
        if (!frm.doc.tc_name) return;

        frappe.db.get_value("Terms and Conditions", frm.doc.tc_name, "terms").then((r) => {
            if (r.message && r.message.terms) {
                frm.set_value("terms", r.message.terms);
            }
        });
    }
});
