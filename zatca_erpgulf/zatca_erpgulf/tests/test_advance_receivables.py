from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext.accounts.utils import get_payment_ledger_entries

from zatca_erpgulf.overrides.advance_receivables import (
    ZatcaJournalEntry,
    ZatcaPaymentReconciliation,
    create_dunning,
    filter_advance_invoice_rows,
    get_outstanding_reference_documents,
    run_query_report,
)
from zatca_erpgulf.zatca_erpgulf.advance_deduction import (
    validate_advance_payment_invoice_cancellation,
)


class _Query:
    def select(self, *args):
        return self

    def where(self, *args):
        return self

    def run(self, **kwargs):
        return [frappe._dict(name="Debtors - TC", account_type="Receivable")]


def _gl(**values):
    defaults = {
        "posting_date": "2026-08-10",
        "company": "Test Company",
        "account": "Debtors - TC",
        "party_type": "Customer",
        "party": "Test Customer",
        "project": None,
        "cost_center": "Main - TC",
        "finance_book": None,
        "due_date": "2026-08-10",
        "voucher_detail_no": None,
        "account_currency": "SAR",
        "debit": 0,
        "credit": 0,
        "debit_in_account_currency": 0,
        "credit_in_account_currency": 0,
        "against_voucher_type": None,
        "against_voucher": None,
        "advance_voucher_no": None,
        "remarks": None,
    }
    defaults.update(values)
    return frappe._dict(defaults)


class TestAdvancePaymentLedgerMapping(FrappeTestCase):
    def _payment_ledger(self, entries, cancel=0):
        with patch("erpnext.accounts.utils.qb.from_", return_value=_Query()), patch(
            "erpnext.accounts.utils.get_dimensions", return_value=[]
        ):
            return get_payment_ledger_entries(entries, cancel=cancel)

    def test_real_v15_mapping_closes_advance_not_final_invoice(self):
        advance_debit = _gl(
            voucher_type="Sales Invoice",
            voucher_no="SINV-ADV",
            debit=150,
            debit_in_account_currency=150,
        )
        final_debit = _gl(
            voucher_type="Sales Invoice",
            voucher_no="SINV-FINAL",
            debit=1150,
            debit_in_account_currency=1150,
        )
        deduction_credit = _gl(
            voucher_type="Sales Invoice",
            voucher_no="SINV-FINAL",
            against_voucher_type="Sales Invoice",
            against_voucher="SINV-ADV",
            credit=150,
            credit_in_account_currency=150,
        )
        payment_credit = _gl(
            voucher_type="Payment Entry",
            voucher_no="ACC-PAY",
            against_voucher_type="Sales Invoice",
            against_voucher="SINV-FINAL",
            credit=150,
            credit_in_account_currency=150,
        )

        before_payment = self._payment_ledger(
            [advance_debit, final_debit, deduction_credit]
        )
        self.assertEqual(self._payment_ledger([advance_debit])[0].amount, 150)
        balances = {}
        for row in before_payment:
            balances[row.against_voucher_no] = balances.get(row.against_voucher_no, 0) + row.amount

        self.assertEqual(balances["SINV-ADV"], 0)
        self.assertEqual(balances["SINV-FINAL"], 1150)

        after_payment = self._payment_ledger([payment_credit])
        balances["SINV-FINAL"] += after_payment[0].amount
        self.assertEqual(balances["SINV-FINAL"], 1000)

    def test_partial_release_and_cancellation_reverse_the_same_advance(self):
        release = _gl(
            voucher_type="Sales Invoice",
            voucher_no="SINV-FINAL",
            against_voucher_type="Sales Invoice",
            against_voucher="SINV-ADV",
            credit=40,
            credit_in_account_currency=40,
        )
        submitted = self._payment_ledger([release])[0]
        cancelled = self._payment_ledger([release], cancel=1)[0]

        self.assertEqual(submitted.against_voucher_no, "SINV-ADV")
        self.assertEqual(submitted.amount, -40)
        self.assertEqual(cancelled.against_voucher_no, "SINV-ADV")
        self.assertEqual(cancelled.amount, 40)
        self.assertEqual(submitted.amount + cancelled.amount, 0)


class TestAdvanceReceivableExclusions(FrappeTestCase):
    def test_filter_removes_only_advance_sales_invoices(self):
        rows = [
            frappe._dict(voucher_type="Sales Invoice", voucher_no="SINV-ADV"),
            frappe._dict(voucher_type="Sales Invoice", voucher_no="SINV-NORMAL"),
            frappe._dict(voucher_type="Journal Entry", voucher_no="JV-1"),
        ]
        with patch(
            "zatca_erpgulf.overrides.advance_receivables.get_advance_invoice_names",
            return_value={"SINV-ADV"},
        ):
            filtered = filter_advance_invoice_rows(
                rows,
                voucher_type_field="voucher_type",
                voucher_no_field="voucher_no",
            )

        self.assertEqual([row.voucher_no for row in filtered], ["SINV-NORMAL", "JV-1"])

    def test_old_schema_does_not_query_marker_column(self):
        rows = [frappe._dict(voucher_type="Sales Invoice", voucher_no="SINV-1")]
        with patch(
            "zatca_erpgulf.overrides.advance_receivables.supports_advance_payment_marker",
            return_value=False,
        ), patch("zatca_erpgulf.overrides.advance_receivables.frappe.get_all") as get_all:
            filtered = filter_advance_invoice_rows(
                rows,
                voucher_type_field="voucher_type",
                voucher_no_field="voucher_no",
            )

        self.assertEqual(filtered, rows)
        get_all.assert_not_called()

    def test_payment_entry_outstanding_rpc_filters_advance(self):
        rows = [
            frappe._dict(voucher_type="Sales Invoice", voucher_no="SINV-ADV"),
            frappe._dict(voucher_type="Sales Invoice", voucher_no="SINV-NORMAL"),
        ]
        with patch(
            "erpnext.accounts.doctype.payment_entry.payment_entry.get_outstanding_reference_documents",
            return_value=rows,
        ), patch(
            "zatca_erpgulf.overrides.advance_receivables.get_advance_invoice_names",
            return_value={"SINV-ADV"},
        ):
            result = get_outstanding_reference_documents({})

        self.assertEqual([row.voucher_no for row in result], ["SINV-NORMAL"])

    def test_payment_entry_rpc_preserves_standard_none_result(self):
        with patch(
            "erpnext.accounts.doctype.payment_entry.payment_entry.get_outstanding_reference_documents",
            return_value=None,
        ):
            self.assertIsNone(get_outstanding_reference_documents({"party_type": "Member"}))

    def test_payment_reconciliation_filters_advance_invoice_rows(self):
        reconciliation = ZatcaPaymentReconciliation({"doctype": "Payment Reconciliation"})
        reconciliation.set(
            "invoices",
            [
                {"invoice_type": "Sales Invoice", "invoice_number": "SINV-ADV"},
                {"invoice_type": "Sales Invoice", "invoice_number": "SINV-NORMAL"},
            ],
        )
        with patch(
            "erpnext.accounts.doctype.payment_reconciliation.payment_reconciliation.PaymentReconciliation.get_invoice_entries"
        ), patch(
            "zatca_erpgulf.overrides.advance_receivables.get_advance_invoice_names",
            return_value={"SINV-ADV"},
        ):
            reconciliation.get_invoice_entries()

        self.assertEqual(
            [row.invoice_number for row in reconciliation.invoices],
            ["SINV-NORMAL"],
        )

    def test_accounts_receivable_writeoff_filters_advance_invoice(self):
        journal = ZatcaJournalEntry({"doctype": "Journal Entry"})
        journal.write_off_based_on = "Accounts Receivable"
        rows = [frappe._dict(name="SINV-ADV"), frappe._dict(name="SINV-NORMAL")]
        with patch(
            "erpnext.accounts.doctype.journal_entry.journal_entry.JournalEntry.get_values",
            return_value=rows,
        ), patch(
            "zatca_erpgulf.overrides.advance_receivables.get_advance_invoice_names",
            return_value={"SINV-ADV"},
        ):
            result = journal.get_values()

        self.assertEqual([row.name for row in result], ["SINV-NORMAL"])

    def test_direct_dunning_creation_is_blocked_for_advance(self):
        advance = SimpleNamespace(
            meta=SimpleNamespace(has_field=lambda fieldname: fieldname == "is_advance_payment"),
            is_advance_payment=1,
            get=lambda fieldname, default=None: 1 if fieldname == "is_advance_payment" else default,
        )
        with patch(
            "zatca_erpgulf.overrides.advance_receivables.supports_advance_payment_marker",
            return_value=True,
        ), patch(
            "zatca_erpgulf.overrides.advance_receivables.frappe.get_doc",
            return_value=advance,
        ), patch(
            "erpnext.accounts.doctype.sales_invoice.sales_invoice.create_dunning"
        ) as standard_create:
            with self.assertRaisesRegex(frappe.ValidationError, "cannot be created"):
                create_dunning("SINV-ADV")
        standard_create.assert_not_called()

    def test_accounts_receivable_result_and_total_exclude_advance(self):
        standard_result = {
            "columns": [
                {"fieldname": "voucher_no", "fieldtype": "Data"},
                {"fieldname": "outstanding", "fieldtype": "Currency"},
            ],
            "result": [
                {"voucher_type": "Sales Invoice", "voucher_no": "SINV-ADV", "outstanding": 150},
                {"voucher_type": "Sales Invoice", "voucher_no": "SINV-NORMAL", "outstanding": 1000},
                ["", 1150],
            ],
            "add_total_row": True,
            "chart": {"data": {"datasets": [{"values": [150, 1000]}]}},
            "report_summary": [{"value": 1150}],
        }
        with patch("frappe.desk.query_report.run", return_value=standard_result), patch(
            "zatca_erpgulf.overrides.advance_receivables.supports_advance_payment_marker",
            return_value=True,
        ), patch(
            "zatca_erpgulf.overrides.advance_receivables.get_advance_invoice_names",
            return_value={"SINV-ADV"},
        ):
            result = run_query_report("Accounts Receivable")

        self.assertEqual(result["result"][0]["voucher_no"], "SINV-NORMAL")
        self.assertEqual(result["result"][-1][1], 1000)
        self.assertIsNone(result["chart"])
        self.assertIsNone(result["report_summary"])

    def test_old_schema_report_result_is_unchanged(self):
        standard_result = {"columns": [], "result": [{"voucher_no": "SINV-1"}]}
        with patch("frappe.desk.query_report.run", return_value=standard_result), patch(
            "zatca_erpgulf.overrides.advance_receivables.supports_advance_payment_marker",
            return_value=False,
        ), patch(
            "zatca_erpgulf.overrides.advance_receivables.get_advance_invoice_names"
        ) as get_names:
            result = run_query_report("Accounts Receivable")

        self.assertIs(result, standard_result)
        get_names.assert_not_called()

    def test_accounts_receivable_summary_uses_filtered_live_rows(self):
        standard_result = {
            "columns": [{"fieldname": "outstanding", "fieldtype": "Currency"}],
            "result": [{"party": "Test Customer", "outstanding": 1150}],
            "add_total_row": False,
        }
        filtered_rows = [frappe._dict(party="Test Customer", outstanding=1000)]
        with patch("frappe.desk.query_report.run", return_value=standard_result), patch(
            "zatca_erpgulf.overrides.advance_receivables.supports_advance_payment_marker",
            return_value=True,
        ), patch(
            "zatca_erpgulf.overrides.advance_receivables.ZatcaAccountsReceivableSummary.run",
            return_value=(standard_result["columns"], filtered_rows),
        ) as summary_run:
            result = run_query_report(
                "Accounts Receivable Summary",
                filters={"company": "Test Company", "report_date": "2026-08-10"},
            )

        summary_run.assert_called_once()
        self.assertEqual(result["result"], filtered_rows)


class TestAdvanceCancellationGuard(FrappeTestCase):
    def test_consumed_advance_cannot_be_cancelled(self):
        doc = SimpleNamespace(name="SINV-ADV")
        with patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.supports_advance_deduction_schema",
            return_value=True,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.is_advance_payment_invoice",
            return_value=True,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction._submitted_final_allocation_total",
            return_value=40,
        ):
            with self.assertRaisesRegex(frappe.ValidationError, "Cancel those final invoices first"):
                validate_advance_payment_invoice_cancellation(doc)

    def test_old_schema_cancellation_guard_is_noop_without_queries(self):
        with patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.supports_advance_deduction_schema",
            return_value=False,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction._submitted_final_allocation_total"
        ) as total:
            validate_advance_payment_invoice_cancellation(SimpleNamespace(name="SINV-ADV"))
        total.assert_not_called()
