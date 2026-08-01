(function () {
    "use strict";

    const STANDARD_INCOME_ACCOUNT_QUERY =
        "erpnext.controllers.queries.get_income_account";

    function is_advance_payment_invoice(frm) {
        return Boolean(
            cint(frm.doc.is_advance_payment) ||
            cint(frm.doc.custom_is_advance_payment)
        );
    }

    function get_income_account_query(frm) {
        if (!is_advance_payment_invoice(frm)) {
            return {
                query: STANDARD_INCOME_ACCOUNT_QUERY,
                filters: {
                    company: frm.doc.company,
                    disabled: 0
                }
            };
        }

        return {
            filters: {
                company: frm.doc.company || "",
                is_group: 0,
                disabled: 0,
                account_type: ["not in", ["Receivable", "Payable"]]
            }
        };
    }

    function apply_income_account_query(frm) {
        frm.set_query("income_account", "items", function () {
            return get_income_account_query(frm);
        });
    }

    function apply_preferred_advance_account(frm) {
        if (!is_advance_payment_invoice(frm) || !frm.doc.company) return;

        frappe.db.get_value(
            "Company",
            frm.doc.company,
            ["default_deferred_revenue_account", "default_income_account"]
        ).then(function (response) {
            const values = (response && response.message) || {};
            const preferred = values.default_deferred_revenue_account || "";
            const ordinary = values.default_income_account || "";

            if (!preferred) {
                frappe.show_alert({
                    indicator: "orange",
                    message: __(
                        "Default Deferred Revenue Account is not configured. Choose the advance Income Account manually."
                    )
                });
                return;
            }

            (frm.doc.items || []).forEach(function (row) {
                if (!row.income_account || row.income_account === ordinary) {
                    frappe.model.set_value(
                        row.doctype,
                        row.name,
                        "income_account",
                        preferred
                    );
                }
            });
        });
    }

    function configure_advance_income_account(frm) {
        apply_income_account_query(frm);
        apply_preferred_advance_account(frm);
    }

    frappe.ui.form.on("Sales Invoice", {
        setup: configure_advance_income_account,
        onload: configure_advance_income_account,
        refresh: configure_advance_income_account,
        company: configure_advance_income_account,
        is_advance_payment: configure_advance_income_account,
        custom_is_advance_payment: configure_advance_income_account
    });
})();
