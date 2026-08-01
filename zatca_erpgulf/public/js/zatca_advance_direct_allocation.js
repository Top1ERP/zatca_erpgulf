(function () {
    "use strict";

    const TABLE_FIELD = "custom_zatca_advance_deduction_details";
    const CHILD_DOCTYPE = "ZATCA Sales Invoice Advance Deduction";
    const DETAILS_METHOD =
        "zatca_erpgulf.zatca_erpgulf.advance_deduction.get_advance_allocation_details";
    const QUERY_METHOD =
        "zatca_erpgulf.zatca_erpgulf.advance_deduction.get_available_advance_invoice_query";

    function roundCurrency(value) {
        return Math.round((Number(value || 0) + Number.EPSILON) * 100) / 100;
    }

    function clearDerivedFields(cdt, cdn) {
        [
            "payment_entry",
            "advance_invoice_date",
            "advance_status",
            "currency",
            "advance_total_amount",
            "advance_taxable_amount",
            "advance_tax_amount",
            "allocated_taxable_amount",
            "allocated_tax_amount",
            "remarks"
        ].forEach((fieldname) => frappe.model.set_value(cdt, cdn, fieldname, null));
    }

    function updateAllocationSplit(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        const total = roundCurrency(row.allocated_total_amount);
        const advanceTotal = roundCurrency(row.advance_total_amount);
        const advanceTaxable = roundCurrency(row.advance_taxable_amount);

        if (!advanceTotal || total <= 0) {
            frappe.model.set_value(cdt, cdn, "allocated_taxable_amount", 0);
            frappe.model.set_value(cdt, cdn, "allocated_tax_amount", 0);
            updateDocumentTotals(frm);
            return;
        }

        const taxable = roundCurrency((total * advanceTaxable) / advanceTotal);
        const tax = roundCurrency(total - taxable);
        frappe.model.set_value(cdt, cdn, "allocated_taxable_amount", taxable);
        frappe.model.set_value(cdt, cdn, "allocated_tax_amount", tax);
        updateDocumentTotals(frm);
    }

    function updateDocumentTotals(frm) {
        const rows = frm.doc[TABLE_FIELD] || [];
        const taxable = roundCurrency(
            rows.reduce((total, row) => total + Number(row.allocated_taxable_amount || 0), 0)
        );
        const tax = roundCurrency(
            rows.reduce((total, row) => total + Number(row.allocated_tax_amount || 0), 0)
        );
        const inclusive = roundCurrency(
            rows.reduce((total, row) => total + Number(row.allocated_total_amount || 0), 0)
        );

        frm.set_value("custom_zatca_advance_deducted_taxable_amount", taxable);
        frm.set_value("custom_zatca_advance_deducted_vat_amount", tax);
        frm.set_value("custom_zatca_prepaid_amount", inclusive);
        frm.set_value("custom_zatca_advance_deduction_count", rows.length);
    }

    function loadAdvanceDetails(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        const selectedAdvance = row.advance_invoice;

        if (!selectedAdvance) {
            clearDerivedFields(cdt, cdn);
            frappe.model.set_value(cdt, cdn, "allocated_total_amount", 0);
            updateDocumentTotals(frm);
            return;
        }

        frappe.call({
            method: DETAILS_METHOD,
            args: {
                advance_invoice: selectedAdvance,
                final_invoice: frm.is_new() ? null : frm.doc.name
            },
            freeze: false,
            callback(response) {
                const currentRow = locals[cdt] && locals[cdt][cdn];
                if (!currentRow || currentRow.advance_invoice !== selectedAdvance) {
                    return;
                }

                const values = response.message || {};
                [
                    "payment_entry",
                    "advance_invoice_date",
                    "advance_status",
                    "currency",
                    "advance_total_amount",
                    "advance_taxable_amount",
                    "advance_tax_amount"
                ].forEach((fieldname) => {
                    frappe.model.set_value(cdt, cdn, fieldname, values[fieldname] || null);
                });

                const currentAllocation = roundCurrency(currentRow.allocated_total_amount);
                if (!currentAllocation && values.available_amount > 0) {
                    frappe.model.set_value(
                        cdt,
                        cdn,
                        "allocated_total_amount",
                        roundCurrency(values.available_amount)
                    );
                }
                frappe.model.set_value(
                    cdt,
                    cdn,
                    "remarks",
                    __("Available before this allocation: {0}", [
                        format_currency(values.available_amount, values.currency)
                    ])
                );
                updateAllocationSplit(frm, cdt, cdn);
            }
        });
    }

    frappe.ui.form.on("Sales Invoice", {
        setup(frm) {
            frm.set_query("advance_invoice", TABLE_FIELD, function () {
                return {
                    query: QUERY_METHOD,
                    filters: {
                        company: frm.doc.company,
                        customer: frm.doc.customer,
                        currency: frm.doc.currency,
                        final_invoice: frm.is_new() ? null : frm.doc.name
                    }
                };
            });
        },
        refresh(frm) {
            updateDocumentTotals(frm);
        }
    });

    frappe.ui.form.on(CHILD_DOCTYPE, {
        advance_invoice: loadAdvanceDetails,
        allocated_total_amount: updateAllocationSplit,
        custom_zatca_advance_deduction_details_remove(frm) {
            updateDocumentTotals(frm);
        }
    });
})();
