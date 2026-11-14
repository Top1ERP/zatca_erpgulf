/* Complete template script in a synthetic VM; no transport or site. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { catalog } = require('./test_company_compliance_messages.js');
const source = fs.readFileSync(path.resolve(__dirname, '../../public/js/zatca_tax_template_validation.js'), 'utf8');
let count = 0;

function environment({ phase = 'Phase-2', enabled = 1, rules = 1, selected = false,
    category = 'Exempted', doctype = 'Item Tax Template', legacy = false, missingRules = false,
    language = 'en', getValue } = {}) {
    const handlers = {}, writes = [], properties = {}, visible = {}, queries = {}, calls = [];
    const context = vm.createContext({
        __(key) { return language === 'ar' ? catalog.get(key) || key : key; },
        cint(value) { return parseInt(value || 0, 10); },
        flt(value) { return Number(value || 0); },
        frappe: {
            ui: { form: { on(dt, value) { handlers[dt] = value; } } },
            model: { set_value(...args) { writes.push(args); } },
            db: { async get_value(dt, name, fields) {
                calls.push([dt, name, fields]);
                if (getValue) return getValue(dt, name, fields);
                if (Array.isArray(fields)) {
                    if (legacy && fields[1] === 'custom_phase_1_or_2') throw Error('Absent primary field');
                    return { message: { custom_zatca_invoice_enabled: enabled, [fields[1]]: phase } };
                }
                if (missingRules) throw Error('Optional rule field absent');
                return { message: { custom_enforce_zatca_tax_category_rate_validation: rules } };
            } }
        }
    });
    vm.runInContext(source, context, { timeout: 1000 });
    const frm = {
        doctype, doc: { doctype, company: 'COMPANY', custom_zatca_tax_category: category,
            custom_exemption_reason_code: category === 'Exempted' ? 'VATEX-SA-29' : '',
            custom_zatca_vat_account: selected ? 'VAT-15' : '',
            taxes: [{ doctype: 'Item Tax Template Detail', name: 'ROW', tax_type: 'VAT-15', tax_rate: 15, rate: 15 },
                    { doctype: 'Item Tax Template Detail', name: 'ZERO', tax_type: 'VAT-0', tax_rate: 0, rate: 0 }] },
        fields_dict: { custom_zatca_tax_category: {}, custom_exemption_reason_code: {},
            ...(doctype === 'Item Tax Template' ? { custom_zatca_vat_account: {} } : {}) },
        set_df_property(field, property, value) { properties[field + '.' + property] = value; },
        toggle_display(field, value) { visible[field] = Boolean(value); },
        set_query(field, query) { queries[field] = query; },
        set_value(field, value) { this.doc[field] = value; }
    };
    return { frm, context, handlers, writes, properties, visible, queries, calls };
}

async function main() {
    for (const phase of ['Phase-1', 'Phase-2', '', 'unknown']) {
    for (const enabled of [0, 1]) {
    for (const rules of [0, 1]) {
    for (const selected of [false, true]) {
    for (const category of ['Standard', 'Exempted', 'Zero Rated']) {
    for (const doctype of ['Item Tax Template', 'Sales Taxes and Charges Template']) {
    for (const language of ['en', 'ar']) {
        const e = environment({ phase, enabled, rules, selected, category, doctype, language });
        // Sales template has no selector, including in legacy fixture data.
        if (doctype !== 'Item Tax Template') delete e.frm.doc.custom_zatca_vat_account;
        await e.handlers[doctype].refresh(e.frm);
        const active = phase === 'Phase-2' && enabled === 1;
        assert.equal(e.visible.custom_zatca_tax_category, active);
        if (doctype === 'Item Tax Template') {
            assert.equal(e.visible.custom_zatca_vat_account, active);
            assert.equal(e.properties['custom_zatca_vat_account.reqd'], false);
            const filters = e.queries.custom_zatca_vat_account().filters;
            assert.equal(filters.company, 'COMPANY');
            assert.equal(filters.is_group, 0);
            assert.deepEqual(Array.from(filters.name[1]), ['VAT-15', 'VAT-0']);
            assert.equal(e.frm.doc.custom_zatca_vat_account, selected ? 'VAT-15' : '');
        }
        const expectedWrites = active && rules && category !== 'Standard'
            && !(doctype === 'Item Tax Template' && selected) ? 1 : 0;
        assert.equal(e.writes.length, expectedWrites);
        if (expectedWrites) assert.equal(e.writes[0][3], 0);
        // A category callback must preserve the same phase/rule/selection gate.
        e.writes.length = 0;
        e.handlers[doctype].custom_zatca_tax_category(e.frm);
        assert.equal(e.writes.length, expectedWrites);
        count++;
    }}}}}}}
    for (const legacy of [false, true]) {
    for (const missingRules of [false, true]) {
        const e = environment({ phase: ' Phase-2 ', legacy, missingRules });
        await e.handlers['Item Tax Template'].refresh(e.frm);
        assert.equal(e.visible.custom_zatca_vat_account, true);
        assert.equal(e.writes.length, missingRules ? 0 : 1);
        if (legacy) assert.ok(e.calls.some(call => Array.isArray(call[2]) && call[2][1] === 'phase_1_or_2'));
        // Link queries reflect later rows and current company; no stale capture.
        e.frm.doc.company = 'NEW-COMPANY';
        e.frm.doc.taxes = [{ tax_type: 'NEW-ACCOUNT' }];
        e.handlers['Item Tax Template Detail'].taxes_remove(e.frm);
        assert.equal(e.visible.custom_zatca_vat_account, false);
        const filters = e.queries.custom_zatca_vat_account().filters;
        assert.equal(filters.company, 'NEW-COMPANY');
        assert.deepEqual(Array.from(filters.name[1]), ['NEW-ACCOUNT']);
        count++;
    }}
    for (const staleOptional of [false, true]) {
        let resolveOld, rejectOld, enteredOld;
        const entered = new Promise(resolve => { enteredOld = resolve; });
        const pending = new Promise((resolve, reject) => { resolveOld = resolve; rejectOld = reject; });
        const e = environment({ selected: true, getValue(dt, name, fields) {
            if (name === 'COMPANY' && (staleOptional ? !Array.isArray(fields) : Array.isArray(fields))) { enteredOld(); return pending; }
            return Promise.resolve({ message: Array.isArray(fields)
                ? { custom_zatca_invoice_enabled: 1, [fields[1]]: name === 'NEW' ? 'Phase-1' : 'Phase-2' }
                : { custom_enforce_zatca_tax_category_rate_validation: 1 } });
        } });
        const older = e.handlers['Item Tax Template'].refresh(e.frm);
        await entered;
        e.frm.doc.company = 'NEW';
        await e.handlers['Item Tax Template'].company(e.frm);
        if (staleOptional) rejectOld(Error('Old optional lookup failed'));
        else resolveOld({ message: { custom_zatca_invoice_enabled: 1, custom_phase_1_or_2: 'Phase-2' } });
        await older;
        assert.equal(e.frm.__zatca_template_phase, 'Phase-1');
        assert.equal(e.visible.custom_zatca_vat_account, false);
        assert.equal(e.visible.custom_zatca_tax_category, false);
        assert.equal(e.writes.length, 0);
        count++;
    }
    for (const key of ['ZATCA VAT Account',
        'For a multi-row Item Tax Template, explicitly select the VAT account. Other rows must be zero overrides. Leave blank to retain legacy source selection.']) {
        assert.ok(/[\u0600-\u06ff]/.test(catalog.get(key)), key);
        count++;
    }
    console.log(`Template VAT UI checks passed: ${count}`);
}
main().catch(error => { console.error(error); process.exitCode = 1; });
