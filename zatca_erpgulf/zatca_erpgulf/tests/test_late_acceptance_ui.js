/* Actual Desk asset in an offline synthetic VM; no site/browser/authority. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {catalog} = require("./test_company_compliance_messages.js");
const source = fs.readFileSync(path.resolve(__dirname,
    "../doctype/zatca_issuance/zatca_issuance.js"), "utf8");
let count = 0;

function setup(lang, state = "OUTCOME_UNKNOWN") {
    const c = {buttons: new Map(), calls: [], messages: [], reloads: 0, dirty: false, fresh: false};
    const translate = value => {
        if (lang !== "ar") return value;
        assert.ok(catalog.has(value), value); return catalog.get(value);
    };
    const frm = {doc: {name: "ORIGINAL", state, active_attempt: "NEWER", state_version: 4},
        is_dirty: () => c.dirty, is_new: () => c.fresh,
        add_custom_button(label, fn) {c.buttons.set(label, fn);},
        remove_custom_button(label) {c.buttons.delete(label);},
        reload_doc() {c.reloads++;}, save() {assert.fail("No generic ledger save");}};
    const frappe = {user_roles: ["System Manager"],
        ui: {form: {on(dt, events) {assert.equal(dt, "ZATCA Issuance"); c.refresh = () => events.refresh(frm);}}},
        prompt(fields, fn, title, button) {c.prompt = {fields, fn, title, button};},
        confirm(text, fn) {c.confirm = {text, fn};},
        call(options) {c.calls.push(options);}, msgprint(options) {c.messages.push(options);}};
    vm.runInNewContext(source, {frappe, __: translate});
    c.frm = frm; c.frappe = frappe; c.t = translate;
    c.click = () => c.buttons.get(translate("Review Late Acceptance"))();
    return c;
}

for (const lang of ["en", "ar"]) {
    for (const state of ["OUTCOME_UNKNOWN", "DISPATCHING"]) {
        const c = setup(lang, state); c.refresh(); assert.equal(c.calls.length, 0); c.click();
        assert.ok(c.prompt.title); assert.equal(c.prompt.fields[0].fieldtype, "Link");
        assert.equal(c.prompt.fields[0].options, "ZATCA Dispatch Attempt");
        assert.deepEqual(JSON.parse(JSON.stringify(c.prompt.fields[0].get_query())),
            {filters: {issuance: "ORIGINAL", state: "RESPONSE_RETAINED"}});
        c.prompt.fn({accepted_attempt_id: "OLDER"}); assert.ok(c.confirm.text);
        assert.equal(c.calls.length, 0); c.confirm.fn(); assert.equal(c.calls.length, 1);
        const call = c.calls[0];
        assert.equal(call.method, "zatca_erpgulf.zatca_erpgulf.late_acceptance.reconcile_response");
        assert.deepEqual(JSON.parse(JSON.stringify(call.args)), {issuance_id: "ORIGINAL",
            expected_attempt_id: "NEWER", expected_state_version: 4, accepted_attempt_id: "OLDER"});
        call.callback({message: {status: "RESOLVED", accepted: true, message: "SAVED EVIDENCE"}});
        assert.equal(c.messages.length, 1); assert.equal(c.messages[0].indicator, "green");
        assert.equal(c.messages[0].message, "SAVED EVIDENCE"); assert.equal(c.reloads, 1); count++;
    }
    for (const reason of ["role", "new", "no-attempt", "PREPARED", "REJECTED", "REPORTED", "CLEARED", "REVIEW_REQUIRED"]) {
        const c = setup(lang);
        if (reason === "role") c.frappe.user_roles = [];
        else if (reason === "new") c.fresh = true;
        else if (reason === "no-attempt") c.frm.doc.active_attempt = null;
        else c.frm.doc.state = reason;
        c.refresh(); assert.equal(c.buttons.has(c.t("Review Late Acceptance")), false);
        assert.equal(c.calls.length, 0); count++;
    }
    for (const reason of ["dirty", "navigate-prompt", "revision-prompt", "attempt-prompt", "navigate-confirm", "revision-confirm", "navigate-result", "wrong-result"]) {
        const c = setup(lang); c.refresh();
        if (reason === "dirty") c.dirty = true;
        c.click();
        if (reason === "dirty") {assert.equal(c.prompt, undefined); count++; continue;}
        if (reason === "navigate-prompt") c.frm.doc.name = "OTHER";
        if (reason === "revision-prompt") c.frm.doc.state_version++;
        if (reason === "attempt-prompt") c.frm.doc.active_attempt = "OTHER";
        c.prompt.fn({accepted_attempt_id: "OLDER"});
        if (reason.endsWith("prompt")) {assert.equal(c.confirm, undefined); count++; continue;}
        if (reason === "navigate-confirm") c.frm.doc.name = "OTHER";
        if (reason === "revision-confirm") c.frm.doc.state_version++;
        c.confirm.fn();
        if (reason.endsWith("confirm")) {assert.equal(c.calls.length, 0); count++; continue;}
        if (reason === "navigate-result") c.frm.doc.name = "OTHER";
        c.calls[0].callback({message: {status: reason === "wrong-result" ? "REVIEW" : "RESOLVED", message: "STALE"}});
        assert.equal(c.messages.length, 0); assert.equal(c.reloads, 0); count++;
    }
}
console.log("Late acceptance review: " + count + " synthetic cases passed");
