"""One observed invoice value for a request and its local XML consumers.

The reader retains its existing path, decoding and whitespace contract. This
module performs no discovery, signing, persistence or HTTP. When a native
issuing scope exists, it observes the captured value for its final content fence. A captured value is not proof of authentic submission.
"""

import base64
from dataclasses import dataclass


@dataclass(frozen=True, repr=False)
class InvoicePayload:
    """Keep native values unchanged and avoid printing XML/UUID/hash in repr.

    Normal XML readers return immutable Base64 text. Caller-supplied mutable
    identity/hash objects are not copied or certified deeply immutable here.
    """

    invoice_hash: object
    uuid: object
    invoice_base64: object

    def as_payload(self):
        """Return a fresh dict in the original serialization key order."""
        return {
            "invoiceHash": self.invoice_hash,
            "uuid": self.uuid,
            "invoice": self.invoice_base64,
        }

    def xml_text(self):
        """Decode only when an existing attachment/QR consumer needs text.

        Retain the former permissive Base64 and strict UTF-8 behavior; do not
        normalize XML, change its encoding declaration or introduce a parser.
        """
        return base64.b64decode(self.invoice_base64).decode("utf-8")


def read_invoice_payload(uuid, invoice_hash, path, *, read_xml):
    """Call the current reader once; keep the optional scope content observation."""
    from .issuing_attempt import ACTIVE
    current = ACTIVE.get()
    if current is not None:
        current.require_runtime(current.runtime)
    payload = InvoicePayload(invoice_hash, uuid, read_xml(path))
    if current is not None:
        current.observe_payload(payload, path)
    return payload
