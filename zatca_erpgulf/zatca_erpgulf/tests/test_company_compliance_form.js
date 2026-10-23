/* Actual Company handlers in an offline VM; no site, HTTP, files or credentials. */
const assert = require("node:assert/strict");
const { browser, catalog } = require("./test_company_compliance_messages.js");
const actions = { single: "custom_check_compliance", all: "custom_run_all_compliance", automatic: "custom_run_zatca_onboarding_checks" };
const text = {
    inactive: "The Company settings form is no longer active. Reopen it before starting Compliance.",
    save: "Save the Company settings before running Compliance. No Compliance request was sent.",
    incomplete: "Saved Company identity or revision is incomplete. Review settings before running Compliance.",
    sample: "Please enter Sample Invoice Number to Test first.",
    review: "Review saved CSR and private-key settings before saving an already-open form or generating another CSR or CSID. Preserve unsaved changes before reloading.",
    before: "The Company form changed before Compliance started. Preserve edits and review saved settings. No Compliance request was sent.",
    after: "The Company form changed while Compliance was running. The request may have completed. Preserve edits and review the original Company outcome before another request.",
    unknown: "The Company Compliance request outcome is not confirmed. Preserve edits and review the outcome before another request; no automatic retry was performed.",
    preparation: "Company Compliance preparation could not be completed. No Compliance request was sent.",
    consent: "This alternative submits temporary samples for ZATCA Compliance in the saved Company environment. It is not a local-only preview. No customer or sales invoice is created and no certificate is issued by this test. Choose this method or Run All Compliance, not both. Continue?"
};
const kinds = ["Simplified Invoice", "Standard Invoice", "Simplified Credit Note", "Standard Credit Note", "Simplified Debit Note", "Standard Debit Note"];
const tick = async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); };
let count = 0;

function setup(lang, mode) {
    const b = browser(lang);
    b.context.console = { log() { assert.fail("No source/response/error console dump"); } };
    Object.assign(b.frm.doc, { custom_validation_type: "Standard Invoice", custom_csr_config: "PRIVATE-CONFIG",
        custom_otp: "PRIVATE-OTP", custom_private_key: "PRIVATE-KEY" });
    b.route = ["Form", "Company", b.frm.doc.name];
    b.context.frappe.get_route = () => b.route;
    b.dirty = false;
    b.frm.is_dirty = () => b.dirty;
    b.frm.is_new = () => false;
    b.frm.save = b.frm.reload_doc = b.frm.set_value = () => assert.fail("No automatic form write/reload");
    b.confirms = [];
    b.context.frappe.confirm = (message, yes, no) => {
        b.confirms.push(message); b.yes = yes; b.no = no;
        if (!b.pauseConsent) yes();
    };
    b.context.frappe.call = options => {
        b.calls.push(options);
        assert.match(options.method, /^zatca_erpgulf\.zatca_erpgulf\.(?:company_compliance\.run_company_compliance_summary|csr_configuration\.prepare_csr_config|sign_invoice_first\.(?:create_csr|create_csid|production_csid))$/);
        assert.ok(!JSON.stringify(options.args).includes("PRIVATE"));
        return new Promise((resolve, reject) => { b.resolve = resolve; b.reject = reject; });
    };
    b.click = (selected = mode) => b.handlers[actions[selected]](b.frm);
    b.credential = selected => b.handlers[selected === "csr" ? "custom_create_csr" : selected === "configuration" ?
        "custom_create_csr_configuration" : selected === "production" ? "custom_generate_production_csids" : "custom_generate_compliance_csid"](b.frm);
    b.start = async () => { const task = b.click(); await tick(); return { task }; };
    b.result = outcome => ({ results: (mode === "single" ? kinds.slice(0, 1) : kinds).map(type => ({
        type, status: outcome === "FAIL" ? "FAIL" : "PASS", message: outcome === "FAIL" ?
            "Compliance check failed. See technical details." : outcome === "WARNING" ?
            "Completed with warnings. See technical details." : "Completed successfully." })),
        ...(mode === "single" ? { single_check: true } : mode === "automatic" ? { all_passed: outcome !== "FAIL" } : {}) });
    b.notice = key => {
        assert.equal(b.dialogs.length, 1);
        assert.equal(b.dialogs[0].message, lang === "ar" ? catalog.get(text[key]) : text[key]);
        assert.ok(!JSON.stringify(b.dialogs).includes("PRIVATE"));
    };
    return b;
}

async function main() {
    for (const key of Object.values(text)) {
        assert.ok(catalog.has(key)); assert.notEqual(catalog.get(key), key);
    }
    for (const lang of ["en", "ar"]) for (const mode of Object.keys(actions)) {
        for (const fault of ["dirty", "local", "new", "unknown-dirty", "dirty-error", "route-error", "route", "active", "unsupported", "name", "modified", "abbr", "sample"]) {
            const b = setup(lang, mode); let key = "save";
            if (fault === "dirty") b.dirty = true;
            if (fault === "local") b.frm.doc.__islocal = true;
            if (fault === "new") b.frm.is_new = () => true;
            if (fault === "unknown-dirty") delete b.frm.is_dirty;
            if (fault === "dirty-error") b.frm.is_dirty = () => { throw Error("PRIVATE"); };
            if (fault === "route-error") { b.context.frappe.get_route = () => { throw Error("PRIVATE"); }; key = "inactive"; }
            if (fault === "route") { b.route = ["List", "Company"]; key = "inactive"; }
            if (fault === "active") { b.context.cur_frm = {}; key = "inactive"; }
            if (fault === "unsupported") { b.frm.doc.doctype = "Other"; key = "inactive"; }
            if (fault === "name") { b.frm.doc.name = ""; key = "inactive"; }
            if (fault === "modified") { b.frm.doc.modified = ""; key = "incomplete"; }
            if (fault === "abbr") { b.frm.doc.abbr = ""; key = "incomplete"; }
            if (fault === "sample") {
                if (mode === "automatic") continue;
                b.frm.doc.custom_sample_invoice_number_to_test = ""; key = "sample";
            }
            const before = JSON.stringify(b.frm.doc);
            await b.click(); b.notice(key); assert.equal(b.calls.length, 0); assert.equal(b.confirms.length, 0);
            assert.equal(JSON.stringify(b.frm.doc), before); count++;
        }
        for (const outcome of ["PASS", "WARNING", "FAIL"]) {
            const b = setup(lang, mode), before = JSON.stringify(b.frm.doc);
            if (mode === "automatic") delete b.frm.doc.custom_sample_invoice_number_to_test;
            const expectedDoc = JSON.stringify(b.frm.doc), result = b.result(outcome), original = JSON.stringify(result);
            const { task } = await b.start();
            for (const selected of Object.keys(actions)) assert.equal(b.click(selected), task);
            for (const selected of ["csr", "configuration", "compliance", "production"]) assert.equal(b.credential(selected), task);
            assert.equal(b.calls.length, 1);
            assert.equal(JSON.stringify(b.calls[0].args), JSON.stringify({ company_name: b.frm.doc.name,
                expected_modified: b.frm.doc.modified, mode }));
            assert.equal(b.calls[0].freeze, true); assert.equal(b.events.length, 0);
            if (mode === "automatic") assert.equal(b.confirms[0], lang === "ar" ? catalog.get(text.consent) : text.consent);
            else assert.equal(b.confirms.length, 0);
            b.resolve({ message: result }); assert.equal(await task, undefined);
            assert.equal(b.dialogs.length, 1);
            assert.equal(b.dialogs[0].indicator, outcome === "FAIL" ? "red" : outcome === "WARNING" ? "orange" : "green");
            assert.equal(JSON.stringify(b.frm.doc), expectedDoc); assert.equal(JSON.stringify(result), original);
            assert.ok(!JSON.stringify(b.dialogs).includes("PRIVATE"));
            if (mode !== "automatic") assert.equal(JSON.stringify(b.frm.doc), before); count++;
        }
        for (const change of ["dirty", "document", "name", "modified", "abbr", "environment", "type", "sample", "route", "active"]) {
            const b = setup(lang, mode); const { task } = await b.start();
            if (change === "dirty") { b.dirty = true; b.frm.doc.custom_otp = "KEEP PRIVATE EDIT"; }
            if (change === "document") b.frm.doc = { ...b.frm.doc };
            const fields = { name: "name", modified: "modified", abbr: "abbr", environment: "custom_select",
                type: "custom_validation_type", sample: "custom_sample_invoice_number_to_test" };
            if (fields[change]) b.frm.doc[fields[change]] = "OTHER";
            if (change === "route") b.route = ["List", "Company"];
            if (change === "active") b.context.cur_frm = {};
            const before = JSON.stringify(b.frm.doc);
            b.resolve({ message: b.result("PASS") }); await task; b.notice("after");
            assert.equal(JSON.stringify(b.frm.doc), before); assert.equal(b.calls.length, 1); count++;
        }
        for (const reply of [undefined, null, {}, "OK", { results: [] }, { results: [null] }]) {
            const b = setup(lang, mode); const { task } = await b.start();
            b.resolve({ message: reply }); await task;
            assert.equal(b.dialogs.length, 1); assert.equal(b.dialogs[0].indicator, "red"); count++;
        }
        for (const status of [401, 403, 417, 500]) {
            const b = setup(lang, mode); const { task } = await b.start();
            b.dialogs.push({ message: "Framework-owned error" });
            b.reject({ status, responseJSON: { _server_messages: "PRIVATE" } }); await task;
            assert.equal(b.dialogs.length, 1); assert.equal(b.calls.length, 1); count++;
        }
        {
            const b = setup(lang, mode); const { task } = await b.start();
            b.dialogs.push({ message: "Framework-owned exception reply" }); b.resolve({ exc: "PRIVATE" }); await task;
            assert.equal(b.dialogs.length, 1); count++;
        }
        for (const error of [Error("PRIVATE"), {}, { status: 0 }]) {
            const b = setup(lang, mode); const { task } = await b.start(); b.reject(error); await task; b.notice("unknown");
            assert.equal(b.calls.length, 1); b.dialogs.length = 0;
            const next = (await b.start()).task; assert.equal(b.calls.length, 2, "Only explicit later clicks, not a durable hold");
            b.resolve({ message: b.result("PASS") }); await next; assert.equal(b.dialogs.length, 1); count++;
        }
        for (const prior of ["csr", "compliance", "production"]) {
            const b = setup(lang, mode), task = b.credential(prior);
            assert.equal(b.click(), task); await tick(); b.resolve({ exc: "PRIVATE" }); await task;
            b.dirty = true; await b.click(); b.notice("review"); assert.equal(b.calls.length, 1); count++;
        }
        {
            const b = setup(lang, mode), task = b.credential("configuration");
            assert.equal(b.click(), task); b.resolve({ exc: "PRIVATE" }); await task;
            const next = (await b.start()).task; b.resolve({ message: b.result("PASS") }); await next;
            assert.equal(b.calls.length, 2, "Read-only preparation is not a credential mutation"); count++;
        }
        {
            const b = setup(lang, mode); const { task } = await b.start();
            b.resolve({ message: b.result("PASS") }); await task;
            b.dialogs.length = 0; const next = b.credential("production"); await tick();
            assert.equal(b.calls.length, 2); b.resolve({ exc: "PRIVATE" }); await next; count++;
        }
        if (mode !== "automatic") continue;
        for (const answer of ["decline", "close"]) {
            const b = setup(lang, mode); b.pauseConsent = true;
            const task = b.click(); assert.equal(b.calls.length, 0);
            for (const selected of Object.keys(actions)) assert.equal(b.click(selected), task);
            for (const selected of ["csr", "configuration", "compliance", "production"]) assert.equal(b.credential(selected), task);
            // Frappe routes close-without-primary-action to the reject callback.
            b.no(); await task; assert.equal(b.calls.length, 0); assert.equal(b.dialogs.length, 0);
            const explicit = b.click("all"); b.resolve({ message: { results: [] } }); await explicit;
            assert.equal(b.calls.length, 1); count++;
        }
        for (const change of ["dirty", "document", "modified", "abbr", "environment", "type", "sample", "route", "active"]) {
            const b = setup(lang, mode); b.pauseConsent = true; const task = b.click();
            if (change === "dirty") b.dirty = true;
            if (change === "document") b.frm.doc = { ...b.frm.doc };
            const fields = { modified: "modified", abbr: "abbr", environment: "custom_select", type: "custom_validation_type", sample: "custom_sample_invoice_number_to_test" };
            if (fields[change]) b.frm.doc[fields[change]] = "OTHER";
            if (change === "route") b.route = ["List", "Company"];
            if (change === "active") b.context.cur_frm = {};
            const before = JSON.stringify(b.frm.doc);
            b.yes(); await task; b.notice("before"); assert.equal(b.calls.length, 0);
            assert.equal(JSON.stringify(b.frm.doc), before); count++;
        }
        {
            const b = setup(lang, mode); b.context.frappe.confirm = () => { throw Error("PRIVATE"); };
            await b.click(); b.notice("preparation"); assert.equal(b.calls.length, 0); count++;
        }
    }
    console.log("Company Compliance form: " + count + " synthetic cases passed");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
