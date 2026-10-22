/* Real menu callbacks + shared presenter, inside a network-free synthetic VM. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { browser, catalog, escape } = require("./test_company_compliance_messages.js");

const raw = 'Original {"code":"mock-error","request_id":"unchanged"} هيئة <script>alert(1)</script>';
const created = "Debug XML attached successfully.";
const failed = "Debug XML generation failed. See technical details.";
const skipped = "Debug XML was skipped for an intra-company transfer. The invoice was not changed.";
const disabled = "ZATCA E-Invoicing is disabled for this Company. No debug XML was generated.";
const local = "ZATCA E-Invoicing is disabled for this Company. Debug XML will be generated locally only; no submission will be performed.";
const existing = "Existing XML/QR was found. A separate debug XML will be generated.";
const denied = "You do not have permission to create a debug XML attachment for this invoice.";
const review = "Debug XML attachment could not be confirmed. Review the source and existing files before retrying.";
const cases = [
    [{ status: "success", message: created, file_name: "DEBUG_INVOICE_MOCK.xml", notices: [] }, "green"],
    [{ status: "success", message: created, file_name: "DEBUG_INVOICE_<img>.xml", notices: [local, local, existing] }, "orange"],
    [{ status: "skipped", message: skipped, notices: [] }, "orange"],
    [{ status: "skipped", message: disabled, notices: [] }, "orange"],
    [{ status: "error", message: failed, technical_details: raw, notices: [] }, "red"],
    [{ status: "error", message: failed, technical_details: raw, notices: [raw, raw, existing] }, "red"],
    [{ status: "error", message: failed, technical_details: denied, notices: [denied] }, "red"],
    [{ status: "error", message: failed, technical_details: review, notices: [review] }, "red"],
    [null, "red"], [undefined, "red"], [{}, "red"], ["unexpected", "red"],
    [{ status: "success", message: created }, "red"],
    [{ status: "skipped", message: raw }, "red"]
];
let count = 0;

async function main() {
for (const [doctype, file, method] of [
    ["Sales Invoice", "our_sales_invoice.js", "zatca_erpgulf.zatca_erpgulf.debug_xml.debug_call"],
    ["POS Invoice", "our_pos_invoice.js", "zatca_erpgulf.zatca_erpgulf.pos_debug_xml.debug_call"]
]) {
    const source = fs.readFileSync(path.resolve(__dirname, "../../public/js", file), "utf8");
    // Compile the complete source, evaluate only the actual Debug menu registration.
    new vm.Script(source);
    const anchor = source.lastIndexOf("frappe.ui.form.on('" + doctype + "', {");
    assert.ok(anchor >= 0);
    for (const lang of ["en", "ar"]) {
        for (const [original, indicator] of cases) {
            const response = original && typeof original === "object" ? { ...original } : original;
            if (response && response.status === "success" && response.file_name) {
                response.attachment = { name: "MOCK-FILE", file_name: response.file_name,
                    file_url: "/private/files/DEBUG_INVOICE_MOCK.xml", is_private: 1,
                    attached_to_doctype: doctype, attached_to_name: "MOCK-INVOICE" };
            }
            const b = browser(lang);
            let refresh, menu, calls = 0;
            const before = JSON.stringify(response);
            b.frm.doc = { name: "MOCK-INVOICE", doctype };
            b.frm.is_new = () => false;
            b.context.cur_frm = b.frm;
            b.context.frappe.get_route = () => ["Form", doctype, "MOCK-INVOICE"];
            b.frm.get_docinfo = () => ({ attachments: [] });
            b.frm.attachments = { update_attachment() { b.events.push("attachment"); } };
            b.frm.page = { add_menu_item(label, callback) { menu = callback; } };
            b.context.frappe.ui.form.on = (registered, handlers) => {
                assert.equal(registered, doctype);
                refresh = handlers.refresh;
            };
            b.context.frappe.call = options => {
                if (options.method.endsWith("get_qr_regeneration_state")) return;
                calls++;
                assert.equal(options.method, method);
                assert.equal(options.args.invoice_number, "MOCK-INVOICE");
                assert.equal(options.freeze, true);
                return Promise.resolve({ message: response });
            };
            vm.runInContext(source.slice(anchor), b.context, { timeout: 1000 });
            refresh(b.frm);
            assert.equal(typeof menu, "function");
            await menu();
            assert.equal(calls, 1);
            assert.equal(b.dialogs.length, 1);
            assert.equal(b.dialogs[0].indicator, indicator);
            assert.ok(!b.events.includes("reload"), "Debug never reloads the invoice");
            assert.equal(b.events.filter(event => event === "attachment").length,
                response && response.status === "success" && response.file_name ? 1 : 0);
            assert.equal(b.dialogs[0].title, lang === "ar" ? "نتيجة إنشاء XML للفحص التقني" : "Debug XML Result");
            assert.equal(JSON.stringify(response), before, "Display does not translate/mutate stored values");
            assert.ok(!b.translated.includes(raw));
            assert.ok(!b.dialogs[0].message.includes("<script>"));
            assert.ok(!b.dialogs[0].message.includes("<img>"));
            if (response && response.technical_details) {
                assert.equal((b.dialogs[0].message.match(/<details>/g) || []).length, 1);
                assert.ok(b.dialogs[0].message.includes(escape(response.technical_details)));
            }
            if (lang === "ar") {
                assert.ok(b.dialogs[0].message.includes("عملية فحص تقني محلية"));
                if (response && response.message === created && response.file_name) {
                    assert.ok(b.dialogs[0].message.includes(catalog.get(created)));
                }
                if (response && response.notices && response.notices.includes(denied)) {
                    assert.ok(b.dialogs[0].message.includes(catalog.get(denied)));
                }
                if (response && response.notices && response.notices.includes(review)) {
                    assert.ok(b.dialogs[0].message.includes(catalog.get(review)));
                }
            }
            count++;
        }
        const b = browser(lang);
        b.frm.doc = { name: "MOCK-INVOICE", doctype };
        b.context.cur_frm = b.frm;
        b.context.frappe.get_route = () => ["Form", doctype, "MOCK-INVOICE"];
        b.context.frappe.msgprint({ message: "Framework-owned validation/session error" });
        b.context.frappe.ui.form.on = (registered, handlers) => { b.refresh = handlers.refresh; };
        b.frm.is_new = () => false;
        b.frm.page = { add_menu_item(label, callback) { b.menu = callback; } };
        b.context.frappe.call = options => {
            if (!options.method.endsWith("get_qr_regeneration_state")) return Promise.resolve({ exc: "mock server error" });
        };
        vm.runInContext(source.slice(anchor), b.context, { timeout: 1000 });
        b.refresh(b.frm);
        await b.menu();
        assert.equal(b.dialogs.length, 1, "Framework error must not add an unconfirmed summary");
        count++;
    }
}
console.log("Debug messages: " + count + " synthetic cases passed");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
