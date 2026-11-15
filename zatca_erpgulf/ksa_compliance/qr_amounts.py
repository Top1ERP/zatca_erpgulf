"""QR monetary source selection, separate from encoding, FX and persistence.

Phase1 reads saved gross/VAT in document currency. Phase2 reads BT-115 and
BT-110 from the XML being signed; it never subtracts prepayments from VAT or
chooses the first accounting TaxTotal. Existing artifacts are owned elsewhere.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

CBC = "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}"
CAC = "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}"
REVIEW = "The QR amounts could not be verified. Review the invoice totals, currency and tax amounts before generating the QR code."


class QRAmountError(ValueError):
    """Static English code only, without XML, money, issuer or credential data."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class QRAmounts:
    currency: str
    invoice_total: str
    vat_total: str


def _currency(value):
    if not isinstance(value, str) or re.fullmatch(r"[A-Z]{3}", value) is None:
        raise QRAmountError("qr_document_currency")
    return value


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise QRAmountError("qr_amount_value")
    text = str(value)
    # Native money has no exponent/currency symbol/grouping; bound the parser
    # to the TLV text field rather than allocating an unbounded Decimal input.
    if not 0 < len(text) <= 255 or re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", text) is None:
        raise QRAmountError("qr_amount_value")
    try:
        value = Decimal(text)
        if value.is_finite() and value == value.quantize(Decimal(".01")):
            return value
    except InvalidOperation:
        pass
    raise QRAmountError("qr_amount_precision")


def phase1_document_amounts(doc):
    """Use native DOC gross and VAT; never base money or partial advance math.

    These scalar observations do not identify VAT accounts, certify GL/source
    provenance or calculate an invoice/receivable. The initial-advance hook and
    ordinary adapter retain their own eligibility and existing-QR preservation.
    """
    currency = _currency(doc.get("currency"))
    try:
        returned = int(doc.get("is_return") or 0) == 1
    except (ValueError, TypeError, OverflowError):
        raise QRAmountError("qr_return_flag") from None
    sign = -1 if returned else 1
    gross = _number(doc.get("grand_total")) * sign
    vat = _number(doc.get("total_taxes_and_charges")) * sign
    if gross < 0 or vat < 0:
        raise QRAmountError("qr_amount_direction")
    return QRAmounts(currency, f"{abs(gross):.2f}", f"{abs(vat):.2f}")


def _one(parent, tag, code):
    nodes = parent.findall(tag)
    if len(nodes) != 1:
        raise QRAmountError(code)
    return nodes[0]


def _text(node, code):
    if len(node) or not isinstance(node.text, str) or not node.text.strip():
        raise QRAmountError(code)
    return node.text.strip()


def _xml_money(node, currency):
    text = _text(node, "qr_amount_value")
    if node.get("currencyID") != currency:
        raise QRAmountError("qr_amount_currency")
    if _number(text) < 0:
        raise QRAmountError("qr_amount_direction")
    return text


def phase2_xml_amounts(root):
    """Select exactly one DOC payable and detailed DOC tax, regardless of order.

    This is not complete UBL/Schematron, receipt or signature validation. Read
    direct root children only: line-level VAT and reference documents cannot
    supply document totals. Keep valid XML text/scale, without modifying XML.
    """
    currency = _currency(_text(_one(root, CBC + "DocumentCurrencyCode",
        "qr_document_currency"), "qr_document_currency"))
    legal = _one(root, CAC + "LegalMonetaryTotal", "qr_payable_ambiguous")
    payable = _xml_money(_one(legal, CBC + "PayableAmount", "qr_payable_ambiguous"), currency)
    detailed = [node for node in root.findall(CAC + "TaxTotal") if node.findall(CAC + "TaxSubtotal")]
    if len(detailed) != 1:
        raise QRAmountError("qr_vat_ambiguous")
    vat = _xml_money(_one(detailed[0], CBC + "TaxAmount", "qr_vat_ambiguous"), currency)
    return QRAmounts(currency, payable, vat)
