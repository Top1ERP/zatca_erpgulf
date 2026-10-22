/* Success presentation only: synthetic wizard callbacks, no site or network. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { browser, catalog } = require("./test_company_compliance_messages.js");
const wizard = fs.readFileSync(path.resolve(__dirname,
    "../page/setup_zatca_phase_2/setup_zatca_phase_2.js"), "utf8");
new vm.Script(wizard);
const privateBody = '{"binarySecurityToken":"PRIVATE-TOKEN","secret":"PRIVATE-SECRET","requestID":"PRIVATE-REQUEST"}';
const review = "CSID creation was not confirmed. Review saved settings before trying again.";
let count = 0;

for (const lang of ["en", "ar"]) {
    for (const production of [false, true]) {
        const purpose = production ? "production" : "compliance";
        const message = production ? "Final CSID generated and saved successfully." :
            "Compliance CSID generated and saved successfully.";
        const good = { status: "SUCCESS", purpose, message };
        const cases = [
            [good, true], [JSON.stringify(good), true],
            [{ ...good, secret: "PRIVATE-SECRET" }, true],
            [privateBody, false], ["PRIVATE-SECRET", false], ["{", false],
            [null, false], [undefined, false], ["", false], [[], false], [true, false],
            [{ ...good, purpose: production ? "compliance" : "production" }, false],
            [{ ...good, status: "ERROR" }, false], [{ ...good, status: "success" }, false],
            [{ ...good, message: "PRIVATE-SECRET" }, false], [{ status: "SUCCESS" }, false],
            [JSON.stringify({ ...good, message: privateBody }), false]
        ];
        for (const [value, valid] of cases) {
            const b = browser(lang);
            b.context.value = value;
            b.context.production = production;
            const before = JSON.stringify(value);
            const result = vm.runInContext("zatca_csid_result_message(value, production)", b.context);
            const key = valid ? message : review;
            assert.equal(result, lang === "ar" ? catalog.get(key) : key);
            assert.ok(!result.includes("PRIVATE-"));
            assert.equal(JSON.stringify(value), before);
            assert.ok(!b.translated.includes(privateBody));
            assert.ok(!b.translated.includes("PRIVATE-SECRET"));
            assert.equal(b.calls.length, 0);
            assert.equal(b.dialogs.length, 0, "Server owns the one successful operation notice");
            count++;
        }
        // Evaluate each actual wizard callback without booting its page.
        const operation = production ? "production_csid" : "create_csid";
        const anchor = wizard.indexOf('method: "zatca_erpgulf.zatca_erpgulf.sign_invoice_first.' + operation + '"');
        assert.ok(anchor >= 0);
        const start = wizard.indexOf("callback: function (response)", anchor);
        const end = wizard.indexOf("});", start);
        assert.ok(start > anchor && end > start);
        for (const value of [JSON.stringify(good), privateBody, { ...good }]) {
            const b = browser(lang);
            const fields = [];
            b.context.current_dialog = { set_value(name, text) { fields.push([name, text]); }, refresh() {} };
            b.context.response = { message: value };
            const before = JSON.stringify(value);
            vm.runInContext("({" + wizard.slice(start, end) + "}).callback(response)", b.context);
            assert.equal(fields.length, 1);
            assert.equal(fields[0][0], production ? "final_auth_csid" : "basic_auth_from_csid");
            const key = value === privateBody ? review : message;
            assert.equal(fields[0][1], lang === "ar" ? catalog.get(key) : key);
            assert.ok(!fields[0][1].includes("PRIVATE-"));
            assert.equal(JSON.stringify(value), before);
            assert.equal(b.calls.length, 0);
            assert.equal(b.dialogs.length, 0);
            count++;
        }
    }
}
for (const label of ["Compliance CSID Result", "Final CSID Result"]) {
    assert.ok(wizard.includes('label: __("' + label + '"),\n\t\t\t\t\tfieldtype: "Long Text",\n\t\t\t\t\tread_only: 1'));
}
console.log("CSID success messages: " + count + " synthetic cases passed");
