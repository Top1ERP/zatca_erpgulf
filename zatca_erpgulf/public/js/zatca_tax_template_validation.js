(function () {
    "use strict";

    const NON_STANDARD = [
        "Zero Rated",
        "Exempted",
        "Services outside scope of tax / Not subject to VAT"
    ];
    const EXEMPTION_CODES = {
        Standard: [],
        Exempted: ["VATEX-SA-29", "VATEX-SA-29-7", "VATEX-SA-30"],
        "Zero Rated": [
            "VATEX-SA-32", "VATEX-SA-33", "VATEX-SA-34-1", "VATEX-SA-34-2",
            "VATEX-SA-34-3", "VATEX-SA-34-4", "VATEX-SA-34-5", "VATEX-SA-35",
            "VATEX-SA-36", "VATEX-SA-EDU", "VATEX-SA-HEA", "VATEX-SA-MLTRY"
        ],
        "Services outside scope of tax / Not subject to VAT": ["VATEX-SA-OOS"]
    };

    function phase2Enabled(frm) {
        return Boolean(
            frm.doc.company &&
            frm.__zatca_template_company_enabled === true
        );
    }

    async function loadCompanyState(frm) {
        if (!frm.doc.company) {
            frm.__zatca_template_company_enabled = false;
            return false;
        }
        try {
            let response;
            let phaseField = "custom_phase_1_or_2";
            try {
                response = await frappe.db.get_value(
                    "Company",
                    frm.doc.company,
                    ["custom_zatca_invoice_enabled", phaseField]
                );
            } catch (primaryError) {
                // Older sites may expose the legacy field name only.
                phaseField = "phase_1_or_2";
                response = await frappe.db.get_value(
                    "Company",
                    frm.doc.company,
                    ["custom_zatca_invoice_enabled", phaseField]
                );
            }
            const values = (response && response.message) || {};
            frm.__zatca_template_company_enabled =
                cint(values.custom_zatca_invoice_enabled) === 1;
        } catch (error) {
            // Shared sites may expose neither optional Company field.
            // Treat the optional ZATCA template rules as unavailable.
            frm.__zatca_template_company_enabled = false;
        }
        return frm.__zatca_template_company_enabled;
    }

    const EXEMPTION_REASON_HELP = [
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
        __("VATEX-SA-OOS: Services outside scope of tax / reason provided by taxpayer case by case")
    ].join("<br>");

    function addExemptionReasonTooltip(frm) {
        const field = frm.fields_dict.custom_exemption_reason_code;
        if (!field || !field.$wrapper || field.$wrapper.find(".zatca-exemption-tooltip").length) return;
        const label = field.$wrapper.find("label").first();
        if (!label.length) return;
        const tooltip = new Tooltip({
            containerClass: "zatca-exemption-tooltip",
            tooltipClass: "custom-tooltip",
            iconClass: "info-icon",
            text: EXEMPTION_REASON_HELP,
            links: []
        });
        tooltip.renderTooltip(label[0]);
        // Keep the info icon inline with the label instead of placing it below.
        const container = field.$wrapper.find(".zatca-exemption-tooltip").last();
        if (container.length) {
            label.append(container);
            label.css({ display: "inline-flex", alignItems: "center", width: "auto" });
        }
    }

    function applyCategoryState(frm) {
        const category = String(frm.doc.custom_zatca_tax_category || "").trim();
        const nonStandard = NON_STANDARD.includes(category);
        const allowedCodes = EXEMPTION_CODES[category] || [];
        if (frm.fields_dict.custom_exemption_reason_code) {
            frm.set_df_property("custom_exemption_reason_code", "options", allowedCodes.join("\n"));
            if (frm.doc.custom_exemption_reason_code && !allowedCodes.includes(frm.doc.custom_exemption_reason_code)) {
                frm.set_value("custom_exemption_reason_code", "");
            }
            frm.toggle_display("custom_exemption_reason_code", nonStandard);
            frm.set_df_property("custom_exemption_reason_code", "reqd", nonStandard);
            if (!nonStandard && frm.doc.custom_exemption_reason_code) {
                frm.set_value("custom_exemption_reason_code", "");
            }
        }

        if (nonStandard) {
            (frm.doc.taxes || []).forEach(function (row) {
                const rateField = frm.doctype === "Item Tax Template" ? "tax_rate" : "rate";
                if (flt(row[rateField])) {
                    frappe.model.set_value(row.doctype, row.name, rateField, 0);
                }
            });
        }
    }

    async function refreshTemplateState(frm) {
        // Hide controlled fields immediately while the Company state is loading.
        if (frm.fields_dict.custom_zatca_tax_category) {
            frm.toggle_display("custom_zatca_tax_category", false);
            frm.set_df_property("custom_zatca_tax_category", "reqd", false);
        }
        if (frm.fields_dict.custom_exemption_reason_code) {
            frm.toggle_display("custom_exemption_reason_code", false);
            frm.set_df_property("custom_exemption_reason_code", "reqd", false);
        }

        await loadCompanyState(frm);
        const active = phase2Enabled(frm);
        if (frm.fields_dict.custom_zatca_tax_category) {
            frm.toggle_display("custom_zatca_tax_category", active);
        }
        addExemptionReasonTooltip(frm);
        if (!active) {
            return;
        }
        applyCategoryState(frm);
    }

    ["Sales Taxes and Charges Template", "Item Tax Template"].forEach(function (doctype) {
        frappe.ui.form.on(doctype, {
            onload: refreshTemplateState,
            refresh: refreshTemplateState,
            company: refreshTemplateState,
            custom_zatca_tax_category: applyCategoryState,
            validate: function (frm) {
                if (phase2Enabled(frm)) {
                    applyCategoryState(frm);
                }
            }
        });
    });
})();
