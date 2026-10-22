/* Synthetic UI concurrency only: no browser, site, transport or authority. */
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { browser, catalog } = require("./test_company_compliance_messages.js");

const dirty = "The debug attachment was created for the saved invoice. Your unsaved changes were kept.";
const moved = "The debug result belongs to another form. The current form was not refreshed.";
const manual = "Debug XML was created, but its attachment list could not be refreshed. Review attachments manually; do not generate again just to refresh.";
const save = "Save the invoice before generating Debug XML. No request was sent.";
const inactive = "The invoice form is no longer active. Reopen it before generating Debug XML.";
const uncertain = "The Debug request did not complete visibly. Review existing attachments before trying again.";
let count = 0;

function setup(lang, doctype) {
    const b = browser(lang);
    b.route = ["Form", doctype, "MOCK-INVOICE"];
    b.context.frappe.get_route = () => b.route;
    b.context.cur_frm = b.frm;
    b.frm.doc = { name: "MOCK-INVOICE", doctype, total: 8.7 };
    b.dirty = false;
    b.frm.is_dirty = () => b.dirty;
    b.docinfo = { attachments: [{ name: "ORIGINAL", file_name: "issued.xml" }] };
    b.frm.get_docinfo = () => b.docinfo;
    b.updates = [];
    b.frm.attachments = { update_attachment(value) {
        b.updates.push(value);
        if (!b.docinfo.attachments.some(item => item.name === value.name)) b.docinfo.attachments.push(value);
    } };
    b.frm.reload_doc = b.frm.save = b.frm.set_value = () => { assert.fail("No invoice reload/save/write"); };
    b.context.frappe.call = options => {
        assert.match(options.method, /\.(?:pos_debug_xml|debug_xml)\.debug_call$/);
        assert.deepEqual(Object.keys(options.args), ["invoice_number"]);
        assert.equal(options.args.invoice_number, "MOCK-INVOICE");
        b.calls.push(options);
        return new Promise((resolve, reject) => { b.resolve = resolve; b.reject = reject; });
    };
    b.run = () => vm.runInContext("zatca_run_debug(cur_frm)", b.context, { timeout: 1000 });
    b.result = () => ({ status: "success", message: "Debug XML attached successfully.",
        file_name: "DEBUG_INVOICE_MOCK.xml", notices: [], attachment: {
            name: "MOCK-FILE", file_name: "DEBUG_INVOICE_MOCK.xml", is_private: 1,
            file_url: "/private/files/DEBUG_INVOICE_MOCK.xml", attached_to_doctype: doctype,
            attached_to_name: "MOCK-INVOICE", ignored_extra: "not exported to attachments"
        } });
    b.notice = key => {
        assert.equal(b.dialogs.length, 1);
        assert.equal(b.dialogs[0].indicator, "orange");
        assert.ok(b.dialogs[0].message.includes(lang === "ar" ? catalog.get(key) : key), key);
    };
    b.finish = async task => {
        const response = b.result();
        const original = JSON.stringify(response);
        b.resolve({ message: response });
        assert.equal(await task, response, "Return untouched original response");
        assert.equal(JSON.stringify(response), original);
    };
    return b;
}

async function main() {
    for (const lang of ["en", "ar"]) {
        for (const doctype of ["Sales Invoice", "POS Invoice"]) {
            for (const mode of ["dirty", "local", "unknown-dirty"]) {
                const b = setup(lang, doctype);
                if (mode === "dirty") b.dirty = true;
                if (mode === "local") b.frm.doc.__islocal = true;
                if (mode === "unknown-dirty") delete b.frm.is_dirty;
                await b.run();
                assert.equal(b.calls.length, 0);
                assert.equal(b.updates.length, 0);
                b.notice(save);
                count++;
            }
            for (const change of ["route", "doctype", "name", "doc-object", "active-form"]) {
                const b = setup(lang, doctype);
                if (change === "route") b.route = ["List", doctype];
                if (change === "doctype") b.frm.doc.doctype = "Company";
                if (change === "name") b.frm.doc.name = "OTHER";
                if (change === "doc-object") b.frm.doc = {};
                if (change === "active-form") b.context.cur_frm = {};
                // Capture original form even if the active form has changed.
                b.context.original_frm = b.frm;
                await vm.runInContext("zatca_run_debug(original_frm)", b.context);
                assert.equal(b.calls.length, 0);
                b.notice(inactive);
                count++;
            }
            {
                const b = setup(lang, doctype);
                const task = b.run();
                assert.equal(b.run(), task, "Coalesce concurrent clicks, not later deliberate operations");
                b.frm.doc.total = 99;
                b.frm.doc.note = "keep unsaved edit";
                b.dirty = true;
                await b.finish(task);
                assert.equal(b.calls.length, 1);
                assert.equal(b.updates.length, 1);
                assert.equal(b.docinfo.attachments[0].name, "ORIGINAL");
                assert.equal(b.docinfo.attachments.length, 2);
                assert.deepEqual(Object.keys(b.updates[0]).sort(), ["file_name", "file_url", "is_private", "name"]);
                assert.equal(b.frm.doc.total, 99);
                assert.equal(b.frm.doc.note, "keep unsaved edit");
                b.notice(dirty);
                count++;
            }
            for (const change of ["route", "doctype", "name", "doc-object", "active-form"]) {
                const b = setup(lang, doctype);
                const task = b.run();
                if (change === "route") b.route = ["Form", doctype, "OTHER"];
                if (change === "doctype") b.frm.doc.doctype = "Company";
                if (change === "name") b.frm.doc.name = "OTHER";
                if (change === "doc-object") b.frm.doc = { ...b.frm.doc };
                if (change === "active-form") b.context.cur_frm = {};
                await b.finish(task);
                assert.equal(b.updates.length, 0);
                assert.ok(b.dialogs[0].message.includes("MOCK-INVOICE"));
                b.notice(moved);
                count++;
            }
            for (const fault of ["missing", "external", "javascript", "public", "traversal", "dot", "empty",
                "privacy", "parent", "doctype", "filename", "id", "control", "id-path", "id-markup", "id-unicode", "long-url", "no-api",
                "no-docinfo", "no-array", "throw", "reject", "id-newline", "url-newline"]) {
                const b = setup(lang, doctype);
                const task = b.run();
                const response = b.result();
                const a = response.attachment;
                if (fault === "missing") delete response.attachment;
                if (fault === "external") a.file_url = "https://example.invalid/private/files/a.xml";
                if (fault === "javascript") a.file_url = "javascript:alert(1)";
                if (fault === "public") a.file_url = "/files/a.xml";
                if (fault === "traversal") a.file_url = "/private/files/../a.xml";
                if (fault === "dot") a.file_url = "/private/files/..";
                if (fault === "empty") a.file_url = "/private/files/";
                if (fault === "privacy") a.is_private = "1";
                if (fault === "parent") a.attached_to_name = "OTHER";
                if (fault === "doctype") a.attached_to_doctype = "Company";
                if (fault === "filename") a.file_name = "OTHER.xml";
                if (fault === "id") a.name = "";
                if (fault === "control") a.name = "BAD\nNAME";
                if (fault === "id-path") a.name = "../OTHER";
                if (fault === "id-markup") a.name = 'BAD"><img src=x onerror=alert(1)>';
                if (fault === "id-unicode") a.name = "ملف";
                if (fault === "id-newline") a.name = "MOCK-FILE\n";
                if (fault === "url-newline") a.file_url += "\n";
                if (fault === "long-url") a.file_url = "/private/files/" + "a".repeat(2048);
                if (fault === "no-api") delete b.frm.attachments;
                if (fault === "no-docinfo") delete b.frm.get_docinfo;
                if (fault === "no-array") b.docinfo.attachments = null;
                if (fault === "throw") b.frm.attachments.update_attachment = () => { throw Error("UI failure"); };
                if (fault === "reject") b.frm.attachments.update_attachment = () => Promise.reject(Error("UI failure"));
                const original = JSON.stringify(response);
                b.resolve({ message: response });
                await task;
                assert.equal(b.calls.length, 1, "No automatic regeneration or metadata lookup");
                assert.equal(b.updates.length, 0);
                assert.equal(JSON.stringify(response), original);
                assert.equal(b.frm.doc.total, 8.7);
                b.notice(manual);
                count++;
            }
            for (const framework of [false, true]) {
                const b = setup(lang, doctype);
                const task = b.run();
                if (framework) b.dialogs.push({ message: "Framework-owned error" });
                b.reject(framework ? { status: 403 } : { status: 0 });
                await task;
                assert.equal(b.dialogs.length, 1);
                assert.equal(b.updates.length, 0);
                if (!framework) assert.equal(b.dialogs[0].message, lang === "ar" ? catalog.get(uncertain) : uncertain);
                const next = b.run();
                assert.notEqual(next, task, "Explicit next operation releases pending lock");
                b.resolve({ message: { status: "skipped", message: "ZATCA E-Invoicing is disabled for this Company. No debug XML was generated." } });
                await next;
                assert.equal(b.calls.length, 2);
                count++;
            }
            {
                const b = setup(lang, doctype);
                await b.finish(b.run());
                await b.finish(b.run());
                assert.equal(b.calls.length, 2);
                assert.equal(b.dialogs.length, 2);
                assert.equal(b.docinfo.attachments.length, 2, "Standard attachment update deduplicates by File name");
                assert.equal(b.frm.doc.total, 8.7);
                count++;
            }
        }
    }
    console.log("Debug UI lifecycle: " + count + " synthetic cases passed");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
