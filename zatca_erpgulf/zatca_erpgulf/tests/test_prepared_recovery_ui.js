/* Synthetic read-only ledger form only; no browser/site/HTTP connection. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {catalog} = require("./test_company_compliance_messages.js");
const source = fs.readFileSync(path.resolve(__dirname,
    "../doctype/zatca_issuance/zatca_issuance.js"), "utf8");
let count = 0;

function setup(lang) {
    const state = {buttons: new Map(), calls: [], messages: [], routes: [], reloads: 0, dirty: false, fresh: false};
    const translate = key => {
        if (lang !== "ar") return key;
        assert.ok(catalog.has(key), key); return catalog.get(key);
    };
    const frm = {doc: {name: "ORIGINAL", state: "PREPARED", active_attempt: null},
        is_dirty: () => state.dirty, is_new: () => state.fresh,
        add_custom_button(label, fn) {state.buttons.set(label, fn);},
        remove_custom_button(label) {state.buttons.delete(label);},
        reload_doc() {state.reloads++;}, save() {assert.fail("No generic ledger save");}};
    const frappe = {user_roles: ["System Manager"],
        ui: {form: {on(dt, events) {assert.equal(dt, "ZATCA Issuance"); state.refresh = () => events.refresh(frm);}}},
        confirm(message, fn) {state.confirmation = message; state.confirm = fn;},
        call(options) {state.calls.push(options);},
        msgprint(options) {state.messages.push(options);},
        set_route(...args) {state.routes.push(args);}};
    vm.runInNewContext(source, {frappe, __: translate});
    state.frm = frm; state.frappe = frappe; state.t = translate;
    state.click = () => state.buttons.get(translate("Queue Saved Original"))();
    state.reply = {message: {status: "DEFERRED", accepted: false, request_id: "REQUEST", message: "SAVED MESSAGE"}};
    return state;
}

for (const lang of ["en", "ar"]) {
    const good = setup(lang); good.refresh();
    assert.equal(good.calls.length, 0); good.click();
    assert.ok(good.confirmation); assert.equal(good.calls.length, 0); good.confirm();
    assert.equal(good.calls.length, 1);
    const call = good.calls[0];
    assert.equal(call.method, "zatca_erpgulf.zatca_erpgulf.prepared_recovery.queue_saved_original");
    assert.deepEqual(JSON.parse(JSON.stringify(call.args)), {issuance_id: "ORIGINAL"});
    assert.equal(call.freeze, true); call.callback(good.reply);
    assert.equal(good.messages.length, 1); assert.equal(good.messages[0].message, "SAVED MESSAGE");
    assert.equal(good.messages[0].indicator, "blue"); assert.equal(good.reloads, 1);
    good.messages[0].primary_action.action();
    assert.deepEqual(good.routes, [["Form", "ZATCA Submission Intent", "REQUEST"]]); count++;

    for (const reason of ["new", "role", "attempt", "REPORTED", "CLEARED", "REJECTED", "OUTCOME_UNKNOWN", "DISPATCHING", "REVIEW_REQUIRED"]) {
        const c = setup(lang);
        if (reason === "new") c.fresh = true;
        else if (reason === "role") c.frappe.user_roles = [];
        else if (reason === "attempt") c.frm.doc.active_attempt = "ATTEMPT";
        else c.frm.doc.state = reason;
        c.refresh(); assert.equal(c.buttons.size, 0); assert.equal(c.calls.length, 0); count++;
    }
    for (const reason of ["dirty-before", "dirty-after", "navigate-before", "navigate-after", "review-result"]) {
        const c = setup(lang); c.refresh();
        if (reason === "dirty-before") c.dirty = true;
        c.click();
        if (reason === "dirty-before") {assert.equal(c.confirm, undefined); count++; continue;}
        if (reason === "dirty-after") c.dirty = true;
        if (reason === "navigate-before") c.frm.doc.name = "OTHER";
        c.confirm();
        if (["dirty-after", "navigate-before"].includes(reason)) {assert.equal(c.calls.length, 0); count++; continue;}
        if (reason === "navigate-after") c.frm.doc.name = "OTHER";
        if (reason === "review-result") c.reply.message.status = "REVIEW";
        c.calls[0].callback(c.reply);
        assert.equal(c.messages.length, 0); assert.equal(c.reloads, 0); count++;
    }
}
console.log("Prepared-original recovery: " + count + " synthetic cases passed");
