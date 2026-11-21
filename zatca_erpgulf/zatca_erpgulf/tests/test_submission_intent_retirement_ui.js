/* Synthetic Desk VM only; no site, browser, transport or queue connection. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {catalog} = require("./test_company_compliance_messages.js");
const source = fs.readFileSync(path.resolve(__dirname,
    "../doctype/zatca_submission_intent/zatca_submission_intent.js"), "utf8");
let count = 0;

function setup(lang, state = "READY") {
    const result = {buttons: new Map(), calls: [], messages: [], reloads: 0, dirty: false, fresh: false};
    const translate = value => {
        if (lang !== "ar") return value;
        assert.ok(catalog.has(value), value);
        return catalog.get(value);
    };
    const frm = {doc: {name: "REQUEST", state, fence_token: state === "RUNNING" ? "FENCE" : null},
        is_new: () => result.fresh, is_dirty: () => result.dirty,
        add_custom_button(label, fn) {result.buttons.set(label, fn);},
        remove_custom_button(label) {result.buttons.delete(label);},
        reload_doc() {result.reloads++;}, save() {assert.fail("No generic document save");}};
    const frappe = {user_roles: ["System Manager"],
        ui: {form: {on(dt, handlers) {assert.equal(dt, "ZATCA Submission Intent"); result.refresh = () => handlers.refresh(frm);}}},
        confirm(message, fn) {result.confirmation = message; result.confirm = fn;},
        call(options) {result.calls.push(options);}, msgprint(message) {result.messages.push(message);}};
    vm.runInNewContext(source, {frappe, __: translate});
    result.frm = frm; result.frappe = frappe; result.t = translate;
    result.click = () => result.buttons.get(translate("Retire Unissued Request"))();
    return result;
}

for (const lang of ["en", "ar"]) {
    for (const state of ["READY", "WAITING", "RUNNING", "REVIEW"]) {
        const c = setup(lang, state); c.refresh();
        const label = c.t("Reconcile Saved Result");
        if (["READY", "WAITING"].includes(state)) assert.equal(c.buttons.has(label), false);
        else {
            c.buttons.get(label)(); assert.ok(c.confirmation); c.confirm();
            assert.equal(c.calls.length, 1);
            assert.equal(c.calls[0].method, "zatca_erpgulf.zatca_erpgulf.submission_intent_reconciliation.reconcile_request");
            assert.equal(c.calls[0].args.expected_state, state);
            c.calls[0].callback({message: {status: "COMPLETE", accepted: true, message: "SAVED RESULT"}});
            assert.deepEqual(c.messages, ["SAVED RESULT"]); assert.equal(c.reloads, 1);
            c.frm.doc.state = "COMPLETE"; c.refresh(); assert.equal(c.buttons.size, 0);
        }
        count++;
    }
    for (const state of ["READY", "WAITING", "RUNNING", "REVIEW"]) {
        const c = setup(lang, state); c.refresh();
        assert.equal(c.calls.length, 0); c.click();
        assert.ok(c.confirmation); assert.equal(c.calls.length, 0); c.confirm();
        assert.equal(c.calls.length, 1);
        const call = c.calls[0];
        assert.equal(call.method, "zatca_erpgulf.zatca_erpgulf.submission_intent_retirement.retire_request");
        assert.deepEqual(JSON.parse(JSON.stringify(call.args)), {
            record_id: "REQUEST", expected_state: state, expected_fence: state === "RUNNING" ? "FENCE" : null});
        assert.equal(call.freeze, true);
        call.callback({message: {status: "RETIRED", accepted: false, message: "TRANSLATED RESULT"}});
        assert.deepEqual(c.messages, ["TRANSLATED RESULT"]); assert.equal(c.reloads, 1);
        c.frm.doc.state = "RETIRED"; c.refresh(); assert.equal(c.buttons.size, 0); count++;
    }
    for (const state of ["STAGED", "COMPLETE", "RETIRED", "UNKNOWN"]) {
        const c = setup(lang, state); c.refresh(); assert.equal(c.buttons.size, 0); count++;
    }
    for (const cause of ["new", "role", "dirty", "navigate-before-confirm", "navigate-after-call"]) {
        const c = setup(lang);
        if (cause === "new") c.fresh = true;
        if (cause === "role") c.frappe.user_roles = [];
        c.refresh();
        if (["new", "role"].includes(cause)) {assert.equal(c.buttons.size, 0); count++; continue;}
        if (cause === "dirty") c.dirty = true;
        c.click();
        if (cause === "dirty") {assert.equal(c.confirm, undefined); count++; continue;}
        if (cause === "navigate-before-confirm") c.frm.doc.name = "OTHER";
        c.confirm();
        if (cause === "navigate-before-confirm") assert.equal(c.calls.length, 0);
        else {
            c.frm.doc.name = "OTHER";
            c.calls[0].callback({message: {status: "RETIRED", message: "STALE"}});
            assert.equal(c.messages.length, 0); assert.equal(c.reloads, 0);
        }
        count++;
    }
}
console.log("Intent retirement and saved-result reconciliation: " + count + " synthetic cases passed");
