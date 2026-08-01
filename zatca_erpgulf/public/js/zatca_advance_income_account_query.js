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

    frappe.ui.form.on("Sales Invoice", {
        setup: apply_income_account_query,
        onload: apply_income_account_query,
        refresh: apply_income_account_query,
        company: apply_income_account_query,
        is_advance_payment: apply_income_account_query,
        custom_is_advance_payment: apply_income_account_query
    });
})();
