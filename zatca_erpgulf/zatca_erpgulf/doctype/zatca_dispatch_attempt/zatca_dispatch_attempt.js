// Explicit review of one prior attempt; no automatic unknown-outcome retry.
frappe.ui.form.on("ZATCA Dispatch Attempt", {
    refresh(frm) {
        const uncertain = ["STARTED", "OUTCOME_UNKNOWN"].includes(frm.doc.state);
        const technical = frm.doc.state === "RESPONSE_RETAINED" &&
            ["AUTHORIZATION_FAILED", "TECHNICAL_FAILURE"].includes(frm.doc.outcome);
        const actions = [
            {label: "Request Exact Retry", title: "Exact Retry Request", allowed: uncertain || technical,
                confirmation: "The previous attempt may already have been received. Request a deliberate retry of the exact same XML, UUID and hash after server eligibility checks? No new invoice will be generated.",
                method: "zatca_erpgulf.zatca_erpgulf.exact_retry.queue_exact_retry"},
            {label: "Prepare Corrected XML", title: "Corrected XML Request",
                allowed: frm.doc.state === "RESPONSE_RETAINED" && frm.doc.outcome === "VALIDATION_REJECTED",
                confirmation: "Prepare a new corrected XML version locally from the current saved invoice? It will receive a new UUID and invoice counter while retaining the rejected original. Posting dates and amounts are not edited. This does not send anything to ZATCA.",
                method: "zatca_erpgulf.zatca_erpgulf.corrected_preparation.queue_corrected_preparation"}
        ];
        for (const action of actions) frm.remove_custom_button(__(action.label));
        if (frm.is_new() || !(frappe.user_roles || []).includes("System Manager")) return;
        for (const action of actions) {
            if (!action.allowed) continue;
            frm.add_custom_button(__(action.label), () => {
            if (frm.is_dirty()) return;
            const attempt_id = frm.doc.name;
            const issuance_id = frm.doc.issuance;
            const fence_token = frm.doc.fence_token;
            const current = () => frm.doc.name === attempt_id && frm.doc.issuance === issuance_id &&
                frm.doc.fence_token === fence_token && !frm.is_dirty();
            frappe.confirm(__(action.confirmation), () => {
                if (!current()) return;
                frappe.call({
                    method: action.method,
                    args: {issuance_id, attempt_id, fence_token}, freeze: true,
                    callback(r) {
                        if (!current() || !r.message || r.message.status !== "DEFERRED") return;
                        const result = r.message;
                        frappe.msgprint({title: __(action.title), message: result.message, indicator: "blue",
                            primary_action: {label: __("View Request"), action() {
                                frappe.set_route("Form", "ZATCA Submission Intent", result.request_id);
                            }}});
                        frm.reload_doc();
                    }
                });
            });
            });
        }
    }
});
