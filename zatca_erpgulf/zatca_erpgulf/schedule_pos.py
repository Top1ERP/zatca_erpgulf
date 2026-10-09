"""POS worker; use the same Company eligibility rules as Sales Invoice."""

from zatca_erpgulf.zatca_erpgulf.background_worker import run_pending_background_invoices
from zatca_erpgulf.zatca_erpgulf.pos_sign import zatca_background_on_submit
from zatca_erpgulf.zatca_erpgulf.scheduling import convert_to_time, is_time_in_range


def submit_posinvoices_to_zatca_background_process():
    """Keep POS transaction commits under the existing scheduler job boundary."""
    run_pending_background_invoices("POS Invoice", zatca_background_on_submit)
