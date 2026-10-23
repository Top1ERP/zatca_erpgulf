// Shared UI boundaries: translate display text, never raw authority diagnostics.
// Request helpers keep explicit routing and never mutate client credential fields.
function zatca_csid_succeeded(value, production) {
    let result;
    try { result = typeof value === "string" ? JSON.parse(value) : value; }
    catch (error) { return false; }
    return !!(result && typeof result === "object" && !Array.isArray(result) && result.status === "SUCCESS" &&
        result.purpose === (production ? "production" : "compliance") &&
        result.message === (production ? "Final CSID generated and saved successfully." :
            "Compliance CSID generated and saved successfully."));
}

function zatca_csid_result_message(value, production) {
    const purpose = production ? "production" : "compliance";
    const messages = {
        compliance: __("Compliance CSID generated and saved successfully."),
        production: __("Final CSID generated and saved successfully.")
    };
    // Do not copy an old/raw response into a wizard credential field. Parsing
    // does not authorize progression or replace the server's saved settings.
    return zatca_csid_succeeded(value, production) ? messages[purpose] :
        __("CSID creation was not confirmed. Review saved settings before trying again.");
}

// UI-only click/review guards, not durable idempotency or server access control.
const zatca_credential_pending = new WeakMap();
const zatca_credential_review = new WeakSet();

function zatca_run_csid(frm, production) {
    return zatca_run_credential_form(frm, production ? "production" : "compliance");
}

function zatca_run_csr(frm) {
    return zatca_run_credential_form(frm, "csr");
}

function zatca_run_csr_configuration(frm) {
    return zatca_run_credential_form(frm, "configuration");
}

function zatca_csr_configuration_draft(result, name, modified) {
    const keys = ["csr.common.name", "csr.serial.number", "csr.organization.identifier",
        "csr.organization.unit.name", "csr.organization.name", "csr.country.name",
        "csr.invoice.type", "csr.location.address", "csr.industry.business.category"];
    if (!result || typeof result !== "object" || Array.isArray(result) || result.status !== "DRAFT" ||
        result.company_name !== name || result.modified !== modified || typeof result.config !== "string" ||
        result.config.length > 16384 || /[\u0000-\u0009\u000b-\u001f\u007f\u0085\u2028\u2029]/.test(result.config)) return false;
    const lines = result.config.split("\n");
    // Shape only, not certificate/CSR or authority validation. Never render
    // this draft as HTML or translate its field contents.
    return lines.length === keys.length && lines.every((line, index) =>
        line.startsWith(keys[index] + "=") && line.length > keys[index].length + 1);
}

function zatca_run_credential_form(frm, operation) {
    if (zatca_credential_pending.has(frm)) return zatca_credential_pending.get(frm);
    const csr = operation === "csr";
    const configuration = operation === "configuration";
    const production = operation === "production";
    const doc = frm && frm.doc;
    const fields = ["doctype", "name", "modified", "abbr", "custom_select", "custom_linked_doctype"];
    if (csr || configuration) fields.push("custom_csr_config");
    if (configuration) fields.push("company_name", "tax_id",
        "custom_zatca__location_for_csr_configuratoin", "custom_zatca__company_category_for_csr_configuration");
    const snapshot = doc && fields.map(field => doc[field]);
    const company = doc && doc.doctype === "Company";
    const active = (staged = false) => {
        try {
            const route = typeof frappe.get_route === "function" ? frappe.get_route() : null;
            return doc && frm.doc === doc && Array.isArray(route) && route.length === 3 &&
                route[0] === "Form" && route[1] === snapshot[0] && route[2] === snapshot[1] &&
                (typeof cur_frm === "undefined" || cur_frm === frm) &&
                fields.every((field, index) => (staged && configuration && field === "custom_csr_config") ||
                    doc[field] === snapshot[index]);
        } catch (error) { return false; }
    };
    const clean = () => {
        try {
            return !doc.__islocal && !(typeof frm.is_new === "function" && frm.is_new()) &&
                typeof frm.is_dirty === "function" && frm.is_dirty() === false;
        } catch (error) { return false; }
    };
    const name = value => typeof value === "string" && value.length > 0 && value.length <= 140 &&
        value === value.trim() && !/[\u0000-\u001f\u007f]/.test(value);
    const environment = value => typeof value === "string" &&
        ["Sandbox", "Simulation", "Production"].includes(value.trim());
    const guard = message => {
        frappe.msgprint({ title: configuration ? __("CSR Configuration Result") :
            csr ? __("CSR Generation Result") : __("CSID Generation Result"), indicator: "orange", message });
        return Promise.resolve();
    };
    if (!doc || !(configuration ? doc.doctype === "Company" :
        ["Company", "ZATCA Multiple Setting"].includes(doc.doctype)) || !name(doc.name) || !active()) {
        return guard(csr || configuration ? __("The CSR settings form is no longer active. Reopen it before starting the operation.") :
            __("The CSID settings form is no longer active. Reopen it before starting the operation."));
    }
    // Review takes precedence over dirty-input guidance: never recommend saving
    // a stale form after the server may have changed credential fields.
    if (zatca_credential_review.has(doc)) {
        return guard(csr || configuration ? __("Review saved CSR and private-key settings before saving an already-open form or generating another CSR or CSID. Preserve unsaved changes before reloading.") :
            __("Review saved CSID settings before saving an already-open form or starting another CSID operation. Preserve unsaved changes before reloading."));
    }
    if (!clean()) {
        return guard(configuration ? __("Save the Company settings before preparing CSR configuration. No draft was requested or saved.") :
            csr ? __("Save the Company or device settings and CSR configuration before generating CSR. No CSR generation request was sent.") :
            __("Save the Company or device settings, including OTP and environment, before generating CSID. No CSID request was sent."));
    }
    if (typeof doc.modified !== "string" || !doc.modified.trim() ||
        (!configuration && (company ? !name(doc.abbr) || !environment(doc.custom_select) : !name(doc.custom_linked_doctype)))) {
        return guard(configuration ? __("Saved Company revision is missing. Review the Company before preparing CSR configuration.") :
            csr ? __("Saved CSR source settings are incomplete. Review the Company link and selected environment. No CSR generation request was sent.") :
            __("Saved CSID source settings are incomplete. Review the Company link and selected environment. No CSID request was sent."));
    }
    const changed = () => guard(csr ?
        __("CSR generation was cancelled because the form changed. Preserve edits and review saved settings. No CSR generation request was sent.") :
        __("CSID generation was cancelled because the form changed while reading saved settings. Preserve edits and review the active form. No CSID request was sent."));
    let attempted = false;
    let staging = false;
    const task = (async () => {
        try {
            if (configuration) {
                // This endpoint only reads one saved Company; no key or
                // credential request and no server-side configuration save.
                const r = await frappe.call({
                    method: "zatca_erpgulf.zatca_erpgulf.csr_configuration.prepare_csr_config",
                    args: { company_name: snapshot[1], expected_modified: snapshot[2] },
                    freeze: true, freeze_message: __("Preparing CSR configuration...")
                });
                if (r && r.exc) return;
                if (!active() || !clean()) return guard(__("The Company form changed while preparing CSR configuration. The draft was not applied. Preserve edits and review the active form."));
                const result = r && r.message;
                if (!zatca_csr_configuration_draft(result, snapshot[1], snapshot[2])) {
                    return guard(__("No confirmed CSR configuration draft was returned. No draft was applied or saved."));
                }
                staging = true;
                await frm.set_value("custom_csr_config", result.config);
                // A field hook can fail or change/navigation can occur during
                // async staging. Do not undo edits or retry the setter.
                if (!active(true) || doc.custom_csr_config !== result.config) {
                    return guard(__("CSR configuration staging could not be confirmed. Review the form before saving; no automatic save was performed."));
                }
                return guard(__("CSR configuration was placed in the form as an unsaved draft. Review it and save manually. No private key or certificate was generated."));
            }
            if (csr) {
                // CSR generation replaces the saved private key. This consent
                // is not credential activation or proof that rotation is safe.
                const confirmed = await new Promise(resolve => frappe.confirm(
                    __("Generating CSR replaces the saved private key and may make existing certificates unusable. Continue only for an intentional onboarding or renewal operation."),
                    () => resolve(true), () => resolve(false)));
                if (!confirmed) return;
                if (!active() || !clean()) return changed();
            }
            let abbr = doc.abbr, portal = doc.custom_select;
            if (!company) {
                // Read only routing metadata, never a full Company with secrets.
                const lookup = await frappe.call({ method: "frappe.client.get_value",
                    args: { doctype: "Company", filters: doc.custom_linked_doctype,
                        fieldname: ["abbr", "custom_select"] } });
                if (lookup && lookup.exc) return;
                if (!active() || !clean()) {
                    return changed();
                }
                const selected = lookup && lookup.message;
                if (!selected || !name(selected.abbr) || !environment(selected.custom_select)) {
                    return guard(csr ? __("Saved CSR source settings are incomplete. Review the Company link and selected environment. No CSR generation request was sent.") :
                        __("Saved CSID source settings are incomplete. Review the Company link and selected environment. No CSID request was sent."));
                }
                abbr = selected.abbr;
                portal = selected.custom_select;
            }
            const args = { zatca_doc: { doctype: snapshot[0], name: snapshot[1] }, company_abbr: abbr };
            if (!production) args.portal_type = portal;
            // Entering this RPC proves neither saved state nor issuance. Keep the old
            // document on review even after rejection, malformed reply or loss.
            zatca_credential_review.add(doc);
            attempted = true;
            const r = await frappe.call({
                method: csr ? "zatca_erpgulf.zatca_erpgulf.sign_invoice_first.create_csr" :
                    production ? "zatca_erpgulf.zatca_erpgulf.sign_invoice_first.production_csid" :
                    "zatca_erpgulf.zatca_erpgulf.sign_invoice_first.create_csid",
                args, freeze: true,
                freeze_message: csr ? __("Generating CSR...") :
                    production ? __("Generating Final CSID...") : __("Generating Compliance CSID...")
            });
            if (r && r.exc) return;
            if (csr) {
                // Legacy CSR returns encoded material, not a structured commit
                // receipt. Never display/copy it or claim validated issuance.
                return guard(__("The CSR generation call returned. Review saved CSR and private-key settings before any further operation; this does not confirm certificate issuance. Preserve unsaved changes before reloading."));
            }
            if (!zatca_csid_succeeded(r && r.message, production)) {
                return guard(__("CSID creation was not confirmed. Review saved settings before trying again."));
            }
            // The server owns the one success notice, including review guidance.
            // Never save, reload, sync credentials or overwrite source fields.
            return;
        } catch (error) {
            if (configuration) {
                zatca_operation_client_error(error, "CSR Configuration Failed", staging ?
                    __("CSR configuration staging could not be confirmed. Review the form before saving; no automatic save was performed.") :
                    __("CSR configuration preparation could not be completed. No draft was applied or saved."));
                return;
            }
            if (csr) {
                zatca_operation_client_error(error, "CSR Generation Failed", attempted ?
                    __("CSR generation could not be confirmed. The saved private key may have changed. Preserve edits and review saved settings before another CSR or CSID operation.") :
                    __("CSR preparation could not be completed. No CSR generation request was sent."));
                return;
            }
            zatca_operation_client_error(error, "CSID Generation Failed", attempted ?
                __("The CSID request outcome is not confirmed in this form. Preserve edits and review saved settings and the onboarding status before another request.") :
                __("Saved Company settings could not be read. No CSID request was sent."));
        }
    })().finally(() => zatca_credential_pending.delete(frm));
    zatca_credential_pending.set(frm, task);
    return task;
}

function zatca_compliance_summary(response, automatic, single = false) {
    const escape = value => frappe.utils.escape_html(String(value ?? ""));
    // Explicit keys are discoverable by Frappe's translation extractor.
    const labels = {
        "Simplified Invoice": __("Simplified Invoice"),
        "Standard Invoice": __("Standard Invoice"),
        "Simplified Credit Note": __("Simplified Credit Note"),
        "Standard Credit Note": __("Standard Credit Note"),
        "Simplified Debit Note": __("Simplified Debit Note"),
        "Standard Debit Note": __("Standard Debit Note")
    };
    const messages = new Map([
        ["Completed successfully.", __("Completed successfully.")],
        ["Completed with warnings. See technical details.", __("Completed with warnings. See technical details.")],
        ["Already completed by ZATCA; treated as PASS.", __("Already completed by ZATCA; treated as PASS.")],
        ["Compliance check failed. See technical details.", __("Compliance check failed. See technical details.")]
    ]);
    const results = Array.isArray(response.results) ? response.results.map(row =>
        row && typeof row === "object" ? row : {}) : [];
    const details = new Map();
    let passed = 0;
    const rows = results.map(row => {
        const ok = row.status === "PASS";
        if (ok) passed += 1;
        const label = Object.prototype.hasOwnProperty.call(labels, row.type) ? labels[row.type] : row.type;
        const message = messages.get(row.message) || __("Compliance check failed. See technical details.");
        // Group identical original diagnostics, not translated or parsed variants.
        // JSON below is only a view of parsed validation fields, not a raw log.
        const raw = typeof row.technical_details === "string" ? row.technical_details :
            (row.validation_details && typeof row.validation_details === "object" ? JSON.stringify(row.validation_details, null, 2) :
            (!messages.has(row.message) && typeof row.message === "string" ? row.message : ""));
        if (raw) {
            if (!details.has(raw)) details.set(raw, []);
            details.get(raw).push(label);
        }
        return '<tr><td>' + escape(label) + '</td><td><strong class="' +
            (ok ? 'text-success' : 'text-danger') + '">' + escape(ok ? __("PASS") : __("FAIL")) +
            '</strong></td><td>' + escape(message) + '</td></tr>';
    }).join("");
    const expected = single ? 1 : 6;
    const complete = results.length === expected && passed === expected &&
        new Set(results.map(row => row.type)).size === expected &&
        results.every(row => Object.prototype.hasOwnProperty.call(labels, row.type)) &&
        (!automatic || response.all_passed === true) &&
        (!single || response.single_check === true);
    const technical = Array.from(details, ([raw, types]) =>
        '<details><summary>' + escape(__("Technical details")) + ': ' +
        types.map(escape).join(', ') + '</summary><pre style="white-space:pre-wrap" dir="auto">' +
        escape(raw) + '</pre></details>').join("");
    const note = automatic ? '<p>' + escape(__("This alternative test uses temporary documents only; no customer or sales invoice was created.")) + '</p>' : '';
    const empty = results.length ? '' : '<p>' + escape(__("No compliance results were returned. Completion has not been confirmed.")) + '</p>';
    frappe.msgprint({
        title: single ? __("Compliance Check Result") : automatic ?
            (complete ? __("Automatic ZATCA Onboarding Test Passed") : __("Automatic ZATCA Onboarding Test Failed")) :
            __("Compliance Results Summary"),
        indicator: complete ? (results.some(row => row.message === "Completed with warnings. See technical details.") ? "orange" : "green") : "red",
        wide: true,
        message: note + '<p><strong>' + escape(__("Passed")) + ':</strong> ' + passed +
            ' &nbsp; <strong>' + escape(__("Failed")) + ':</strong> ' + (results.length - passed) + '</p>' +
            empty + '<div style="max-height:450px;overflow:auto"><table class="table table-bordered"><thead><tr><th>' +
            escape(__("Validation Type")) + '</th><th>' + escape(__("Status")) + '</th><th>' +
            escape(__("Message")) + '</th></tr></thead><tbody>' + rows + '</tbody></table>' + technical + '</div>' +
            (automatic && complete ? '<p><strong>' +
                escape(__("You may now use Generate Final CSID. Do not run both onboarding methods for the same compliance setup.")) +
                '</strong></p>' : '')
    });
}

function zatca_operation_client_error(error, title, message) {
    // Frappe owns HTTP/permission/session/validation dialogs. Do not display a
    // second dialog on rejection. Never stringify an XHR as "[object Object]".
    const frameworkStatuses = [401, 403, 404, 413, 500, 502, 504, 508];
    if (error && (frameworkStatuses.includes(error.status) || error._server_messages ||
        (error.responseJSON && error.responseJSON._server_messages))) return;
    frappe.msgprint({
        title: __(title),
        message: message || __("The operation could not be completed. Reload the form and try again."),
        indicator: "red"
    });
}

// Only the view translates these keys. Raw exception/authority text is escaped.
function zatca_debug_succeeded(response) {
    return response && response.status === "success" && response.message === "Debug XML attached successfully." &&
        typeof response.file_name === "string" && response.file_name.length > 0;
}

function zatca_debug_summary(value, context) {
    const response = value && typeof value === "object" ? value : {};
    const escape = text => frappe.utils.escape_html(String(text ?? ""));
    const messages = new Map([
        ["Debug XML attached successfully.", __("Debug XML attached successfully.")],
        ["Debug XML generation failed. See technical details.", __("Debug XML generation failed. See technical details.")],
        ["Debug XML was skipped for an intra-company transfer. The invoice was not changed.",
            __("Debug XML was skipped for an intra-company transfer. The invoice was not changed.")],
        ["ZATCA E-Invoicing is disabled for this Company. No debug XML was generated.",
            __("ZATCA E-Invoicing is disabled for this Company. No debug XML was generated.")],
        ["ZATCA E-Invoicing is disabled for this Company. Debug XML will be generated locally only; no submission will be performed.",
            __("ZATCA E-Invoicing is disabled for this Company. Debug XML will be generated locally only; no submission will be performed.")],
        ["Existing XML/QR was found. A separate debug XML will be generated.",
            __("Existing XML/QR was found. A separate debug XML will be generated.")],
        ["You do not have permission to create a debug XML attachment for this invoice.",
            __("You do not have permission to create a debug XML attachment for this invoice.")],
        ["Debug XML attachment could not be confirmed. Review the source and existing files before retrying.",
            __("Debug XML attachment could not be confirmed. Review the source and existing files before retrying.")],
        ["The debug attachment was created for the saved invoice. Your unsaved changes were kept.",
            __("The debug attachment was created for the saved invoice. Your unsaved changes were kept.")],
        ["The debug result belongs to another form. The current form was not refreshed.",
            __("The debug result belongs to another form. The current form was not refreshed.")],
        ["Debug XML was created, but its attachment list could not be refreshed. Review attachments manually; do not generate again just to refresh.",
            __("Debug XML was created, but its attachment list could not be refreshed. Review attachments manually; do not generate again just to refresh.")]
    ]);
    const success = zatca_debug_succeeded(response);
    const skipped = response.status === "skipped" && [
        "Debug XML was skipped for an intra-company transfer. The invoice was not changed.",
        "ZATCA E-Invoicing is disabled for this Company. No debug XML was generated."
    ].includes(response.message);
    const notices = Array.from(new Set(Array.isArray(response.notices) ? response.notices.filter(item => typeof item === "string") : []));
    const diagnostic = typeof response.technical_details === "string" ? response.technical_details :
        (typeof response.message === "string" && !messages.has(response.message) ? response.message : "");
    const details = [diagnostic, ...notices.filter(item => !messages.has(item))].filter(Boolean);
    const text = success || skipped ? messages.get(response.message) :
        (response.status === "error" ? messages.get("Debug XML generation failed. See technical details.") :
            __("No confirmed Debug XML result was returned. Review before trying again."));
    frappe.msgprint({
        title: __("Debug XML Result"),
        indicator: success ? (notices.length ? "orange" : "green") : (skipped ? "orange" : "red"),
        wide: true,
        message: (context ? '<p><strong>' + escape(__("Document")) + ':</strong> ' +
            escape(context.doctype === "POS Invoice" ? __("POS Invoice") : __("Sales Invoice")) +
            ' / ' + escape(context.name) + '</p>' : '') + '<p>' + escape(text) + '</p><p>' +
            escape(__("This is a local debug operation, not a ZATCA submission.")) + '</p>' +
            (success ? '<p><strong>' + escape(__("File")) + ':</strong> ' + escape(response.file_name) + '</p>' : '') +
            notices.filter(item => messages.has(item)).map(item => '<p>' + escape(messages.get(item)) + '</p>').join('') +
            (details.length ? '<details><summary>' + escape(__("Technical details")) +
                '</summary><pre style="white-space:pre-wrap" dir="auto">' +
                escape(Array.from(new Set(details)).join('\n\n')) + '</pre></details>' : '')
    });
}

// One pending Debug operation per form. No durable retry/idempotency assertion.
const zatca_debug_pending = new WeakMap();

function zatca_run_debug(frm) {
    if (zatca_debug_pending.has(frm)) return zatca_debug_pending.get(frm);
    const methods = {
        "Sales Invoice": "zatca_erpgulf.zatca_erpgulf.debug_xml.debug_call",
        "POS Invoice": "zatca_erpgulf.zatca_erpgulf.pos_debug_xml.debug_call"
    };
    const doc = frm && frm.doc;
    const context = doc && { doctype: doc.doctype, name: doc.name };
    const sameView = () => {
        const route = typeof frappe.get_route === "function" ? frappe.get_route() : null;
        return frm.doc === doc && doc.doctype === context.doctype && doc.name === context.name &&
            Array.isArray(route) && route.length === 3 && route[0] === "Form" &&
            route[1] === context.doctype && route[2] === context.name &&
            (typeof cur_frm === "undefined" || cur_frm === frm);
    };
    if (!context || !Object.prototype.hasOwnProperty.call(methods, context.doctype) || !context.name || !sameView()) {
        frappe.msgprint({ title: __("Debug XML Result"), indicator: "orange",
            message: __("The invoice form is no longer active. Reopen it before generating Debug XML.") });
        return Promise.resolve();
    }
    if (doc.__islocal || typeof frm.is_dirty !== "function" || frm.is_dirty()) {
        frappe.msgprint({ title: __("Debug XML Result"), indicator: "orange",
            message: __("Save the invoice before generating Debug XML. No request was sent.") });
        return Promise.resolve();
    }
    const task = (async () => {
        try {
            const r = await frappe.call({ method: methods[context.doctype],
                args: { invoice_number: context.name }, freeze: true,
                freeze_message: __("Generating Debug XML...") });
            if (r && r.exc) return;
            const response = r && r.message;
            const notices = Array.isArray(response && response.notices) ? [...response.notices] : [];
            if (zatca_debug_succeeded(response)) {
                if (!sameView()) {
                    notices.push("The debug result belongs to another form. The current form was not refreshed.");
                } else {
                    if (frm.is_dirty()) notices.push("The debug attachment was created for the saved invoice. Your unsaved changes were kept.");
                    const attachment = response.attachment;
                    // The stock attachment renderer embeds File IDs in a link.
                    const valid = attachment && typeof attachment.name === "string" &&
                        attachment.name.length > 0 && attachment.name.length <= 140 &&
                        !/[^A-Za-z0-9_-]/.test(attachment.name) &&
                        attachment.file_name === response.file_name && attachment.is_private === 1 &&
                        attachment.attached_to_doctype === context.doctype && attachment.attached_to_name === context.name &&
                        typeof attachment.file_url === "string" && attachment.file_url.length <= 2048 &&
                        !/\s/.test(attachment.file_url) &&
                        /^\/private\/files\/[A-Za-z0-9_.-]+$/.test(attachment.file_url) &&
                        ![".", ".."].includes(attachment.file_url.split("/").pop());
                    try {
                        if (!valid || !frm.attachments || typeof frm.attachments.update_attachment !== "function" ||
                            typeof frm.get_docinfo !== "function" || !Array.isArray(frm.get_docinfo().attachments)) {
                            throw new Error("debug_attachment_view_unavailable");
                        }
                        // Update only attachment metadata through the standard API.
                        // Never call attachment_uploaded (it can set invoice fields).
                        await frm.attachments.update_attachment({ name: attachment.name, file_name: attachment.file_name,
                            file_url: attachment.file_url, is_private: 1 });
                    } catch (error) {
                        notices.push("Debug XML was created, but its attachment list could not be refreshed. Review attachments manually; do not generate again just to refresh.");
                    }
                }
            }
            // UI-only copy: English server payload and raw diagnostics stay intact.
            zatca_debug_summary(response && typeof response === "object" ? { ...response, notices } : response, context);
            return response;
        } catch (error) {
            zatca_operation_client_error(error, "Debug XML Result",
                __("The Debug request did not complete visibly. Review existing attachments before trying again."));
        }
    })().finally(() => zatca_debug_pending.delete(frm));
    zatca_debug_pending.set(frm, task);
    return task;
}
