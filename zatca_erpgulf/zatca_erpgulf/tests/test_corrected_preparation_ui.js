/* Actual attempt form, synthetic English/Arabic VM; no site, queue or HTTP. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {catalog} = require("./test_company_compliance_messages.js");
const source = fs.readFileSync(path.resolve(__dirname,
    "../doctype/zatca_dispatch_attempt/zatca_dispatch_attempt.js"), "utf8");
let count = 0;

function setup(lang) {
    const c = {buttons: new Map(), calls: [], messages: [], routes: [], reloads: 0, dirty: false, fresh: false};
    const t = value => {
        if (lang !== "ar") return value;
        assert.ok(catalog.has(value), value); return catalog.get(value);
    };
    const frm = {doc: {name: "REJECTED", issuance: "ORIGINAL", fence_token: "FENCE", state: "RESPONSE_RETAINED", outcome: "VALIDATION_REJECTED"},
        is_new: () => c.fresh, is_dirty: () => c.dirty,
        add_custom_button(label, fn) {c.buttons.set(label, fn);}, remove_custom_button(label) {c.buttons.delete(label);},
        reload_doc() {c.reloads++;}, save() {assert.fail("No generic attempt save");}};
    const frappe = {user_roles: ["System Manager"],
        ui: {form: {on(dt, events) {assert.equal(dt, "ZATCA Dispatch Attempt"); c.refresh = () => events.refresh(frm);}}},
        confirm(text, fn) {c.confirmation = text; c.confirm = fn;}, call(options) {c.calls.push(options);},
        msgprint(options) {c.messages.push(options);}, set_route(...args) {c.routes.push(args);}};
    vm.runInNewContext(source, {frappe, __: t});
    c.frm = frm; c.frappe = frappe; c.t = t;
    c.click = () => c.buttons.get(t("Prepare Corrected XML"))();
    return c;
}

for (const lang of ["en", "ar"]) {
    const good = setup(lang); good.refresh(); assert.equal(good.calls.length, 0);
    assert.equal(good.buttons.has(good.t("Request Exact Retry")), false);
    good.click(); assert.ok(good.confirmation); assert.equal(good.calls.length, 0); good.confirm();
    const call = good.calls[0];
    assert.equal(call.method, "zatca_erpgulf.zatca_erpgulf.corrected_preparation.queue_corrected_preparation");
    assert.deepEqual(JSON.parse(JSON.stringify(call.args)), {issuance_id: "ORIGINAL", attempt_id: "REJECTED", fence_token: "FENCE"});
    assert.equal(call.freeze, true);
    call.callback({message: {status: "DEFERRED", accepted: false, request_id: "REQUEST", message: "LOCAL PREPARATION PENDING"}});
    assert.equal(good.messages.length, 1); assert.equal(good.messages[0].indicator, "blue");
    assert.equal(good.messages[0].message, "LOCAL PREPARATION PENDING"); assert.equal(good.reloads, 1);
    good.messages[0].primary_action.action();
    assert.deepEqual(good.routes, [["Form", "ZATCA Submission Intent", "REQUEST"]]); count++;

    for (const reason of ["role", "new", "STARTED", "OUTCOME_UNKNOWN", "AUTHORIZATION_FAILED", "TECHNICAL_FAILURE", "REPORTING_MATCHED", "CLEARANCE_DISABLED", "UNCONFIRMED"]) {
        const c = setup(lang);
        if (reason === "role") c.frappe.user_roles = [];
        else if (reason === "new") c.fresh = true;
        else if (["STARTED", "OUTCOME_UNKNOWN"].includes(reason)) c.frm.doc.state = reason;
        else c.frm.doc.outcome = reason;
        c.refresh(); assert.equal(c.buttons.has(c.t("Prepare Corrected XML")), false);
        assert.equal(c.calls.length, 0); count++;
    }
    for (const reason of ["dirty", "navigate", "fence", "issuance", "after-navigation", "wrong-result"]) {
        const c = setup(lang); c.refresh(); if (reason === "dirty") c.dirty = true;
        c.click();
        if (reason === "dirty") {assert.equal(c.confirm, undefined); count++; continue;}
        if (reason === "navigate") c.frm.doc.name = "OTHER";
        if (reason === "fence") c.frm.doc.fence_token = "OTHER";
        if (reason === "issuance") c.frm.doc.issuance = "OTHER";
        c.confirm();
        if (["navigate", "fence", "issuance"].includes(reason)) {assert.equal(c.calls.length, 0); count++; continue;}
        if (reason === "after-navigation") c.frm.doc.name = "OTHER";
        c.calls[0].callback({message: {status: reason === "wrong-result" ? "REVIEW" : "DEFERRED", message: "STALE"}});
        assert.equal(c.messages.length, 0); assert.equal(c.reloads, 0); count++;
    }
}
console.log("Corrected XML preparation: " + count + " synthetic cases passed");
