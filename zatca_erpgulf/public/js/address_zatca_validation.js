function zatca_address_check(frm) {
    frappe.call({
        method: "zatca_erpgulf.zatca_erpgulf.address_validation.get_zatca_address_validation_state",
        args: { doc: frm.doc },
        callback(r) { frm.__zatca_address_state = r.message || {}; },
    });
}

frappe.ui.form.on("Address", {
    refresh(frm) {
        if (frm.fields_dict.address_line1) {
            frm.set_df_property("address_line1", "label", __("Address in English"));
        }
        if (frm.fields_dict.address_line2) {
            frm.set_df_property("address_line2", "label", __("Short Address"));
        }
        zatca_address_check(frm);
    },
    country: zatca_address_check,
    is_your_company_address: zatca_address_check,
    address_line1: zatca_address_check,
    address_line2: zatca_address_check,
    custom_building_number: zatca_address_check,
    pincode: zatca_address_check,
    before_save(frm) {
        const state = frm.__zatca_address_state || {};
        if (state.scope !== "warning" || !state.errors || !state.errors.length || frm.__zatca_address_warning_confirmed) return;
        frappe.validated = false;
        const dialog = new frappe.ui.Dialog({
            title: __("ZATCA Address Validation"),
            fields: [{ fieldtype: "HTML", options: state.errors.map((item) => `• ${__(item)}`).join("<br>") }],
            primary_action_label: __("Continue"),
            primary_action() {
                frm.__zatca_address_warning_confirmed = true;
                dialog.hide();
                frm.save();
            },
        });
        dialog.set_secondary_action(() => dialog.hide());
        dialog.set_secondary_action_label(__("Return to edit"));
        dialog.show();
    },
});
