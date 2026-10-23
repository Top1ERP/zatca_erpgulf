/* Actual Company handler in an offline VM. No site/browser/HTTP/key generation. */
const assert = require("node:assert/strict");
const { browser, catalog } = require("./test_company_compliance_messages.js");
const text = {
    inactive: "The CSR settings form is no longer active. Reopen it before starting the operation.",
    save: "Save the Company settings before preparing CSR configuration. No draft was requested or saved.",
    revision: "Saved Company revision is missing. Review the Company before preparing CSR configuration.",
    review: "Review saved CSR and private-key settings before saving an already-open form or generating another CSR or CSID. Preserve unsaved changes before reloading.",
    changed: "The Company form changed while preparing CSR configuration. The draft was not applied. Preserve edits and review the active form.",
    malformed: "No confirmed CSR configuration draft was returned. No draft was applied or saved.",
    staging: "CSR configuration staging could not be confirmed. Review the form before saving; no automatic save was performed.",
    draft: "CSR configuration was placed in the form as an unsaved draft. Review it and save manually. No private key or certificate was generated.",
    failed: "CSR configuration preparation could not be completed. No draft was applied or saved."
};
const config = "csr.common.name=TEST\ncsr.serial.number=TEST-SERIAL\ncsr.organization.identifier=TEST-VAT\n" +
    "csr.organization.unit.name=TEST-UNIT\ncsr.organization.name=PRIVATE <script> شركة\ncsr.country.name=SA\n" +
    "csr.invoice.type=1100\ncsr.location.address=TEST-CITY\ncsr.industry.business.category=TEST-CATEGORY";
const tick = async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); };
let count = 0;

function setup(lang) {
    const b = browser(lang);
    Object.assign(b.frm.doc, { company_name: "TEST COMPANY", tax_id: "TEST-VAT",
        custom_zatca__location_for_csr_configuratoin: "TEST CITY",
        custom_zatca__company_category_for_csr_configuration: "TEST CATEGORY",
        custom_csr_config: "KEEP OLD CONFIG", custom_private_key: "PRIVATE-KEY" });
    b.route = ["Form", b.frm.doc.doctype, b.frm.doc.name];
    b.context.frappe.get_route = () => b.route;
    b.context.console = { log() { assert.fail("No raw response/error console output"); } };
    b.dirty = false;
    b.frm.is_dirty = () => b.dirty;
    b.frm.is_new = () => false;
    b.frm.save = b.frm.reload_doc = () => assert.fail("No automatic form save/reload");
    b.sets = [];
    b.frm.set_value = async (field, value) => {
        assert.equal(field, "custom_csr_config");
        b.sets.push({ field, value });
        if (b.setter) return b.setter(field, value);
        b.frm.doc[field] = value; b.dirty = true;
    };
    b.context.frappe.call = options => {
        b.calls.push(options);
        assert.match(options.method, /^zatca_erpgulf\.zatca_erpgulf\.(?:csr_configuration\.prepare_csr_config|sign_invoice_first\.(?:create_csr|create_csid|production_csid))$/);
        assert.ok(!JSON.stringify(options.args).includes("PRIVATE"));
        return new Promise((resolve, reject) => { b.resolve = resolve; b.reject = reject; });
    };
    b.run = () => b.handlers.custom_create_csr_configuration(b.frm);
    b.credential = mode => b.handlers[mode === "csr" ? "custom_create_csr" : mode === "production" ?
        "custom_generate_production_csids" : "custom_generate_compliance_csid"](b.frm);
    b.reply = () => ({ status: "DRAFT", company_name: b.frm.doc.name, modified: b.frm.doc.modified, config });
    b.notice = (key, indicator = "orange") => {
        assert.equal(b.dialogs.length, 1);
        assert.equal(b.dialogs[0].message, lang === "ar" ? catalog.get(text[key]) : text[key]);
        assert.equal(b.dialogs[0].indicator, indicator);
        assert.ok(!JSON.stringify(b.dialogs).includes("PRIVATE"));
    };
    return b;
}

async function main() {
    for (const key of [...Object.values(text), "CSR Configuration Result", "CSR Configuration Failed", "Preparing CSR configuration..."]) {
        assert.ok(catalog.has(key)); assert.notEqual(catalog.get(key), key);
    }
    for (const lang of ["en", "ar"]) {
        for (const fault of ["dirty", "local", "new", "unknown-dirty", "dirty-error", "route-error", "route", "active", "unsupported", "name", "revision"]) {
            const b = setup(lang); let key = "save";
            if (fault === "dirty") b.dirty = true;
            if (fault === "local") b.frm.doc.__islocal = true;
            if (fault === "new") b.frm.is_new = () => true;
            if (fault === "unknown-dirty") delete b.frm.is_dirty;
            if (fault === "dirty-error") b.frm.is_dirty = () => { throw Error("PRIVATE"); };
            if (fault === "route-error") { b.context.frappe.get_route = () => { throw Error("PRIVATE"); }; key = "inactive"; }
            if (fault === "route") { b.route = ["List", "Company"]; key = "inactive"; }
            if (fault === "active") { b.context.cur_frm = {}; key = "inactive"; }
            if (fault === "unsupported") { b.frm.doc.doctype = "ZATCA Multiple Setting"; key = "inactive"; }
            if (fault === "name") { b.frm.doc.name = ""; key = "inactive"; }
            if (fault === "revision") { b.frm.doc.modified = ""; key = "revision"; }
            const before = JSON.stringify(b.frm.doc);
            await b.run(); b.notice(key);
            assert.equal(b.calls.length, 0); assert.equal(b.sets.length, 0);
            assert.equal(JSON.stringify(b.frm.doc), before); count++;
        }
        {
            const b = setup(lang);
            // Configuration preparation does not depend on an environment/OTP/abbr.
            delete b.frm.doc.custom_select; delete b.frm.doc.abbr;
            const before = { ...b.frm.doc };
            const task = b.run();
            for (const mode of ["csr", "compliance", "production"]) assert.equal(b.credential(mode), task);
            assert.equal(b.run(), task); assert.equal(b.calls.length, 1);
            assert.equal(b.calls[0].method, "zatca_erpgulf.zatca_erpgulf.csr_configuration.prepare_csr_config");
            assert.equal(JSON.stringify(b.calls[0].args), JSON.stringify({ company_name: before.name, expected_modified: before.modified }));
            assert.equal(b.calls[0].freeze, true);
            assert.equal(b.calls[0].freeze_message, lang === "ar" ? catalog.get("Preparing CSR configuration...") : "Preparing CSR configuration...");
            const result = b.reply(), original = JSON.stringify(result);
            b.resolve({ message: result }); assert.equal(await task, undefined); b.notice("draft");
            assert.equal(JSON.stringify(result), original);
            assert.deepEqual(b.frm.doc, { ...before, custom_csr_config: config });
            assert.equal(b.dirty, true); assert.equal(b.sets.length, 1);
            b.dialogs.length = 0; await b.run(); b.notice("save");
            assert.equal(b.calls.length, 1, "The draft is never saved or regenerated automatically"); count++;
        }
        for (const change of ["dirty", "document", "name", "modified", "abbr", "environment", "config", "tax", "company-name", "location", "category", "route", "active"]) {
            const b = setup(lang), result = b.reply();
            const task = b.run();
            if (change === "dirty") b.dirty = true;
            if (change === "document") b.frm.doc = { ...b.frm.doc };
            const fields = { name: "name", modified: "modified", abbr: "abbr", environment: "custom_select",
                config: "custom_csr_config", tax: "tax_id", "company-name": "company_name",
                location: "custom_zatca__location_for_csr_configuratoin", category: "custom_zatca__company_category_for_csr_configuration" };
            if (fields[change]) b.frm.doc[fields[change]] = "KEEP PRIVATE EDIT";
            if (change === "route") b.route = ["List", "Company"];
            if (change === "active") b.context.cur_frm = {};
            const before = JSON.stringify(b.frm.doc);
            b.resolve({ message: result }); await task; b.notice("changed");
            assert.equal(b.sets.length, 0); assert.equal(JSON.stringify(b.frm.doc), before); count++;
        }
        for (const fault of ["missing", "array", "string", "status", "company", "revision", "empty", "non-string", "oversize", "control", "line-count", "duplicate-key", "empty-value", "nel", "line-separator", "paragraph-separator"]) {
            const b = setup(lang); let result = b.reply();
            if (fault === "missing") result = undefined;
            if (fault === "array") result = [];
            if (fault === "string") result = "PRIVATE";
            if (fault === "status") result.status = "SUCCESS";
            if (fault === "company") result.company_name = "OTHER";
            if (fault === "revision") result.modified = "OTHER";
            if (fault === "empty") result.config = "";
            if (fault === "non-string") result.config = {};
            if (fault === "oversize") result.config = "x".repeat(16385);
            if (fault === "control") result.config += "\0";
            if (fault === "line-count") result.config += "\ncsr.extra=PRIVATE";
            if (fault === "duplicate-key") result.config = config.replace("csr.serial.number=", "csr.common.name=");
            if (fault === "empty-value") result.config = config.replace("csr.invoice.type=1100", "csr.invoice.type=");
            if (fault === "nel") result.config += "\x85csr.extra=PRIVATE";
            if (fault === "line-separator") result.config += "\u2028csr.extra=PRIVATE";
            if (fault === "paragraph-separator") result.config += "\u2029csr.extra=PRIVATE";
            const before = JSON.stringify(b.frm.doc), response = JSON.stringify(result);
            const task = b.run(); b.resolve({ message: result }); await task; b.notice("malformed");
            assert.equal(b.sets.length, 0); assert.equal(JSON.stringify(b.frm.doc), before);
            assert.equal(JSON.stringify(result), response); count++;
        }
        for (const mode of ["csr", "compliance", "production"]) {
            const b = setup(lang);
            const task = b.credential(mode); assert.equal(b.run(), task); await tick();
            assert.equal(b.calls.length, 1);
            b.resolve({ exc: "PRIVATE" }); await task;
            b.dirty = true; await b.run(); b.notice("review");
            assert.equal(b.calls.length, 1); assert.equal(b.sets.length, 0); count++;
        }
        for (const status of [401, 403, 417, 500]) {
            const b = setup(lang); const task = b.run();
            b.dialogs.push({ message: "Framework-owned error" });
            b.reject({ status, responseJSON: { _server_messages: "PRIVATE" } }); await task;
            assert.equal(b.dialogs.length, 1); assert.equal(b.sets.length, 0); count++;
        }
        {
            const b = setup(lang); const task = b.run();
            b.dialogs.push({ message: "Framework-owned exception reply" });
            b.resolve({ exc: "PRIVATE" }); await task;
            assert.equal(b.dialogs.length, 1); assert.equal(b.sets.length, 0); count++;
        }
        for (const error of [new Error("PRIVATE"), {}, { status: 0 }]) {
            const b = setup(lang); const task = b.run(); b.reject(error); await task; b.notice("failed", "red");
            assert.equal(b.sets.length, 0); b.dialogs.length = 0;
            const explicit = b.run(); assert.equal(b.calls.length, 2, "Read-only failure permits a new explicit attempt");
            b.resolve({ message: b.reply() }); await explicit; b.notice("draft"); count++;
        }
        for (const fault of ["before", "after", "navigation", "document", "field-hook", "source-hook"]) {
            const b = setup(lang);
            b.setter = async (field, value) => {
                if (fault === "before") throw Error("PRIVATE");
                b.frm.doc[field] = value; b.dirty = true;
                if (fault === "after") throw Error("PRIVATE");
                if (fault === "navigation") b.route = ["List", "Company"];
                if (fault === "document") b.frm.doc = { ...b.frm.doc, name: "OTHER" };
                if (fault === "field-hook") b.frm.doc[field] = "KEEP HOOK EDIT";
                if (fault === "source-hook") b.frm.doc.tax_id = "KEEP HOOK TAX";
            };
            const task = b.run(); b.resolve({ message: b.reply() }); await task;
            b.notice("staging", ["before", "after"].includes(fault) ? "red" : "orange");
            assert.equal(b.sets.length, 1); assert.equal(b.calls.length, 1);
            if (fault === "field-hook") assert.equal(b.frm.doc.custom_csr_config, "KEEP HOOK EDIT");
            if (fault === "source-hook") assert.equal(b.frm.doc.tax_id, "KEEP HOOK TAX"); count++;
        }
        for (const change of ["none", "navigation", "config-edit"]) {
            const b = setup(lang);
            b.setter = (field, value) => {
                b.frm.doc[field] = value; b.dirty = true;
                return new Promise(resolve => { b.finishHook = resolve; });
            };
            const task = b.run(); b.resolve({ message: b.reply() }); await tick();
            assert.equal(b.sets.length, 1); assert.equal(b.dialogs.length, 0);
            for (const mode of ["csr", "compliance", "production"]) assert.equal(b.credential(mode), task);
            assert.equal(b.run(), task);
            if (change === "navigation") b.route = ["List", "Company"];
            if (change === "config-edit") b.frm.doc.custom_csr_config = "KEEP LATER EDIT";
            b.finishHook(); await task; b.notice(change === "none" ? "draft" : "staging");
            assert.equal(b.calls.length, 1); assert.equal(b.sets.length, 1);
            if (change === "config-edit") assert.equal(b.frm.doc.custom_csr_config, "KEEP LATER EDIT"); count++;
        }
        {
            const b = setup(lang);
            const task = b.run(); b.resolve({ message: b.reply() }); await task;
            b.dialogs.length = 0;
            await b.credential("compliance");
            assert.equal(b.calls.length, 1, "Unsaved draft blocks credential creation");
            // Model a separate deliberate manual save, not an automatic form RPC.
            b.frm.doc.modified = "2026-10-23 10:00:00"; b.dirty = false; b.dialogs.length = 0;
            const explicit = b.credential("compliance"); await tick();
            assert.equal(b.calls.length, 2, "Draft preparation did not taint a credential attempt");
            b.resolve({ exc: "PRIVATE" }); await explicit; count++;
        }
    }
    console.log("CSR configuration form: " + count + " synthetic cases passed");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
