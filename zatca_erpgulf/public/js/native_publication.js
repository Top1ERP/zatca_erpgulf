/* Custody views only. Never save a QR/data URI or request signing/submission. */
(() => {
    if (frappe.zatca_native_publication) return;
    const views = new WeakMap();
    const group = () => __("ZATCA Phase-2");
    const labels = ["Download issued ZATCA XML", "Download original ZATCA XML", "Refresh issued ZATCA document"];
    const review = "The saved ZATCA document cannot be displayed or printed safely. Review its issuance, response and saved invoice data. No document was regenerated or sent.";
    const save = "Save or discard invoice changes before viewing the issued ZATCA document.";
    const signature = doc => JSON.stringify([doc.doctype, doc.name, doc.modified,
        doc.custom_uuid, doc.custom_zatca_icv, doc.custom_zatca_issuing_unit]);
    const clean = frm => typeof frm.is_dirty === "function" && !frm.is_dirty() && !frm.doc.__islocal;
    function active(frm, token) {
        const route = frappe.get_route();
        return views.get(frm) === token && frm.doc === token.doc && signature(frm.doc) === token.signature &&
            typeof cur_frm !== "undefined" && cur_frm === frm && route[0] === "Form" &&
            route[1] === token.doc.doctype && route[2] === token.doc.name;
    }
    function clear(frm) {
        const previous = views.get(frm);
        previous?.section?.closest(".native-zatca-publication").remove();
        if (previous?.fieldVisibility !== undefined) frm.toggle_display("ksa_einv_qr", previous.fieldVisibility);
        for (const label of labels) frm.remove_custom_button(__(label), group());
        views.delete(frm);
    }
    function newToken(frm) {
        const field = frm.fields_dict?.ksa_einv_qr;
        const token = { doc: frm.doc, signature: signature(frm.doc) };
        if (field) {
            token.fieldVisibility = !field.df.hidden;
            frm.toggle_display("ksa_einv_qr", false);
        }
        return token;
    }
    function section(frm, token, message, image) {
        const body = $("<div>").addClass("native-zatca-document");
        $("<p>").text(message).appendTo(body);
        if (image) $("<img>").attr({ src: image, alt: __("Issued ZATCA QR code"),
            style: "max-width:100%;height:auto;" }).appendTo(body);
        token.section = frm.dashboard.add_section(body, __("Issued ZATCA document"), "native-zatca-publication");
    }
    function valid(result) {
        return result && result.status === "READY" && typeof result.accepted === "boolean" &&
            /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(result.issuance_id) &&
            ["SIMPLIFIED_GENERATED_XML", "STANDARD_CLEARED_XML", "STANDARD_303_REPORTED_XML"].includes(result.source_kind) &&
            ["PREPARED", "DISPATCHING", "OUTCOME_UNKNOWN", "REPORTED", "CLEARED"].includes(result.state) &&
            result.accepted === ["REPORTED", "CLEARED"].includes(result.state) &&
            (result.accepted || result.source_kind === "SIMPLIFIED_GENERATED_XML") &&
            typeof result.qr_data_uri === "string" && result.qr_data_uri.length <= 2 * 1024 * 1024 &&
            /^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/.test(result.qr_data_uri);
    }
    function download(frm, token, result, original) {
        if (!active(frm, token) || !clean(frm)) return;
        const method = original ? "download_original" : "download_xml";
        const args = { doctype: token.doc.doctype, invoice_name: token.doc.name, issuance_id: result.issuance_id };
        const query = Object.entries(args).map(([key, value]) => `${key}=${encodeURIComponent(value)}`).join("&");
        window.open(`/api/method/zatca_erpgulf.zatca_erpgulf.native_publication.${method}?${query}`, "_blank", "noopener");
    }
    async function refresh(frm) {
        clear(frm);
        const marker = frm.doc.custom_zatca_issuing_unit;
        const native = typeof marker === "string" && marker.startsWith("egs:");
        if (!native) return;
        // Suppress an old persisted field in this native form. Printing resolves
        // the normal field server-side; the preview never changes model data.
        const token = newToken(frm);
        views.set(frm, token);
        if (!active(frm, token)) return;
        frm.$wrapper.off("dirty.zatca_native_publication").on("dirty.zatca_native_publication", () => {
            if (views.get(frm) !== token) return;
            clear(frm);
            const dirty = newToken(frm);
            views.set(frm, dirty);
            section(frm, dirty, __(save));
        });
        if (!clean(frm)) { section(frm, token, __(save)); return; }
        frm.add_custom_button(__(labels[2]), () => refresh(frm), group());
        let result;
        try {
            const response = await frappe.call({
                method: "zatca_erpgulf.zatca_erpgulf.native_publication.preview", type: "GET",
                args: { doctype: token.doc.doctype, invoice_name: token.doc.name },
                // Render one local review on a failed read, with no raw popup.
                error() {}
            });
            result = response?.message;
        } catch (error) { result = null; }
        if (!active(frm, token) || !clean(frm)) return;
        if (!valid(result)) { section(frm, token, __(review)); return; }
        // Translate display text only; do not localize states or persisted logs.
        const message = result.accepted ? "ZATCA acceptance is confirmed by the saved response." :
            "Generated document; ZATCA acceptance is not confirmed.";
        section(frm, token, __(message), result.qr_data_uri);
        frm.add_custom_button(__(labels[0]), () => download(frm, token, result, false), group());
        frm.add_custom_button(__(labels[1]), () => download(frm, token, result, true), group());
    }
    frappe.zatca_native_publication = { refresh };
    for (const doctype of ["Sales Invoice", "POS Invoice"]) frappe.ui.form.on(doctype, { refresh });
})();
