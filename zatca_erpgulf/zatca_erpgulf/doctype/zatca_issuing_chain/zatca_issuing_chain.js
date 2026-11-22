// Explicit local history steps. Refresh never captures, audits or sends anything.
frappe.ui.form.on("ZATCA Issuing Chain", {
    refresh(frm) {
        const actions = [
            ["Capture Next History Page", "capture"],
            ["Audit Captured History", "audit"],
            ["Restart Captured History Audit", "restart-audit"]
        ];
        actions.forEach(([label]) => frm.remove_custom_button(__(label)));
        const token = (frm.__zatca_history_token || 0) + 1;
        frm.__zatca_history_token = token;
        if (frm.is_new() || !(frappe.user_roles || []).includes("System Manager") ||
            frm.doc.registration_kind !== "LEGACY_REVIEWED" || frm.doc.active ||
            frm.doc.state_version !== 0 || !frm.doc.registration_review_key) return;
        const review_id = frm.doc.name;
        const current = () => frm.__zatca_history_token === token && frm.doc.name === review_id &&
            !frm.is_dirty() && !frm.doc.active && frm.doc.state_version === 0 &&
            frm.doc.registration_kind === "LEGACY_REVIEWED" && !!frm.doc.registration_review_key;
        let busy = false;
        for (const [label, operation] of actions) {
            frm.add_custom_button(__(label), () => {
                if (!current() || busy) return;
                const run = () => {
                    if (!current() || busy) return;
                    busy = true;
                    frappe.call({
                        method: "zatca_erpgulf.zatca_erpgulf.history_review_actions.review_saved_history",
                        type: "POST", args: {review_id, operation}, freeze: true,
                        callback(r) {
                            if (!current() || !r.message || r.message.review_id !== review_id ||
                                !["CAPTURED", "CAPTURE_EXHAUSTED", "AUDITED"].includes(r.message.status)) return;
                            frappe.msgprint({title: __("Saved History Review"),
                                message: r.message.message, indicator: "blue"});
                            frm.reload_doc();
                        },
                        always() { busy = false; }
                    });
                };
                if (operation === "restart-audit") {
                    frappe.confirm(__("Restart the local audit from the current captured head? The saved checkpoint will be replaced; captured pages remain retained. Nothing will be sent to ZATCA."), run);
                } else run();
            });
        }
    }
});
