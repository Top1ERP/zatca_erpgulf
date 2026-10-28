"""Pure direct-child currency semantics for the inspected Frappe 15/16 helpers.

Staged input declarations only: no ORM/SQL, cache mutation or source attestation.
Keep this separate from parent.precision(field, parentfield), which passes the
parent document to get_field_currency. A future authorized child reader must
prove these inputs, including physical columns absent from applied metadata.
"""

from dataclasses import dataclass, field
import hashlib

from .calculation_precision import FieldPrecisionResolution
from .financial_source_observation import TABLE_FIELDS, _canonical, _child_type, _name
from .source_metadata import PROFILE as METADATA_PROFILE, SourceMetadata, _pin_metadata

ABSENT = ("absent",)
NULL = ("null",)


class ChildFieldCurrencyError(ValueError):
    """Static English code; never expose child, Company or cached values."""


def _text(value):
    """Preserve absent/NULL/blank declarations, although get() merges the first two."""
    if type(value) is not tuple:
        raise ValueError
    if value in (ABSENT, NULL):
        return None
    if (len(value) != 2 or value[0] != "str" or type(value[1]) is not str
            or len(value[1].encode("utf-8")) > 4096 or "\0" in value[1]):
        raise ValueError
    return value[1]


@dataclass(frozen=True, repr=False)
class ChildCurrencyInputs:
    """Explicit saved-child-shaped declarations, NOT permission/native evidence.

    company_lookup is empty, or (exact child Company name, tagged currency).
    It must come from that child's own Company link, never a parent fallback.
    parent_doc_currency models v16's extra in-memory parent_doc fallback only.
    No default argument implies a real field/column/record is absent in storage.
    """

    doctype: str = field(repr=False)
    name: str = field(repr=False)
    parenttype: str = field(repr=False)
    parent: str = field(repr=False)
    parentfield: str = field(repr=False)
    row_currency: tuple = field(repr=False)
    row_company: tuple = field(repr=False)
    parent_has_currency: bool = field(repr=False)
    parent_currency: tuple = field(repr=False)
    parent_doc_currency: tuple = field(default=ABSENT, repr=False)
    company_lookup: tuple = field(default=(), repr=False)

    def __post_init__(self):
        try:
            for value in (self.doctype, self.name, self.parenttype, self.parent, self.parentfield):
                _name(value)
            if (self.parenttype not in ("Sales Invoice", "POS Invoice")
                    or self.parentfield not in TABLE_FIELDS
                    or self.doctype != _child_type(self.parenttype, self.parentfield)
                    or type(self.parent_has_currency) is not bool):
                raise ValueError
            for value in (self.row_currency, self.row_company, self.parent_currency, self.parent_doc_currency):
                _text(value)
            if not self.parent_has_currency and self.parent_currency != ABSENT:
                raise ValueError
            if type(self.company_lookup) is not tuple:
                raise ValueError
            if self.company_lookup:
                if len(self.company_lookup) != 2 or not _text(self.row_company):
                    raise ValueError
                company, currency = self.company_lookup
                _name(company)
                _text(currency)
                if company != _text(self.row_company):
                    raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise ChildFieldCurrencyError("child_currency_inputs")

    def __repr__(self):
        return "<ChildCurrencyInputs protected supplied declarations, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("child_currency_not_serializable")


def _pin_inputs(inputs):
    if type(inputs) is not ChildCurrencyInputs:
        raise ValueError
    # Revalidate even a frozen object: trusted in-process code can bypass frozen.
    return ChildCurrencyInputs(**{key: getattr(inputs, key) for key in inputs.__dataclass_fields__})


def _resolve(options, inputs, major):
    if options == "currency":
        currency = _text(inputs.row_currency)
        if currency:
            return currency, "ROW_CURRENCY", inputs.name
        if inputs.parent_has_currency:
            currency = _text(inputs.parent_currency)
            if currency:
                return currency, "PARENT_CURRENCY", inputs.parent
            if major == 16:
                currency = _text(inputs.parent_doc_currency)
                if currency:
                    return currency, "PARENT_DOCUMENT_CURRENCY", inputs.parent
    elif options == "Company:company:default_currency":
        if _text(inputs.row_company):
            # Missing lookup evidence is not the same as a known NULL lookup.
            if not inputs.company_lookup:
                raise ValueError
            currency = _text(inputs.company_lookup[1])
            if currency:
                return currency, "ROW_COMPANY_CURRENCY", inputs.parent
    else:
        raise ValueError
    return None, "UNRESOLVED", None


@dataclass(frozen=True, repr=False)
class ChildFieldCurrencyResolution:
    """Fresh direct-child currency, with explicit effective-cache comparison.

    Existing metadata/default snapshots stay byte-identical. This local contract
    is not a source receipt or a complete row.precision cache/ACL/transaction gate.
    """

    metadata: SourceMetadata = field(repr=False)
    fieldname: str = field(repr=False)
    inputs: ChildCurrencyInputs = field(repr=False)
    erp_major: int
    currency: str | None = field(init=False, repr=False)
    origin: str = field(init=False)
    cache_key: tuple | None = field(init=False, repr=False)
    sha256: str = field(init=False)

    def __post_init__(self):
        try:
            metadata, inputs = _pin_metadata(self.metadata), _pin_inputs(self.inputs)
            if (type(self.erp_major) is not int or self.erp_major not in (15, 16)
                    or metadata.profile != METADATA_PROFILE or metadata.name != inputs.doctype
                    or not metadata.istable or type(self.fieldname) is not str):
                raise ValueError
            definition = metadata.get_field(self.fieldname)
            if definition is None or definition.fieldtype != "Currency":
                raise ValueError
            currency, origin, owner = _resolve(definition.options, inputs, self.erp_major)
            if currency is not None:
                _name(currency)
            cache_key = None if owner is None else (inputs.doctype, owner)
            body = dict(profile="direct-child-field-currency/v1", erp_major=self.erp_major,
                metadata_sha256=metadata.sha256, fieldname=self.fieldname,
                inputs={key: getattr(inputs, key) for key in inputs.__dataclass_fields__},
                currency=currency, origin=origin, cache_key=cache_key)
            digest = hashlib.sha256(b"zatca-direct-child-field-currency/v1\0" + _canonical(body)).hexdigest()
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise ChildFieldCurrencyError("child_currency_resolution")
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "inputs", inputs)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "cache_key", cache_key)
        object.__setattr__(self, "sha256", digest)

    def _pin(self):
        pinned = ChildFieldCurrencyResolution(self.metadata, self.fieldname, self.inputs, self.erp_major)
        if pinned != self:
            raise ValueError
        return pinned

    def require_cached_match(self, *, row_entry=ABSENT, parent_entry=ABSENT):
        """Check effective tagged cache slots without touching either cache.

        A truthy row entry wins over the parent entry. Both keys use the CHILD
        DocType. Missing/NULL/blank entries all trigger lookup, but setdefault
        does NOT replace a present NULL/blank slot. Preserve slot presence to
        detect a blocked fresh result. An unused parent slot is not certified.
        """
        try:
            pinned = self._pin()
            if pinned.inputs.name == pinned.inputs.parent and row_entry != parent_entry:
                # Both references address the SAME child-DocType/name cache slot.
                raise ValueError
            row, parent = _text(row_entry), _text(parent_entry)
            if not (row or parent) and pinned.currency:
                if pinned.cache_key == (pinned.inputs.doctype, pinned.inputs.name):
                    if row_entry == ABSENT:
                        row = pinned.currency
                elif parent_entry == ABSENT:
                    parent = pinned.currency
            if (row or parent) != pinned.currency:
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise ChildFieldCurrencyError("child_currency_cache_mismatch")

    def resolve_precision(self, defaults, *, currency_context=None):
        """Reuse the shared precision policy, binding consumed v16 format currency.

        Configured field/default precision need not resolve a missing currency.
        An unresolved currency cannot authorize a Currency(None) format lookup.
        Document numeric precision caches still require their separate comparison.
        """
        try:
            pinned = self._pin()
            result = FieldPrecisionResolution(pinned.metadata, pinned.fieldname, defaults,
                pinned.erp_major, currency_context)
            if (result.origin in ("LOCALE_NUMBER_FORMAT", "CURRENCY_NUMBER_FORMAT")
                    and result.currency_context.currency != pinned.currency):
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise ChildFieldCurrencyError("child_currency_precision")
        return result

    def __repr__(self):
        return "<ChildFieldCurrencyResolution protected direct-child declarations, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("child_currency_not_serializable")
