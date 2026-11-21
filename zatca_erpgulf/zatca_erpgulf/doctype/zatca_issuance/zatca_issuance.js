// A deliberate manual first-send request; no automatic action on refresh.
frappe.ui.form.on("ZATCA Issuance", {
    refresh(frm) {
        frm.remove_custom_button(__("Queue Saved Original"));
        frm.remove_custom_button(__("Review Late Acceptance"));
        if (frm.is_new() || !(frappe.user_roles || []).includes("System Manager")) return;
        if (["DISPATCHING", "OUTCOME_UNKNOWN"].includes(frm.doc.state) && frm.doc.active_attempt) {
            add_late_acceptance_review(frm);
        }
        if (frm.doc.state !== "PREPARED" || frm.doc.active_attempt) return;
        frm.add_custom_button(__("Queue Saved Original"), () => {
            if (frm.is_dirty()) return;
            const issuance_id = frm.doc.name;
            frappe.confirm(__("Register an explicit manual request to send this exact saved original? No XML or invoice identity will be regenerated. This is not an unknown-outcome retry."), () => {
                if (frm.doc.name !== issuance_id || frm.is_dirty()) return;
                frappe.call({
                    method: "zatca_erpgulf.zatca_erpgulf.prepared_recovery.queue_saved_original",
                    args: {issuance_id}, freeze: true,
                    callback(r) {
                        if (frm.doc.name !== issuance_id || !r.message || r.message.status !== "DEFERRED") return;
                        const result = r.message;
                        frappe.msgprint({
                            title: __("Saved Original Request"), message: result.message, indicator: "blue",
                            primary_action: {
                                label: __("View Request"),
                                action() { frappe.set_route("Form", "ZATCA Submission Intent", result.request_id); }
                            }
                        });
                        frm.reload_doc();
                    }
                });
            });
        });
    }
});

function add_late_acceptance_review(frm) {
    frm.add_custom_button(__("Review Late Acceptance"), () => {
        if (frm.is_dirty()) return;
        const issuance_id = frm.doc.name;
        const expected_attempt_id = frm.doc.active_attempt;
        const expected_state_version = frm.doc.state_version;
        const current = () => frm.doc.name === issuance_id && !frm.is_dirty() &&
            frm.doc.active_attempt === expected_attempt_id && frm.doc.state_version === expected_state_version;
        frappe.prompt([{fieldname: "accepted_attempt_id", fieldtype: "Link", options: "ZATCA Dispatch Attempt",
            label: __("Earlier Response Attempt"), reqd: 1,
            get_query: () => ({filters: {issuance: issuance_id, state: "RESPONSE_RETAINED"}})}], values => {
            if (!current()) return;
            const accepted_attempt_id = values.accepted_attempt_id;
            frappe.confirm(__("Resolve this original only from an earlier matching saved acceptance? The server will review the newer attempt and retain both histories. Nothing will be generated or sent."), () => {
                if (!current()) return;
                frappe.call({method: "zatca_erpgulf.zatca_erpgulf.late_acceptance.reconcile_response",
                    args: {issuance_id, expected_attempt_id, expected_state_version, accepted_attempt_id}, freeze: true,
                    callback(r) {
                        if (!current() || !r.message || r.message.status !== "RESOLVED") return;
                        frappe.msgprint({title: __("Late Acceptance Review"), message: r.message.message, indicator: "green"});
                        frm.reload_doc();
                    }});
            });
        }, __("Review Late Acceptance"), __("Review Saved Response"));
    });
}
