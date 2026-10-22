// Presentation only: never translate or rewrite a raw authority diagnostic.
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

function zatca_operation_client_error(error, title) {
    // Frappe owns HTTP/permission/session/validation dialogs. Do not display a
    // second dialog on rejection. Never stringify an XHR as "[object Object]".
    const frameworkStatuses = [401, 403, 404, 413, 500, 502, 504, 508];
    if (error && (frameworkStatuses.includes(error.status) || error._server_messages ||
        (error.responseJSON && error.responseJSON._server_messages))) return;
    frappe.msgprint({
        title: __(title),
        message: __("The operation could not be completed. Reload the form and try again."),
        indicator: "red"
    });
}

// Only the view translates these keys. Raw exception/authority text is escaped.
function zatca_debug_summary(value) {
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
            __("Existing XML/QR was found. A separate debug XML will be generated.")]
    ]);
    const success = response.status === "success" && response.message === "Debug XML attached successfully." &&
        typeof response.file_name === "string" && response.file_name.length > 0;
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
        message: '<p>' + escape(text) + '</p><p>' +
            escape(__("This is a local debug operation, not a ZATCA submission.")) + '</p>' +
            (success ? '<p><strong>' + escape(__("File")) + ':</strong> ' + escape(response.file_name) + '</p>' : '') +
            notices.filter(item => messages.has(item)).map(item => '<p>' + escape(messages.get(item)) + '</p>').join('') +
            (details.length ? '<details><summary>' + escape(__("Technical details")) +
                '</summary><pre style="white-space:pre-wrap" dir="auto">' +
                escape(Array.from(new Set(details)).join('\n\n')) + '</pre></details>' : '')
    });
}
