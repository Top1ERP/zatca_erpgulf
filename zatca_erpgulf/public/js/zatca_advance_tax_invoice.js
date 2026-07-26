frappe.ui.form.on("ZATCA Advance Tax Invoice", {
    refresh: function (frm) {
        if (frm.is_new()) return;

        frm.dashboard.clear_headline();

        if (frm.doc.zatca_status) {
            const color = {
                "Cleared": "green",
                "Reported": "green",
                "Phase 1 QR Created": "green",
                "Failed": "red",
                "Warning": "orange",
                "Debug XML Created": "blue",
                "Preflight Passed": "blue",
                "Not Submitted": "gray"
            }[frm.doc.zatca_status] || "gray";

            frm.dashboard.set_headline_alert(
                `<b>${__("ZATCA Status")}:</b> ${frappe.utils.escape_html(__(frm.doc.zatca_status))}`,
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
            frm.add_custom_button(__("Finalize and Generate QR Code"), function () {
                frappe.confirm(__("Finalize this advance tax invoice and generate the Phase 1 QR Code?"), function () {
                    frappe.call({
                        method: "zatca_erpgulf.zatca_erpgulf.advance_payment_debug.finalize_advance_tax_invoice",
                        args: { advance_invoice_name: frm.doc.name },
                        freeze: true,
                        freeze_message: __("Finalizing and generating QR Code..."),
                        callback: function (r) {
                            frm.reload_doc();
                            if (r.message && r.message.qr_code) {
                                frappe.show_alert({ message: __("QR Code generated successfully."), indicator: "green" });
                            }
                        }
                    });
                });
            }, __("ZATCA"));
        }

        if (frm.doc.status === "Final" && !["Cleared", "Reported", "Phase 1 QR Created"].includes(frm.doc.zatca_status)) {
            frappe.db.get_value(
                "Company",
                frm.doc.company,
                [
                    "custom_zatca_advance_payment_submission_mode",
                    "custom_zatca_advance_signing_enabled",
                    "custom_zatca_advance_api_submission_enabled"
                ]
            ).then((r) => {
                const c = r.message || {};
                if (
                    c.custom_zatca_advance_payment_submission_mode === "Submit to ZATCA"
                    && cint(c.custom_zatca_advance_signing_enabled)
                    && cint(c.custom_zatca_advance_api_submission_enabled)
                ) {
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
            });
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

        const locked = frm.doc.status === "Final" || ["Submitted", "Cleared", "Reported", "Phase 1 QR Created"].includes(frm.doc.zatca_status);
        if (!locked || frappe.user.has_role("System Manager")) {
            frm.add_custom_button(__("Delete and Unlink Payment Entry"), function () {
                frappe.confirm(__("This will delete this ZATCA Advance Tax Invoice, remove its attachments, and clear the linked Payment Entry fields. Continue?"), function () {
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

frappe.ui.form.on("ZATCA Advance Tax Invoice", {
	before_cancel(frm) {
		const zatca_status = String(frm.doc.zatca_status || "").toUpperCase().replaceAll("-", " ");
		const status = String(frm.doc.status || "").toUpperCase().replaceAll("-", " ");

		const protected_statuses = [
			"REPORTED",
			"CLEARED",
			"PHASE 2 REPORTED",
			"PHASE 2 CLEARED",
			"PHASE 2 CLEARANCE",
			"PHASE 2 REPORTING",
			"PHASE 1 QR CREATED",
			"PHASE 1 QR GENERATED",
			"FINAL",
			"SUBMITTED"
		];

		const is_protected =
			protected_statuses.includes(zatca_status) ||
			protected_statuses.includes(status);

		if (!is_protected) {
			return;
		}

		if (!frappe.user.has_role("System Manager")) {
			frappe.throw(
				__(
					"Only System Manager or Administrator can force-cancel a reported/cleared/protected ZATCA Advance Tax Invoice."
				)
			);
		}

		return new Promise((resolve, reject) => {
			frappe.confirm(
				__(
					"This ZATCA Advance Tax Invoice may already be reported, cleared, or protected by ZATCA rules.<br><br>" +
					"This cancellation is internal in the system only. It does not reverse, cancel, amend, or notify ZATCA about the reported/cleared invoice.<br><br>" +
					"If this advance invoice is linked to another active transaction, the system will block cancellation.<br><br>" +
					"Do you want to continue?"
				),
				() => resolve(),
				() => reject()
			);
		});
	}
});
