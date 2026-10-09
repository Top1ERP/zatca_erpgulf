"""Non-production identity and file lifetimes, independent of Frappe.

These helpers never allocate live counters, mutate an invoice, or choose API
credentials. Callers still own validation and the selected API environment.
"""

from contextlib import contextmanager
from collections.abc import Iterator
from tempfile import NamedTemporaryFile
from uuid import UUID, uuid4


def preview_invoice_uuid(existing_uuid, purpose: str) -> str:
    """Reuse an issued UUID for debugging; give compliance samples a fresh UUID.

    A missing/placeholder UUID gets a disposable value, never one persisted on
    the source invoice. A typo in the purpose must not select the live workflow.
    """
    if purpose not in ("debug", "compliance"):
        raise ValueError("Unsupported non-production invoice purpose.")
    if purpose == "debug" and existing_uuid:
        try:
            UUID(str(existing_uuid).strip())
        except ValueError:
            pass
        else:
            return str(existing_uuid).strip()
    return str(uuid4())


@contextmanager
def temporary_compliance_xml(xml_content: str) -> Iterator[str]:
    """Expose exact UTF-8 bytes to the legacy path-based HTTP client, then unlink.

    Linux Bench can reopen a named temporary file while its handle is open.
    The unique, owner-only file is removed on both success and exception. Its
    name contains no invoice identifier and cannot collide with a live artifact.
    """
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", prefix="zatca-compliance-", suffix=".xml"
    ) as handle:
        handle.write(xml_content)
        handle.flush()
        yield handle.name
