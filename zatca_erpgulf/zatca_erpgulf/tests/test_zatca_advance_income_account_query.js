"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const sourcePaths = [
    "../../public/js/zatca_advance_income_account_query.js",
    "../../public/js/zatca_advance_invoice_ui.js",
    "../../public/js/zatca_advance_direct_allocation.js"
].map((relativePath) => path.resolve(__dirname, relativePath));

const salesInvoiceHandlers = [];
let deductionHandlers = null;
const rowIndex = new Map();
const counters = {
    capabilityCalls: 0,
    companyCalls: 0,
    itemCalls: 0,
    detailCalls: 0,
    modelSetValues: 0
};

let capabilityResponse = {
    advance_payment_marker: false,
    advance_payment_entry_link: false,
    advance_deduction: false
};
let capabilityFailure = false;
let companyAccountValues = {
    default_deferred_revenue_account: "Customer Advances - TC",
    default_income_account: "Sales - TC"
};
let deferCompanyResponse = false;
let companyResolvers = [];
let allocationDetails = {};
let deferAllocationResponse = false;
let allocationCallbacks = [];
const alerts = [];

const context = {
    console,
    Promise,
    Object,
    Array,
    Number,
    Math,
    JSON,
    setTimeout,
    clearTimeout,
    locals: {},
    frappe: {
        call(options) {
            if (
                options.method ===
                "zatca_erpgulf.zatca_erpgulf.zatca_runtime.get_zatca_runtime_capabilities"
            ) {
                counters.capabilityCalls += 1;
                if (capabilityFailure) {
                    return Promise.reject(
                        new Error("capability unavailable")
                    );
                }
                return Promise.resolve({
                    message: Object.assign({}, capabilityResponse)
                });
            }

            if (
                options.method ===
                "zatca_erpgulf.zatca_erpgulf.advance_deduction.get_advance_allocation_details"
            ) {
                counters.detailCalls += 1;
                if (deferAllocationResponse) {
                    allocationCallbacks.push(options.callback);
                } else {
                    options.callback({
                        message: Object.assign({}, allocationDetails)
                    });
                }
                return Promise.resolve();
            }

            throw new Error(`Unexpected frappe.call: ${options.method}`);
        },
        db: {
            get_value(doctype) {
                if (doctype === "Company") {
                    counters.companyCalls += 1;
                    if (deferCompanyResponse) {
                        return new Promise((resolve) => {
                            companyResolvers.push(resolve);
                        });
                    }
                    return Promise.resolve({
                        message: Object.assign(
                            {},
                            companyAccountValues
                        )
                    });
                }

                if (doctype === "Item") {
                    counters.itemCalls += 1;
                    return Promise.resolve({
                        message: {
                            name: "Advance Payment",
                            disabled: 0,
                            is_stock_item: 0
                        }
                    });
                }

                throw new Error(
                    `Unexpected frappe.db.get_value: ${doctype}`
                );
            }
        },
        model: {
            set_value(doctype, name, fieldname, value) {
                counters.modelSetValues += 1;
                const row = rowIndex.get(name);
                assert.ok(row, `Missing row ${name}`);

                if (
                    fieldname &&
                    typeof fieldname === "object"
                ) {
                    Object.assign(row, fieldname);
                } else {
                    row[fieldname] = value;
                }
                return Promise.resolve();
            }
        },
        show_alert(message) {
            alerts.push(message);
        },
        ui: {
            form: {
                on(doctype, handlers) {
                    if (doctype === "Sales Invoice") {
                        salesInvoiceHandlers.push(handlers);
                    } else if (
                        doctype ===
                        "ZATCA Sales Invoice Advance Deduction"
                    ) {
                        deductionHandlers = handlers;
                    }
                }
            }
        }
    },
    cint(value) {
        const parsed = Number.parseInt(value || 0, 10);
        return Number.isNaN(parsed) ? 0 : parsed;
    },
    __(value) {
        return value;
    },
    format_currency(value, currency) {
        return `${currency || ""} ${value || 0}`.trim();
    }
};

context.globalThis = context;

for (const sourcePath of sourcePaths) {
    vm.runInNewContext(
        fs.readFileSync(sourcePath, "utf8"),
        context,
        { filename: sourcePath }
    );
}

function resetState() {
    Object.keys(counters).forEach((key) => {
        counters[key] = 0;
    });
    capabilityResponse = {
        advance_payment_marker: false,
        advance_payment_entry_link: false,
        advance_deduction: false
    };
    capabilityFailure = false;
    companyAccountValues = {
        default_deferred_revenue_account:
            "Customer Advances - TC",
        default_income_account: "Sales - TC"
    };
    deferCompanyResponse = false;
    companyResolvers = [];
    allocationDetails = {};
    deferAllocationResponse = false;
    allocationCallbacks = [];
    alerts.length = 0;
    rowIndex.clear();
    context.locals = {};
}

function completeFields() {
    return [
        "is_advance_payment",
        "custom_is_advance_payment",
        "is_return",
        "is_debit_note",
        "allocate_advances_automatically",
        "advances",
        "custom_zatca_advance_deduction_details",
        "custom_zatca_prepaid_amount",
        "custom_zatca_advance_deduction_count",
        "custom_zatca_advance_deducted_taxable_amount",
        "custom_zatca_advance_deducted_vat_amount"
    ];
}

function createForm(doc, fields = completeFields()) {
    const formDoc = Object.assign(
        {
            doctype: "Sales Invoice",
            name: "SINV-TEST",
            company: "Test Company",
            customer: "Test Customer",
            currency: "SAR",
            items: [],
            advances: []
        },
        doc
    );

    for (const row of formDoc.items || []) {
        rowIndex.set(row.name, row);
    }
    for (
        const row of
        formDoc.custom_zatca_advance_deduction_details || []
    ) {
        rowIndex.set(row.name, row);
    }

    return {
        doc: formDoc,
        fields_dict: Object.fromEntries(
            fields.map((fieldname) => [fieldname, {}])
        ),
        queryRegistrations: [],
        queryFactories: {},
        formSetValues: [],
        clearedTables: [],
        toggles: [],
        dfProperties: [],
        refreshedFields: [],

        set_query(fieldname, childTable, queryFactory) {
            this.queryRegistrations.push({
                fieldname,
                childTable
            });
            this.queryFactories[
                `${childTable || ""}:${fieldname}`
            ] = queryFactory;
        },

        set_value(fieldname, value) {
            this.formSetValues.push({ fieldname, value });
            this.doc[fieldname] = value;
            return Promise.resolve();
        },

        clear_table(fieldname) {
            this.clearedTables.push(fieldname);
            this.doc[fieldname] = [];
        },

        toggle_display(fieldname, visible) {
            this.toggles.push({ fieldname, visible });
        },

        set_df_property(fieldname, property, value) {
            this.dfProperties.push({ fieldname, property, value });
        },

        refresh_field(fieldname) {
            this.refreshedFields.push(fieldname);
        },

        add_child(fieldname, values) {
            const row = Object.assign(
                {
                    doctype: "Sales Invoice Item",
                    name: `NEW-ROW-${rowIndex.size + 1}`
                },
                values
            );
            this.doc[fieldname] =
                this.doc[fieldname] || [];
            this.doc[fieldname].push(row);
            rowIndex.set(row.name, row);
            return row;
        },

        script_manager: {
            trigger() {
                return Promise.resolve();
            }
        },

        is_new() {
            return Boolean(this.doc.__islocal);
        }
    };
}

async function runSalesHandler(index, eventName, frm) {
    const handler = salesInvoiceHandlers[index][eventName];
    assert.strictEqual(
        typeof handler,
        "function",
        `Missing Sales Invoice handler ${index}:${eventName}`
    );
    await handler(frm);
}

function addChildRow(row) {
    context.locals[
        "ZATCA Sales Invoice Advance Deduction"
    ] = context.locals[
        "ZATCA Sales Invoice Advance Deduction"
    ] || {};
    context.locals[
        "ZATCA Sales Invoice Advance Deduction"
    ][row.name] = row;
    rowIndex.set(row.name, row);
}

function normalize(value) {
    return JSON.parse(JSON.stringify(value));
}

async function flushPromises() {
    await Promise.resolve();
    await Promise.resolve();
}

function latestVisibility(frm, fieldname) {
    const change = [...frm.toggles]
        .reverse()
        .find((row) => row.fieldname === fieldname);
    return change ? change.visible : undefined;
}

function enabledCapabilities(frm) {
    frm.__zatca_runtime_capabilities = Object.freeze({
        advance_payment_marker: true,
        advance_payment_entry_link: true,
        advance_deduction: true
    });
}

async function testFailClosedCapability() {
    resetState();
    const frm = createForm({
        is_advance_payment: 1,
        custom_is_advance_payment: 1,
        items: [
            {
                doctype: "Sales Invoice Item",
                name: "ROW-CLOSED",
                income_account: "Sales - TC"
            }
        ]
    });

    await runSalesHandler(0, "setup", frm);
    await runSalesHandler(1, "onload", frm);
    await runSalesHandler(2, "setup", frm);
    await runSalesHandler(2, "refresh", frm);

    assert.strictEqual(counters.capabilityCalls, 1);
    assert.strictEqual(counters.companyCalls, 0);
    assert.strictEqual(counters.itemCalls, 0);
    assert.strictEqual(counters.detailCalls, 0);
    assert.strictEqual(counters.modelSetValues, 0);
    assert.strictEqual(frm.formSetValues.length, 0);
    assert.strictEqual(frm.queryRegistrations.length, 0);
    assert.strictEqual(frm.toggles.length, 0);
    assert.strictEqual(frm.dfProperties.length, 0);
}

async function testCapabilityFailureAlsoFailsClosed() {
    resetState();
    capabilityFailure = true;
    const frm = createForm({
        is_advance_payment: 1,
        items: [
            {
                doctype: "Sales Invoice Item",
                name: "ROW-FAILURE",
                income_account: "Sales - TC"
            }
        ]
    });

    await runSalesHandler(0, "setup", frm);
    await runSalesHandler(1, "onload", frm);
    await runSalesHandler(2, "setup", frm);

    assert.strictEqual(counters.capabilityCalls, 1);
    assert.strictEqual(counters.companyCalls, 0);
    assert.strictEqual(counters.modelSetValues, 0);
    assert.strictEqual(frm.formSetValues.length, 0);
    assert.strictEqual(frm.queryRegistrations.length, 0);
}

async function testDeductionCapabilityIsInert() {
    resetState();
    const frm = createForm({
        is_advance_payment: 0,
        custom_zatca_advance_deduction_details: [
            {
                doctype:
                    "ZATCA Sales Invoice Advance Deduction",
                name: "DED-INERT",
                advance_invoice: "ADV-0001",
                allocated_total_amount: 100,
                allocated_taxable_amount: 86.96,
                allocated_tax_amount: 13.04
            }
        ],
        custom_zatca_prepaid_amount: 100
    });
    frm.__zatca_runtime_capabilities = Object.freeze({
        advance_payment_marker: true,
        advance_payment_entry_link: true,
        advance_deduction: false
    });
    const row =
        frm.doc.custom_zatca_advance_deduction_details[0];
    addChildRow(row);

    await runSalesHandler(2, "setup", frm);
    await runSalesHandler(2, "refresh", frm);
    await deductionHandlers.advance_invoice(
        frm,
        row.doctype,
        row.name
    );
    await deductionHandlers.allocated_total_amount(
        frm,
        row.doctype,
        row.name
    );
    await deductionHandlers
        .custom_zatca_advance_deduction_details_remove(frm);

    assert.strictEqual(frm.queryRegistrations.length, 0);
    assert.strictEqual(frm.formSetValues.length, 0);
    assert.strictEqual(counters.modelSetValues, 0);
    assert.strictEqual(counters.detailCalls, 0);
    assert.strictEqual(
        frm.doc.custom_zatca_prepaid_amount,
        100
    );
}

async function testDeductionFieldsRemainUntouched() {
    resetState();
    const deductionRows = [
        {
            doctype:
                "ZATCA Sales Invoice Advance Deduction",
            name: "DED-PRESERVED",
            advance_invoice: "ADV-0001",
            allocated_total_amount: 115
        }
    ];
    const frm = createForm({
        is_advance_payment: 1,
        remarks: "User remarks",
        items: [
            {
                doctype: "Sales Invoice Item",
                name: "ROW-MANUAL-DEDUCTION-OFF",
                income_account: "Manual Advance - TC"
            }
        ],
        custom_zatca_advance_deduction_details:
            deductionRows,
        custom_zatca_prepaid_amount: 115,
        custom_zatca_advance_deduction_count: 1,
        custom_zatca_advance_deducted_taxable_amount: 100,
        custom_zatca_advance_deducted_vat_amount: 15
    });
    frm.__zatca_runtime_capabilities = Object.freeze({
        advance_payment_marker: true,
        advance_payment_entry_link: true,
        advance_deduction: false
    });

    await runSalesHandler(1, "onload", frm);

    assert.strictEqual(
        frm.doc.custom_zatca_advance_deduction_details,
        deductionRows
    );
    assert.strictEqual(
        frm.doc.custom_zatca_prepaid_amount,
        115
    );
    assert.strictEqual(
        frm.doc.custom_zatca_advance_deduction_count,
        1
    );
    assert.strictEqual(
        frm.doc.custom_zatca_advance_deducted_taxable_amount,
        100
    );
    assert.strictEqual(
        frm.doc.custom_zatca_advance_deducted_vat_amount,
        15
    );
    assert.strictEqual(
        frm.clearedTables.includes(
            "custom_zatca_advance_deduction_details"
        ),
        false
    );
    assert.strictEqual(frm.formSetValues.length, 0);
    assert.strictEqual(counters.modelSetValues, 0);
}

async function testMarkerPriority() {
    resetState();
    const primaryFrm = createForm(
        {
            is_advance_payment: 0,
            custom_is_advance_payment: 1
        },
        completeFields()
    );
    primaryFrm.__zatca_runtime_capabilities =
        Object.freeze({
            advance_payment_marker: true,
            advance_payment_entry_link: true,
            advance_deduction: true
        });

    await runSalesHandler(0, "setup", primaryFrm);
    await runSalesHandler(1, "onload", primaryFrm);

    assert.strictEqual(
        primaryFrm.queryRegistrations.length,
        0,
        "Primary false must override legacy true"
    );
    assert.strictEqual(counters.companyCalls, 0);
    assert.strictEqual(counters.modelSetValues, 0);
    assert.strictEqual(primaryFrm.formSetValues.length, 0);

    resetState();
    const legacyFields = completeFields().filter(
        (fieldname) => fieldname !== "is_advance_payment"
    );
    const legacyFrm = createForm(
        {
            custom_is_advance_payment: 1
        },
        legacyFields
    );
    legacyFrm.__zatca_runtime_capabilities =
        Object.freeze({
            advance_payment_marker: true,
            advance_payment_entry_link: true,
            advance_deduction: true
        });

    await runSalesHandler(0, "setup", legacyFrm);

    assert.strictEqual(
        legacyFrm.queryRegistrations.length,
        1,
        "Legacy true must work only when primary metadata is absent"
    );
    assert.strictEqual(counters.companyCalls, 1);
}

async function testScriptOwnedAccountRestoration() {
    resetState();
    const changedRow = {
        doctype: "Sales Invoice Item",
        name: "ROW-CHANGED",
        income_account: "Sales - TC"
    };
    const legitimateDeferredRow = {
        doctype: "Sales Invoice Item",
        name: "ROW-LEGITIMATE",
        income_account: "Customer Advances - TC"
    };
    const frm = createForm({
        is_advance_payment: 1,
        remarks: "User remarks",
        items: [changedRow, legitimateDeferredRow]
    });
    frm.__zatca_runtime_capabilities = Object.freeze({
        advance_payment_marker: true,
        advance_payment_entry_link: true,
        advance_deduction: true
    });

    await runSalesHandler(0, "setup", frm);
    await runSalesHandler(1, "onload", frm);

    assert.strictEqual(
        changedRow.income_account,
        "Customer Advances - TC"
    );
    assert.strictEqual(
        legitimateDeferredRow.income_account,
        "Customer Advances - TC"
    );
    assert.strictEqual(counters.companyCalls, 2);
    assert.strictEqual(counters.modelSetValues, 1);

    frm.doc.is_advance_payment = 0;
    await runSalesHandler(
        1,
        "is_advance_payment",
        frm
    );

    assert.strictEqual(
        changedRow.income_account,
        "Sales - TC"
    );
    assert.strictEqual(
        legitimateDeferredRow.income_account,
        "Customer Advances - TC",
        "A legitimate pre-existing deferred account must remain untouched"
    );
    assert.strictEqual(
        counters.companyCalls,
        2,
        "Ordinary transition must not request Company accounts"
    );
}

async function testCapabilityTruePreservesBehavior() {
    resetState();
    const ordinaryRow = {
        doctype: "Sales Invoice Item",
        name: "ROW-ORDINARY",
        income_account: "Sales - TC"
    };
    const manualRow = {
        doctype: "Sales Invoice Item",
        name: "ROW-MANUAL",
        income_account: "Manual Advance - TC"
    };
    const incomeFrm = createForm({
        is_advance_payment: 1,
        items: [ordinaryRow, manualRow]
    });
    incomeFrm.__zatca_runtime_capabilities =
        Object.freeze({
            advance_payment_marker: true,
            advance_payment_entry_link: true,
            advance_deduction: true
        });

    await runSalesHandler(0, "setup", incomeFrm);

    const incomeQuery = normalize(
        incomeFrm.queryFactories[
            "items:income_account"
        ]()
    );
    assert.deepStrictEqual(incomeQuery, {
        filters: {
            company: "Test Company",
            is_group: 0,
            disabled: 0,
            account_type: [
                "not in",
                ["Receivable", "Payable"]
            ]
        }
    });
    assert.strictEqual(
        ordinaryRow.income_account,
        "Customer Advances - TC"
    );
    assert.strictEqual(
        manualRow.income_account,
        "Manual Advance - TC"
    );

    resetState();
    const deductionRow = {
        doctype:
            "ZATCA Sales Invoice Advance Deduction",
        name: "DED-ACTIVE",
        advance_invoice: "ADV-0001",
        allocated_total_amount: 115,
        allocated_taxable_amount: 100,
        allocated_tax_amount: 15
    };
    const allocationFrm = createForm({
        is_advance_payment: 0,
        custom_zatca_advance_deduction_details: [
            deductionRow
        ]
    });
    allocationFrm.__zatca_runtime_capabilities =
        Object.freeze({
            advance_payment_marker: true,
            advance_payment_entry_link: true,
            advance_deduction: true
        });
    addChildRow(deductionRow);

    await runSalesHandler(2, "setup", allocationFrm);
    await runSalesHandler(2, "refresh", allocationFrm);

    assert.strictEqual(
        allocationFrm.queryRegistrations.length,
        1
    );
    assert.strictEqual(
        allocationFrm.doc.custom_zatca_prepaid_amount,
        115
    );
    assert.strictEqual(
        allocationFrm.doc
            .custom_zatca_advance_deducted_taxable_amount,
        100
    );
    assert.strictEqual(
        allocationFrm.doc
            .custom_zatca_advance_deducted_vat_amount,
        15
    );
    assert.strictEqual(
        allocationFrm.doc
            .custom_zatca_advance_deduction_count,
        1
    );
}

async function testEmptyAllocationResponseDoesNotMutate() {
    resetState();
    allocationDetails = {};
    const row = {
        doctype:
            "ZATCA Sales Invoice Advance Deduction",
        name: "DED-EMPTY",
        advance_invoice: "ADV-0001",
        allocated_total_amount: 0
    };
    const frm = createForm({
        is_advance_payment: 0,
        custom_zatca_advance_deduction_details: [row]
    });
    frm.__zatca_runtime_capabilities = Object.freeze({
        advance_payment_marker: true,
        advance_payment_entry_link: true,
        advance_deduction: true
    });
    addChildRow(row);

    await deductionHandlers.advance_invoice(
        frm,
        row.doctype,
        row.name
    );

    assert.strictEqual(counters.detailCalls, 1);
    assert.strictEqual(counters.modelSetValues, 0);
    assert.strictEqual(
        Object.prototype.hasOwnProperty.call(
            row,
            "remarks"
        ),
        false
    );
}

async function testStaleCompanyResponseDoesNotMutate() {
    resetState();
    deferCompanyResponse = true;
    const row = {
        doctype: "Sales Invoice Item",
        name: "ROW-STALE-COMPANY",
        income_account: "Sales - TC"
    };
    const frm = createForm({
        is_advance_payment: 1,
        items: [row]
    });
    frm.__zatca_runtime_capabilities = Object.freeze({
        advance_payment_marker: true,
        advance_payment_entry_link: true,
        advance_deduction: true
    });

    const pending = salesInvoiceHandlers[0].setup(frm);
    await flushPromises();
    assert.strictEqual(companyResolvers.length, 1);

    frm.doc.is_advance_payment = 0;
    await runSalesHandler(
        0,
        "is_advance_payment",
        frm
    );

    companyResolvers[0]({
        message: Object.assign({}, companyAccountValues)
    });
    await pending;

    assert.strictEqual(row.income_account, "Sales - TC");
    assert.strictEqual(counters.modelSetValues, 0);
}

async function testStaleAllocationResponseDoesNotMutate() {
    resetState();
    deferAllocationResponse = true;
    const row = {
        doctype:
            "ZATCA Sales Invoice Advance Deduction",
        name: "DED-STALE",
        advance_invoice: "ADV-0001",
        allocated_total_amount: 0
    };
    const frm = createForm({
        is_advance_payment: 0,
        custom_zatca_advance_deduction_details: [row]
    });
    frm.__zatca_runtime_capabilities = Object.freeze({
        advance_payment_marker: true,
        advance_payment_entry_link: true,
        advance_deduction: true
    });
    addChildRow(row);

    await deductionHandlers.advance_invoice(
        frm,
        row.doctype,
        row.name
    );
    assert.strictEqual(allocationCallbacks.length, 1);

    frm.doc.company = "Changed Company";
    allocationCallbacks[0]({
        message: {
            payment_entry: "PE-0001",
            available_amount: 115,
            currency: "SAR"
        }
    });

    assert.strictEqual(counters.modelSetValues, 0);
}

async function testCapabilitiesAreFetchedOncePerForm() {
    resetState();
    capabilityResponse = {
        advance_payment_marker: true,
        advance_payment_entry_link: true,
        advance_deduction: true
    };
    const frm = createForm({
        is_advance_payment: 0
    });

    await runSalesHandler(0, "setup", frm);
    await runSalesHandler(1, "onload", frm);
    await runSalesHandler(2, "setup", frm);
    await runSalesHandler(2, "refresh", frm);

    assert.strictEqual(counters.capabilityCalls, 1);
}

async function testEachInvoiceTypeClearsAndHidesTheOthers() {
    const scenarios = [
        {
            selected: "is_advance_payment",
            expected: {
                is_advance_payment: 1,
                is_return: 0,
                is_debit_note: 0
            }
        },
        {
            selected: "is_return",
            expected: {
                is_advance_payment: 0,
                is_return: 1,
                is_debit_note: 0
            }
        },
        {
            selected: "is_debit_note",
            expected: {
                is_advance_payment: 0,
                is_return: 0,
                is_debit_note: 1
            }
        }
    ];

    for (const scenario of scenarios) {
        resetState();
        const frm = createForm({
            is_advance_payment: 1,
            is_return: 1,
            is_debit_note: 1,
            remarks: "User remarks",
            items: [
                {
                    doctype: "Sales Invoice Item",
                    name: `ROW-TYPE-${scenario.selected}`,
                    income_account: "Manual Advance - TC"
                }
            ]
        });
        enabledCapabilities(frm);

        await runSalesHandler(1, scenario.selected, frm);

        for (const fieldname of [
            "is_advance_payment",
            "is_return",
            "is_debit_note"
        ]) {
            assert.strictEqual(
                frm.doc[fieldname],
                scenario.expected[fieldname],
                `${scenario.selected} must normalize ${fieldname}`
            );
            assert.strictEqual(
                latestVisibility(frm, fieldname),
                fieldname === scenario.selected,
                `${scenario.selected} must control ${fieldname} visibility`
            );
        }

        assert.ok(
            frm.dfProperties.some((row) =>
                row.fieldname === "is_advance_payment" &&
                row.property === "description" &&
                row.value ===
                    "Use this only for the initial advance payment invoice, not for the final invoice."
            )
        );
    }
}

async function testClearingActiveInvoiceTypeShowsAllChoices() {
    resetState();
    const frm = createForm({
        is_advance_payment: 0,
        is_return: 0,
        is_debit_note: 0,
        remarks: "User remarks"
    });
    enabledCapabilities(frm);

    await runSalesHandler(1, "is_return", frm);

    for (const fieldname of [
        "is_advance_payment",
        "is_return",
        "is_debit_note"
    ]) {
        assert.strictEqual(latestVisibility(frm, fieldname), true);
    }
    assert.strictEqual(frm.formSetValues.length, 0);
}

async function testRefreshDoesNotNormalizeStoredConflict() {
    resetState();
    const frm = createForm({
        is_advance_payment: 1,
        is_return: 1,
        is_debit_note: 1,
        remarks: "User remarks",
        items: [
            {
                doctype: "Sales Invoice Item",
                name: "ROW-CONFLICT-REFRESH",
                income_account: "Manual Advance - TC"
            }
        ]
    });
    enabledCapabilities(frm);

    await runSalesHandler(1, "refresh", frm);

    assert.strictEqual(frm.doc.is_advance_payment, 1);
    assert.strictEqual(frm.doc.is_return, 1);
    assert.strictEqual(frm.doc.is_debit_note, 1);
    for (const fieldname of [
        "is_advance_payment",
        "is_return",
        "is_debit_note"
    ]) {
        assert.strictEqual(latestVisibility(frm, fieldname), true);
    }
    assert.strictEqual(frm.formSetValues.length, 0);
}

async function testLegacyMarkerUsesSameExclusiveBehavior() {
    resetState();
    const fields = completeFields().filter(
        (fieldname) => fieldname !== "is_advance_payment"
    );
    const frm = createForm(
        {
            custom_is_advance_payment: 1,
            is_return: 1,
            is_debit_note: 1,
            remarks: "User remarks",
            items: [
                {
                    doctype: "Sales Invoice Item",
                    name: "ROW-LEGACY-TYPE",
                    income_account: "Manual Advance - TC"
                }
            ]
        },
        fields
    );
    enabledCapabilities(frm);

    await runSalesHandler(1, "custom_is_advance_payment", frm);

    assert.strictEqual(frm.doc.custom_is_advance_payment, 1);
    assert.strictEqual(frm.doc.is_return, 0);
    assert.strictEqual(frm.doc.is_debit_note, 0);
    assert.strictEqual(latestVisibility(frm, "custom_is_advance_payment"), true);
    assert.strictEqual(latestVisibility(frm, "is_return"), false);
    assert.strictEqual(latestVisibility(frm, "is_debit_note"), false);
}

async function main() {
    assert.strictEqual(
        salesInvoiceHandlers.length,
        3,
        "All three Sales Invoice scripts must register handlers"
    );
    assert.ok(
        deductionHandlers,
        "Direct-allocation child handlers must register"
    );

    await testFailClosedCapability();
    await testCapabilityFailureAlsoFailsClosed();
    await testDeductionCapabilityIsInert();
    await testDeductionFieldsRemainUntouched();
    await testMarkerPriority();
    await testScriptOwnedAccountRestoration();
    await testCapabilityTruePreservesBehavior();
    await testEmptyAllocationResponseDoesNotMutate();
    await testStaleCompanyResponseDoesNotMutate();
    await testStaleAllocationResponseDoesNotMutate();
    await testCapabilitiesAreFetchedOncePerForm();
    await testEachInvoiceTypeClearsAndHidesTheOthers();
    await testClearingActiveInvoiceTypeShowsAllChoices();
    await testRefreshDoesNotNormalizeStoredConflict();
    await testLegacyMarkerUsesSameExclusiveBehavior();

    console.log(
        "JavaScript frontend compatibility hardening tests: PASS"
    );
    console.log("Validated 17 targeted compatibility scenarios.");
}

main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
