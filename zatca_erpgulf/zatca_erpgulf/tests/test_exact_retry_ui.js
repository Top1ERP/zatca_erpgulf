/* Synthetic attempt form: no browser, site, queue or network connection. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {catalog} = require("./test_company_compliance_messages.js");
const source = fs.readFileSync(path.resolve(__dirname,
    "../doctype/zatca_dispatch_attempt/zatca_dispatch_attempt.js"), "utf8");
let count = 0;

function setup(lang, status, outcome = null) {
    const c = {buttons: new Map(), calls: [], messages: [], routes: [], reloads: 0, dirty: false, fresh: false};
    const translate = key => {
        if (lang !== "ar") return key;
        assert.ok(catalog.has(key), key); return catalog.get(key);
    };
    const frm = {doc: {name: "ATTEMPT", issuance: "ORIGINAL", fence_token: "FENCE", state: status, outcome},
        is_new: () => c.fresh, is_dirty: () => c.dirty,
        add_custom_button(label, fn) {c.buttons.set(label, fn);},
        remove_custom_button(label) {c.buttons.delete(label);},
        reload_doc() {c.reloads++;}, save() {assert.fail("No generic attempt save");}};
    const frappe = {user_roles: ["System Manager"],
        ui: {form: {on(dt, events) {assert.equal(dt, "ZATCA Dispatch Attempt"); c.refresh = () => events.refresh(frm);}}},
        confirm(message, fn) {c.confirmation = message; c.confirm = fn;},
        call(options) {c.calls.push(options);}, msgprint(options) {c.messages.push(options);},
        set_route(...args) {c.routes.push(args);}};
    vm.runInNewContext(source, {frappe, __: translate});
    c.frm = frm; c.frappe = frappe; c.t = translate;
    c.click = () => c.buttons.get(translate("Request Exact Retry"))();
    c.reply = {message: {status: "DEFERRED", accepted: false, request_id: "REQUEST", message: "PENDING RETRY"}};
    return c;
}

for (const lang of ["en", "ar"]) {
    for (const [state, outcome] of [["STARTED", null], ["OUTCOME_UNKNOWN", null],
            ["RESPONSE_RETAINED", "AUTHORIZATION_FAILED"], ["RESPONSE_RETAINED", "TECHNICAL_FAILURE"]]) {
        const c = setup(lang, state, outcome); c.refresh(); assert.equal(c.calls.length, 0);
        c.click(); assert.ok(c.confirmation); assert.equal(c.calls.length, 0); c.confirm();
        assert.equal(c.calls.length, 1);
        assert.equal(c.calls[0].method, "zatca_erpgulf.zatca_erpgulf.exact_retry.queue_exact_retry");
        assert.deepEqual(JSON.parse(JSON.stringify(c.calls[0].args)), {
            issuance_id: "ORIGINAL", attempt_id: "ATTEMPT", fence_token: "FENCE"});
        c.calls[0].callback(c.reply);
        assert.equal(c.messages.length, 1); assert.equal(c.messages[0].indicator, "blue");
        assert.equal(c.messages[0].message, "PENDING RETRY"); c.messages[0].primary_action.action();
        assert.deepEqual(c.routes, [["Form", "ZATCA Submission Intent", "REQUEST"]]); count++;
    }
    for (const outcome of ["REPORTING_MATCHED", "CLEARANCE_MATCHED", "VALIDATION_REJECTED", "CLEARANCE_DISABLED", "UNCONFIRMED"]) {
        const c = setup(lang, "RESPONSE_RETAINED", outcome); c.refresh();
        assert.equal(c.buttons.has(c.t("Request Exact Retry")), false); count++;
    }
    for (const reason of ["role", "new", "dirty", "navigation-before", "navigation-after", "review"]) {
        const c = setup(lang, "OUTCOME_UNKNOWN");
        if (reason === "role") c.frappe.user_roles = [];
        if (reason === "new") c.fresh = true;
        c.refresh();
        if (["role", "new"].includes(reason)) {assert.equal(c.buttons.size, 0); count++; continue;}
        if (reason === "dirty") c.dirty = true;
        c.click();
        if (reason === "dirty") {assert.equal(c.confirm, undefined); count++; continue;}
        if (reason === "navigation-before") c.frm.doc.name = "OTHER";
        c.confirm();
        if (reason === "navigation-before") {assert.equal(c.calls.length, 0); count++; continue;}
        if (reason === "navigation-after") c.frm.doc.name = "OTHER";
        if (reason === "review") c.reply.message.status = "REVIEW";
        c.calls[0].callback(c.reply); assert.equal(c.messages.length, 0); count++;
    }
}
console.log("Explicit exact retry: " + count + " synthetic cases passed");
