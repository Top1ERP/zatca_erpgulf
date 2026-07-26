function applyTooltips(context, fieldsWithTooltips) {
    fieldsWithTooltips.forEach((field) => {
        let fieldContainer;
        if (context.fields_dict?.[field.fieldname]) {
            fieldContainer = context.fields_dict[field.fieldname];
        }
        else if (context.dialog?.fields_dict?.[field.fieldname]) {
            fieldContainer = context.dialog.fields_dict[field.fieldname];
        }
        else if (context.page) {
            fieldContainer = $(context.page).find(`[data-fieldname="${field.fieldname}"]`).closest('.frappe-control');
        }
        if (!fieldContainer) {
            console.error(`Field '${field.fieldname}' not found in the provided context.`);
            return;
        }
        const fieldWrapper = fieldContainer.$wrapper || $(fieldContainer); // Handle both Doctype/Dialog and Page contexts
        if (!fieldWrapper || fieldWrapper.length === 0) {
            console.error(`Field wrapper for '${field.fieldname}' not found.`);
            return;
        }
        let labelElement;
        if (fieldWrapper.find('label').length > 0) {
            labelElement = fieldWrapper.find('label').first();
        } else if (fieldWrapper.find('.control-label').length > 0) {
            labelElement = fieldWrapper.find('.control-label').first();
        }
        if (!labelElement && (context.dialog || context.page)) {
            labelElement = fieldWrapper.find('.form-control').first();
        }

        if (!labelElement || labelElement.length === 0) {
            console.error(`Label for field '${field.fieldname}' not found.`);
            return;
        }
        const tooltipContainer = labelElement.next('.tooltip-container');
        if (tooltipContainer.length === 0) {
            const tooltip = new Tooltip({
                containerClass: "tooltip-container",
                tooltipClass: "custom-tooltip",
                iconClass: "info-icon",
                text: field.text,
                links: field.links,
            });
            tooltip.renderTooltip(labelElement[0]);
        }
    });
}
frappe.realtime.on('hide_gif', () => {
    $('#custom-gif-overlay').remove();
});

frappe.realtime.on('show_gif', (data) => {
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

// Listen for the event to hide the GIF
frappe.realtime.on('hide_gif', () => {
    $('#custom-gif-overlay').remove();
});

// frappe.ui.form.on("Sales Invoice", {
//     refresh: function (frm) {
//         if (frm.doc.docstatus === 1 && !["CLEARED", "REPORTED"].includes(frm.doc.custom_zatca_status)) {
//             frm.add_custom_button(__("Send invoice to ZATCA"), function () {
//                 frm.call({
//                     method: "zatca_erpgulf.zatca_erpgulf.sign_invoice.zatca_background",
//                     args: {
//                         "invoice_number": frm.doc.name,
//                         "source_doc": frm.doc

//                     },
//                     callback: function (r) {

//                         console.log("response.message");
//                         frm.reload_doc();

//                     }


//                 });
//             }, __("ZATCA Phase-2"));
//         }

frappe.ui.form.on("Sales Invoice", {
    refresh: function (frm) {
        // Load the company doctype to check phase setting
        if (frm.doc.company) {
            frappe.db.get_value("Company", frm.doc.company, "custom_phase_1_or_2")
                .then(value => {
                    let phase = value.message.custom_phase_1_or_2;

                    if (
                        frm.doc.docstatus === 1 &&
                        !["CLEARED", "REPORTED"].includes(frm.doc.custom_zatca_status) &&
                        phase === "Phase-2"
                    ) {
                        frm.add_custom_button(
                            __("Send invoice to ZATCA"),
                            function () {
                                frm.call({
                                    method: "zatca_erpgulf.zatca_erpgulf.sign_invoice.zatca_background",
                                    args: {
                                        invoice_number: frm.doc.name,
                                        source_doc: frm.doc
                                    },
                                    callback: function (r) {
                                        console.log(r.message);
                                        frm.reload_doc();
                                    }
                                });
                            },
                            __("ZATCA Phase-2")
                        );
                    }
                });
        }
   

        frm.page.add_menu_item(__('Print PDF-A3'), function () {
            // Create a dialog box with fields for Print Format, Letterhead, and Language
            const dialog = new frappe.ui.Dialog({
                title: __('Generate PDF-A3'),
                fields: [
                    {
                        fieldtype: 'Link',
                        fieldname: 'print_format',
                        label: __('Print Format'),
                        options: 'Print Format',
                        // default: 'Claudion Invoice Format', // Default print format if any
                        reqd: 1,
                        get_query: function () {
                            return {
                                filters: {
                                    doc_type: 'Sales Invoice' // Filters print formats related to Sales Invoice
                                }
                            };
                        }
                    },
                    {
                        fieldtype: 'Link',
                        fieldname: 'letterhead',
                        label: __('Letterhead'),
                        options: 'Letter Head', // Options should be the 'Letter Head' doctype
                        reqd: 0
                    },
                    {
                        fieldtype: 'Link',
                        fieldname: 'language',
                        label: __('Language'),
                        options: 'Language', // Options should be the 'Language' doctype
                        // default: 'en', // Default language
                        reqd: 1
                    }
                ],
                primary_action_label: __('Generate PDF-A3'),
                primary_action: function () {
                    const values = dialog.get_values();
                    frappe.call({
                        method: 'zatca_erpgulf.zatca_erpgulf.pdf_a3.embed_file_in_pdf',
                        args: {
                            invoice_name: frm.doc.name,
                            print_format: values.print_format,
                            letterhead: values.letterhead,
                            language: values.language
                        },
                        callback: function (r) {
                            if (r.message) {
                                // Open the generated PDF in a new tab
                                console.log(r.message)
                                const pdf_url = r.message;
                                window.open(pdf_url, '_blank');
                                frm.reload_doc();

                            } else {
                                frappe.msgprint(__('Failed to generate PDF-A3'));
                            }
                        }

                    });
                    dialog.hide();
                }
            });
            dialog.show();
        });



    }
});

frappe.ui.form.on('Sales Invoice', {
    refresh: function (frm) {
        const taxCategoryHelp = [
                    __("Tax category code values:"),
                    __("S: Standard rate."),
                    __("Z: Zero rated goods or services."),
                    __("E: Exempt from tax."),
                    __("O: Outside scope of tax / not subject to VAT."),
                    __("When the invoice contains mixed tax categories, use Item Tax Template on every item row."),
                ].join("<br>");

        const taxExemptionCodeHelp = [
                    __("Tax exemption / exception reason code. Required for Zero Rated, Exempted, Out of Scope, and Export cases."),
                    __("VATEX-SA-29: Financial services mentioned in Article 29 of the VAT Regulations"),
                    __("VATEX-SA-29-7: Life insurance services mentioned in Article 29 of the VAT Regulations"),
                    __("VATEX-SA-30: Real estate transactions mentioned in Article 30 of the VAT Regulations"),
                    __("VATEX-SA-32: Export of goods"),
                    __("VATEX-SA-33: Export of services"),
                    __("VATEX-SA-34-1: The international transport of goods"),
                    __("VATEX-SA-34-2: International transport of passengers"),
                    __("VATEX-SA-34-3: Services directly connected and incidental to international passenger transport"),
                    __("VATEX-SA-34-4: Supply of a qualifying means of transport"),
                    __("VATEX-SA-34-5: Services relating to goods or passenger transportation"),
                    __("VATEX-SA-35: Medicines and medical equipment"),
                    __("VATEX-SA-36: Qualifying metals"),
                    __("VATEX-SA-EDU: Private education to citizen"),
                    __("VATEX-SA-HEA: Private healthcare to citizen"),
                    __("VATEX-SA-MLTRY: Supply of qualified military goods"),
                    __("VATEX-SA-OOS: Services outside scope of tax / reason provided by taxpayer case by case"),
                ].join("<br>");

        const discountReasonHelp = [
                    __("Discount reason code. Optional in the invoice, but use the official code when a discount reason is submitted."),
                    __("41: Bonus for works ahead of schedule"),
                    __("42: Other bonus"),
                    __("60: Manufacturer's consumer discount"),
                    __("62: Due to military status"),
                    __("63: Due to work accident"),
                    __("64: Special agreement"),
                    __("65: Production error discount"),
                    __("66: New outlet discount"),
                    __("67: Sample discount"),
                    __("68: End of range discount"),
                    __("70: Incoterm discount"),
                    __("71: Point of sales threshold allowance"),
                    __("88: Material surcharge/deduction"),
                    __("95: Discount"),
                    __("100: Special rebate"),
                    __("102: Fixed long term"),
                    __("103: Temporary"),
                    __("104: Standard"),
                    __("105: Yearly turnover"),
                ].join("<br>");

        const fieldsWithTooltips = [
            {
                fieldname: "custom_zatca_tax_category",
                text: taxCategoryHelp,
                links: [],
            },
            {
                fieldname: "custom_exemption_reason_code",
                text: taxExemptionCodeHelp,
                links: [],
            },
            {
                fieldname: "custom_zatca_discount_reason_code",
                text: discountReasonHelp,
                links: [],
            },
            {
                fieldname: "custom_zatca_discount_reason",
                text: discountReasonHelp,
                links: [],
            },
            {
                fieldname: "custom_submit_line_item_discount_to_zatca",
                text: __("Controls whether line item discounts are submitted to ZATCA as line-level discount data where supported."),
                links: [],
            },
            {
                fieldname: "custom_zatca_third_party_invoice",
                text: [
                    __("Third-party invoice: issued by an external party, such as an accounting office, on behalf of the seller after meeting the VAT requirements."),
                ].join("<br>"),
                links: [],
            },
            {
                fieldname: "custom_zatca_nominal_invoice",
                text: [
                    __("Nominal invoice: used when goods or services are supplied for free or at a reduced price as part of a promotional activity."),
                ].join("<br>"),
                links: [],
            },
            {
                fieldname: "custom_zatca_export_invoice",
                text: [
                    __("Export invoice: used when the supplier and customer intend the goods or services to be supplied outside the GCC / Saudi VAT scope according to the applicable export rules."),
                ].join("<br>"),
                links: [],
            },
            {
                fieldname: "custom_summary_invoice",
                text: [
                    __("Summary invoice: used to combine more than one supply of goods or services within a specific period into one summary tax invoice."),
                ].join("<br>"),
                links: [],
            },
            {
                fieldname: "custom_self_billed_invoice",
                text: [
                    __("Self-billed invoice: issued by the buyer on behalf of the supplier under a self-billing agreement."),
                ].join("<br>"),
                links: [],
            },
            {
                fieldname: "custom_uuid",
                text: __("Persisted ZATCA UUID used by the invoice XML and signing flow."),
                links: [],
            },
            {
                fieldname: "custom_zatca_status",
                text: __("Read-only ZATCA submission status."),
                links: [],
            },
            {
                fieldname: "custom_zatca_status_notification",
                text: __("Visual ZATCA status notification shown on the invoice."),
                links: [],
            },
        ];
        applyTooltips(frm, fieldsWithTooltips);
        const css = `
            .popover-content {
                font-family: Arial, sans-serif;
                background-color: #f9f9f9;
                color: #007bff; /* Blue text */
                border: 1px solid #cfe2f3;
                border-radius: 8px;
                padding: 15px;
                max-width: 300px;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            }

            .popover-title {
                font-size: 16px;
                font-weight: bold;
                color: #0056b3; /* Darker blue for the title */
                margin-bottom: 10px;
            }

            .popover-body {
                font-size: 14px;
                line-height: 1.6;
                color: #007bff;
            }
        `;
        $('<style>').text(css).appendTo('head'); // Add the CSS dynamically

        // Attach popover to the "subject" field
        const attachPopover = (fieldname, title, body) => {
            setTimeout(() => {
                $(`[data-fieldname="${fieldname}"]`).popover({
                    trigger: 'hover',
                    placement: 'top',
                    content: `
                        <div class="popover-content">
                            <h4 class="popover-title">${title}</h4>
                            <p class="popover-body">${body}</p>
                        </div>
                    `,
                    html: true
                });
            }, 500);
        };

        // Attach popovers to specific fields

    }
});
frappe.ui.form.on('Sales Invoice', {
    refresh(frm) {
        const response = frm.doc.custom_zatca_full_response;
        if (!response) return;

        try {
            let jsonText = null;

            // Try extract after 'ZATCA Response:'
            const anchor = 'ZATCA Response:';
            if (response.includes(anchor)) {
                const afterAnchor = response.split(anchor)[1];
                const firstBrace = afterAnchor.indexOf('{');
                const lastBrace = afterAnchor.lastIndexOf('}');
                if (firstBrace !== -1 && lastBrace !== -1) {
                    jsonText = afterAnchor.slice(firstBrace, lastBrace + 1).trim();
                }
            }

            // Fallback: first JSON block in the entire response
            if (!jsonText && response.includes('{')) {
                const firstBrace = response.indexOf('{');
                const lastBrace = response.lastIndexOf('}');
                jsonText = response.slice(firstBrace, lastBrace + 1).trim();
            }

            if (!jsonText) {
                console.warn("⚠️ No JSON detected in ZATCA response");
                return;
            }

            // Safely parse JSON
            const zatca = JSON.parse(jsonText);
            const vr = zatca?.validationResults;

            // Extract errors & warnings
            let errors = Array.isArray(vr?.errorMessages) ? vr.errorMessages : [];
            const warnings = Array.isArray(vr?.warningMessages) ? vr.warningMessages : [];

            // 🔴 Special condition → ignore Duplicate-Invoice error
            errors = errors.filter(e => !(e.code === "Invoice-Errors" && e.category === "Duplicate-Invoice"));

            // If no valid errors/warnings remain, stop
            if (!errors.length && !warnings.length) return;

            let combined_html = "";

            if (errors.length) {
                combined_html += `<div style="color:#b71c1c; font-weight:bold;">Errors:</div>`;
                combined_html += `<div style="color:#b71c1c;">` + errors.map(e =>
                    `<div style="margin-left:10px;"><b>${e.code}</b>: ${e.message}</div>`
                ).join('') + `</div>`;
            }

            if (warnings.length) {
                combined_html += `<div style="color:#ef6c00; font-weight:bold; margin-top:10px;">Warnings:</div>`;
                combined_html += `<div style="color:#ef6c00;">` + warnings.map(w =>
                    `<div style="margin-left:10px;"><b>${w.code}</b>: ${w.message}</div>`
                ).join('') + `</div>`;
            }

            // Show orange if only warnings, red if errors exist
            const alertColor = errors.length ? 'red' : 'orange';

            frm.dashboard.clear_headline();
            frm.dashboard.set_headline_alert(combined_html, alertColor);

        } catch (e) {
            console.warn("❌ ZATCA JSON parse failed", e);
        }
    }
});


// frappe.ui.form.on('Sales Invoice', {
//     refresh(frm) {
//         const response = frm.doc.custom_zatca_full_response;
//         if (!response) return;

//         try {
//             let jsonText = null;

//             // Try extract after 'ZATCA Response:'
//             const anchor = 'ZATCA Response:';
//             if (response.includes(anchor)) {
//                 const afterAnchor = response.split(anchor)[1];
//                 const firstBrace = afterAnchor.indexOf('{');
//                 const lastBrace = afterAnchor.lastIndexOf('}');
//                 if (firstBrace !== -1 && lastBrace !== -1) {
//                     jsonText = afterAnchor.slice(firstBrace, lastBrace + 1).trim();
//                 }
//             }

//             // Fallback: first JSON block in the entire response
//             if (!jsonText && response.includes('{')) {
//                 const firstBrace = response.indexOf('{');
//                 const lastBrace = response.lastIndexOf('}');
//                 jsonText = response.slice(firstBrace, lastBrace + 1).trim();
//             }

//             if (!jsonText) {
//                 console.warn("⚠️ No JSON detected in ZATCA response");
//                 return;
//             }

//             // Safely parse JSON
//             const zatca = JSON.parse(jsonText);
//             const vr = zatca?.validationResults;

//             const errors = Array.isArray(vr?.errorMessages) ? vr.errorMessages : [];
//             const warnings = Array.isArray(vr?.warningMessages) ? vr.warningMessages : [];

//             if (!errors.length && !warnings.length) return;

//             let combined_html = "";

//             if (errors.length) {
//                 combined_html += `<div style="color:#b71c1c; font-weight:bold;">Errors:</div>`;
//                 combined_html += `<div style="color:#b71c1c;">` + errors.map(e =>
//                     `<div style="margin-left:10px;"><b>${e.code}</b>: ${e.message}</div>`
//                 ).join('') + `</div>`;
//             }

//             if (warnings.length) {
//                 combined_html += `<div style="color:#ef6c00; font-weight:bold; margin-top:10px;">Warnings:</div>`;
//                 combined_html += `<div style="color:#ef6c00;">` + warnings.map(w =>
//                     `<div style="margin-left:10px;"><b>${w.code}</b>: ${w.message}</div>`
//                 ).join('') + `</div>`;
//             }

//             // Show orange if no errors, red if errors exist
//             const alertColor = errors.length ? 'red' : 'orange';

//             frm.dashboard.clear_headline();
//             frm.dashboard.set_headline_alert(combined_html, alertColor);

//         } catch (e) {
//             console.warn("❌ ZATCA JSON parse failed", e);
//         }
//     }
// });


frappe.ui.form.on('Sales Invoice', {
    refresh: function(frm) {
        if (!frm.is_new()) {
            // Add menu item like Print PDF-A3
            frm.page.add_menu_item(__('Create XML for Debug'), function() {
                frappe.call({
                    method: "zatca_erpgulf.zatca_erpgulf.debug_xml.debug_call",
                    args: {
                        invoice_number: frm.doc.name
                    },
                    freeze: true,
                    freeze_message: __("Generating Debug XML..."),
                    callback: function(r) {
                        if (r.message && r.message.status === "success") {
                            frappe.msgprint(__('✅ Debug XML attached successfully!'));
                            frm.reload_doc();
                        }
                    }
                });
            });
        }
    }
});
