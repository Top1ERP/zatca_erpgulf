/* Synthetic browser VM only: no network, Frappe runtime, site or customer. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.resolve(__dirname, "../../public/js/company.js"), "utf8");
const shared = fs.readFileSync(path.resolve(__dirname, "../../public/js/operation_messages.js"), "utf8");
const csv = fs.readFileSync(path.resolve(__dirname, "../../translations/ar.csv"), "utf8");
// CSV quoted commas/escaped quotes/newlines must not break translation lookup.
function parseCSV(text) {
    const rows = [];
    let row = [], cell = "", quoted = false;
    for (let i = 0; i < text.length; i++) {
        const c = text[i];
        if (c === '"') {
            if (quoted && text[i + 1] === '"') { cell += '"'; i++; }
            else quoted = !quoted;
        } else if (!quoted && (c === ',' || c === '\n')) {
            row.push(cell); cell = "";
            if (c === '\n') { rows.push(row); row = []; }
        } else if (c !== '\r') cell += c;
    }
    if (cell || row.length) { row.push(cell); rows.push(row); }
    return rows;
}
const catalog = new Map(parseCSV(csv));
const kinds = ["Simplified Invoice", "Standard Invoice", "Simplified Credit Note",
    "Standard Credit Note", "Simplified Debit Note", "Standard Debit Note"];
const raw = 'ERROR signed-properties-hashing {"message":"UNCHANGED هيئة","request_id":"mock-id"} <script>alert(1)</script>';
let count = 0;
const escape = value => String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");

function browser(lang = "en") {
    const dialogs = [], translated = [], calls = [], events = [];
    let handlers, reply = {}, rejection, reloadError;
    const frappe = {
        realtime: { on() {} }, ui: { form: { on(doctype, value) { handlers = value; } } },
        utils: { escape_html: escape }, msgprint(value) { dialogs.push(value); },
        dom: { freeze() { events.push("freeze"); }, unfreeze() { events.push("unfreeze"); } },
        confirm(message, yes) { yes(); },
        async call(options) {
            assert.match(options.method, /^zatca_erpgulf\.zatca_erpgulf\.sign_invoice(?:_first)?\./);
            calls.push(options);
            if (rejection) {
                if (rejection.framework) dialogs.push({ message: "Framework-owned error" });
                throw rejection.error;
            }
            return { message: reply };
        }
    };
    const context = vm.createContext({ frappe, console, __(key) {
        translated.push(key);
        return lang === "ar" ? catalog.get(key) || key : key;
    }});
    vm.runInContext(shared + "\n" + source, context, { timeout: 1000 });
    const frm = {
        doc: { name: "FICTIONAL COMPANY", doctype: "Company", abbr: "FC",
            modified: "2026-10-23 09:00:00", custom_select: "Production",
            custom_sample_invoice_number_to_test: "SYNTHETIC-INVOICE" },
        is_dirty() { return false; },
        async save() { throw new Error("Batch must not save Company"); },
        async reload_doc() { events.push("reload"); if (reloadError) throw reloadError; }
    };
    frappe.get_route = () => ["Form", frm.doc.doctype, frm.doc.name];
    context.cur_frm = frm;
    return { context, dialogs, translated, calls, events, frm, handlers,
        reply(value) { reply = value; },
        reject(error, framework = false) { rejection = { error, framework }; },
        reloadFail() { reloadError = new Error("mock reload fault"); }
    };
}

async function main() {
    for (const lang of ["en", "ar"]) {
        for (const automatic of [false, true]) {
            for (const failures of [0, 1, 6]) {
                const b = browser(lang);
                const response = {
                    results: kinds.map((type, index) => ({ type,
                        status: index < failures ? "FAIL" : "PASS",
                        message: index < failures ? "Compliance check failed. See technical details." : "Completed successfully.",
                        ...(index < failures ? { technical_details: raw } : {}) })),
                    all_passed: failures === 0
                };
                const original = JSON.stringify(response);
                b.reply(response);
                await b.handlers[automatic ? "custom_run_zatca_onboarding_checks" : "custom_run_all_compliance"](b.frm);
                assert.equal(b.dialogs.length, 1);
                assert.equal(b.calls.length, 1);
                assert.equal(b.dialogs[0].indicator, failures ? "red" : "green");
                assert.equal(JSON.stringify(response), original, "Presentation never rewrites English/raw data");
                assert.equal(b.events.at(-1), "unfreeze");
                assert.ok(!b.events.includes("reload"), "Batch must not discard unsaved Company fields");
                assert.equal((b.dialogs[0].message.match(/<details>/g) || []).length, failures ? 1 : 0);
                assert.ok(!b.translated.includes(raw));
                assert.ok(!b.dialogs[0].message.includes("<script>"));
                if (failures) assert.ok(b.dialogs[0].message.includes(escape(raw)));
                if (lang === "ar") {
                    assert.ok(b.dialogs[0].message.includes("فاتورة مبسطة"));
                    if (failures < 6) assert.ok(b.dialogs[0].message.includes("ناجح"));
                    if (failures) assert.ok(b.dialogs[0].message.includes("فشل فحص الامتثال"));
                }
                count++;
            }
        }
        for (const status of [401, 403, 404, 413, 417, 500, 502, 504, 508]) {
            for (const action of ["custom_run_all_compliance", "custom_run_zatca_onboarding_checks", "custom_generate_compliance_csid", "custom_check_compliance"]) {
                const b = browser(lang);
                b.reject({ status, responseJSON: { _server_messages: '["Original error"]' } }, true);
                await b.handlers[action](b.frm);
                assert.equal(b.dialogs.length, 1, "Do not duplicate the framework dialog");
                assert.equal(b.calls.length, 1, "Exercise the RPC, not a form guard");
                count++;
            }
        }
        for (const error of [new Error("raw internal failure"), {}, { status: 0 }, { status: 417 }]) {
            const b = browser(lang);
            b.reject(error);
            await b.handlers.custom_run_all_compliance(b.frm);
            assert.equal(b.dialogs.length, 1);
            assert.ok(!b.dialogs[0].message.includes("[object Object]"));
            assert.ok(!b.dialogs[0].message.includes("raw internal failure"));
            if (lang === "ar") assert.ok(b.dialogs[0].message.includes("تعذّر إكمال العملية"));
            count++;
        }
        const b = browser(lang);
        b.reply({ results: kinds.map(type => ({ type, status: "PASS", message: "Already completed by ZATCA; treated as PASS." })), all_passed: true });
        await b.handlers.custom_run_zatca_onboarding_checks(b.frm);
        assert.equal(b.dialogs.length, 1);
        assert.equal(b.dialogs[0].indicator, "green");
        assert.ok(b.dialogs[0].message.includes(lang === "ar" ? "اكتمل مسبقًا" : "Already completed"));
        count++;
    }
    for (const results of [undefined, [], [null], ["unexpected"], kinds.map(() => ({ type: kinds[0], status: "PASS" }))]) {
        const b = browser();
        b.reply({ results, all_passed: true });
        await b.handlers.custom_run_zatca_onboarding_checks(b.frm);
        assert.equal(b.dialogs.length, 1);
        assert.equal(b.dialogs[0].indicator, "red");
        assert.ok(!b.dialogs[0].message.includes("You may now use Generate Final CSID"));
        count++;
    }
    for (const lang of ["en", "ar"]) {
        const b = browser(lang);
        const validation = { status: "WARNING", warningMessages: [{ code: "MOCK-WARNING", message: raw }] };
        const reply = { results: kinds.map(type => ({ type, status: "PASS", message: "Completed with warnings. See technical details.",
            validation_details: validation })), all_passed: true };
        const original = JSON.stringify(reply);
        b.reply(reply);
        await b.handlers.custom_run_zatca_onboarding_checks(b.frm);
        assert.equal(b.dialogs.length, 1);
        assert.equal(b.dialogs[0].indicator, "orange");
        assert.equal((b.dialogs[0].message.match(/<details>/g) || []).length, 1);
        assert.ok(b.dialogs[0].message.includes(escape(JSON.stringify(validation, null, 2))));
        assert.ok(b.dialogs[0].message.includes(lang === "ar" ? "وجود تحذيرات" : "Completed with warnings"));
        assert.equal(JSON.stringify(reply), original);
        assert.ok(!b.translated.includes(raw));
        count++;
    }
    for (const lang of ["en", "ar"]) {
        for (const failed of [false, true]) {
            const b = browser(lang);
            const response = { single_check: true, results: [{ type: "Standard Invoice", status: failed ? "FAIL" : "PASS",
                message: failed ? "Compliance check failed. See technical details." : "Completed successfully.",
                ...(failed ? { technical_details: raw } : {}) }] };
            b.reply(response);
            await b.handlers.custom_check_compliance(b.frm);
            assert.equal(b.dialogs.length, 1);
            assert.equal(b.dialogs[0].indicator, failed ? "red" : "green");
            assert.equal(b.dialogs[0].title, lang === "ar" ? "نتيجة فحص الامتثال" : "Compliance Check Result");
            assert.deepEqual(Object.keys(b.calls[0].args).sort(), ["company_name", "invoice_number"]);
            assert.ok(!b.events.includes("reload"));
            assert.ok(!b.dialogs[0].message.includes("You may now use Generate Final CSID"));
            assert.ok(!b.translated.includes(raw));
            count++;
        }
        const b = browser(lang);
        b.frm.doc.custom_sample_invoice_number_to_test = "";
        await b.handlers.custom_check_compliance(b.frm);
        assert.equal(b.dialogs.length, 1);
        assert.equal(b.calls.length, 0);
        count++;
    }
    const b = browser();
    b.reply({ results: kinds.map(type => ({ type, status: "PASS", message: "Completed successfully." })) });
    b.reloadFail();
    await b.handlers.custom_run_all_compliance(b.frm);
    assert.equal(b.dialogs.length, 1, "Batch needs no Company reload/save");
    assert.equal(b.dialogs[0].indicator, "green");
    assert.ok(!b.events.includes("reload"));
    count++;
    console.log("Company compliance messages: " + count + " synthetic cases passed");
}

module.exports = { browser, catalog, escape };
if (require.main === module) {
    main().catch(error => { console.error(error); process.exitCode = 1; });
}
