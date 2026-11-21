// Explicit review of one prior attempt; no automatic unknown-outcome retry.
frappe.ui.form.on("ZATCA Dispatch Attempt", {
    refresh(frm) {
        frm.remove_custom_button(__("Request Exact Retry"));
        const uncertain = ["STARTED", "OUTCOME_UNKNOWN"].includes(frm.doc.state);
        const technical = frm.doc.state === "RESPONSE_RETAINED" &&
            ["AUTHORIZATION_FAILED", "TECHNICAL_FAILURE"].includes(frm.doc.outcome);
        if (frm.is_new() || !(frappe.user_roles || []).includes("System Manager") ||
            !(uncertain || technical)) return;
        frm.add_custom_button(__("Request Exact Retry"), () => {
            if (frm.is_dirty()) return;
            const attempt_id = frm.doc.name;
            const issuance_id = frm.doc.issuance;
            const fence_token = frm.doc.fence_token;
            frappe.confirm(__("The previous attempt may already have been received. Request a deliberate retry of the exact same XML, UUID and hash after server eligibility checks? No new invoice will be generated."), () => {
                if (frm.doc.name !== attempt_id || frm.is_dirty()) return;
                frappe.call({
                    method: "zatca_erpgulf.zatca_erpgulf.exact_retry.queue_exact_retry",
                    args: {issuance_id, attempt_id, fence_token}, freeze: true,
                    callback(r) {
                        if (frm.doc.name !== attempt_id || !r.message || r.message.status !== "DEFERRED") return;
                        const result = r.message;
                        frappe.msgprint({title: __("Exact Retry Request"), message: result.message, indicator: "blue",
                            primary_action: {label: __("View Request"), action() {
                                frappe.set_route("Form", "ZATCA Submission Intent", result.request_id);
                            }}});
                        frm.reload_doc();
                    }
                });
            });
        });
    }
});
