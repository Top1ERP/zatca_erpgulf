/* Synthetic Desk VM only; no browser, installed schema or network. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {catalog} = require("./test_company_compliance_messages.js");
const source = fs.readFileSync(path.resolve(__dirname,
    "../doctype/zatca_issuing_chain/zatca_issuing_chain.js"), "utf8");
let count = 0;

function setup(lang) {
    const c = {buttons: new Map(), calls: [], messages: [], reloads: 0, dirty: false, fresh: false};
    const translate = key => {
        if (lang !== "ar") return key;
        assert.ok(catalog.has(key), key); return catalog.get(key);
    };
    c.frm = {doc: {name: "REVIEW", registration_kind: "LEGACY_REVIEWED", active: 0,
        state_version: 0, registration_review_key: "OWNER"},
        is_new: () => c.fresh, is_dirty: () => c.dirty,
        add_custom_button(label, action) {c.buttons.set(label, action);},
        remove_custom_button(label) {c.buttons.delete(label);},
        reload_doc() {c.reloads++;}, save() {assert.fail("No generic chain save");}};
    c.frappe = {user_roles: ["System Manager"],
        ui: {form: {on(dt, handlers) {
            assert.equal(dt, "ZATCA Issuing Chain"); c.refresh = () => handlers.refresh(c.frm);
        }}},
        call(options) {c.calls.push(options);},
        confirm(message, action) {c.confirmation = message; c.confirm = action;},
        msgprint(options) {c.messages.push(options);}};
    vm.runInNewContext(source, {frappe: c.frappe, __: translate});
    c.click = label => c.buttons.get(translate(label))();
    c.reply = {message: {status: "AUDITED", review_id: "REVIEW", message: "TRANSLATED SUMMARY"}};
    return c;
}

for (const lang of ["en", "ar"]) {
    for (const [label, operation] of [["Capture Next History Page", "capture"],
        ["Audit Captured History", "audit"], ["Restart Captured History Audit", "restart-audit"]]) {
        const c = setup(lang); c.refresh();
        assert.equal(c.calls.length, 0); assert.equal(c.buttons.size, 3);
        c.click(label);
        if (operation === "restart-audit") {assert.equal(c.calls.length, 0); c.confirm();}
        assert.equal(c.calls.length, 1); const call = c.calls[0];
        assert.equal(call.type, "POST"); assert.equal(call.freeze, true);
        assert.equal(call.method, "zatca_erpgulf.zatca_erpgulf.history_review_actions.review_saved_history");
        assert.deepEqual(JSON.parse(JSON.stringify(call.args)), {review_id: "REVIEW", operation});
        c.click("Audit Captured History"); assert.equal(c.calls.length, 1);
        call.callback(c.reply); call.always();
        assert.equal(c.messages.length, 1); assert.equal(c.reloads, 1);
        assert.equal(c.messages[0].message, "TRANSLATED SUMMARY"); count++;
    }
    for (const reason of ["new", "role", "active", "version", "kind", "slot"]) {
        const c = setup(lang);
        if (reason === "new") c.fresh = true;
        if (reason === "role") c.frappe.user_roles = [];
        if (reason === "active") c.frm.doc.active = 1;
        if (reason === "version") c.frm.doc.state_version = 1;
        if (reason === "kind") c.frm.doc.registration_kind = "NEW_EGS";
        if (reason === "slot") c.frm.doc.registration_review_key = null;
        c.refresh(); assert.equal(c.buttons.size, 0); assert.equal(c.calls.length, 0); count++;
    }
    for (const reason of ["dirty", "navigate", "refresh", "active", "wrong-review", "wrong-status"]) {
        const c = setup(lang); c.refresh(); c.click("Audit Captured History");
        if (reason === "dirty") c.dirty = true;
        if (reason === "navigate") c.frm.doc.name = "OTHER";
        if (reason === "refresh") c.refresh();
        if (reason === "active") c.frm.doc.active = 1;
        if (reason === "wrong-review") c.reply.message.review_id = "OTHER";
        if (reason === "wrong-status") c.reply.message.status = "ACCEPTED";
        c.calls[0].callback(c.reply); c.calls[0].always();
        assert.equal(c.messages.length, 0); assert.equal(c.reloads, 0); count++;
    }
    const changed = setup(lang); changed.refresh(); changed.click("Restart Captured History Audit");
    changed.dirty = true; changed.confirm(); assert.equal(changed.calls.length, 0); count++;
    const failed = setup(lang); failed.refresh(); failed.click("Audit Captured History");
    failed.calls[0].always(); failed.click("Audit Captured History");
    assert.equal(failed.calls.length, 2); count++;
}
console.log("Saved history actions: " + count + " synthetic cases passed");
