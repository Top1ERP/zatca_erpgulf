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
            zatca_operation_client_error(e, "Compliance CSID Generation Failed");
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
            zatca_operation_client_error(error, "Run All Compliance Failed");
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
            zatca_operation_client_error(error, "Automatic ZATCA Onboarding Test Failed");
        } finally {
            frappe.dom.unfreeze();
        }
    },

    custom_check_compliance: async function (frm) {
        if (!frm.doc.custom_sample_invoice_number_to_test) {
            frappe.msgprint(__('Please enter Sample Invoice Number to Test first.'));
            return;
        }
        try {
            const r = await frappe.call({
                method: "zatca_erpgulf.zatca_erpgulf.sign_invoice.run_single_compliance_summary",
                args: {
                    invoice_number: frm.doc.custom_sample_invoice_number_to_test,
                    company_name: frm.doc.name
                },
                freeze: true,
                freeze_message: __("Running compliance check...")
            });
            if (r.exc) return;
            zatca_compliance_summary(r.message || {}, false, true);
        } catch (error) {
            zatca_operation_client_error(error, "Compliance Check Failed");
        }
    }
});
