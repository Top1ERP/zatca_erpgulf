// Presentation only: never translate or rewrite a raw authority diagnostic.
function zatca_compliance_summary(response, automatic) {
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
    const complete = results.length === 6 && passed === 6 &&
        new Set(results.map(row => row.type)).size === 6 &&
        results.every(row => Object.prototype.hasOwnProperty.call(labels, row.type)) &&
        (!automatic || response.all_passed === true);
    const technical = Array.from(details, ([raw, types]) =>
        '<details><summary>' + escape(__("Technical details")) + ': ' +
        types.map(escape).join(', ') + '</summary><pre style="white-space:pre-wrap" dir="auto">' +
        escape(raw) + '</pre></details>').join("");
    const note = automatic ? '<p>' + escape(__("This alternative test uses temporary documents only; no customer or sales invoice was created.")) + '</p>' : '';
    const empty = results.length ? '' : '<p>' + escape(__("No compliance results were returned. Completion has not been confirmed.")) + '</p>';
    frappe.msgprint({
        title: automatic ?
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

function zatca_compliance_client_error(error, title) {
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

frappe.realtime.on('hide_gif', () => {
    $('#custom-gif-overlay').remove();
});

frappe.realtime.on('show_gif', (data) => {
    console.log("Show gif called");
    const gifHtml = `
        <div id="custom-gif-overlay" style="
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(255, 255, 255, 0.8);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 1050;">
            <img src="${data.gif_url}" alt="Loading..." style="width: 100px; height: 100px;">
        </div>`;
    $('body').append(gifHtml);
});

frappe.ui.form.on("Company", {
    refresh(frm) {
        if (!frm.is_new() && zatca_is_saudi_country(frm.doc.country)) {
            // Use the existing ERPNext/Frappe button location if present:
            // Manage > Create Tax Template
            // Remove first to avoid duplicate buttons, then add our idempotent ZATCA/KSA implementation.
            try {
                frm.remove_custom_button(__("Create Tax Template"), __("Manage"));
            } catch (e) {
                // Ignore if the button does not exist.
            }

            frm.add_custom_button(
                __("Create Tax Template"),
                function () {
                    frappe.confirm(
                        __("This will create or update KSA VAT tax accounts and tax templates for this company. KSA VAT 15% will be set as the default Sales Taxes and Charges Template. Continue?"),
                        function () {
                            frappe.call({
                                method: "zatca_erpgulf.ksa_compliance.tax_templates.create_or_update_ksa_tax_templates",
                                args: {
                                    company: frm.doc.name
                                },
                                freeze: true,
                                freeze_message: __("Creating / Updating KSA VAT Templates..."),
                                callback: function (r) {
                                    if (r.exc) {
                                        return;
                                    }

                                    const msg = r.message || {};
                                    const accounts = msg.accounts || [];
                                    const sales = msg.sales_templates || [];
                                    const purchase = msg.purchase_templates || [];
                                    const item_tax = msg.item_tax_templates || [];

                                    frappe.msgprint({
                                        title: __("Tax Templates Updated"),
                                        indicator: "green",
                                        message: `
                                            <p><b>${__("Company")}:</b> ${frappe.utils.escape_html(msg.company || frm.doc.name)}</p>
                                            <p><b>${__("Accounts")}:</b> ${accounts.length}</p>
                                            <p><b>${__("Sales Tax Templates")}:</b> ${sales.length}</p>
                                            <p><b>${__("Purchase Tax Templates")}:</b> ${purchase.length}</p>
                                            <p><b>${__("Item Tax Templates")}:</b> ${item_tax.length}</p>
                                            <p>${__("KSA VAT 15% is now the default Sales Taxes and Charges Template.")}</p>
                                        `
                                    });

                                    frm.reload_doc();
                                }
                            });
                        }
                    );
                },
                __("Manage")
            );
        }
    },

    custom_generate_production_csids: function (frm) {
        frappe.call({
            method: "zatca_erpgulf.zatca_erpgulf.sign_invoice_first.production_csid",
            args: {
                "zatca_doc": {
                    "doctype": frm.doc.doctype,
                    "name": frm.doc.name
                },
                "company_abbr": frm.doc.abbr
            },
            callback: function (r) {
                if (!r.exc) {
                    frm.save();
                }
            },
        });
    },

    custom_generate_compliance_csid: async function (frm) {
        try {
            // OTP and environment changes are held in the form until Save.
            // Persist them before the server reads Company from the database.
            if (frm.is_dirty()) {
                await frm.save();
            }

            const r = await frappe.call({
                method: "zatca_erpgulf.zatca_erpgulf.sign_invoice_first.create_csid",
                args: {
                    "zatca_doc": {
                        "doctype": frm.doc.doctype,
                        "name": frm.doc.name
                    },
                    "portal_type": frm.doc.custom_select,
                    "company_abbr": frm.doc.abbr
                },
                freeze: true,
                freeze_message: __('Generating Compliance CSID...')
            });

            if (!r.exc) {
                // The server stores the returned certificate and request ID.
                // Reload instead of saving the stale client copy over them.
                await frm.reload_doc();
            }
        } catch (e) {
            zatca_compliance_client_error(e, "Compliance CSID Generation Failed");
        }
    },

    custom_create_csr: function (frm) {
        frappe.call({
            method: "zatca_erpgulf.zatca_erpgulf.sign_invoice_first.create_csr",
            args: {
                "zatca_doc": {
                    "doctype": frm.doc.doctype,
                    "name": frm.doc.name
                },
                "portal_type": frm.doc.custom_select,
                "company_abbr": frm.doc.abbr
            },
            callback: function (r) {
                if (!r.exc) {
                    frm.save();
                }
            },
        });
    },

    custom_create_csr_configuration: function (frm) {
        frappe.call({
            method: "zatca_erpgulf.zatca_erpgulf.csr_configuration.get_csr_config",
            args: {
                company_abbr: frm.doc.abbr
            },
            callback: function (r) {
                if (!r.exc && r.message) {
                    frm.set_value("custom_csr_config", r.message);
                    frappe.msgprint("CSR Configuration generated successfully.");
                    frm.save();
                }
            },
        });
    },

    custom_run_all_compliance: async function (frm) {
        if (!frm.doc.custom_sample_invoice_number_to_test) {
            frappe.msgprint(__('Please enter Sample Invoice Number to Test first.'));
            return;
        }
        frappe.dom.freeze(__('Running all compliance checks...'));
        try {
            const r = await frappe.call({
                method: "zatca_erpgulf.zatca_erpgulf.sign_invoice.run_all_compliance_summary",
                args: {
                    company_name: frm.doc.name,
                    invoice_number: frm.doc.custom_sample_invoice_number_to_test
                }
            });
            if (r.exc) return; // The framework already presents the server error.
            // No Company setting is changed here. Avoid a restore/save/reload
            // that could overwrite server values or discard dirty form edits.
            zatca_compliance_summary(r.message || {}, false);
        } catch (error) {
            zatca_compliance_client_error(error, "Run All Compliance Failed");
        } finally {
            frappe.dom.unfreeze();
        }
    },

    custom_run_zatca_onboarding_checks: async function (frm) {
        const confirmed = await new Promise(resolve => {
            frappe.confirm(
                __('This is an alternative to Run All Compliance. It creates temporary documents and does not create customers or sales invoices. Choose one method only before generating the Production CSID. Continue?'),
                () => resolve(true),
                () => resolve(false)
            );
        });
        if (!confirmed) return;
        frappe.dom.freeze(__('Running the automatic ZATCA onboarding test...'));
        try {
            const r = await frappe.call({
                method: "zatca_erpgulf.zatca_erpgulf.sign_invoice.run_automatic_zatca_onboarding_checks",
                args: { company_name: frm.doc.name }
            });
            if (r.exc) return;
            zatca_compliance_summary(r.message || {}, true);
        } catch (error) {
            zatca_compliance_client_error(error, "Automatic ZATCA Onboarding Test Failed");
        } finally {
            frappe.dom.unfreeze();
        }
    },

    custom_check_compliance: function (frm) {
        frappe.call({
            method: "zatca_erpgulf.zatca_erpgulf.sign_invoice.zatca_call_compliance",
            args: {
                "invoice_number": frm.doc.custom_sample_invoice_number_to_test,
                "company_name": frm.doc.name,
                "compliance_type": "1",
                "company_abbr": frm.doc.abbr,
                "source_doc": frm.doc,
            },
            callback: function (r) {
                if (!r.exc) {
                    // keep existing behavior
                }
            },
        });
    }
});
