frappe.listview_settings["ZATCA Advance Tax Invoice"] = {
    add_fields: ["company", "customer", "posting_date", "currency", "total_amount", "base_total_amount", "status", "zatca_status", "preflight_status"],

    get_indicator: function (doc) {
        const status = doc.zatca_status || "Not Submitted";

        if (["Cleared", "Reported"].includes(status)) return [__(status), "green", "zatca_status,=," + status];
        if (status === "Failed") return [__(status), "red", "zatca_status,=,Failed"];
        if (status === "Warning") return [__(status), "orange", "zatca_status,=,Warning"];
        if (["Debug XML Created", "Preflight Passed"].includes(status)) return [__(status), "blue", "zatca_status,=," + status];

        return [__(status), "gray", "zatca_status,=," + status];
    }
};
