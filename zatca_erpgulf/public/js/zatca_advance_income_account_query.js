(function () {
    "use strict";

    const CAPABILITY_METHOD =
        "zatca_erpgulf.zatca_erpgulf.zatca_runtime.get_zatca_runtime_capabilities";
    const STANDARD_INCOME_ACCOUNT_QUERY =
        "erpnext.controllers.queries.get_income_account";
    const CLOSED_CAPABILITIES = Object.freeze({
        advance_payment_marker: false,
        advance_payment_entry_link: false,
        advance_deduction: false
    });

    function fieldExists(frm, fieldname) {
        return Boolean(
            frm &&
            frm.fields_dict &&
            frm.fields_dict[fieldname]
        );
    }

    function authoritativeMarkerField(frm) {
        if (fieldExists(frm, "is_advance_payment")) {
            return "is_advance_payment";
        }
        if (fieldExists(frm, "custom_is_advance_payment")) {
            return "custom_is_advance_payment";
        }
        return "";
    }

    function normalizeCapabilities(response) {
        const values = response && response.message;
        if (!values || typeof values !== "object" || Array.isArray(values)) {
            return CLOSED_CAPABILITIES;
        }

        return Object.freeze({
            advance_payment_marker: values.advance_payment_marker === true,
            advance_payment_entry_link:
                values.advance_payment_entry_link === true,
            advance_deduction: values.advance_deduction === true
        });
    }

    function getCapabilities(frm) {
        if (frm.__zatca_runtime_capabilities) {
            return Promise.resolve(frm.__zatca_runtime_capabilities);
        }
        if (frm.__zatca_runtime_capabilities_promise) {
            return frm.__zatca_runtime_capabilities_promise;
        }

        let request;
        try {
            request = frappe.call({
                method: CAPABILITY_METHOD,
                args: {},
                freeze: false
            });
        } catch (error) {
            frm.__zatca_runtime_capabilities = CLOSED_CAPABILITIES;
            return Promise.resolve(CLOSED_CAPABILITIES);
        }

        frm.__zatca_runtime_capabilities_promise = Promise.resolve(request)
            .then(normalizeCapabilities, function () {
                return CLOSED_CAPABILITIES;
            })
            .then(function (capabilities) {
                frm.__zatca_runtime_capabilities = capabilities;
                return capabilities;
            });

        return frm.__zatca_runtime_capabilities_promise;
    }

    function capabilityAvailable(frm, capability) {
        return Boolean(
            frm.__zatca_runtime_capabilities &&
            frm.__zatca_runtime_capabilities[capability] === true
        );
    }

    function isAdvanceInvoice(frm, capabilities) {
        const available = capabilities
            ? capabilities.advance_payment_marker === true
            : capabilityAvailable(frm, "advance_payment_marker");

        if (!available) {
            return false;
        }

        const markerField = authoritativeMarkerField(frm);
        return Boolean(markerField && cint(frm.doc[markerField]));
    }

    function currentRoute() {
        if (typeof frappe.get_route !== "function") {
            return null;
        }
        return (frappe.get_route() || []).join("/");
    }

    function captureFormState(frm) {
        const markerField = authoritativeMarkerField(frm);
        return {
            doc: frm.doc,
            doctype: frm.doc.doctype || "",
            name: frm.doc.name || "",
            company: frm.doc.company || "",
            marker_field: markerField,
            marker_value: markerField
                ? cint(frm.doc[markerField])
                : 0,
            route: currentRoute()
        };
    }

    function isCurrentFormState(frm, state) {
        if (!frm || !state || frm.doc !== state.doc) {
            return false;
        }
        if (
            (frm.doc.doctype || "") !== state.doctype ||
            (frm.doc.name || "") !== state.name ||
            (frm.doc.company || "") !== state.company
        ) {
            return false;
        }

        const markerField = authoritativeMarkerField(frm);
        if (
            markerField !== state.marker_field ||
            (markerField ? cint(frm.doc[markerField]) : 0) !==
                state.marker_value
        ) {
            return false;
        }

        if (
            state.route !== null &&
            currentRoute() !== state.route
        ) {
            return false;
        }

        if (
            typeof cur_frm !== "undefined" &&
            cur_frm &&
            cur_frm !== frm
        ) {
            return false;
        }

        return true;
    }

    function rememberIncomeAccountChange(
        frm,
        row,
        appliedAccount
    ) {
        frm.__zatca_changed_income_accounts =
            frm.__zatca_changed_income_accounts || {};

        const existing =
            frm.__zatca_changed_income_accounts[row.name];
        if (existing) {
            existing.applied = appliedAccount;
            return;
        }

        frm.__zatca_changed_income_accounts[row.name] = {
            previous: row.income_account || "",
            applied: appliedAccount
        };
    }

    frappe.zatcaAdvanceRuntime = Object.freeze({
        getCapabilities,
        capabilityAvailable,
        authoritativeMarkerField,
        isAdvanceInvoice,
        captureFormState,
        isCurrentFormState,
        rememberIncomeAccountChange
    });

    function getAdvanceIncomeAccountQuery(frm) {
        return {
            filters: {
                company: frm.doc.company || "",
                is_group: 0,
                disabled: 0,
                account_type: ["not in", ["Receivable", "Payable"]]
            }
        };
    }

    function applyAdvanceIncomeAccountQuery(frm) {
        frm.set_query("income_account", "items", function () {
            return getAdvanceIncomeAccountQuery(frm);
        });
        frm.__zatca_advance_income_query_applied = true;
    }

    function restoreStandardIncomeAccountQuery(frm) {
        if (!frm.__zatca_advance_income_query_applied) {
            return;
        }

        frm.set_query("income_account", "items", function () {
            return {
                query: STANDARD_INCOME_ACCOUNT_QUERY,
                filters: {
                    company: frm.doc.company,
                    disabled: 0
                }
            };
        });
        frm.__zatca_advance_income_query_applied = false;
    }

    async function applyPreferredAdvanceAccount(
        frm,
        state,
        operation
    ) {
        if (!frm.doc.company) {
            return;
        }

        const response = await frappe.db.get_value(
            "Company",
            frm.doc.company,
            [
                "default_deferred_revenue_account",
                "default_income_account"
            ]
        );

        const runtime = frappe.zatcaAdvanceRuntime;
        if (
            frm.__zatca_income_query_operation !== operation ||
            !runtime.isCurrentFormState(frm, state) ||
            !runtime.capabilityAvailable(
                frm,
                "advance_payment_marker"
            ) ||
            !runtime.isAdvanceInvoice(frm)
        ) {
            return;
        }

        const values = (response && response.message) || {};
        const preferred =
            values.default_deferred_revenue_account || "";
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
                runtime.rememberIncomeAccountChange(
                    frm,
                    row,
                    preferred
                );
                frappe.model.set_value(
                    row.doctype,
                    row.name,
                    "income_account",
                    preferred
                );
            }
        });
    }

    async function configureAdvanceIncomeAccount(frm) {
        const runtime = frappe.zatcaAdvanceRuntime;
        const operation =
            (frm.__zatca_income_query_operation || 0) + 1;
        frm.__zatca_income_query_operation = operation;

        const state = runtime.captureFormState(frm);
        const capabilities = await runtime.getCapabilities(frm);

        if (
            frm.__zatca_income_query_operation !== operation ||
            !runtime.isCurrentFormState(frm, state) ||
            capabilities.advance_payment_marker !== true ||
            !runtime.capabilityAvailable(
                frm,
                "advance_payment_marker"
            )
        ) {
            return;
        }

        if (!runtime.isAdvanceInvoice(frm, capabilities)) {
            restoreStandardIncomeAccountQuery(frm);
            return;
        }

        applyAdvanceIncomeAccountQuery(frm);
        await applyPreferredAdvanceAccount(frm, state, operation);
    }

    frappe.ui.form.on("Sales Invoice", {
        setup: configureAdvanceIncomeAccount,
        onload: configureAdvanceIncomeAccount,
        refresh: configureAdvanceIncomeAccount,
        company: configureAdvanceIncomeAccount,
        is_advance_payment: configureAdvanceIncomeAccount,
        custom_is_advance_payment: configureAdvanceIncomeAccount
    });
})();
