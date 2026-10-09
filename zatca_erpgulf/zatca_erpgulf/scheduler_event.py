"""Sales worker and cron dispatcher; policy is shared with the POS worker."""

from zatca_erpgulf.zatca_erpgulf.background_worker import run_pending_background_invoices
from zatca_erpgulf.zatca_erpgulf.schedule_pos import (
    submit_posinvoices_to_zatca_background_process,
)
from zatca_erpgulf.zatca_erpgulf.scheduling import convert_to_time, is_time_in_range
from zatca_erpgulf.zatca_erpgulf.sign_invoice import zatca_background_on_submit


def submit_invoices_to_zatca_background():
    """Send only invoices whose own Company currently authorizes the worker."""
    run_pending_background_invoices(
        "Sales Invoice", zatca_background_on_submit, commit_per_invoice=True
    )


def submit_invoices_to_zatca_background_process():
    """Keep the public cron entry point without duplicate discovery queries."""
    submit_invoices_to_zatca_background()
    submit_posinvoices_to_zatca_background_process()
