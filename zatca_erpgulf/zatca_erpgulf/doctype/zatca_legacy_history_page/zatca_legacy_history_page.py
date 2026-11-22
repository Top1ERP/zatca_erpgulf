"""Read-only metadata; historical XML is held only in service-owned ciphertext."""

from zatca_erpgulf.zatca_erpgulf.service_owned_record import ServiceOwnedIssuanceRecord


class ZATCALegacyHistoryPage(ServiceOwnedIssuanceRecord):
    pass
