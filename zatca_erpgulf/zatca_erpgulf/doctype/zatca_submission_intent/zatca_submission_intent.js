// Explicit local review actions; no authority submission or automatic retry.
frappe.ui.form.on("ZATCA Submission Intent", {
    refresh(frm) {
        const actions = [
            {
                label: "Retire Unissued Request", states: ["STAGED", "READY", "WAITING", "RUNNING", "REVIEW"],
                confirmation: "Retire this local request only if no invoice was generated? Its history will remain, and an issued document cannot be retired here.",
                method: "zatca_erpgulf.zatca_erpgulf.submission_intent_retirement.retire_request", terminal: "RETIRED"
            },
            {
                label: "Reconcile Saved Result", states: ["RUNNING", "REVIEW"],
                confirmation: "Complete this stopped request only from its saved original and matching response, without generating or sending anything?",
                method: "zatca_erpgulf.zatca_erpgulf.submission_intent_reconciliation.reconcile_request", terminal: "COMPLETE"
            }
        ];
        for (const action of actions) frm.remove_custom_button(__(action.label));
        if (frm.is_new() || !(frappe.user_roles || []).includes("System Manager")) return;
        for (const action of actions) {
            if (!action.states.includes(frm.doc.state)) continue;
            frm.add_custom_button(__(action.label), () => {
                if (frm.is_dirty()) return;
                const record_id = frm.doc.name;
                const expected_state = frm.doc.state;
                const expected_fence = frm.doc.fence_token || null;
                frappe.confirm(__(action.confirmation), () => {
                    if (frm.doc.name !== record_id || frm.is_dirty()) return;
                    frappe.call({
                        method: action.method,
                        args: {record_id, expected_state, expected_fence}, freeze: true,
                        callback(r) {
                            if (frm.doc.name === record_id && r.message && r.message.status === action.terminal) {
                                frappe.msgprint(r.message.message);
                                frm.reload_doc();
                            }
                        }
                    });
                });
            });
        }
    }
});
