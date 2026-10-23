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
        return zatca_run_csid(frm, true);
    },

    custom_generate_compliance_csid: function (frm) {
        return zatca_run_csid(frm, false);
    },

    custom_create_csr: function (frm) {
        return zatca_run_csr(frm);
    },

    custom_create_csr_configuration: function (frm) {
        return zatca_run_csr_configuration(frm);
    },

    custom_run_all_compliance: function (frm) {
        return zatca_run_company_compliance(frm, "all");
    },

    custom_run_zatca_onboarding_checks: function (frm) {
        return zatca_run_company_compliance(frm, "automatic");
    },

    custom_check_compliance: function (frm) {
        return zatca_run_company_compliance(frm, "single");
    }
});
