/* Native renewal preparation in a synthetic Desk VM; no site or network. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {catalog} = require("./test_company_compliance_messages.js");
const source = fs.readFileSync(path.resolve(__dirname,
    "../doctype/zatca_issuing_chain/zatca_issuing_chain.js"), "utf8");
let count = 0;

function setup(lang) {
    const c = {buttons: new Map(), calls: [], messages: [], routes: [], reloads: 0, dirty: false, fresh: false};
    const t = key => {
        if (lang !== "ar") return key;
        assert.ok(catalog.has(key), key); return catalog.get(key);
    };
    c.frm = {doc: {name: "OLD-CHAIN", active: 1, active_owner_key: "OWNER", registration_kind: "NEW_EGS"},
        is_new: () => c.fresh, is_dirty: () => c.dirty,
        add_custom_button(label, action) {c.buttons.set(label, action);},
        remove_custom_button(label) {c.buttons.delete(label);},
        reload_doc() {c.reloads++;}, save() {assert.fail("No owner or chain save");}};
    c.route = ["Form", "ZATCA Issuing Chain", "OLD-CHAIN"];
    c.frappe = {user_roles: ["System Manager"], get_route: () => c.route,
        ui: {form: {on(dt, handlers) {c.refresh = () => handlers.refresh(c.frm);}}},
        prompt(fields, action, title, primary) {c.prompt = {fields, action, title, primary};},
        call(options) {c.calls.push(options);}, msgprint(options) {c.messages.push(options);},
        set_route(...args) {c.routes.push(args);}};
    vm.runInNewContext(source, {frappe: c.frappe, __: t});
    c.click = () => c.buttons.get(t("Prepare Certificate Renewal"))();
    c.reply = {message: {old_chain: "OLD-CHAIN", renewal_id: "PENDING", state: "CSR_READY", message: "TRANSLATED RESULT"}};
    return c;
}

for (const lang of ["en", "ar"]) {
    const c = setup(lang); c.refresh(); assert.equal(c.calls.length, 0);
    c.click(); assert.equal(c.calls.length, 0); assert.equal(c.prompt.fields[0].reqd, 1);
    c.prompt.action({reason: "Reviewed pending renewal"});
    assert.equal(c.calls.length, 1); const call = c.calls[0];
    assert.equal(call.type, "POST"); assert.equal(call.freeze, true);
    assert.equal(call.method, "zatca_erpgulf.zatca_erpgulf.native_renewal.prepare_certificate_renewal");
    assert.deepEqual(JSON.parse(JSON.stringify(call.args)), {chain_id: "OLD-CHAIN", reason: "Reviewed pending renewal"});
    c.prompt.action({reason: "Duplicate"}); assert.equal(c.calls.length, 1);
    call.callback(c.reply); call.always(); assert.equal(c.messages.length, 1); assert.equal(c.reloads, 1);
    c.messages[0].primary_action.action(); assert.deepEqual(c.routes, [["Form", "ZATCA CSID Renewal", "PENDING"]]); count++;
    for (const reason of ["new", "role", "inactive", "missing-owner"]) {
        const v = setup(lang);
        if (reason === "new") v.fresh = true;
        if (reason === "role") v.frappe.user_roles = [];
        if (reason === "inactive") v.frm.doc.active = 0;
        if (reason === "missing-owner") v.frm.doc.active_owner_key = null;
        v.refresh(); assert.equal(v.buttons.size, 0); assert.equal(v.calls.length, 0); count++;
    }
    for (const reason of ["dirty", "navigate", "route", "refresh", "owner", "inactive", "response-chain", "response-state"]) {
        const v = setup(lang); v.refresh(); v.click(); v.prompt.action({reason: "REASON"});
        if (reason === "dirty") v.dirty = true;
        if (reason === "navigate") v.frm.doc.name = "OTHER";
        if (reason === "route") v.route = ["List", "Company"];
        if (reason === "refresh") v.refresh();
        if (reason === "owner") v.frm.doc.active_owner_key = "OTHER";
        if (reason === "inactive") v.frm.doc.active = 0;
        if (reason === "response-chain") v.reply.message.old_chain = "OTHER";
        if (reason === "response-state") v.reply.message.state = "FINAL_READY";
        v.calls[0].callback(v.reply); v.calls[0].always();
        assert.equal(v.messages.length, 0); assert.equal(v.reloads, 0); count++;
    }
    const changed = setup(lang); changed.refresh(); changed.click(); changed.dirty = true;
    changed.prompt.action({reason: "REASON"}); assert.equal(changed.calls.length, 0); count++;
    const failed = setup(lang); failed.refresh(); failed.click(); failed.prompt.action({reason: "REASON"});
    failed.calls[0].always(); failed.click(); failed.prompt.action({reason: "REASON"});
    assert.equal(failed.calls.length, 2); count++;
}
console.log("Native renewal preparation: " + count + " synthetic cases passed");
