(function () {
    "use strict";

    const TABLE_FIELD =
        "custom_zatca_advance_deduction_details";
    const CHILD_DOCTYPE =
        "ZATCA Sales Invoice Advance Deduction";

    const TOTAL_FIELDS = [
        "custom_zatca_advance_deducted_taxable_amount",
        "custom_zatca_advance_deducted_vat_amount",
        "custom_zatca_prepaid_amount",
        "custom_zatca_advance_deduction_count"
    ];

    const DETAILS_METHOD =
        "zatca_erpgulf.zatca_erpgulf.advance_deduction.get_advance_allocation_details";

    const QUERY_METHOD =
        "zatca_erpgulf.zatca_erpgulf.advance_deduction.get_available_advance_invoice_query";

    function runtime() {
        return frappe.zatcaAdvanceRuntime;
    }

    function fieldExists(frm, fieldname) {
        return Boolean(
            frm &&
            frm.fields_dict &&
            frm.fields_dict[fieldname]
        );
    }

    function isReturn(frm) {
        return Number(frm?.doc?.is_return || 0) === 1;
    }

    function allocationFeatureExists(frm) {
        const helper = runtime();
        return Boolean(
            helper &&
            helper.capabilityAvailable(
                frm,
                "advance_deduction"
            ) &&
            fieldExists(frm, TABLE_FIELD)
        );
    }

    async function getCurrentAllocationState(frm) {
        const helper = runtime();
        if (!helper) {
            return null;
        }

        const state = helper.captureFormState(frm);
        const capabilities = await helper.getCapabilities(frm);

        if (
            capabilities.advance_deduction !== true ||
            !helper.isCurrentFormState(frm, state) ||
            !allocationFeatureExists(frm)
        ) {
            return null;
        }

        return state;
    }

    function childRowExists(cdt, cdn) {
        return Boolean(
            typeof locals !== "undefined" &&
            locals &&
            locals[cdt] &&
            locals[cdt][cdn]
        );
    }

    function roundCurrency(value) {
        return (
            Math.round(
                (Number(value || 0) + Number.EPSILON) * 100
            ) / 100
        );
    }

    function finalInvoiceRemainingAmount(frm, currentRow) {
        const invoiceTotal = Math.abs(roundCurrency(
            frm.doc.rounded_total || frm.doc.grand_total
        ));
        if (!invoiceTotal) {
            return Number.POSITIVE_INFINITY;
        }
        const rows = Array.isArray(frm.doc[TABLE_FIELD])
            ? frm.doc[TABLE_FIELD]
            : [];
        const allocatedElsewhere = rows.reduce(function (total, row) {
            if (currentRow && row.name === currentRow.name) {
                return total;
            }
            return total + (isReturn(frm)
                ? Math.abs(roundCurrency(row.allocated_total_amount))
                : roundCurrency(row.allocated_total_amount));
        }, 0);
        return Math.max(0, roundCurrency(invoiceTotal - allocatedElsewhere));
    }

    function clampAllocationAmount(frm, cdt, cdn) {
        if (!childRowExists(cdt, cdn)) {
            return;
        }

        const row = locals[cdt][cdn];
        const rawRequested = roundCurrency(row.allocated_total_amount);
        if (isReturn(frm) && rawRequested > 0) {
            frappe.model.set_value(cdt, cdn, "allocated_total_amount", -rawRequested);
            frappe.msgprint({
                title: __("Invalid advance reversal amount"),
                message: __("Return ZATCA advance reversal amount must be negative."),
                indicator: "red"
            });
        }
        const requested = isReturn(frm)
            ? Math.abs(rawRequested)
            : Math.max(0, rawRequested);
        const available = Number(row.__zatca_available_amount);
        const advanceLimit = Number.isFinite(available)
            ? Math.max(0, roundCurrency(available))
            : roundCurrency(row.advance_total_amount);
        const invoiceLimit = finalInvoiceRemainingAmount(frm, row);
        const originalFinalAllocationLimit = isReturn(frm)
            ? Number(row.__zatca_return_source_amount)
            : Number.POSITIVE_INFINITY;
        const capped = Math.min(
            requested,
            advanceLimit,
            invoiceLimit,
            Number.isFinite(originalFinalAllocationLimit)
                ? Math.max(0, roundCurrency(originalFinalAllocationLimit))
                : Number.POSITIVE_INFINITY
        );

        if (requested !== capped) {
            frappe.model.set_value(
                cdt,
                cdn,
                "allocated_total_amount",
                isReturn(frm) ? -capped : capped
            );
            frappe.show_alert({
                message: isReturn(frm)
                    ? __(
                        "Return reversal was limited to the amount allocated by the original final invoice."
                    )
                    : __(
                        "Applied amount was limited to the remaining invoice and advance balance."
                    ),
                indicator: "orange"
            });
        }
    }

    function setParentValueIfFieldExists(
        frm,
        fieldname,
        value
    ) {
        if (
            !allocationFeatureExists(frm) ||
            !fieldExists(frm, fieldname)
        ) {
            return Promise.resolve();
        }

        return frm.set_value(fieldname, value);
    }

    function clearDerivedFields(frm, cdt, cdn) {
        if (
            !allocationFeatureExists(frm) ||
            !childRowExists(cdt, cdn)
        ) {
            return;
        }

        [
            "payment_entry",
            "advance_invoice_date",
            "advance_status",
            "currency",
            "available_advance_remaining_amount",
            "advance_total_amount",
            "advance_taxable_amount",
            "advance_tax_amount",
            "allocated_taxable_amount",
            "allocated_tax_amount",
            "remarks"
        ].forEach(function (fieldname) {
            frappe.model.set_value(
                cdt,
                cdn,
                fieldname,
                null
            );
        });
    }

    function updateAllocationSplit(frm, cdt, cdn) {
        if (
            !allocationFeatureExists(frm) ||
            !childRowExists(cdt, cdn)
        ) {
            return;
        }

        const row = locals[cdt][cdn];
        const total = roundCurrency(row.allocated_total_amount);
        const advanceTotal = roundCurrency(
            row.advance_total_amount
        );
        const advanceTaxable = roundCurrency(
            row.advance_taxable_amount
        );

        if (!advanceTotal || !total) {
            frappe.model.set_value(
                cdt,
                cdn,
                "allocated_taxable_amount",
                0
            );

            frappe.model.set_value(
                cdt,
                cdn,
                "allocated_tax_amount",
                0
            );

            updateDocumentTotals(frm);
            return;
        }

        const taxable = roundCurrency((Math.abs(total) * advanceTaxable) / advanceTotal) *
            (isReturn(frm) ? -1 : 1);

        const tax = roundCurrency(Math.abs(total) - Math.abs(taxable)) *
            (isReturn(frm) ? -1 : 1);

        frappe.model.set_value(
            cdt,
            cdn,
            "allocated_taxable_amount",
            taxable
        );

        frappe.model.set_value(
            cdt,
            cdn,
            "allocated_tax_amount",
            tax
        );

        updateDocumentTotals(frm);
    }

    function configureAllocationGrid(frm) {
        const field = frm.fields_dict && frm.fields_dict[TABLE_FIELD];
        if (!field || !field.grid) {
            return;
        }

        // Keep Applied Total Incl. VAT editable directly in the child grid.
        field.grid.editable_grid = true;
        if (field.df) {
            field.df.editable_grid = 1;
        }
        field.grid.refresh();
    }

    function hydrateExistingRows(frm, state) {
        const rows = Array.isArray(frm.doc[TABLE_FIELD])
            ? frm.doc[TABLE_FIELD]
            : [];
        rows.forEach(function (row) {
            if (
                row.advance_invoice &&
                (
                    !row.payment_entry ||
                    !Number(row.advance_total_amount || 0) ||
                    row.available_advance_remaining_amount == null ||
                    (
                        !Number(row.available_advance_remaining_amount) &&
                        Number(row.advance_total_amount || 0) > 0
                    )
                )
            ) {
                loadAdvanceDetails(
                    frm,
                    row.doctype || CHILD_DOCTYPE,
                    row.name,
                    state
                );
            }
        });
    }

    function updateDocumentTotals(frm) {
        if (!allocationFeatureExists(frm)) {
            return;
        }

        const rows = Array.isArray(frm.doc[TABLE_FIELD])
            ? frm.doc[TABLE_FIELD]
            : [];

        const taxable = roundCurrency(
            rows.reduce(function (total, row) {
                return (
                    total +
                    Number(
                        row.allocated_taxable_amount || 0
                    )
                );
            }, 0)
        );

        const tax = roundCurrency(
            rows.reduce(function (total, row) {
                return (
                    total +
                    Number(row.allocated_tax_amount || 0)
                );
            }, 0)
        );

        const inclusive = roundCurrency(
            rows.reduce(function (total, row) {
                return (
                    total +
                    Number(row.allocated_total_amount || 0)
                );
            }, 0)
        );

        setParentValueIfFieldExists(
            frm,
            TOTAL_FIELDS[0],
            taxable
        );

        setParentValueIfFieldExists(
            frm,
            TOTAL_FIELDS[1],
            tax
        );

        setParentValueIfFieldExists(
            frm,
            TOTAL_FIELDS[2],
            inclusive
        );

        setParentValueIfFieldExists(
            frm,
            TOTAL_FIELDS[3],
            rows.length
        );
    }

    function loadAdvanceDetails(frm, cdt, cdn, state) {
        const helper = runtime();
        if (
            !helper ||
            !allocationFeatureExists(frm) ||
            !helper.isCurrentFormState(frm, state) ||
            !childRowExists(cdt, cdn)
        ) {
            return;
        }

        const row = locals[cdt][cdn];
        const selectedAdvance = row.advance_invoice;

        if (!selectedAdvance) {
            clearDerivedFields(frm, cdt, cdn);

            frappe.model.set_value(
                cdt,
                cdn,
                "allocated_total_amount",
                0
            );

            updateDocumentTotals(frm);
            return;
        }

        frappe.call({
            method: DETAILS_METHOD,
            args: {
                advance_invoice: selectedAdvance,
                final_invoice: frm.is_new()
                    ? null
                    : frm.doc.name
            },
            freeze: false,
            callback(response) {
                if (
                    !allocationFeatureExists(frm) ||
                    !helper.isCurrentFormState(frm, state) ||
                    !childRowExists(cdt, cdn)
                ) {
                    return;
                }

                const currentRow = locals[cdt][cdn];

                if (
                    currentRow.advance_invoice !==
                    selectedAdvance
                ) {
                    return;
                }

                const values = response && response.message;
                if (
                    !values ||
                    typeof values !== "object" ||
                    Array.isArray(values) ||
                    !Object.keys(values).length
                ) {
                    return;
                }

                [
                    "payment_entry",
                    "advance_invoice_date",
                    "advance_status",
                    "currency",
                    "available_advance_remaining_amount",
                    "advance_total_amount",
                    "advance_taxable_amount",
                    "advance_tax_amount"
                ].forEach(function (fieldname) {
                    frappe.model.set_value(
                        cdt,
                        cdn,
                        fieldname,
                        values[fieldname] != null ? values[fieldname] : null
                    );
                });

                currentRow.__zatca_available_amount = roundCurrency(
                    values.available_amount
                );
                const currentAllocation = roundCurrency(
                    currentRow.allocated_total_amount
                );

                if (!currentAllocation && currentRow.__zatca_available_amount > 0) {
                    frappe.model.set_value(
                        cdt,
                        cdn,
                        "allocated_total_amount",
                        (isReturn(frm) ? -1 : 1) * Math.min(
                            currentRow.__zatca_available_amount,
                            finalInvoiceRemainingAmount(frm, currentRow)
                        )
                    );
                }
                clampAllocationAmount(frm, cdt, cdn);

                frappe.model.set_value(
                    cdt,
                    cdn,
                    "remarks",
                    __(
                        "Available before this allocation: {0}",
                        [
                            format_currency(
                                values.available_amount,
                                values.currency
                            )
                        ]
                    )
                );

                updateAllocationSplit(frm, cdt, cdn);
                frm.refresh_field(TABLE_FIELD);
            }
        });
    }

    frappe.ui.form.on("Sales Invoice", {
        setup(frm) {
            // Register the Link query synchronously.  Waiting for the async
            // runtime-capability probe here leaves the child Link field with
            // ERPNext's unrestricted default query during form initialization.
            if (fieldExists(frm, TABLE_FIELD)) {
                frm.set_query(
                    "advance_invoice",
                    TABLE_FIELD,
                    function () {
                        return {
                            query: QUERY_METHOD,
                            filters: {
                                company: frm.doc.company || "",
                                customer: frm.doc.customer || "",
                                currency: frm.doc.currency || "",
                                final_invoice: frm.is_new()
                                    ? null
                                    : frm.doc.name
                            }
                        };
                    }
                );
            }

            getCurrentAllocationState(frm).then(function (state) {
                if (!state) {
                    return;
                }
                configureAllocationGrid(frm);
            });
        },

        async refresh(frm) {
            const state = await getCurrentAllocationState(frm);
            if (!state) {
                return;
            }

            // Keep refresh read-only for saved invoices; hydration and totals use
            // set_value() and can mark a draft dirty merely by opening it.
            if (!frm.is_new()) {
                configureAllocationGrid(frm);
                return;
            }

            configureAllocationGrid(frm);
            hydrateExistingRows(frm, state);
            updateDocumentTotals(frm);
        }
    });

    frappe.ui.form.on(CHILD_DOCTYPE, {
        async advance_invoice(frm, cdt, cdn) {
            const state = await getCurrentAllocationState(frm);
            if (!state) {
                return;
            }

            loadAdvanceDetails(frm, cdt, cdn, state);
        },

        async allocated_total_amount(frm, cdt, cdn) {
            const state = await getCurrentAllocationState(frm);
            if (!state) {
                return;
            }

            clampAllocationAmount(frm, cdt, cdn);
            updateAllocationSplit(frm, cdt, cdn);
            frm.refresh_field(TABLE_FIELD);
        },

        async custom_zatca_advance_deduction_details_remove(
            frm
        ) {
            const state = await getCurrentAllocationState(frm);
            if (!state) {
                return;
            }

            updateDocumentTotals(frm);
        }
    });
})();

// A return created from a final invoice must carry the original allocation
// rows so the server can treat them as reversals.  ERPNext does not always
// copy custom child tables when the return is created from the form button.
(function () {
    const TABLE_FIELD = "custom_zatca_advance_deduction_details";
    frappe.ui.form.on("Sales Invoice", {
        async refresh(frm) {
            if (frm.doc.docstatus !== 0 || !frm.doc.is_return || !frm.doc.return_against ||
                frm.__zatca_return_rows_initialized) return;
            if (!frm.fields_dict?.[TABLE_FIELD]) return;
            frm.__zatca_return_rows_initialized = true;
            const source = await frappe.db.get_doc("Sales Invoice", frm.doc.return_against);
            const rows = source?.[TABLE_FIELD] || [];
            const sourceLimits = Object.fromEntries(
                rows.map((sourceRow) => [
                    sourceRow.advance_invoice,
                    Math.abs(Number(sourceRow.allocated_total_amount || 0))
                ])
            );
            const existingRows = frm.doc[TABLE_FIELD] || [];
            existingRows.forEach((row) => {
                if (sourceLimits[row.advance_invoice] != null) {
                    row.__zatca_return_source_amount =
                        sourceLimits[row.advance_invoice];
                }
            });
            if (existingRows.length || !rows.length) {
                frm.refresh_field(TABLE_FIELD);
                return;
            }
            rows.forEach((sourceRow) => {
                const row = frm.add_child(TABLE_FIELD);
                row.__zatca_return_source_amount = Math.abs(
                    Number(sourceRow.allocated_total_amount || 0)
                );
                Object.keys(sourceRow).forEach((fieldname) => {
                    if (!["name", "parent", "parenttype", "parentfield", "idx"].includes(fieldname) &&
                        frm.fields_dict[TABLE_FIELD].grid.docfields.some(df => df.fieldname === fieldname)) {
                        row[fieldname] = fieldname === "allocated_total_amount" ||
                            fieldname === "allocated_taxable_amount" ||
                            fieldname === "allocated_tax_amount"
                            ? -Math.abs(Number(sourceRow[fieldname] || 0))
                            : sourceRow[fieldname];
                    }
                });
            });
            frm.refresh_field(TABLE_FIELD);
            frappe.show_alert({
                message: __("The ZATCA advance allocation rows were copied as return reversals."),
                indicator: "blue"
            });
        }
    });
})();
