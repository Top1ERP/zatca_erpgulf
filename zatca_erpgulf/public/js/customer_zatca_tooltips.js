function zatca_first_present(doc, fieldnames, fallback = undefined) {
    for (const fieldname of fieldnames) {
        if (doc && Object.prototype.hasOwnProperty.call(doc, fieldname)) return doc[fieldname];
    }
    return fallback;
}

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

async function zatca_load_customer_policy(frm) {
    const response = await frappe.call({
        method: "zatca_erpgulf.zatca_erpgulf.customer_validation.get_customer_validation_policy_for_form",
        args: { customer: frm.doc.name && !frm.is_new() ? frm.doc.name : null },
    });
    const policy = response.message || {};
    let country = String(frm.doc.territory || "").trim().toLowerCase();
    if (frm.doc.customer_primary_address) {
        const address = await frappe.db.get_value("Address", frm.doc.customer_primary_address, "country");
        country = String(address?.message?.country || country).trim().toLowerCase();
    }
    frm.__zatca_customer_policy = {
        enabled: !!policy.enabled,
        require_on_save: !!policy.require_on_save,
        zatca_phase2: !!policy.zatca_phase2,
        needs_id: !!policy.enabled && ["sa", "saudi arabia"].includes(country) && !Number(zatca_first_present(frm.doc, ["custom_b2c", "b2c", "is_b2c", "zatca_b2c"], 0) || 0),
    };
    zatca_sync_customer_fields_visibility(frm);

}
function zatca_sync_customer_fields_visibility(frm) {
    const policy = frm.__zatca_customer_policy || {};
    const fields = [
        ["custom_b2c", ["custom_b2c", "b2c", "is_b2c", "zatca_b2c"]],
        ["custom_buyer_id_type", ["custom_buyer_id_type", "buyer_id_type", "zatca_buyer_id_type"]],
        ["custom_buyer_id", ["custom_buyer_id", "buyer_id", "zatca_buyer_id"]],
    ];
    // Customer ZATCA identification fields are a Phase-2 UI feature.
    // Hide them in Phase-1 even when legacy records contain old values; the
    // server-side aliases still preserve compatibility for those records.
    const visible = !!policy.zatca_phase2;
    fields.forEach(([canonical]) => {
        if (frm.fields_dict[canonical]) frm.toggle_display(canonical, visible);
    });
}

function zatca_sync_arabic_names(frm, source) {
    if (frm.__zatca_syncing_arabic_names) return;
    const fields = ["zatca_customer_name_in_arabic", "customer_name_in_arabic", "custom_customer_name_in_arabic"]
        .filter((fieldname) => !!frm.fields_dict[fieldname]);
    const value = frm.doc[source] || "";
    frm.__zatca_syncing_arabic_names = true;
    fields.filter((fieldname) => fieldname !== source && (frm.doc[fieldname] || "") !== value)
        .forEach((fieldname) => frm.set_value(fieldname, value));
    frm.__zatca_syncing_arabic_names = false;
}

function zatca_missing_tax_id_hint(frm) {
    const state = frm.__zatca_customer_policy;
    if (!state || !state.enabled || !state.needs_id || frm.doc.tax_id) return;
    frappe.show_alert({ message: __("Tax ID is empty for this Saudi B2B customer. Provide a 15-digit Tax ID when available."), indicator: "orange" }, 7);
}

function zatca_live_buyer_hint(frm) {
    const state = frm.__zatca_customer_policy;
    const rawValue = String(zatca_first_present(frm.doc, ["custom_buyer_id", "buyer_id", "zatca_buyer_id"], "") || "");
    const rawTaxId = String(frm.doc.tax_id || "");
    const value = rawValue.trim();
    const taxId = rawTaxId.trim();
    const type = String(zatca_first_present(frm.doc, ["custom_buyer_id_type", "buyer_id_type", "zatca_buyer_id_type"], "") || "").trim().toUpperCase();
    if (!state || !state.enabled || !state.needs_id || !value || !type) return;
    const valid = type === "TIN" ? /^3\d{9}$/.test(value) : !/\s/.test(value);
    const whitespaceInvalid = /\s/.test(rawValue) || /\s/.test(rawTaxId);
    const taxIdInvalid = taxId && !/^3\d{13}3$/.test(taxId);
    const tinMismatch = type === "TIN" && taxId && !taxId.startsWith(value);
    const key = `${type}:${value}`;
    if ((valid && !whitespaceInvalid && !taxIdInvalid && !tinMismatch) || frm.__zatca_last_buyer_hint === key) return;
    frm.__zatca_last_buyer_hint = key;
    const message = whitespaceInvalid
        ? __("Buyer ID and Tax ID must not contain spaces.")
        : taxIdInvalid
            ? __("The customer is in Saudi Arabia based on Territory or the primary address. Tax ID must contain 15 digits, start with 3, and end with 3.")
            : tinMismatch
                ? __("TIN and Tax ID do not match. TIN must equal the first 10 digits of Tax ID.<br>TIN: {0}<br>Tax ID: {1}").replace("{0}", value).replace("{1}", taxId)
                : __("Buyer ID format is invalid for the selected ZATCA identification type.");
    frappe.show_alert({ message, indicator: "orange" }, 7);
}

frappe.ui.form.on("Customer", {
    refresh(frm) { zatca_sync_customer_fields_visibility(frm); zatca_load_customer_policy(frm).catch(() => {}); },
    custom_b2c(frm) { zatca_load_customer_policy(frm).catch(() => {}); },
    customer_primary_address(frm) { zatca_load_customer_policy(frm).catch(() => {}); },
    territory(frm) { zatca_load_customer_policy(frm).catch(() => {}); },
    custom_buyer_id(frm) { zatca_live_buyer_hint(frm); },
    custom_buyer_id_type(frm) { zatca_live_buyer_hint(frm); },
    tax_id(frm) { zatca_missing_tax_id_hint(frm); },
    zatca_customer_name_in_arabic(frm) { zatca_sync_arabic_names(frm, "zatca_customer_name_in_arabic"); },
    customer_name_in_arabic(frm) { zatca_sync_arabic_names(frm, "customer_name_in_arabic"); },
    custom_customer_name_in_arabic(frm) { zatca_sync_arabic_names(frm, "custom_customer_name_in_arabic"); },
    before_save(frm) {
        const state = frm.__zatca_customer_policy;
        const customerType = String(frm.doc.customer_type || "").trim().toLowerCase();
        if (["individual", "partnership"].includes(customerType)) return;
        if (!state || !state.enabled || !state.needs_id || state.require_on_save || zatca_first_present(frm.doc, ["custom_buyer_id", "buyer_id", "zatca_buyer_id"], "")) return;
        if (frm.__zatca_customer_warning_confirmed) return;
        frappe.validated = false;
        const dialog = new frappe.ui.Dialog({ title: __("ZATCA Customer Validation"), fields: [{ fieldtype: "HTML", options: __("Buyer ID is empty. Continue saving this incomplete Saudi B2B Customer record?") }], primary_action_label: __("Continue Saving"), primary_action() { frm.__zatca_customer_warning_confirmed = true; dialog.hide(); frm.save(); } });
        dialog.set_secondary_action(() => dialog.hide());
        dialog.set_secondary_action_label(__("Return to Edit"));
        dialog.show();
    },
});
