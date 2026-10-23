/* Actual device handler in a network-free VM; no browser/site/authority calls. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { browser, catalog, escape } = require("./test_company_compliance_messages.js");
const source = fs.readFileSync(path.resolve(__dirname,
    "../doctype/zatca_multiple_setting/zatca_multiple_setting.js"), "utf8");
const text = {
    inactive: "The device settings form is no longer active. Reopen it before starting Compliance.",
    save: "Save the device settings before running Compliance. No Compliance request was sent.",
    incomplete: "Saved device Company, sample invoice or revision is missing. Review the settings before running Compliance.",
    review: "Review saved CSR and private-key settings before saving an already-open form or generating another CSR or CSID. Preserve unsaved changes before reloading.",
    changed: "The device form changed while Compliance was running. The request may have completed. Preserve edits and review the original device outcome before another request.",
    unknown: "The device Compliance request outcome is not confirmed. Preserve edits and review the outcome before another request; no automatic retry was performed."
};
const kinds = ["Simplified Invoice", "Standard Invoice", "Simplified Credit Note", "Standard Credit Note", "Simplified Debit Note", "Standard Debit Note"];
const raw = 'Original {"code":"TEST-FAILURE"} <script> العربية';
const tick = async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); };
let count = 0;

function setup(lang) {
    const b = browser(lang);
    b.context.console = { log() { assert.fail("No raw Company/device/response console dump"); } };
    b.context.frappe.ui.form.on = (doctype, handlers) => {
        assert.equal(doctype, "ZATCA Multiple Setting"); b.handlers = handlers;
    };
    vm.runInContext(source, b.context, { timeout: 1000 });
    Object.assign(b.frm.doc, { doctype: "ZATCA Multiple Setting", name: "TEST DEVICE",
        custom_linked_doctype: "FICTIONAL COMPANY", custom_sample_invoice_number_to_test: "TEST INVOICE",
        custom_private_key: "PRIVATE-KEY", custom_otp: "PRIVATE-OTP" });
    b.route = ["Form", b.frm.doc.doctype, b.frm.doc.name];
    b.context.frappe.get_route = () => b.route;
    b.dirty = false;
    b.frm.is_dirty = () => b.dirty;
    b.frm.is_new = () => false;
    b.frm.save = b.frm.reload_doc = b.frm.set_value = () => assert.fail("No form save/reload/mutation");
    b.context.frappe.call = options => {
        b.calls.push(options);
        if (options.method === "frappe.client.get_value") {
            assert.equal(options.args.filters, "FICTIONAL COMPANY");
            assert.equal(JSON.stringify(options.args.fieldname), '["abbr","custom_select"]');
            return Promise.resolve({ message: { abbr: "FC", custom_select: "Production" } });
        }
        assert.match(options.method, /^zatca_erpgulf\.zatca_erpgulf\.(?:device_compliance\.run_device_compliance_summary|sign_invoice_first\.(?:create_csr|create_csid|production_csid))$/);
        assert.ok(!JSON.stringify(options.args).includes("PRIVATE"));
        return new Promise((resolve, reject) => { b.resolve = resolve; b.reject = reject; });
    };
    b.click = () => b.handlers.custom_check_compliance(b.frm);
    b.credential = mode => b.handlers[mode === "csr" ? "custom_create_csr" : mode === "production" ?
        "custom_generate_final_csids" : "custom_generate_compliance_csid"](b.frm);
    b.notice = key => {
        assert.equal(b.dialogs.length, 1);
        assert.equal(b.dialogs[0].message, lang === "ar" ? catalog.get(text[key]) : text[key]);
        assert.ok(!JSON.stringify(b.dialogs).includes("PRIVATE"));
    };
    b.result = (kind = kinds[0], outcome = "PASS") => ({ single_check: true, results: [{
        type: kind, status: outcome === "FAIL" ? "FAIL" : "PASS",
        message: outcome === "FAIL" ? "Compliance check failed. See technical details." :
            outcome === "WARNING" ? "Completed with warnings. See technical details." :
            outcome === "ALREADY" ? "Already completed by ZATCA; treated as PASS." : "Completed successfully.",
        ...(outcome === "FAIL" ? { technical_details: raw } : {}) }] });
    return b;
}

async function main() {
    for (const key of Object.values(text)) {
        assert.ok(catalog.has(key)); assert.notEqual(catalog.get(key), key);
    }
    for (const lang of ["en", "ar"]) {
        for (const fault of ["dirty", "local", "new", "unknown-dirty", "dirty-error", "route-error", "route", "active", "unsupported", "name", "modified", "company", "invoice"]) {
            const b = setup(lang); let key = "save";
            if (fault === "dirty") b.dirty = true;
            if (fault === "local") b.frm.doc.__islocal = true;
            if (fault === "new") b.frm.is_new = () => true;
            if (fault === "unknown-dirty") delete b.frm.is_dirty;
            if (fault === "dirty-error") b.frm.is_dirty = () => { throw Error("PRIVATE"); };
            if (fault === "route-error") { b.context.frappe.get_route = () => { throw Error("PRIVATE"); }; key = "inactive"; }
            if (fault === "route") { b.route = ["List", "Company"]; key = "inactive"; }
            if (fault === "active") { b.context.cur_frm = {}; key = "inactive"; }
            if (fault === "unsupported") { b.frm.doc.doctype = "Company"; key = "inactive"; }
            if (fault === "name") { b.frm.doc.name = ""; key = "inactive"; }
            if (fault === "modified") { b.frm.doc.modified = ""; key = "incomplete"; }
            if (fault === "company") { b.frm.doc.custom_linked_doctype = ""; key = "incomplete"; }
            if (fault === "invoice") { b.frm.doc.custom_sample_invoice_number_to_test = ""; key = "incomplete"; }
            const before = JSON.stringify(b.frm.doc);
            await b.click(); b.notice(key); assert.equal(b.calls.length, 0);
            assert.equal(JSON.stringify(b.frm.doc), before); count++;
        }
        for (const kind of kinds) for (const outcome of ["PASS", "WARNING", "ALREADY", "FAIL"]) {
            const b = setup(lang), before = JSON.stringify(b.frm.doc);
            const result = b.result(kind, outcome), original = JSON.stringify(result);
            const task = b.click();
            assert.equal(b.click(), task);
            for (const mode of ["csr", "compliance", "production"]) assert.equal(b.credential(mode), task);
            assert.equal(b.calls.length, 1, "No Company lookup or duplicate check");
            assert.equal(JSON.stringify(b.calls[0].args), JSON.stringify({ device_name: "TEST DEVICE",
                expected_modified: "2026-10-23 09:00:00" }));
            assert.equal(b.calls[0].freeze, true);
            assert.equal(b.calls[0].freeze_message, lang === "ar" ? catalog.get("Running compliance check...") : "Running compliance check...");
            b.resolve({ message: result }); assert.equal(await task, undefined);
            assert.equal(b.dialogs.length, 1);
            assert.equal(b.dialogs[0].title, lang === "ar" ? catalog.get("Compliance Check Result") : "Compliance Check Result");
            assert.equal(b.dialogs[0].indicator, outcome === "FAIL" ? "red" : outcome === "WARNING" ? "orange" : "green");
            assert.ok(b.dialogs[0].message.includes(lang === "ar" ? catalog.get(kind) : kind));
            assert.ok(!b.dialogs[0].message.includes("<script>"));
            if (outcome === "FAIL") assert.ok(b.dialogs[0].message.includes(escape(raw)));
            assert.equal(JSON.stringify(b.frm.doc), before); assert.equal(JSON.stringify(result), original);
            assert.ok(!JSON.stringify(b.dialogs).includes("PRIVATE")); count++;
        }
        for (const change of ["dirty", "document", "name", "modified", "company", "invoice", "route", "active"]) {
            const b = setup(lang), task = b.click();
            if (change === "dirty") { b.dirty = true; b.frm.doc.custom_otp = "KEEP PRIVATE EDIT"; }
            if (change === "document") b.frm.doc = { ...b.frm.doc };
            const fields = { name: "name", modified: "modified", company: "custom_linked_doctype", invoice: "custom_sample_invoice_number_to_test" };
            if (fields[change]) b.frm.doc[fields[change]] = "OTHER";
            if (change === "route") b.route = ["List", "Company"];
            if (change === "active") b.context.cur_frm = {};
            const before = JSON.stringify(b.frm.doc);
            b.resolve({ message: b.result() }); await task; b.notice("changed");
            assert.equal(JSON.stringify(b.frm.doc), before); assert.equal(b.calls.length, 1); count++;
        }
        for (const value of [undefined, null, "OK", {}, { results: [] }, { results: [null] },
            { results: [{ type: kinds[0], status: "PASS" }], single_check: false }]) {
            const b = setup(lang), task = b.click();
            b.resolve({ message: value }); await task;
            assert.equal(b.dialogs.length, 1); assert.equal(b.dialogs[0].indicator, "red");
            assert.equal(b.calls.length, 1); count++;
        }
        for (const status of [401, 403, 417, 500]) {
            const b = setup(lang), task = b.click();
            b.dialogs.push({ message: "Framework-owned error" });
            b.reject({ status, responseJSON: { _server_messages: "PRIVATE" } }); await task;
            assert.equal(b.dialogs.length, 1); assert.equal(b.calls.length, 1); count++;
        }
        {
            const b = setup(lang), task = b.click();
            b.dialogs.push({ message: "Framework-owned exception reply" });
            b.resolve({ exc: "PRIVATE" }); await task; assert.equal(b.dialogs.length, 1); count++;
        }
        for (const error of [Error("PRIVATE"), {}, { status: 0 }]) {
            const b = setup(lang), task = b.click(); b.reject(error); await task; b.notice("unknown");
            assert.equal(b.calls.length, 1, "No automatic retry");
            b.dialogs.length = 0;
            const explicit = b.click(); assert.equal(b.calls.length, 2, "Only a later explicit click, not a durable hold");
            b.resolve({ message: b.result() }); await explicit; assert.equal(b.dialogs.length, 1); count++;
        }
        for (const mode of ["csr", "compliance", "production"]) {
            const b = setup(lang), task = b.credential(mode);
            assert.equal(b.click(), task); await tick();
            b.resolve({ exc: "PRIVATE" }); await task;
            b.dirty = true; await b.click(); b.notice("review");
            assert.equal(b.calls.length, 2, "Only the prior metadata read and credential RPC"); count++;
        }
        {
            const b = setup(lang), task = b.click(); b.resolve({ message: b.result() }); await task;
            b.dialogs.length = 0;
            const explicit = b.credential("production"); await tick();
            assert.equal(b.calls.length, 3, "Completed check is not a CSID mutation/review hold");
            b.resolve({ exc: "PRIVATE" }); await explicit; count++;
        }
    }
    console.log("Device Compliance form: " + count + " synthetic cases passed");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
