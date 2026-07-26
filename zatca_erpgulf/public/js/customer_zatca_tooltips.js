(function () {
    function zatca_escape_html(value) {
        if (frappe.utils && frappe.utils.escape_html) {
            return frappe.utils.escape_html(value || "");
        }

        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function translated_html(lines) {
        return lines.map(function (line) {
            return zatca_escape_html(__(line));
        }).join("<br>");
    }

    function add_info_icon(frm, fieldname, content_html) {
        const field = frm.get_field(fieldname);

        if (!field || !field.$wrapper) {
            return;
        }

        const label = field.$wrapper.find(".control-label").first();

        if (!label.length || label.find(".zatca-customer-info-icon").length) {
            return;
        }

        const icon = $(`
            <span class="zatca-customer-info-icon text-info" style="margin-inline-start: 6px; cursor: pointer;">
                <i class="fa fa-info-circle"></i>
            </span>
        `);

        icon.attr("data-toggle", "popover");
        icon.attr("data-trigger", "click hover");
        icon.attr("data-placement", "auto");
        icon.attr("data-html", "true");
        icon.attr("data-content", content_html);

        label.append(icon);

        icon.popover({
            html: true,
            trigger: "click hover",
            placement: "auto",
            container: "body",
            content: content_html,
        });
    }

    frappe.ui.form.on("Customer", {
        refresh: function (frm) {
            const customerIdHelp = translated_html([
                "Customer ID Type for ZATCA. Select the type that matches the customer identification number.",
                "TIN: Tax Identification Number issued by ZATCA; usually the first 10 digits of the VAT number",
                "CRN: Commercial Registration Number issued by the Ministry of Commerce",
                "MOM: MHRSD license for labor-related activities",
                "MLS: MOMRAH license for municipal activities",
                "700: National Establishment Number",
                "SAG: MISA license for foreign companies and investors",
                "NAT: Saudi National ID",
                "GCC: GCC National ID",
                "IQA: Saudi residence permit / Iqama",
                "PAS: Passport number for non-resident individuals",
                "OTH: Other ID when none of the listed IDs applies",
                "VAT note: if the 11th digit in the VAT number is 1, it indicates Group VAT. Otherwise, it is Single VAT.",
            ]);

            add_info_icon(frm, "custom_buyer_id_type", customerIdHelp);
        },
    });
})();
