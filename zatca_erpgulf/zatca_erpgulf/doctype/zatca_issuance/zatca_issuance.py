"""Read-only service-owned issuance metadata; no controller writes."""

from zatca_erpgulf.zatca_erpgulf.service_owned_record import ServiceOwnedIssuanceRecord


class ZATCAIssuance(ServiceOwnedIssuanceRecord):
    pass
