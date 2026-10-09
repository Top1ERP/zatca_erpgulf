"""Read-only characterization of retry gaps, not approval of legacy behavior.

Keep UUID/counter migration grounded in the actual metadata and HTTP adapters.
All database/network boundaries are mocked; files are pytest temporary files.
"""

import xml.etree.ElementTree as ET
from uuid import UUID

import pytest
import requests

from zatca_erpgulf.zatca_erpgulf import createxml, posxml, sign_invoice, pos_sign
from zatca_erpgulf.zatca_erpgulf.tests.test_generation_routes import (
    ADAPTERS as GENERATION_ADAPTERS, generation_boundary,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_legacy_submission_context import (
    ADAPTERS as XML_ADAPTERS, legacy_boundary,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import isolated
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import (
    ValidationError, boundary, select_owner,
)


ADAPTERS = (
    (sign_invoice, "reporting_api", "sales", True),
    (sign_invoice, "clearance_api", "sales", True),
    (pos_sign, "reporting_api", "pos", False),
    (pos_sign, "clearance_api", "pos", False),
) + tuple((m, fn, attr, False) for m, fn, _, attr, *_ in XML_ADAPTERS) + tuple(
    (m, fn, attr, False) for m, fn, attr, *_ in GENERATION_ADAPTERS
)
ISSUED_UUID = "b05809d9-7851-4767-b7e9-47af44c80cb9"


@pytest.fixture
def retry_boundary(legacy_boundary, generation_boundary):
    # Both fixtures extend the same cached saved-record/HTTP boundary.
    assert legacy_boundary is generation_boundary
    b = legacy_boundary
    for invoice in (b.sales, b.pos):
        invoice.custom_uuid = ISSUED_UUID
        invoice.custom_zatca_icv = 77
        invoice.custom_zatca_issuing_unit = "existing-chain"
        select_owner(b, invoice, "device")
    return b


def submit(b, adapter):
    module, fn, attr, *_ = adapter
    doc = getattr(b, attr)
    return getattr(module, fn)(ISSUED_UUID, "test-hash", str(b.path), doc.name, doc)


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("status", [400, 401, 503])
def test_http_failure_uuid_policy_is_inconsistent_but_icv_is_retained(retry_boundary, adapter, status):
    b = retry_boundary
    before = b.path.read_bytes()
    b.response.status_code = status
    with pytest.raises(ValidationError):
        submit(b, adapter)
    invoice = getattr(b, adapter[2])
    assert invoice.custom_uuid == (ISSUED_UUID if adapter[3] else "Not Submitted")
    assert invoice.custom_zatca_icv == 77
    assert invoice.custom_zatca_issuing_unit == "existing-chain"
    assert b.device.custom_pih == "previous"
    b.device.save.assert_not_called()
    assert b.path.read_bytes() == before


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_transport_unknown_outcome_preserves_saved_fields_at_http_boundary(retry_boundary, adapter):
    b = retry_boundary
    before = b.path.read_bytes()
    b.post.side_effect = requests.Timeout("TEST UNKNOWN REMOTE OUTCOME")
    with pytest.raises(requests.Timeout):
        submit(b, adapter)
    invoice = getattr(b, adapter[2])
    assert invoice.custom_uuid == ISSUED_UUID
    assert invoice.custom_zatca_icv == 77
    assert invoice.custom_zatca_issuing_unit == "existing-chain"
    b.device.save.assert_not_called()
    assert b.path.read_bytes() == before


@pytest.mark.parametrize("existing", [None, "Not Submitted", ISSUED_UUID])
def test_pos_live_metadata_always_regenerates_even_for_existing_issuance(isolated, existing):
    invoice, _, _, _, _ = isolated
    invoice.custom_uuid = existing
    values = []
    for _ in range(2):
        root, value, doc = posxml.salesinvoice_data(ET.Element("Invoice"), invoice.name)
        UUID(value)
        assert root.find("cbc:UUID").text == value
        assert doc is invoice
        values.append(value)
    assert values[0] != values[1]
    assert all(value != existing for value in values)
    assert invoice.custom_uuid == existing
    invoice.db_set.assert_not_called()
    assert invoice.custom_zatca_icv == 77


@pytest.mark.parametrize("existing", [ISSUED_UUID, "arbitrary-non-UUID-text"])
def test_sales_live_uuid_guard_is_only_a_placeholder_filter(isolated, existing):
    invoice, _, _, _, _ = isolated
    invoice.custom_uuid = existing
    _, first, _ = createxml.salesinvoice_data(ET.Element("Invoice"), invoice.name)
    _, second, _ = createxml.salesinvoice_data(ET.Element("Invoice"), invoice.name)
    assert first == second == existing
    invoice.db_set.assert_not_called()


@pytest.mark.parametrize("existing", [None, "Not Submitted", "false", "0"])
def test_sales_persists_a_new_uuid_once_for_missing_or_placeholder(isolated, existing):
    invoice, _, _, _, _ = isolated
    invoice.custom_uuid = existing
    _, first, _ = createxml.salesinvoice_data(ET.Element("Invoice"), invoice.name)
    _, second, _ = createxml.salesinvoice_data(ET.Element("Invoice"), invoice.name)
    UUID(first)
    assert first == second == invoice.custom_uuid
    invoice.db_set.assert_called_once_with("custom_uuid", first, commit=True, update_modified=False)


@pytest.mark.parametrize("adapter", XML_ADAPTERS)
def test_existing_xml_wrapper_uses_artifact_identity_not_saved_invoice_uuid(legacy_boundary, adapter):
    b = legacy_boundary
    module, _, wrapper, attr, *_ = adapter
    doc = getattr(b, attr)
    doc.custom_uuid = ISSUED_UUID
    select_owner(b, doc, "device")
    before = b.path.read_bytes()
    getattr(module, wrapper)(doc, b.relative_path, doc.name)
    # This synthetic artifact deliberately has a different UUID. The current
    # wrapper sends it without reconciling the saved issuance identity.
    assert b.post.call_args.kwargs["json"]["uuid"] == "test-uuid"
    assert doc.custom_uuid == "test-uuid"
    assert b.path.read_bytes() == before
