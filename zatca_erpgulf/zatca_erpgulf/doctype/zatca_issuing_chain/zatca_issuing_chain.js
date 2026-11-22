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
        add_native_renewal_preparation(frm, token);
        if (frm.is_new() || !(frappe.user_roles || []).includes("System Manager") ||
            frm.doc.registration_kind !== "LEGACY_REVIEWED" || frm.doc.active ||
            frm.doc.state_version !== 0 || !frm.doc.registration_review_key) return;
        const review_id = frm.doc.name;
        const current = () => frm.__zatca_history_token === token && frm.doc.name === review_id &&
            native_chain_route_is_current(review_id) &&
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

function add_native_renewal_preparation(frm, token) {
    const label = __("Prepare Certificate Renewal");
    frm.remove_custom_button(label);
    if (frm.is_new() || !(frappe.user_roles || []).includes("System Manager") ||
        frm.doc.active !== 1 || !frm.doc.active_owner_key) return;
    const chain_id = frm.doc.name;
    const owner_key = frm.doc.active_owner_key;
    let busy = false;
    const current = () => frm.__zatca_history_token === token && frm.doc.name === chain_id &&
        native_chain_route_is_current(chain_id) &&
        !frm.is_dirty() && frm.doc.active === 1 && frm.doc.active_owner_key === owner_key;
    frm.add_custom_button(label, () => {
        if (!current() || busy) return;
        frappe.prompt([{fieldname: "reason", fieldtype: "Small Text", reqd: 1,
            label: __("Renewal Preparation Reason"),
            description: __("Prepare a separate key and CSR locally. The current certificate and invoice counter will not be replaced, and no request will be sent to ZATCA.")}], values => {
            if (!current() || busy) return;
            busy = true;
            frappe.call({
                method: "zatca_erpgulf.zatca_erpgulf.native_renewal.prepare_certificate_renewal",
                type: "POST", args: {chain_id, reason: values.reason}, freeze: true,
                callback(r) {
                    if (!current() || !r.message || r.message.old_chain !== chain_id ||
                        r.message.state !== "CSR_READY" || !r.message.renewal_id) return;
                    const renewal_id = r.message.renewal_id;
                    frappe.msgprint({title: __("Certificate Renewal Preparation"),
                        message: r.message.message, indicator: "blue",
                        primary_action: {label: __("View Pending Renewal"),
                            action() { frappe.set_route("Form", "ZATCA CSID Renewal", renewal_id); }}});
                    frm.reload_doc();
                },
                always() { busy = false; }
            });
        }, __("Prepare Certificate Renewal"), __("Prepare Renewal Locally"));
    });
}

function native_chain_route_is_current(name) {
    if (typeof frappe.get_route !== "function") return false;
    const route = frappe.get_route();
    return Array.isArray(route) && route.length === 3 && route[0] === "Form" &&
        route[1] === "ZATCA Issuing Chain" && route[2] === name;
}
