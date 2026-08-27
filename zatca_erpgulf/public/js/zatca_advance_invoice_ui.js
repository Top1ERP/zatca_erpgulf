(function () {
    "use strict";

    const ADVANCE_ITEM_CODE = "Advance Payment";
    const ADVANCE_MARKER_HELP =
        "Use this only for the initial advance payment invoice, not for the final invoice.";
    const STANDARD_INVOICE_TYPE_FIELDS =
        ["is_return", "is_debit_note"];
    const AUTO_REMARKS = [
        "Advance Payment Invoice",
        "فاتورة الدفعة المقدمة"
    ];
    const STANDARD_ADVANCE_FIELDS = [
        "allocate_advances_automatically",
        "get_advances",
        "advances"
    ];
    const ZATCA_INTEGRATION_FIELDS = [
        "custom_section_break_gqwpx",
        "custom_zatca_tax_category",
        "custom_exemption_reason_code",
        "custom_zatca_discount_reason",
        "custom_submit_line_item_discount_to_zatca",
        "custom_column_break_hb6s7",
        "custom_zatca_third_party_invoice",
        "custom_zatca_nominal_invoice",
        "custom_zatca_export_invoice",
        "custom_summary_invoice",
        "custom_self_billed_invoice",
        "custom_column_break_h3ntp",
        "custom_uuid",
        "custom_zatca_status",
        "custom_zatca_status_notification",
    ];
    const ZATCA_DEDUCTION_FIELDS = [
        "custom_zatca_advance_deduction_section",
        "custom_section_break_qhp4f",
        "custom_zatca_prepaid_amount",
        "custom_zatca_advance_deduction_count",
        "custom_zatca_advance_deduction_details",
        "custom_zatca_advance_deduction_totals_section",
        "custom_zatca_advance_deducted_taxable_amount",
        "custom_zatca_advance_deduction_totals_column_break",
        "custom_zatca_advance_deducted_vat_amount"
    ];

    function runtime() {
        return frappe.zatcaAdvanceRuntime;
    }

    function fieldExists(frm, fieldname) {
        return Boolean(frm.fields_dict && frm.fields_dict[fieldname]);
    }

    function invoiceTypeFields(frm) {
        const helper = runtime();
        const markerField = helper
            ? helper.authoritativeMarkerField(frm)
            : "";

        return STANDARD_INVOICE_TYPE_FIELDS
            .concat(markerField ? [markerField] : [])
            .filter(function (fieldname) {
                return fieldExists(frm, fieldname);
            });
    }

    function setInvoiceTypeVisibility(
        frm,
        fields,
        activeField
    ) {
        fields.forEach(function (fieldname) {
            frm.toggle_display(
                fieldname,
                !activeField || fieldname === activeField
            );
        });
    }

    function applyAdvanceMarkerHelp(frm) {
        const helper = runtime();
        const markerField = helper
            ? helper.authoritativeMarkerField(frm)
            : "";
        if (!markerField || !fieldExists(frm, markerField)) {
            return;
        }

        frm.set_df_property(
            markerField,
            "description",
            __(ADVANCE_MARKER_HELP)
        );
    }

    async function synchronizeInvoiceTypes(
        frm,
        selectedField
    ) {
        const helper = runtime();
        if (!helper || frm.__zatca_invoice_type_syncing) {
            return;
        }

        const operation =
            (frm.__zatca_invoice_type_operation || 0) + 1;
        frm.__zatca_invoice_type_operation = operation;
        const activeDocument = frm.doc;
        const capabilities = await helper.getCapabilities(frm);

        if (
            frm.__zatca_invoice_type_operation !== operation ||
            frm.doc !== activeDocument ||
            capabilities.advance_payment_marker !== true
        ) {
            return;
        }

        applyAdvanceMarkerHelp(frm);
        const fields = invoiceTypeFields(frm);

        if (
            selectedField &&
            fields.includes(selectedField) &&
            cint(frm.doc[selectedField])
        ) {
            frm.__zatca_invoice_type_syncing = true;
            try {
                for (const fieldname of fields) {
                    if (
                        fieldname !== selectedField &&
                        cint(frm.doc[fieldname])
                    ) {
                        await frm.set_value(fieldname, 0);
                    }
                }
            } finally {
                frm.__zatca_invoice_type_syncing = false;
            }
        }

        const selected = fields.filter(function (fieldname) {
            return cint(frm.doc[fieldname]);
        });
        setInvoiceTypeVisibility(
            frm,
            fields,
            selected.length === 1 ? selected[0] : ""
        );
    }

    function operationIsCurrent(frm, state, operation) {
        const helper = runtime();
        return Boolean(
            helper &&
            frm.__zatca_advance_ui_operation === operation &&
            helper.isCurrentFormState(frm, state) &&
            helper.capabilityAvailable(
                frm,
                "advance_payment_marker"
            )
        );
    }

    function setFieldVisibility(frm, fieldname, visible) {
        if (!fieldExists(frm, fieldname)) {
            return;
        }
        frm.toggle_display(fieldname, visible);
    }

    function applyVisibility(frm, advance, capabilities, zatcaEnabled) {
        STANDARD_ADVANCE_FIELDS.forEach(function (fieldname) {
            setFieldVisibility(frm, fieldname, !advance);
        });

        ZATCA_INTEGRATION_FIELDS.forEach(function (fieldname) {
            setFieldVisibility(
                frm,
                fieldname,
                zatcaEnabled
            );
        });

        ZATCA_DEDUCTION_FIELDS.forEach(function (fieldname) {
            setFieldVisibility(
                frm,
                fieldname,
                zatcaEnabled && capabilities.advance_deduction === true
                    ? !advance
                    : false
            );
        });

        const markerField = runtime().authoritativeMarkerField(frm);
        if (markerField) {
            // Credit/Debit Note modes must keep the advance marker hidden.
            const otherInvoiceTypeSelected =
                cint(frm.doc.is_return) || cint(frm.doc.is_debit_note);
            setFieldVisibility(
                frm,
                markerField,
                zatcaEnabled && !otherInvoiceTypeSelected
            );
        }
    }

    async function getCompanyZatcaEnabled(frm) {
        if (!frm.doc.company) {
            return false;
        }
        const response = await frappe.db.get_value(
            "Company",
            frm.doc.company,
            ["custom_zatca_invoice_enabled", "custom_phase_1_or_2"]
        );
        const values = (response && response.message) || {};
        return cint(values.custom_zatca_invoice_enabled) === 1;
    }

    function selectAdvanceNamingSeries(frm) {
        const field = frm.get_field && frm.get_field("naming_series");
        if (!field || !field.df) {
            return;
        }
        const options = String(field.df.options || "")
            .split("\n")
            .map(function (option) { return option.trim(); })
            .filter(Boolean);
        const advanceSeries = options.find(function (option) {
            return option.toUpperCase().startsWith("ADV-");
        });
        if (!advanceSeries) {
            if (!frm.__zatca_advance_series_warned) {
                frappe.msgprint({
                    title: __("Advance Payment Invoice naming series"),
                    message: __(
                        "Advance Payment Invoice requires an ADV- naming series. Add an ADV- series in Sales Invoice naming settings before saving."
                    )
                });
                frm.__zatca_advance_series_warned = true;
            }
            return;
        }
        frm.__zatca_advance_series_warned = false;
        if (!String(frm.doc.naming_series || "").toUpperCase().startsWith("ADV-")) {
            frm.set_value("naming_series", advanceSeries);
        }
    }

    function configurePaymentEntryQuery(frm) {
        if (!fieldExists(frm, "custom_zatca_payment_entry")) {
            return;
        }

        frm.set_query("custom_zatca_payment_entry", function () {
            const filters = {
                docstatus: 1,
                payment_type: "Receive",
                party_type: "Customer"
            };
            // An incomplete parent document must return no Payment Entries;
            // omitting either filter would expose every customer's receipt.
            filters.company = frm.doc.company || ["=", ""];
            filters.party = frm.doc.customer || ["=", ""];
            return { filters: filters };
        });
    }

    async function getCompanyAccounts(frm) {
        if (!frm.doc.company) {
            return {};
        }
        const response = await frappe.db.get_value(
            "Company",
            frm.doc.company,
            [
                "default_deferred_revenue_account",
                "default_income_account"
            ]
        );
        return (response && response.message) || {};
    }

    async function applyDeferredRevenueAccount(
        frm,
        accounts,
        state,
        operation
    ) {
        const deferred =
            accounts.default_deferred_revenue_account || "";
        const ordinary = accounts.default_income_account || "";
        if (!deferred) {
            return;
        }

        for (const row of frm.doc.items || []) {
            if (!operationIsCurrent(frm, state, operation)) {
                return;
            }
            if (
                row.income_account &&
                row.income_account !== ordinary
            ) {
                continue;
            }

            runtime().rememberIncomeAccountChange(
                frm,
                row,
                deferred
            );

            await frappe.model.set_value(
                row.doctype,
                row.name,
                "income_account",
                deferred
            );
        }
    }

    async function restoreScriptChangedIncomeAccounts(
        frm,
        state,
        operation
    ) {
        const changed =
            frm.__zatca_changed_income_accounts || {};

        for (const row of frm.doc.items || []) {
            if (!operationIsCurrent(frm, state, operation)) {
                return;
            }

            const record = changed[row.name];
            if (!record || row.income_account !== record.applied) {
                continue;
            }

            await frappe.model.set_value(
                row.doctype,
                row.name,
                "income_account",
                record.previous
            );
        }

        frm.__zatca_changed_income_accounts = {};
    }

    async function addAdvanceItemWhenAvailable(
        frm,
        state,
        operation
    ) {
        if ((frm.doc.items || []).length) {
            return;
        }

        const response = await frappe.db.get_value(
            "Item",
            ADVANCE_ITEM_CODE,
            ["name", "disabled", "is_stock_item"]
        );

        if (!operationIsCurrent(frm, state, operation)) {
            return;
        }

        const item = (response && response.message) || {};
        if (!item.name || cint(item.disabled)) {
            return;
        }

        const row = frm.add_child("items", {
            item_code: ADVANCE_ITEM_CODE,
            qty: 1
        });
        frm.__zatca_auto_item_rows =
            frm.__zatca_auto_item_rows || {};
        frm.__zatca_auto_item_rows[row.name] = true;

        await frm.script_manager.trigger(
            "item_code",
            row.doctype,
            row.name
        );

        if (!operationIsCurrent(frm, state, operation)) {
            return;
        }

        await frappe.model.set_value(
            row.doctype,
            row.name,
            {
                item_name: __("Advance Payment"),
                description: __("Advance Payment")
            }
        );
        frm.refresh_field("items");
    }

    function removeSessionGeneratedAdvanceItems(frm) {
        const generated = frm.__zatca_auto_item_rows || {};
        if (!Object.keys(generated).length) {
            return;
        }

        frm.doc.items = (frm.doc.items || []).filter(function (row) {
            return !generated[row.name];
        });
        frm.__zatca_auto_item_rows = {};
        frm.refresh_field("items");
    }

    async function clearStandardAllocationFields(frm) {
        if (
            fieldExists(frm, "allocate_advances_automatically") &&
            frm.doc.allocate_advances_automatically
        ) {
            await frm.set_value(
                "allocate_advances_automatically",
                0
            );
        }
        if (
            fieldExists(frm, "advances") &&
            (frm.doc.advances || []).length
        ) {
            frm.clear_table("advances");
            frm.refresh_field("advances");
        }
    }

    async function clearDeductionFields(frm) {
        if (
            fieldExists(
                frm,
                "custom_zatca_advance_deduction_details"
            ) &&
            (
                frm.doc.custom_zatca_advance_deduction_details ||
                []
            ).length
        ) {
            frm.clear_table(
                "custom_zatca_advance_deduction_details"
            );
            frm.refresh_field(
                "custom_zatca_advance_deduction_details"
            );
        }

        for (const fieldname of [
            "custom_zatca_prepaid_amount",
            "custom_zatca_advance_deduction_count",
            "custom_zatca_advance_deducted_taxable_amount",
            "custom_zatca_advance_deducted_vat_amount"
        ]) {
            if (
                fieldExists(frm, fieldname) &&
                Number(frm.doc[fieldname] || 0) !== 0
            ) {
                await frm.set_value(fieldname, 0);
            }
        }
    }

    async function synchronizeAdvanceInvoiceUI(frm) {
        const helper = runtime();
        if (!helper) {
            return;
        }

        const operation =
            (frm.__zatca_advance_ui_operation || 0) + 1;
        frm.__zatca_advance_ui_operation = operation;

        const state = helper.captureFormState(frm);
        configurePaymentEntryQuery(frm);
        const capabilities = await helper.getCapabilities(frm);
        const zatcaEnabled = await getCompanyZatcaEnabled(frm);

        if (
            !helper.isCurrentFormState(frm, state) ||
            frm.__zatca_advance_ui_operation !== operation
        ) {
            return;
        }

        // Company configuration controls visibility even when an old Site
        // cannot expose the optional runtime capability RPC.
        const advance = capabilities.advance_payment_marker === true
            ? helper.isAdvanceInvoice(frm, capabilities)
            : false;
        applyVisibility(frm, advance, capabilities, zatcaEnabled);

        if (capabilities.advance_payment_marker !== true) {
            return;
        }

        if (advance) {
            selectAdvanceNamingSeries(frm);
            await clearStandardAllocationFields(frm);
            if (!operationIsCurrent(frm, state, operation)) {
                return;
            }

            // Deduction rows and totals are cleared in validate, immediately
            // before save, so selecting the marker does not mutate the form.
            if (!operationIsCurrent(frm, state, operation)) {
                return;
            }

            if (
                !frm.doc.remarks ||
                AUTO_REMARKS.includes(frm.doc.remarks)
            ) {
                await frm.set_value(
                    "remarks",
                    __("Advance Payment Invoice")
                );
                frm.__zatca_auto_remarks = true;
            }
            if (!operationIsCurrent(frm, state, operation)) {
                return;
            }

            await addAdvanceItemWhenAvailable(
                frm,
                state,
                operation
            );
            if (!operationIsCurrent(frm, state, operation)) {
                return;
            }

            const accounts = await getCompanyAccounts(frm);
            if (!operationIsCurrent(frm, state, operation)) {
                return;
            }

            await applyDeferredRevenueAccount(
                frm,
                accounts,
                state,
                operation
            );
            return;
        }

        removeSessionGeneratedAdvanceItems(frm);
        if (
            frm.__zatca_auto_remarks &&
            AUTO_REMARKS.includes(frm.doc.remarks || "")
        ) {
            await frm.set_value("remarks", "");
        }
        frm.__zatca_auto_remarks = false;

        if (!operationIsCurrent(frm, state, operation)) {
            return;
        }

        await restoreScriptChangedIncomeAccounts(
            frm,
            state,
            operation
        );
    }

    async function initializeAdvanceInvoiceUI(frm) {
        await synchronizeInvoiceTypes(frm);
        await synchronizeAdvanceInvoiceUI(frm);
    }

    async function handleInvoiceTypeChange(
        frm,
        selectedField
    ) {
        await synchronizeInvoiceTypes(frm, selectedField);
        await synchronizeAdvanceInvoiceUI(frm);
    }

    frappe.ui.form.on("Sales Invoice", {
        onload: initializeAdvanceInvoiceUI,
        refresh: initializeAdvanceInvoiceUI,
        company(frm) {
            configurePaymentEntryQuery(frm);
            return synchronizeAdvanceInvoiceUI(frm);
        },
        customer(frm) {
            configurePaymentEntryQuery(frm);
        },
        is_return(frm) {
            return handleInvoiceTypeChange(frm, "is_return");
        },
        is_debit_note(frm) {
            return handleInvoiceTypeChange(frm, "is_debit_note");
        },
        is_advance_payment(frm) {
            return handleInvoiceTypeChange(frm, "is_advance_payment");
        },
        custom_is_advance_payment(frm) {
            return handleInvoiceTypeChange(
                frm,
                "custom_is_advance_payment"
            );
        },
        async validate(frm) {
            const helper = runtime();
            if (!helper) {
                return;
            }
            const capabilities = await helper.getCapabilities(frm);
            if (
                capabilities.advance_payment_marker === true &&
                helper.isAdvanceInvoice(frm, capabilities) &&
                capabilities.advance_deduction === true
            ) {
                await clearDeductionFields(frm);
            }
        }
    });
})();
