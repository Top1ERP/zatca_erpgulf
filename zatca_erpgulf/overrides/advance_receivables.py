from __future__ import annotations

import json

import frappe
from frappe import _, scrub
from frappe.utils import flt

from erpnext.accounts.doctype.dunning.dunning import Dunning
from erpnext.accounts.doctype.journal_entry.journal_entry import JournalEntry
from erpnext.accounts.doctype.payment_reconciliation.payment_reconciliation import (
    PaymentReconciliation,
)
from erpnext.accounts.party import get_partywise_advanced_payment_amount
from erpnext.accounts.report.accounts_receivable.accounts_receivable import (
    ReceivablePayableReport,
)
from erpnext.accounts.report.accounts_receivable_summary.accounts_receivable_summary import (
    AccountsReceivableSummary,
    get_gl_balance,
)
from erpnext.accounts.utils import get_currency_precision

from zatca_erpgulf.zatca_erpgulf.zatca_runtime import (
    is_advance_payment_invoice,
    supports_advance_payment_marker,
)


RECEIVABLE_REPORTS = {"Accounts Receivable", "Accounts Receivable Summary"}


def _row_value(row, fieldname, default=None):
    getter = getattr(row, "get", None)
    if callable(getter):
        return getter(fieldname, default)
    return getattr(row, fieldname, default)


def _marker_field() -> str:
    meta = frappe.get_meta("Sales Invoice")
    if meta.has_field("is_advance_payment"):
        return "is_advance_payment"
    if meta.has_field("custom_is_advance_payment"):
        return "custom_is_advance_payment"
    return ""


def get_advance_invoice_names(invoice_names) -> set[str]:
    """Resolve only supplied names, and never touch marker SQL on old Sites."""
    names = {str(name) for name in invoice_names if name}
    if not names or not supports_advance_payment_marker():
        return set()

    marker_field = _marker_field()
    if not marker_field:
        return set()

    return set(
        frappe.get_all(
            "Sales Invoice",
            filters={"name": ["in", sorted(names)], marker_field: 1},
            pluck="name",
        )
    )


def filter_advance_invoice_rows(
    rows,
    *,
    voucher_type_field: str,
    voucher_no_field: str,
) -> list:
    rows = list(rows or [])
    candidates = {
        _row_value(row, voucher_no_field)
        for row in rows
        if _row_value(row, voucher_type_field) == "Sales Invoice"
    }
    excluded = get_advance_invoice_names(candidates)
    if not excluded:
        return rows

    return [
        row
        for row in rows
        if not (
            _row_value(row, voucher_type_field) == "Sales Invoice"
            and _row_value(row, voucher_no_field) in excluded
        )
    ]


@frappe.whitelist()
def get_outstanding_reference_documents(args, validate=False):
    from erpnext.accounts.doctype.payment_entry.payment_entry import (
        get_outstanding_reference_documents as standard_get_outstanding,
    )

    rows = standard_get_outstanding(args, validate=validate)
    if rows is None:
        return None
    return filter_advance_invoice_rows(
        rows,
        voucher_type_field="voucher_type",
        voucher_no_field="voucher_no",
    )


class ZatcaPaymentReconciliation(PaymentReconciliation):
    def get_invoice_entries(self):
        super().get_invoice_entries()
        filtered = filter_advance_invoice_rows(
            self.get("invoices") or [],
            voucher_type_field="invoice_type",
            voucher_no_field="invoice_number",
        )
        self.set("invoices", filtered)


class ZatcaJournalEntry(JournalEntry):
    def get_values(self):
        rows = super().get_values()
        if self.write_off_based_on != "Accounts Receivable":
            return rows

        excluded = get_advance_invoice_names(_row_value(row, "name") for row in rows or [])
        return [row for row in rows or [] if _row_value(row, "name") not in excluded]


class ZatcaDunning(Dunning):
    def validate(self):
        excluded = get_advance_invoice_names(
            _row_value(row, "sales_invoice") for row in self.overdue_payments or []
        )
        if excluded:
            frappe.throw(
                _("Advance payment Sales Invoices cannot be included in Dunning: {0}").format(
                    ", ".join(sorted(excluded))
                )
            )
        return super().validate()


@frappe.whitelist()
def create_dunning(source_name, target_doc=None, ignore_permissions=False):
    if supports_advance_payment_marker():
        source = frappe.get_doc("Sales Invoice", source_name)
        if is_advance_payment_invoice(source):
            frappe.throw(_("Dunning cannot be created for an advance payment Sales Invoice."))

    from erpnext.accounts.doctype.sales_invoice.sales_invoice import (
        create_dunning as standard_create_dunning,
    )

    return standard_create_dunning(source_name, target_doc, ignore_permissions)


class ZatcaAccountsReceivableSummary(AccountsReceivableSummary):
    def get_data(self, args):
        self.data = []
        self.receivables = filter_advance_invoice_rows(
            ReceivablePayableReport(self.filters).run(args)[1],
            voucher_type_field="voucher_type",
            voucher_no_field="voucher_no",
        )
        self.currency_precision = get_currency_precision() or 2
        self.get_party_total(args)

        party = None
        for party_type in self.party_type:
            if self.filters.get(scrub(party_type)):
                party = self.filters.get(scrub(party_type))

        party_advance_amount = (
            get_partywise_advanced_payment_amount(
                self.party_type,
                self.filters.report_date,
                self.filters.show_future_payments,
                self.filters.company,
                party=party,
            )
            or {}
        )
        if self.filters.show_gl_balance:
            gl_balance_map = get_gl_balance(
                self.filters.report_date,
                self.filters.company,
                self.account_type,
            )

        for party, party_dict in self.party_total.items():
            if flt(party_dict.outstanding, self.currency_precision) == 0:
                continue

            row = frappe._dict()
            row.party = party
            if self.party_naming_by == "Naming Series":
                doctype = "Supplier" if self.account_type == "Payable" else "Customer"
                fieldname = "supplier_name" if self.account_type == "Payable" else "customer_name"
                row.party_name = frappe.get_cached_value(doctype, party, fieldname)

            row.update(party_dict)
            row.advance = party_advance_amount.get(party, 0)
            row.paid -= row.advance
            if self.filters.show_gl_balance:
                row.gl_balance = gl_balance_map.get(party)
                row.diff = flt(row.outstanding) - flt(row.gl_balance)
            if self.filters.show_future_payments:
                row.remaining_balance = flt(row.outstanding) - flt(row.future_amount)
            self.data.append(row)


def _without_total_row(result: dict) -> list:
    rows = list(result.get("result") or [])
    if result.get("add_total_row") and rows:
        rows.pop()
    return rows


def _replace_report_rows(result: dict, rows: list) -> dict:
    if result.get("add_total_row") and rows:
        from frappe.desk.query_report import add_total_row

        rows = add_total_row(rows, result.get("columns") or [])
    result["result"] = rows
    return result


@frappe.whitelist()
@frappe.read_only()
def run_query_report(
    report_name,
    filters=None,
    user=None,
    ignore_prepared_report=False,
    custom_columns=None,
    is_tree=False,
    parent_field=None,
    are_default_filters=True,
):
    from frappe.desk.query_report import run as standard_run

    result = standard_run(
        report_name,
        filters=filters,
        user=user,
        ignore_prepared_report=ignore_prepared_report,
        custom_columns=custom_columns,
        is_tree=is_tree,
        parent_field=parent_field,
        are_default_filters=are_default_filters,
    )
    if report_name not in RECEIVABLE_REPORTS or not supports_advance_payment_marker():
        return result

    if report_name == "Accounts Receivable":
        original_rows = _without_total_row(result)
        rows = filter_advance_invoice_rows(
            original_rows,
            voucher_type_field="voucher_type",
            voucher_no_field="voucher_no",
        )
        if len(rows) != len(original_rows):
            result["chart"] = None
            result["report_summary"] = None
        return _replace_report_rows(result, rows)

    parsed_filters = json.loads(filters) if isinstance(filters, str) else dict(filters or {})
    parsed_filters.pop("prepared_report_name", None)
    columns, rows = ZatcaAccountsReceivableSummary(frappe._dict(parsed_filters)).run(
        {
            "account_type": "Receivable",
            "naming_by": ["Selling Settings", "cust_master_name"],
        }
    )
    result["columns"] = columns
    result["chart"] = None
    result["report_summary"] = None
    return _replace_report_rows(result, rows)
