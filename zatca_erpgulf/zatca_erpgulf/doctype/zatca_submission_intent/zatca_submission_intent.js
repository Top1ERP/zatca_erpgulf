// An explicit local review action; no authority submission or automatic retry.
frappe.ui.form.on("ZATCA Submission Intent", {
    refresh(frm) {
        frm.remove_custom_button(__("Retire Unissued Request"));
        if (frm.is_new() || !(frappe.user_roles || []).includes("System Manager") ||
            !["READY", "WAITING", "RUNNING", "REVIEW"].includes(frm.doc.state)) return;
        frm.add_custom_button(__("Retire Unissued Request"), () => {
            if (frm.is_dirty()) return;
            const record_id = frm.doc.name;
            const expected_state = frm.doc.state;
            const expected_fence = frm.doc.fence_token || null;
            frappe.confirm(__("Retire this local request only if no invoice was generated? Its history will remain, and an issued document cannot be retired here."), () => {
                if (frm.doc.name !== record_id || frm.is_dirty()) return;
                frappe.call({
                    method: "zatca_erpgulf.zatca_erpgulf.submission_intent_retirement.retire_request",
                    args: {record_id, expected_state, expected_fence},
                    freeze: true,
                    callback(r) {
                        if (frm.doc.name === record_id && r.message && r.message.status === "RETIRED") {
                            frappe.msgprint(r.message.message);
                            frm.reload_doc();
                        }
                    }
                });
            });
        });
    }
});
