/* Read-only form lifecycle in a synthetic VM; no browser/site/HTTP claim. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { catalog } = require("./test_company_compliance_messages.js");
const source = fs.readFileSync(path.resolve(__dirname, "../../public/js/native_publication.js"), "utf8");
const uuid = "10000000-0000-4000-8000-000000000001";
const review = "The saved ZATCA document cannot be displayed or printed safely. Review its issuance, response and saved invoice data. No document was regenerated or sent.";
const save = "Save or discard invoice changes before viewing the issued ZATCA document.";
const pending = "Generated document; ZATCA acceptance is not confirmed.";
const accepted = "ZATCA acceptance is confirmed by the saved response.";
let count = 0;

function setup(lang, doctype) {
    const result = { calls: [], sections: [], buttons: new Map(), opened: [], handlers: [], dirty: false };
    function element() {
        return { children: [], attrs: {}, textValue: "", addClass() { return this; },
            text(value) { this.textValue = value; return this; },
            attr(value) { Object.assign(this.attrs, value); return this; },
            appendTo(parent) { parent.children.push(this); return this; } };
    }
    const translate = key => {
        if (lang === "ar") { assert.ok(catalog.has(key), key); return catalog.get(key); }
        return key;
    };
    const frm = { doc: { doctype, name: "INV / هيئة & ?", modified: "v1", docstatus: 1,
            custom_uuid: uuid, custom_zatca_icv: "1", custom_zatca_issuing_unit: "egs:" + uuid },
        is_dirty: () => result.dirty, toggle_display(field, visible) {
            assert.equal(field, "ksa_einv_qr"); this.fields_dict[field].df.hidden = !visible;
        },
        fields_dict: { ksa_einv_qr: { df: { hidden: false } } },
        set_value() { assert.fail("No form field write"); }, save() { assert.fail("No form save"); },
        reload_doc() { assert.fail("No form reload"); },
        add_custom_button(label, callback) { result.buttons.set(label, callback); },
        remove_custom_button(label) { result.buttons.delete(label); },
        $wrapper: { off() { return this; }, on(event, callback) {
            assert.equal(event, "dirty.zatca_native_publication"); result.onDirty = callback; return this;
        } },
        dashboard: { add_section(body, label, cssClass) {
            assert.equal(cssClass, "native-zatca-publication");
            const section = { body, label, removed: false, closest(selector) {
                assert.equal(selector, ".native-zatca-publication"); return { remove: () => { section.removed = true; } };
            } };
            result.sections.push(section); return section;
        } }
    };
    result.route = ["Form", doctype, frm.doc.name];
    const frappe = { ui: { form: { on(dt, handlers) { result.handlers.push([dt, handlers]); } } },
        get_route: () => result.route,
        call(options) {
            assert.equal(options.type, "GET");
            assert.equal(options.method, "zatca_erpgulf.zatca_erpgulf.native_publication.preview");
            assert.deepEqual(Object.keys(options.args), ["doctype", "invoice_name"]);
            result.calls.push(options);
            return new Promise((resolve, reject) => { result.resolve = resolve; result.reject = reject; });
        } };
    const context = vm.createContext({ frappe, cur_frm: frm, __: translate, $: element,
        window: { open(...args) { result.opened.push(args); } } });
    vm.runInContext(source, context);
    vm.runInContext(source, context);
    assert.equal(result.handlers.length, 2, "Register once per doctype across repeated asset loads");
    result.context = context; result.frm = frm; result.t = translate;
    result.run = () => frappe.zatca_native_publication.refresh(frm);
    result.ready = (accepted = false) => ({ status: "READY", issuance_id: uuid,
        accepted, state: accepted ? "REPORTED" : "PREPARED", source_kind: "SIMPLIFIED_GENERATED_XML",
        qr_data_uri: "data:image/png;base64,iVBORw0KGgo=", message: "IGNORED SERVER HTML <script>" });
    result.visible = () => result.sections.filter(row => !row.removed);
    result.text = () => result.visible().map(row => row.body.children[0].textValue);
    return result;
}

async function main() {
    for (const lang of ["en", "ar"]) for (const doctype of ["Sales Invoice", "POS Invoice"]) {
        for (const confirmed of [false, true]) {
            const b = setup(lang, doctype), original = JSON.stringify(b.frm.doc);
            const task = b.run(); b.resolve({ message: b.ready(confirmed) }); await task;
            assert.deepEqual(b.text(), [b.t(confirmed ? accepted : pending)]);
            assert.equal(b.visible()[0].body.children[1].attrs.src, b.ready().qr_data_uri);
            assert.equal(JSON.stringify(b.frm.doc), original);
            for (const [label, method] of [["Download issued ZATCA XML", "download_xml"],
                ["Download original ZATCA XML", "download_original"]]) {
                b.buttons.get(b.t(label))();
                const opened = b.opened.at(-1);
                const url = new URL(opened[0], "https://fictional.invalid");
                assert.equal(url.pathname, "/api/method/zatca_erpgulf.zatca_erpgulf.native_publication." + method);
                assert.equal(url.searchParams.get("invoice_name"), b.frm.doc.name);
                assert.equal(url.searchParams.get("issuance_id"), uuid);
                assert.equal(opened[2], "noopener");
            }
            b.dirty = true; b.onDirty();
            assert.deepEqual(b.text(), [b.t(save)]);
            assert.equal(b.buttons.size, 0);
            count++;
        }
        for (const mutation of ["legacy", "dirty", "local", "unknown-dirty"]) {
            const b = setup(lang, doctype);
            if (mutation === "legacy") b.frm.doc.custom_zatca_issuing_unit = "LEGACY";
            if (mutation === "dirty") b.dirty = true;
            if (mutation === "local") b.frm.doc.__islocal = true;
            if (mutation === "unknown-dirty") delete b.frm.is_dirty;
            await b.run(); assert.equal(b.calls.length, 0);
            assert.deepEqual(b.text(), mutation === "legacy" ? [] : [b.t(save)]);
            count++;
        }
        for (const change of ["route", "active-form", "doc-object", "name", "uuid", "icv", "marker", "modified", "dirty"]) {
            const b = setup(lang, doctype), task = b.run();
            if (change === "route") b.route = ["List", doctype];
            if (change === "active-form") b.context.cur_frm = {};
            if (change === "doc-object") b.frm.doc = { ...b.frm.doc };
            if (change === "name") b.frm.doc.name = "OTHER";
            if (change === "uuid") b.frm.doc.custom_uuid = "OTHER";
            if (change === "icv") b.frm.doc.custom_zatca_icv = "2";
            if (change === "marker") b.frm.doc.custom_zatca_issuing_unit = "OTHER";
            if (change === "modified") b.frm.doc.modified = "v2";
            if (change === "dirty") b.dirty = true;
            b.resolve({ message: b.ready() }); await task;
            assert.equal(b.visible().length, 0);
            assert.equal(b.opened.length, 0);
            count++;
        }
        for (const fault of ["reject", "missing", "review", "uri", "id", "state", "accepted", "kind"]) {
            const b = setup(lang, doctype), task = b.run(), result = b.ready();
            if (fault === "uri") result.qr_data_uri = "javascript:PRIVATE";
            if (fault === "id") result.issuance_id = "../PRIVATE";
            if (fault === "state") result.state = "REJECTED";
            if (fault === "accepted") result.accepted = true;
            if (fault === "kind") result.source_kind = "STANDARD_CLEARED_XML";
            if (fault === "review") result.status = "REVIEW";
            if (fault === "reject") b.reject(new Error("PRIVATE-DRIVER"));
            else b.resolve(fault === "missing" ? {} : { message: result });
            await task;
            assert.deepEqual(b.text(), [b.t(review)]);
            assert.equal(b.visible()[0].body.children.length, 1);
            assert.equal(b.opened.length, 0);
            count++;
        }
        // A late older request must not replace a newer form preview.
        const b = setup(lang, doctype), old = b.run(), oldResolve = b.resolve;
        const current = b.run(); b.resolve({ message: b.ready(true) }); await current;
        oldResolve({ message: b.ready(false) }); await old;
        assert.deepEqual(b.text(), [b.t(accepted)]); count++;
        b.frm.doc.custom_zatca_issuing_unit = "LEGACY";
        await b.run();
        assert.equal(b.frm.fields_dict.ksa_einv_qr.df.hidden, false);
        assert.equal(b.visible().length, 0); count++;
    }
    console.log(`${count} native publication UI cases passed (synthetic VM only).`);
}
main().catch(error => { console.error(error); process.exitCode = 1; });
