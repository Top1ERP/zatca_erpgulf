"""Pure QR serialization; amounts, timestamp and issuer policy belong to callers.

Phase 1 uses five UTF-8 text tags with one length byte. Phase 2 supplies its
existing tag encoder separately, including binary certificate/signature values.
Do not merge their length, numeric formatting or tag-selection policies.
"""

import base64


MAX_PHASE1_VALUE_BYTES = 255
PHASE1_QR_VALUE_ERROR = (
    "The ZATCA QR value for tag {0} must be valid UTF-8 text and must not exceed 255 bytes."
)


class Phase1QREncodingError(ValueError):
    """English internal code and tag number only, without rejected content."""

    code = "phase1_qr_encoding"

    def __init__(self, tag):
        self.tag = tag
        super().__init__(self.code)


def encode_qr_payload(tlv_data, encode_tag):
    """Keep the producer's tag order and existing UTF-8/binary TLV policy."""
    return base64.b64encode(
        b"".join(encode_tag(tag, value) for tag, value in tlv_data.items())
    ).decode("utf-8")


def _encode_phase1_tag(tag, value):
    encoded = None
    # UTF-8 never uses fewer bytes than characters. Refuse obviously oversized
    # input before allocating its encoded copy; at most 255 characters reach
    # encoding, then the actual byte bound still applies to multibyte text.
    if isinstance(value, str) and len(value) <= MAX_PHASE1_VALUE_BYTES:
        try:
            encoded = value.encode("utf-8")
        except UnicodeEncodeError:
            pass
    # Raise outside the encoding handler so the original value is not retained
    # through an exception context. Never truncate, normalize or use byte length
    # modulo 256 to make an oversized field appear to fit.
    if encoded is None or len(encoded) > MAX_PHASE1_VALUE_BYTES:
        raise Phase1QREncodingError(tag)
    return bytes([tag, len(encoded)]) + encoded


def encode_phase1_qr(*, seller_name, vat_number, timestamp, invoice_total, vat_total):
    """Encode five already formatted strings without interpreting their values.

    This is serialization, not taxpayer/date/amount validation or proof of a
    valid invoice. Preserve whitespace, signs, decimal scale and empty strings;
    the owning adapter enforces its existing required-field and amount policy.
    """
    return encode_qr_payload(
        {1: seller_name, 2: vat_number, 3: timestamp, 4: invoice_total, 5: vat_total},
        _encode_phase1_tag,
    )
