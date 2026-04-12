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
        // Refresh logic if any
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

    custom_generate_compliance_csid: function (frm) {
        frappe.call({
            method: "zatca_erpgulf.zatca_erpgulf.sign_invoice_first.create_csid",
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

        const validationTypes = [
            "Simplified Invoice",
            "Standard Invoice",
            "Simplified Credit Note",
            "Standard Credit Note",
            "Simplified Debit Note",
            "Standard Debit Note"
        ];

        const originalValidationType = frm.doc.custom_validation_type || "";

        frappe.dom.freeze(__('Running all compliance checks...'));

        try {
            const r = await frappe.call({
                method: "zatca_erpgulf.zatca_erpgulf.sign_invoice.run_all_compliance_summary",
                args: {
                    company_name: frm.doc.name,
                    invoice_number: frm.doc.custom_sample_invoice_number_to_test
                }
            });

            // Restore original value visually and in DB only once
            await frm.set_value("custom_validation_type", originalValidationType);
            await frm.save();

            const results = (r && r.message && r.message.results) ? r.message.results : [];

            let html = `
                <div style="max-height: 450px; overflow:auto;">
                    <table class="table table-bordered">
                        <thead>
                            <tr>
                                <th style="width: 30%;">Validation Type</th>
                                <th style="width: 12%;">Status</th>
                                <th>Message</th>
                            </tr>
                        </thead>
                        <tbody>
            `;

            results.forEach(row => {
                const color = row.status === "PASS" ? "green" : "red";
                html += `
                    <tr>
                        <td>${frappe.utils.escape_html(row.type || "")}</td>
                        <td><strong style="color:${color};">${frappe.utils.escape_html(row.status || "")}</strong></td>
                        <td>${frappe.utils.escape_html(row.message || "")}</td>
                    </tr>
                `;
            });

            html += `
                        </tbody>
                    </table>
                </div>
            `;

            const passed = results.filter(x => x.status === "PASS").length;
            const failed = results.filter(x => x.status === "FAIL").length;

            frappe.msgprint({
                title: __('Compliance Results Summary'),
                message: `
                    <p><strong>Passed:</strong> ${passed}</p>
                    <p><strong>Failed:</strong> ${failed}</p>
                    ${html}
                `,
                wide: true
            });

            await frm.reload_doc();

        } catch (e) {
            frappe.msgprint({
                title: __('Run All Compliance Failed'),
                message: frappe.utils.escape_html(e.message || String(e)),
                indicator: 'red'
            });
        } finally {
            frappe.dom.unfreeze();
        }
    },

    custom_check_compliance: function (frm) {
        frappe.call({
            method: "zatca_erpgulf.zatca_erpgulf.sign_invoice.zatca_call_compliance",
            args: {
                "invoice_number": frm.doc.custom_sample_invoice_number_to_test,
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