/* Actual form handlers in a network-free VM; no site/browser/credential RPC. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { browser, catalog } = require("./test_company_compliance_messages.js");
const deviceSource = fs.readFileSync(path.resolve(__dirname,
    "../doctype/zatca_multiple_setting/zatca_multiple_setting.js"), "utf8");
new vm.Script(deviceSource);
const review = "Review saved CSID settings before saving an already-open form or starting another CSID operation. Preserve unsaved changes before reloading.";
const save = "Save the Company or device settings, including OTP and environment, before generating CSID. No CSID request was sent.";
const inactive = "The CSID settings form is no longer active. Reopen it before starting the operation.";
const incomplete = "Saved CSID source settings are incomplete. Review the Company link and selected environment. No CSID request was sent.";
const cancelled = "CSID generation was cancelled because the form changed while reading saved settings. Preserve edits and review the active form. No CSID request was sent.";
const unread = "Saved Company settings could not be read. No CSID request was sent.";
const unknown = "The CSID request outcome is not confirmed in this form. Preserve edits and review saved settings and the onboarding status before another request.";
const unconfirmed = "CSID creation was not confirmed. Review saved settings before trying again.";
let count = 0;

function setup(lang, device, production) {
    const b = browser(lang);
    if (device) {
        b.context.frappe.ui.form.on = (doctype, handlers) => {
            assert.equal(doctype, "ZATCA Multiple Setting");
            b.handlers = handlers;
        };
        vm.runInContext(deviceSource, b.context, { timeout: 1000 });
    }
    b.frm.doc = { doctype: device ? "ZATCA Multiple Setting" : "Company",
        name: device ? "FICTIONAL DEVICE" : "FICTIONAL COMPANY", modified: "2026-10-23 09:00:00",
        abbr: device ? undefined : "FC", custom_select: device ? "Sandbox" : "Production",
        custom_linked_doctype: device ? "FICTIONAL COMPANY" : undefined,
        custom_otp: "PRIVATE-OTP", custom_certificate: "PRIVATE-OLD-CERT" };
    b.route = ["Form", b.frm.doc.doctype, b.frm.doc.name];
    b.context.frappe.get_route = () => b.route;
    b.context.cur_frm = b.frm;
    b.dirty = false;
    b.frm.is_dirty = () => b.dirty;
    b.frm.is_new = () => false;
    b.frm.save = b.frm.reload_doc = b.frm.set_value = () => assert.fail("No automatic form save/reload/write");
    b.sends = [];
    b.selected = { abbr: "FC", custom_select: "Production" };
    b.context.frappe.call = options => {
        b.calls.push(options);
        if (options.method === "frappe.client.get_value") {
            assert.equal(device, true);
            assert.equal(options.args.doctype, "Company");
            assert.equal(options.args.filters, "FICTIONAL COMPANY");
            assert.equal(JSON.stringify(options.args.fieldname), '["abbr","custom_select"]');
            assert.deepEqual(Object.keys(options.args).sort(), ["doctype", "fieldname", "filters"]);
            if (b.pauseLookup) return new Promise((resolve, reject) => { b.resolveLookup = resolve; b.rejectLookup = reject; });
            return Promise.resolve({ message: b.selected });
        }
        assert.match(options.method, /^zatca_erpgulf\.zatca_erpgulf\.sign_invoice_first\.(?:create_csid|production_csid)$/);
        assert.ok(!JSON.stringify(options.args).includes("PRIVATE"));
        assert.equal(options.freeze, true);
        b.sends.push(options);
        return new Promise((resolve, reject) => { b.resolve = resolve; b.reject = reject; });
    };
    b.click = (final = production) => b.handlers[final ?
        (device ? "custom_generate_final_csids" : "custom_generate_production_csids") : "custom_generate_compliance_csid"](b.frm);
    b.start = async () => {
        const task = b.click();
        await Promise.resolve();
        await Promise.resolve();
        return { task };
    };
    b.notice = key => {
        assert.equal(b.dialogs.length, 1);
        assert.equal(b.dialogs[0].message, lang === "ar" ? catalog.get(key) : key);
        assert.equal(b.dialogs[0].indicator, "orange");
        assert.ok(!JSON.stringify(b.dialogs).includes("PRIVATE"));
    };
    b.result = () => JSON.stringify({ status: "SUCCESS", purpose: production ? "production" : "compliance",
        message: production ? "Final CSID generated and saved successfully." : "Compliance CSID generated and saved successfully." });
    b.finish = async task => {
        const result = b.result();
        // Model the existing server-owned single popup, not a second client one.
        b.dialogs.push({ message: "Server-owned CSID result with review guidance" });
        b.resolve({ message: result });
        assert.equal(await task, undefined);
        assert.equal(b.dialogs.length, 1);
    };
    return b;
}

async function main() {
    for (const lang of ["en", "ar"]) for (const device of [false, true]) for (const production of [false, true]) {
        for (const fault of ["dirty", "local", "new", "unknown-dirty", "dirty-error", "route-error", "route", "active", "unsupported", "modified", "source"]) {
            const b = setup(lang, device, production);
            let key = save;
            if (fault === "dirty") b.dirty = true;
            if (fault === "local") b.frm.doc.__islocal = true;
            if (fault === "new") b.frm.is_new = () => true;
            if (fault === "unknown-dirty") delete b.frm.is_dirty;
            if (fault === "dirty-error") b.frm.is_dirty = () => { throw Error("PRIVATE-DIRTY"); };
            if (fault === "route-error") { b.context.frappe.get_route = () => { throw Error("PRIVATE-ROUTE"); }; key = inactive; }
            if (fault === "route") { b.route = ["List", b.frm.doc.doctype]; key = inactive; }
            if (fault === "active") { b.context.cur_frm = {}; key = inactive; }
            if (fault === "unsupported") { b.frm.doc.doctype = "Other"; key = inactive; }
            if (fault === "modified") { delete b.frm.doc.modified; key = incomplete; }
            if (fault === "source") { b.frm.doc[device ? "custom_linked_doctype" : "abbr"] = ""; key = incomplete; }
            const before = JSON.stringify(b.frm.doc);
            await b.click();
            assert.equal(b.calls.length, 0);
            assert.equal(JSON.stringify(b.frm.doc), before);
            b.notice(key);
            count++;
        }
        {
            const b = setup(lang, device, production);
            const before = JSON.stringify(b.frm.doc);
            const { task } = await b.start();
            assert.equal(b.click(!production), task, "One pending operation across both CSID buttons");
            assert.equal(b.sends.length, 1);
            const options = b.sends[0];
            assert.ok(options.method.endsWith(production ? ".production_csid" : ".create_csid"));
            assert.equal(options.args.company_abbr, "FC");
            assert.equal(options.args.zatca_doc.name, b.frm.doc.name);
            assert.equal(options.args.zatca_doc.doctype, b.frm.doc.doctype);
            assert.deepEqual(Object.keys(options.args.zatca_doc).sort(), ["doctype", "name"]);
            assert.deepEqual(Object.keys(options.args).sort(), production ? ["company_abbr", "zatca_doc"] : ["company_abbr", "portal_type", "zatca_doc"]);
            if (!production) assert.equal(options.args.portal_type, "Production", "Device uses linked saved Company environment");
            await b.finish(task);
            assert.equal(JSON.stringify(b.frm.doc), before);
            assert.equal(b.calls.length, device ? 2 : 1);
            b.dialogs.length = 0;
            b.dirty = true;
            await b.click(!production);
            b.notice(review); // Never tell the user to save this stale dirty copy.
            assert.equal(b.sends.length, 1);
            count++;
        }
        for (const change of ["dirty", "route", "document"]) {
            const b = setup(lang, device, production);
            const { task } = await b.start();
            if (change === "dirty") { b.dirty = true; b.frm.doc.custom_otp = "KEEP LOCAL EDIT"; }
            if (change === "route") b.route = ["Form", b.frm.doc.doctype, "OTHER"];
            if (change === "document") b.frm.doc = { ...b.frm.doc, name: "OTHER", custom_otp: "KEEP NEW FORM" };
            const before = JSON.stringify(b.frm.doc);
            await b.finish(task);
            assert.equal(JSON.stringify(b.frm.doc), before);
            assert.equal(b.sends.length, 1);
            count++;
        }
        for (const status of [401, 403, 417, 500]) {
            const b = setup(lang, device, production);
            const { task } = await b.start();
            b.dialogs.push({ message: "Framework-owned validation/session error" });
            b.reject({ status, responseJSON: { _server_messages: "Framework-owned" } });
            await task;
            assert.equal(b.dialogs.length, 1);
            b.dialogs.length = 0;
            await b.click();
            b.notice(review);
            assert.equal(b.sends.length, 1);
            count++;
        }
        {
            const b = setup(lang, device, production);
            const { task } = await b.start();
            b.dialogs.push({ message: "Framework-owned exception response" });
            b.resolve({ exc: "synthetic exception", message: "PRIVATE" });
            await task;
            assert.equal(b.dialogs.length, 1);
            b.dialogs.length = 0;
            await b.click();
            b.notice(review);
            assert.equal(b.sends.length, 1);
            count++;
        }
        for (const error of [new Error("PRIVATE-LOCAL-ERROR"), { status: 0 }, {}]) {
            const b = setup(lang, device, production);
            const { task } = await b.start();
            b.reject(error);
            await task;
            assert.equal(b.dialogs.length, 1);
            assert.equal(b.dialogs[0].message, lang === "ar" ? catalog.get(unknown) : unknown);
            assert.ok(!JSON.stringify(b.dialogs).includes("PRIVATE"));
            assert.equal(b.sends.length, 1);
            count++;
        }
        for (const value of [undefined, null, {}, "", "PRIVATE", { status: "success" },
            { status: "SUCCESS", purpose: production ? "compliance" : "production", message: "PRIVATE" }]) {
            const b = setup(lang, device, production);
            const { task } = await b.start();
            const before = JSON.stringify(value);
            b.resolve({ message: value });
            await task;
            b.notice(unconfirmed);
            assert.equal(JSON.stringify(value), before);
            assert.equal(b.sends.length, 1);
            count++;
        }
        {
            const b = setup(lang, device, production);
            const { task } = await b.start();
            await b.finish(task);
            b.dialogs.length = 0;
            b.frm.doc = { ...b.frm.doc, modified: "2026-10-23 10:00:00" }; // Synthetic fresh load, not proof of remote review.
            const next = (await b.start()).task;
            assert.notEqual(next, task);
            await b.finish(next);
            assert.equal(b.sends.length, 2, "Only a new explicit click, never an automatic retry");
            count++;
        }
        if (!device) continue;
        for (const change of ["dirty", "object", "name", "modified", "link", "environment", "route", "active"]) {
            const b = setup(lang, device, production);
            b.pauseLookup = true;
            const task = b.click();
            if (change === "dirty") b.dirty = true;
            if (change === "object") b.frm.doc = { ...b.frm.doc };
            if (change === "name") b.frm.doc.name = "OTHER";
            if (change === "modified") b.frm.doc.modified = "CHANGED";
            if (change === "link") b.frm.doc.custom_linked_doctype = "OTHER";
            if (change === "environment") b.frm.doc.custom_select = "CHANGED";
            if (change === "route") b.route = ["List", "Company"];
            if (change === "active") b.context.cur_frm = {};
            const before = JSON.stringify(b.frm.doc);
            b.resolveLookup({ message: b.selected });
            await task;
            b.notice(cancelled);
            assert.equal(b.sends.length, 0);
            assert.equal(b.calls.length, 1);
            assert.equal(JSON.stringify(b.frm.doc), before);
            count++;
        }
        for (const selected of [null, {}, [], { abbr: "FC" }, { abbr: "FC", custom_select: "invalid" },
            { abbr: "BAD\n", custom_select: "Production" }]) {
            const b = setup(lang, device, production);
            b.selected = selected;
            await b.click();
            b.notice(incomplete);
            assert.equal(b.calls.length, 1);
            assert.equal(b.sends.length, 0);
            count++;
        }
        for (const framework of [false, true]) {
            const b = setup(lang, device, production);
            b.pauseLookup = true;
            const task = b.click();
            if (framework) b.dialogs.push({ message: "Framework-owned Company read error" });
            b.rejectLookup(framework ? { status: 403 } : Error("PRIVATE-READ"));
            await task;
            assert.equal(b.dialogs.length, 1);
            if (!framework) assert.equal(b.dialogs[0].message, lang === "ar" ? catalog.get(unread) : unread);
            assert.equal(b.sends.length, 0);
            // A read-only lookup failure does not mark the source as attempted.
            b.dialogs.length = 0;
            b.pauseLookup = false;
            const next = (await b.start()).task;
            await b.finish(next);
            assert.equal(b.sends.length, 1);
            count++;
        }
    }
    console.log("CSID form lifecycle: " + count + " synthetic cases passed");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
