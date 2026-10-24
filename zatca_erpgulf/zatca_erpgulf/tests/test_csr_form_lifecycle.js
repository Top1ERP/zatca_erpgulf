/* Network-free actual-handler VM; no key generation, site or authority API. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { browser, catalog } = require("./test_company_compliance_messages.js");
const source = fs.readFileSync(path.resolve(__dirname,
    "../doctype/zatca_multiple_setting/zatca_multiple_setting.js"), "utf8");
const text = {
    inactive: "The CSR settings form is no longer active. Reopen it before starting the operation.",
    review: "Review saved CSR and private-key settings before saving an already-open form or generating another CSR or CSID. Preserve unsaved changes before reloading.",
    save: "Save the Company or device settings and CSR configuration before generating CSR. No CSR generation request was sent.",
    incomplete: "Saved CSR source settings are incomplete. Review the Company link and selected environment. No CSR generation request was sent.",
    changed: "CSR generation was cancelled because the form changed. Preserve edits and review saved settings. No CSR generation request was sent.",
    confirm: "Generating CSR replaces the saved private key for pre-issuance settings only. Existing certificate, authentication or onboarding-reference data blocks this operation. Renewal requires a separately reviewed workflow. Continue?",
    returned: "The CSR generation call returned. Review saved CSR and private-key settings before any further operation; this does not confirm certificate issuance. Preserve unsaved changes before reloading.",
    unknown: "CSR generation could not be confirmed. The saved private key may have changed. Preserve edits and review saved settings before another CSR or CSID operation.",
    preparation: "CSR preparation could not be completed. No CSR generation request was sent."
};
let count = 0;
const tick = async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); };

function setup(lang, device) {
    const b = browser(lang);
    b.context.console = { log() { assert.fail("No credential/source/response console dumps"); } };
    if (device) {
        b.context.frappe.ui.form.on = (doctype, handlers) => {
            assert.equal(doctype, "ZATCA Multiple Setting"); b.handlers = handlers;
        };
        vm.runInContext(source, b.context, { timeout: 1000 });
    }
    Object.assign(b.frm.doc, { doctype: device ? "ZATCA Multiple Setting" : "Company",
        name: device ? "FICTIONAL DEVICE" : "FICTIONAL COMPANY",
        custom_linked_doctype: device ? "FICTIONAL COMPANY" : undefined,
        custom_csr_config: "PRIVATE-CONFIG", custom_private_key: "PRIVATE-OLD-KEY" });
    if (device) { delete b.frm.doc.abbr; b.frm.doc.custom_select = "Sandbox"; }
    b.route = ["Form", b.frm.doc.doctype, b.frm.doc.name];
    b.context.frappe.get_route = () => b.route;
    b.dirty = false;
    b.frm.is_dirty = () => b.dirty;
    b.frm.is_new = () => false;
    b.frm.save = b.frm.reload_doc = b.frm.set_value = () => assert.fail("No automatic form write/reload");
    b.confirms = [];
    b.context.frappe.confirm = (message, yes, no) => {
        b.confirms.push(message); b.yes = yes; b.no = no;
    };
    b.selected = { abbr: "FC", custom_select: "Production" };
    b.sends = [];
    b.context.frappe.call = options => {
        b.calls.push(options);
        if (options.method === "frappe.client.get_value") {
            assert.equal(device, true);
            assert.equal(options.args.filters, "FICTIONAL COMPANY");
            assert.equal(JSON.stringify(options.args), JSON.stringify({ doctype: "Company",
                filters: "FICTIONAL COMPANY", fieldname: ["abbr", "custom_select"] }));
            if (b.pauseLookup) return new Promise((resolve, reject) => { b.lookup = resolve; b.lookupFail = reject; });
            return Promise.resolve({ message: b.selected });
        }
        assert.match(options.method, /^zatca_erpgulf\.zatca_erpgulf\.sign_invoice_first\.(?:create_csr|create_csid|production_csid)$/);
        assert.ok(!JSON.stringify(options.args).includes("PRIVATE"));
        assert.equal(options.freeze, true);
        b.sends.push(options);
        return new Promise((resolve, reject) => { b.resolve = resolve; b.reject = reject; });
    };
    b.click = () => b.handlers.custom_create_csr(b.frm);
    b.csid = production => b.handlers[production ? (device ? "custom_generate_final_csids" :
        "custom_generate_production_csids") : "custom_generate_compliance_csid"](b.frm);
    b.start = async () => {
        const task = b.click(); assert.equal(b.calls.length, 0, "Consent precedes even the metadata lookup");
        assert.equal(b.confirms.length, 1);
        assert.equal(b.confirms[0], lang === "ar" ? catalog.get(text.confirm) : text.confirm);
        b.yes(); await tick(); return { task };
    };
    b.notice = (key, indicator = "orange") => {
        assert.equal(b.dialogs.length, 1);
        assert.equal(b.dialogs[0].message, lang === "ar" ? catalog.get(text[key]) : text[key]);
        assert.equal(b.dialogs[0].indicator, indicator);
        assert.ok(!JSON.stringify(b.dialogs).includes("PRIVATE"));
    };
    return b;
}

async function main() {
    // Every new display key must exist in the actual CSV, not fallback English.
    for (const value of [...Object.values(text), "CSR Generation Result", "CSR Generation Failed", "Generating CSR..."]) {
        assert.ok(catalog.has(value)); assert.notEqual(catalog.get(value), value);
    }
    for (const lang of ["en", "ar"]) for (const device of [false, true]) {
        for (const fault of ["dirty", "local", "new", "unknown-dirty", "dirty-error", "route-error", "route", "active", "unsupported", "modified", "source", "environment"]) {
            const b = setup(lang, device);
            let key = "save";
            if (fault === "dirty") b.dirty = true;
            if (fault === "local") b.frm.doc.__islocal = true;
            if (fault === "new") b.frm.is_new = () => true;
            if (fault === "unknown-dirty") delete b.frm.is_dirty;
            if (fault === "dirty-error") b.frm.is_dirty = () => { throw Error("PRIVATE"); };
            if (fault === "route-error") { b.context.frappe.get_route = () => { throw Error("PRIVATE"); }; key = "inactive"; }
            if (fault === "route") { b.route = ["List", "Company"]; key = "inactive"; }
            if (fault === "active") { b.context.cur_frm = {}; key = "inactive"; }
            if (fault === "unsupported") { b.frm.doc.doctype = "Other"; key = "inactive"; }
            if (fault === "modified") { delete b.frm.doc.modified; key = "incomplete"; }
            if (fault === "source") { b.frm.doc[device ? "custom_linked_doctype" : "abbr"] = ""; key = "incomplete"; }
            if (fault === "environment") {
                if (device) continue;
                b.frm.doc.custom_select = "Other"; key = "incomplete";
            }
            const before = JSON.stringify(b.frm.doc);
            await b.click(); b.notice(key);
            assert.equal(b.calls.length, 0); assert.equal(b.confirms.length, 0);
            assert.equal(JSON.stringify(b.frm.doc), before); count++;
        }
        {
            const b = setup(lang, device);
            const task = b.click();
            assert.equal(b.csid(false), task); assert.equal(b.click(), task);
            b.no(); await task;
            assert.equal(b.calls.length, 0); assert.equal(b.dialogs.length, 0);
            const explicit = b.csid(false); await tick();
            assert.equal(b.sends.length, 1, "Declined consent does not taint credential source");
            b.resolve({ exc: "PRIVATE" }); await explicit; count++;
        }
        {
            const b = setup(lang, device);
            b.context.frappe.confirm = () => { throw Error("PRIVATE-CONFIRM"); };
            await b.click(); b.notice("preparation", "red");
            assert.equal(b.calls.length, 0);
            b.dialogs.length = 0;
            const explicit = b.csid(false); await tick();
            assert.equal(b.sends.length, 1, "Failed consent did not start or mark a credential request");
            b.resolve({ exc: "PRIVATE" }); await explicit; count++;
        }
        for (const change of ["dirty", "route", "document", "modified", "link", "config", "environment", "active"]) {
            const b = setup(lang, device);
            const task = b.click();
            if (change === "dirty") b.dirty = true;
            if (change === "route") b.route = ["Form", "Company", "OTHER"];
            if (change === "document") b.frm.doc = { ...b.frm.doc };
            if (change === "modified") b.frm.doc.modified = "OTHER";
            if (change === "link") b.frm.doc.custom_linked_doctype = "OTHER";
            if (change === "config") b.frm.doc.custom_csr_config = "KEEP PRIVATE EDIT";
            if (change === "environment") b.frm.doc.custom_select = "Simulation";
            if (change === "active") b.context.cur_frm = {};
            const before = JSON.stringify(b.frm.doc);
            b.yes(); await task; b.notice("changed");
            assert.equal(b.calls.length, 0); assert.equal(JSON.stringify(b.frm.doc), before); count++;
        }
        for (const reply of [undefined, null, "", "PRIVATE-ENCODED-CSR", { status: "SUCCESS", key: "PRIVATE" }]) {
            const b = setup(lang, device);
            const { task } = await b.start();
            assert.equal(b.click(), task); assert.equal(b.csid(true), task);
            assert.equal(b.sends.length, 1);
            const options = b.sends[0];
            assert.ok(options.method.endsWith(".create_csr"));
            assert.equal(options.freeze_message, lang === "ar" ? catalog.get("Generating CSR...") : "Generating CSR...");
            assert.equal(JSON.stringify(options.args), JSON.stringify({ zatca_doc: {
                doctype: b.frm.doc.doctype, name: b.frm.doc.name }, company_abbr: "FC", portal_type: "Production" }));
            const before = JSON.stringify(b.frm.doc);
            b.resolve({ message: reply }); await task; b.notice("returned");
            assert.equal(JSON.stringify(b.frm.doc), before);
            b.dialogs.length = 0; b.dirty = true;
            await b.click(); b.notice("review");
            b.dialogs.length = 0; await b.csid(true);
            assert.equal(b.dialogs.length, 1); assert.equal(b.sends.length, 1); count++;
        }
        for (const change of ["dirty", "navigation", "document"]) {
            const b = setup(lang, device);
            const { task } = await b.start();
            if (change === "dirty") { b.dirty = true; b.frm.doc.custom_csr_config = "KEEP PRIVATE EDIT"; }
            if (change === "navigation") b.route = ["List", "Company"];
            if (change === "document") b.frm.doc = { ...b.frm.doc, name: "OTHER" };
            const before = JSON.stringify(b.frm.doc);
            b.resolve({ message: "PRIVATE" }); await task; b.notice("returned");
            assert.equal(JSON.stringify(b.frm.doc), before); count++;
        }
        for (const status of [401, 403, 417, 500, 0]) {
            const b = setup(lang, device);
            const { task } = await b.start();
            if (status) b.dialogs.push({ message: "Framework-owned error" });
            b.reject(status ? { status, responseJSON: { _server_messages: "PRIVATE" } } : Error("PRIVATE"));
            await task;
            if (status) assert.equal(b.dialogs.length, 1); else b.notice("unknown", "red");
            b.dialogs.length = 0; await b.click(); b.notice("review");
            assert.equal(b.sends.length, 1); count++;
        }
        {
            const b = setup(lang, device);
            const { task } = await b.start();
            b.dialogs.push({ message: "Framework-owned exception" });
            b.resolve({ exc: "PRIVATE" }); await task;
            assert.equal(b.dialogs.length, 1);
            b.dialogs.length = 0; await b.click(); b.notice("review"); count++;
        }
        for (const production of [false, true]) {
            const b = setup(lang, device);
            const task = b.csid(production); await tick();
            assert.equal(b.click(), task); assert.equal(b.confirms.length, 0);
            b.resolve({ exc: "PRIVATE" }); await task;
            await b.click(); b.notice("review"); assert.equal(b.sends.length, 1); count++;
        }
        if (!device) continue;
        for (const change of ["dirty", "document", "modified", "link", "config", "route"]) {
            const b = setup(lang, device); b.pauseLookup = true;
            const { task } = await b.start();
            if (change === "dirty") b.dirty = true;
            if (change === "document") b.frm.doc = { ...b.frm.doc };
            if (change === "modified") b.frm.doc.modified = "OTHER";
            if (change === "link") b.frm.doc.custom_linked_doctype = "OTHER";
            if (change === "config") b.frm.doc.custom_csr_config = "KEEP PRIVATE EDIT";
            if (change === "route") b.route = ["List", "Company"];
            const before = JSON.stringify(b.frm.doc);
            b.lookup({ message: b.selected }); await task; b.notice("changed");
            assert.equal(b.sends.length, 0); assert.equal(JSON.stringify(b.frm.doc), before); count++;
        }
        for (const selected of [null, {}, { abbr: "FC", custom_select: "Other" }, { abbr: "", custom_select: "Production" }]) {
            const b = setup(lang, device); b.selected = selected;
            const { task } = await b.start(); await task;
            b.notice("incomplete"); assert.equal(b.sends.length, 0); count++;
        }
        for (const framework of [false, true]) {
            const b = setup(lang, device); b.pauseLookup = true;
            const { task } = await b.start();
            if (framework) b.dialogs.push({ message: "Framework-owned lookup error" });
            b.lookupFail(framework ? { status: 403 } : Error("PRIVATE")); await task;
            if (framework) assert.equal(b.dialogs.length, 1); else b.notice("preparation", "red");
            b.dialogs.length = 0; b.pauseLookup = false;
            const retry = b.click(); b.yes(); await tick();
            assert.equal(b.sends.length, 1, "Only an explicit click after read-only lookup failure");
            b.resolve({ message: "PRIVATE" }); await retry; b.notice("returned"); count++;
        }
        {
            const b = setup(lang, device); b.pauseLookup = true;
            const { task } = await b.start();
            assert.equal(b.csid(false), task);
            b.dialogs.push({ message: "Framework-owned exception reply" });
            b.lookup({ exc: "PRIVATE" }); await task;
            assert.equal(b.dialogs.length, 1); assert.equal(b.sends.length, 0);
            b.dialogs.length = 0; b.pauseLookup = false;
            const retry = b.click(); b.yes(); await tick();
            assert.equal(b.sends.length, 1); b.resolve({ message: "PRIVATE" });
            await retry; b.notice("returned"); count++;
        }
    }
    console.log("CSR form lifecycle: " + count + " synthetic cases passed");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
