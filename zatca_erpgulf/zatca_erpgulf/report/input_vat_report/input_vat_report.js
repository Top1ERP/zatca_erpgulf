frappe.query_reports["Input VAT Report"] = {
    filters: [
        {
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Link",
            options: "Company",
            default: frappe.defaults.get_user_default("Company"),
            reqd: 0
        },
        {
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date",
            default: frappe.datetime.month_start(),
            reqd: 0
        },
        {
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date",
            default: frappe.datetime.month_end(),
            reqd: 0
        },
        {
            fieldname: "zatca_tax_category",
            label: __("ZATCA Tax Category"),
            fieldtype: "Select",
            options: "\nStandard\nZero Rated\nExempted\nServices outside scope of tax / Not subject to VAT",
            reqd: 0
        }
    ]
};
