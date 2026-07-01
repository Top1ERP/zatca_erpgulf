(function () {
    const MODE_FIELD = "custom_zatca_negative_line_validation_mode";
    const ZATCA_ENABLED_FIELD = "custom_zatca_invoice_enabled";

    const MONETARY_FIELDS = [
        ["rate", "Rate"],
        ["amount", "Amount"],
        ["net_rate", "Net Rate"],
        ["net_amount", "Net Amount"],
        ["base_rate", "Base Rate"],
        ["base_amount", "Base Amount"],
        ["base_net_rate", "Base Net Rate"],
        ["base_net_amount", "Base Net Amount"],
    ];

    const RATE_FIELDS = [
        ["rate", "Rate"],
        ["net_rate", "Net Rate"],
        ["base_rate", "Base Rate"],
        ["base_net_rate", "Base Net Rate"],
    ];

    const COMPANY_SETTINGS_CACHE = {};
    const ROW_VALIDATION_TIMERS = {};
    const LAST_ALERT_KEY = {};

    function to_number(value) {
        const number_value = flt(value);
        return Number.isFinite(number_value) ? number_value : 0;
    }

    async function company_has_field(fieldname) {
        try {
            await frappe.model.with_doctype("Company");
            const meta = frappe.get_meta("Company");
            return (meta.fields || []).some((df) => df.fieldname === fieldname);
        } catch (e) {
            return false;
        }
    }

    async function load_company_settings(frm) {
        const company = frm.doc.company;

        if (!company) {
            frm.__zatca_negative_line_settings = {
                enabled: false,
                mode: "Disabled",
            };
            return frm.__zatca_negative_line_settings;
        }

        if (COMPANY_SETTINGS_CACHE[company]) {
            frm.__zatca_negative_line_settings = COMPANY_SETTINGS_CACHE[company];
            return frm.__zatca_negative_line_settings;
        }

        const has_enabled_field = await company_has_field(ZATCA_ENABLED_FIELD);
        const has_mode_field = await company_has_field(MODE_FIELD);

        if (!has_enabled_field) {
            COMPANY_SETTINGS_CACHE[company] = {
                enabled: false,
                mode: "Disabled",
            };
            frm.__zatca_negative_line_settings = COMPANY_SETTINGS_CACHE[company];
            return frm.__zatca_negative_line_settings;
        }

        const fields = [ZATCA_ENABLED_FIELD];

        if (has_mode_field) {
            fields.push(MODE_FIELD);
        }

        const response = await frappe.db.get_value("Company", company, fields);
        const values = response && response.message ? response.message : {};

        COMPANY_SETTINGS_CACHE[company] = {
            enabled: cint(values[ZATCA_ENABLED_FIELD]) === 1,
            mode: has_mode_field ? (values[MODE_FIELD] || "Strict") : "Disabled",
        };

        frm.__zatca_negative_line_settings = COMPANY_SETTINGS_CACHE[company];
        return frm.__zatca_negative_line_settings;
    }

    function get_cached_settings(frm) {
        return frm.__zatca_negative_line_settings || {
            enabled: false,
            mode: "Disabled",
        };
    }

    function is_enabled_strict(frm) {
        const settings = get_cached_settings(frm);
        return settings.enabled && settings.mode === "Strict";
    }

    function is_return_document(frm) {
        return cint(frm.doc.is_return) === 1;
    }

    function build_issue_line(row, field_label, value, detail) {
        const item_code_part = row.item_code ? `, Item ${row.item_code}` : "";
        const detail_part = detail ? ` ${detail}` : "";
        return `Row ${row.idx || ""}${item_code_part}, ${field_label}: ${value}.${detail_part}`;
    }

    function get_interactive_row_issues(frm, row, changed_fieldname) {
        const issues = [];
        const is_return = is_return_document(frm);
        const qty = to_number(row.qty);

        if (changed_fieldname === "qty") {
            if (is_return) {
                if (qty > 0) {
                    issues.push(
                        build_issue_line(
                            row,
                            "Quantity",
                            row.qty,
                            "Return / credit note item quantity must be zero or negative."
                        )
                    );
                }
            } else if (qty < 0) {
                issues.push(
                    build_issue_line(
                        row,
                        "Quantity",
                        row.qty,
                        "Standard invoice and debit note item quantity must be zero or greater."
                    )
                );
            }
        }

        if (is_return) {
            for (const [fieldname, field_label] of RATE_FIELDS) {
                if (changed_fieldname && fieldname !== changed_fieldname) {
                    continue;
                }

                const value = row[fieldname];

                if (to_number(value) < 0) {
                    issues.push(
                        build_issue_line(
                            row,
                            field_label,
                            value,
                            "Item rates must not be negative."
                        )
                    );
                }
            }
        }

        if (!is_return) {
            for (const [fieldname, field_label] of MONETARY_FIELDS) {
                if (changed_fieldname && fieldname !== changed_fieldname) {
                    continue;
                }

                const value = row[fieldname];

                if (to_number(value) < 0) {
                    issues.push(
                        build_issue_line(
                            row,
                            field_label,
                            value,
                            "Item rates, prices, and amounts must not be negative."
                        )
                    );
                }
            }
        }

        return issues;
    }

    function get_save_issues(frm) {
        const issues = [];
        const is_return = is_return_document(frm);

        for (const row of frm.doc.items || []) {
            const qty = to_number(row.qty);

            if (is_return) {
                if (qty > 0) {
                    issues.push(
                        build_issue_line(
                            row,
                            "Quantity",
                            row.qty,
                            "Return / credit note item quantity must be zero or negative."
                        )
                    );
                }

                for (const [fieldname, field_label] of RATE_FIELDS) {
                    const value = row[fieldname];

                    if (to_number(value) < 0) {
                        issues.push(
                            build_issue_line(
                                row,
                                field_label,
                                value,
                                "Item rates must not be negative."
                            )
                        );
                    }
                }

                continue;
            }

            if (qty < 0) {
                issues.push(
                    build_issue_line(
                        row,
                        "Quantity",
                        row.qty,
                        "Standard invoice and debit note item quantity must be zero or greater."
                    )
                );
            }

            for (const [fieldname, field_label] of MONETARY_FIELDS) {
                const value = row[fieldname];

                if (to_number(value) < 0) {
                    issues.push(
                        build_issue_line(
                            row,
                            field_label,
                            value,
                            "Item rates, prices, and amounts must not be negative."
                        )
                    );
                }
            }
        }

        return issues;
    }

    function build_save_message(frm, issues) {
        const shown_issues = issues.slice(0, 10);
        const more_count = issues.length - shown_issues.length;

        let issue_text = shown_issues.map((issue) => `- ${issue}`).join("<br>");

        if (more_count > 0) {
            issue_text += `<br>- ... and ${more_count} more invalid values.`;
        }

        return `
            <div>
                <p><b>ZATCA item line validation failed.</b></p>

                <p><b>For standard invoices and debit notes:</b></p>
                <ul>
                    <li>Item quantity must not be negative.</li>
                    <li>Item rates, prices, and amounts must not be negative.</li>
                    <li>Zero quantity and zero monetary values are allowed by this ZATCA validation layer.</li>
                </ul>

                <p><b>For returns / credit notes:</b></p>
                <ul>
                    <li>Item quantity must not be positive.</li>
                    <li>Item rates must not be negative.</li>
                    <li>Zero quantity is allowed by this ZATCA validation layer.</li>
                </ul>

                <p><b>${frm.doctype} ${frm.doc.name || "(new document)"} contains invalid item values:</b></p>
                <p>${issue_text}</p>

                <p>
                    If a row represents a discount, use the discount fields.<br>
                    If it represents retention or deduction, use the taxes and deductions table.<br>
                    If it represents an advance payment, create a Payment Entry and issue an Advance Tax Invoice (386).
                </p>
            </div>
        `;
    }

    function show_light_alert(frm, row, issues) {
        if (!issues.length) {
            return;
        }

        const key = `${frm.doctype}:${frm.doc.name || "new"}:${row.name}:${issues.join("|")}`;
        const now = Date.now();

        if (LAST_ALERT_KEY[key] && now - LAST_ALERT_KEY[key] < 2500) {
            return;
        }

        LAST_ALERT_KEY[key] = now;

        frappe.show_alert(
            {
                message: `<b>ZATCA:</b> ${issues[0]}`,
                indicator: "red",
            },
            5
        );
    }

    function validate_current_row_later(frm, cdt, cdn, changed_fieldname) {
        const timer_key = `${cdt}:${cdn}:${changed_fieldname || ""}`;

        if (ROW_VALIDATION_TIMERS[timer_key]) {
            clearTimeout(ROW_VALIDATION_TIMERS[timer_key]);
        }

        ROW_VALIDATION_TIMERS[timer_key] = setTimeout(function () {
            Promise.resolve(load_company_settings(frm)).then(function () {
                if (!is_enabled_strict(frm)) {
                    return;
                }

                const row = locals[cdt] && locals[cdt][cdn];

                if (!row) {
                    return;
                }

                const issues = get_interactive_row_issues(frm, row, changed_fieldname);
                show_light_alert(frm, row, issues);
            });
        }, 300);
    }

    function validate_on_save(frm) {
        if (!is_enabled_strict(frm)) {
            return;
        }

        const issues = get_save_issues(frm);

        if (!issues.length) {
            return;
        }

        frappe.validated = false;

        frappe.msgprint({
            title: __("ZATCA Negative Line Validation"),
            message: build_save_message(frm, issues),
            indicator: "red",
        });
    }

    function clear_company_cache(frm) {
        if (frm.doc.company && COMPANY_SETTINGS_CACHE[frm.doc.company]) {
            delete COMPANY_SETTINGS_CACHE[frm.doc.company];
        }

        frm.__zatca_negative_line_settings = null;
    }

    function bind_parent_doctype(doctype) {
        frappe.ui.form.on(doctype, {
            onload: function (frm) {
                load_company_settings(frm);
            },
            refresh: function (frm) {
                load_company_settings(frm);
            },
            company: function (frm) {
                clear_company_cache(frm);
                load_company_settings(frm);
            },
            validate: function (frm) {
                validate_on_save(frm);
            },
        });
    }

    function bind_child_doctype(child_doctype) {
        const handlers = {};
        const fields = ["qty"].concat(MONETARY_FIELDS.map((field) => field[0]));

        for (const fieldname of fields) {
            handlers[fieldname] = function (frm, cdt, cdn) {
                validate_current_row_later(frm, cdt, cdn, fieldname);
            };
        }

        frappe.ui.form.on(child_doctype, handlers);
    }

    bind_parent_doctype("Sales Invoice");
    bind_parent_doctype("POS Invoice");

    bind_child_doctype("Sales Invoice Item");
    bind_child_doctype("POS Invoice Item");
})();
