"""Read-only Desk views over service-owned issuance records.

These guards prevent ordinary generic document edits, including accidental
Administrator changes. They do not sandbox privileged Python/raw SQL. The
owned submission repository uses fixed SQL and owns its transaction explicitly;
no service authorization is accepted through client flags or document fields.
"""

import frappe
from frappe import _
from frappe.model.document import Document


EDIT_REVIEW = 'ZATCA issuance records are maintained by the submission service and cannot be edited manually.'
DELETE_REVIEW = 'ZATCA issuance records must be retained and cannot be deleted manually.'


class ServiceOwnedIssuanceRecord(Document):
    def before_insert(self):
        frappe.throw(_(EDIT_REVIEW))

    def validate(self):
        frappe.throw(_(EDIT_REVIEW))

    def before_save(self):
        frappe.throw(_(EDIT_REVIEW))

    def before_update_after_submit(self):
        frappe.throw(_(EDIT_REVIEW))

    def before_rename(self, *args, **kwargs):
        frappe.throw(_(EDIT_REVIEW))

    def on_trash(self):
        frappe.throw(_(DELETE_REVIEW))
