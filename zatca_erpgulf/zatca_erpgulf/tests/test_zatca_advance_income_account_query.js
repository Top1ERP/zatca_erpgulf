"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const sourcePath = path.resolve(
    __dirname,
    "../../public/js/zatca_advance_income_account_query.js"
);

const source = fs.readFileSync(sourcePath, "utf8");

let registeredDoctype = null;
let registeredHandlers = null;
let companyAccountValues = {
    default_deferred_revenue_account: "Customer Advances - TC",
    default_income_account: "Sales - TC"
};
const alerts = [];

const context = {
    frappe: {
        db: {
            get_value() {
                return {
                    then(callback) {
                        callback({
                            message: Object.assign({}, companyAccountValues)
                        });
                    }
                };
            }
        },
        model: {
            set_value(doctype, name, fieldname, value) {
                const row = activeRows.find((candidate) => candidate.name === name);
                assert.ok(row, `Missing row ${name}`);
                row[fieldname] = value;
            }
        },
        show_alert(message) {
            alerts.push(message);
        },
        ui: {
            form: {
                on(doctype, handlers) {
                    registeredDoctype = doctype;
                    registeredHandlers = handlers;
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
    }
};

let activeRows = [];

vm.runInNewContext(source, context, {
    filename: sourcePath
});

function normalize(value) {
    return JSON.parse(JSON.stringify(value));
}

function createForm(doc) {
    activeRows = doc.items || [];
    return {
        doc: Object.assign({}, doc),
        queryRegistrations: [],
        queryFactory: null,

        set_query(fieldname, childTable, queryFactory) {
            this.queryRegistrations.push({
                fieldname,
                childTable
            });
            this.queryFactory = queryFactory;
        }
    };
}

function applyAndReadQuery(eventName, doc) {
    const frm = createForm(doc);

    registeredHandlers[eventName](frm);

    assert.strictEqual(
        typeof frm.queryFactory,
        "function",
        `${eventName} must register an income_account query`
    );

    return {
        frm,
        query: normalize(frm.queryFactory())
    };
}

assert.strictEqual(
    registeredDoctype,
    "Sales Invoice",
    "The query must be registered on Sales Invoice"
);

const expectedEvents = [
    "setup",
    "onload",
    "refresh",
    "company",
    "is_advance_payment",
    "custom_is_advance_payment"
];

for (const eventName of expectedEvents) {
    assert.strictEqual(
        typeof registeredHandlers[eventName],
        "function",
        `Missing handler: ${eventName}`
    );
}

const regularResult = applyAndReadQuery("setup", {
    company: "Test Company",
    is_advance_payment: 0,
    custom_is_advance_payment: 0
});

assert.deepStrictEqual(
    regularResult.frm.queryRegistrations,
    [
        {
            fieldname: "income_account",
            childTable: "items"
        }
    ],
    "The query must target Sales Invoice Item.income_account"
);

assert.deepStrictEqual(
    regularResult.query,
    {
        query: "erpnext.controllers.queries.get_income_account",
        filters: {
            company: "Test Company",
            disabled: 0
        }
    },
    "A regular Sales Invoice must retain the standard ERPNext income-account query"
);

const standardAdvanceResult = applyAndReadQuery("setup", {
    company: "Test Company",
    is_advance_payment: 1,
    custom_is_advance_payment: 0,
    items: [
        {
            doctype: "Sales Invoice Item",
            name: "ROW-1",
            income_account: "Sales - TC"
        },
        {
            doctype: "Sales Invoice Item",
            name: "ROW-2",
            income_account: "Manually Selected - TC"
        }
    ]
});

assert.deepStrictEqual(
    standardAdvanceResult.query,
    {
        filters: {
            company: "Test Company",
            is_group: 0,
            disabled: 0,
            account_type: [
                "not in",
                [
                    "Receivable",
                    "Payable"
                ]
            ]
        }
    },
    "A standard advance-payment invoice must use the expanded account filter"
);

assert.strictEqual(
    Object.prototype.hasOwnProperty.call(
        standardAdvanceResult.query,
        "query"
    ),
    false,
    "The expanded advance-payment filter must not call the standard income-only query"
);

assert.strictEqual(
    standardAdvanceResult.frm.doc.items[0].income_account,
    "Customer Advances - TC",
    "The Company deferred-revenue default must replace the ordinary default account"
);

assert.strictEqual(
    standardAdvanceResult.frm.doc.items[1].income_account,
    "Manually Selected - TC",
    "A manually selected account must not be overwritten"
);

const compatibilityAdvanceResult = applyAndReadQuery("setup", {
    company: "Test Company",
    is_advance_payment: 0,
    custom_is_advance_payment: 1
});

assert.deepStrictEqual(
    compatibilityAdvanceResult.query,
    standardAdvanceResult.query,
    "The compatibility custom field must activate the same expanded filter"
);

const emptyCompanyResult = applyAndReadQuery("setup", {
    company: null,
    is_advance_payment: 1,
    custom_is_advance_payment: 0
});

assert.strictEqual(
    emptyCompanyResult.query.filters.company,
    "",
    "An unset company must be represented safely as an empty filter value"
);

companyAccountValues = {
    default_deferred_revenue_account: "",
    default_income_account: "Sales - TC"
};
alerts.length = 0;

const noDefaultResult = applyAndReadQuery("refresh", {
    company: "Test Company",
    is_advance_payment: 1,
    custom_is_advance_payment: 0,
    items: [
        {
            doctype: "Sales Invoice Item",
            name: "ROW-3",
            income_account: "Manual Advance Account - TC"
        }
    ]
});

assert.strictEqual(
    noDefaultResult.frm.doc.items[0].income_account,
    "Manual Advance Account - TC",
    "The manual account must remain available when Company has no deferred-revenue default"
);
assert.strictEqual(alerts.length, 1, "A missing Company default must show guidance");

companyAccountValues = {
    default_deferred_revenue_account: "Customer Advances - TC",
    default_income_account: "Sales - TC"
};

const toggleForm = createForm({
    company: "Test Company",
    is_advance_payment: 0,
    custom_is_advance_payment: 0
});

registeredHandlers.setup(toggleForm);

assert.strictEqual(
    normalize(toggleForm.queryFactory()).query,
    "erpnext.controllers.queries.get_income_account",
    "The initial regular invoice state must use the standard query"
);

toggleForm.doc.is_advance_payment = 1;
registeredHandlers.is_advance_payment(toggleForm);

const toggledQuery = normalize(toggleForm.queryFactory());

assert.strictEqual(
    Object.prototype.hasOwnProperty.call(toggledQuery, "query"),
    false,
    "Changing the invoice to advance payment must activate the expanded filter"
);

toggleForm.doc.company = "Second Company";
registeredHandlers.company(toggleForm);

assert.strictEqual(
    normalize(toggleForm.queryFactory()).filters.company,
    "Second Company",
    "Changing the company must rebuild the filter with the new company"
);

for (const eventName of expectedEvents) {
    const result = applyAndReadQuery(eventName, {
        company: "Event Test Company",
        is_advance_payment: 1,
        custom_is_advance_payment: 0
    });

    assert.strictEqual(
        result.query.filters.company,
        "Event Test Company",
        `${eventName} must apply the current company filter`
    );
}

console.log(
    "JavaScript advance income-account query tests: PASS"
);
console.log(
    `Validated ${expectedEvents.length} form events and all query scenarios.`
);
