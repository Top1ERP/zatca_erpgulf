"""Normal root party-currency field READ and same-owned supplemental SQL.

Reuse the authorized numeric graph and link reader. No independent parent
capture, financial-profile expansion, transaction, cache mutation or writer.
"""

import json

from .calculation_child_format_access import require_field_read
from .financial_source_observation import _canonical, _scalar, _name
from .owner_currency_source import MariaDBOwnerCurrencyReader, pin_owner_currency, OwnerCurrencySourceError
from .metadata_source import MariaDBMetadataSourceReader
from .source_metadata import OWNER_CURRENCY_PROFILE, PROPERTIES, SourceFieldDefinition, _pin_metadata

FIELD = "party_account_currency"


class OwnerCurrencyAcquisition:
    """Authorize one supplemental Link; the parent pipeline owns SQL/cleanup."""

    def __init__(self, root, actor, metadata_reader):
        if not callable(metadata_reader):
            raise OwnerCurrencySourceError("owner_currency_dependencies")
        self.root, self.actor, self._metadata = root, actor, metadata_reader
        self._runtime = root._policy._dependencies()[0]
        self.definition, self.level, self.currency = self._observe(root.document)
        self.native = None
        self.recheck_access()

    def _observe(self, doc):
        level = require_field_read(doc, FIELD, self.actor, self._runtime, self.root._policy.DENIED_MESSAGE)
        df = doc.meta.get_field(FIELD)
        definition = SourceFieldDefinition(FIELD, _canonical([[name, _scalar(df.get(name))] for name in PROPERTIES]))
        if definition.fieldtype != "Link" or definition.options != "Currency":
            raise OwnerCurrencySourceError("owner_currency_definition")
        return definition, level, _name(doc.get(FIELD))

    def recheck_access(self):
        self.root.recheck_access()
        expected = self.definition, self.level, self.currency
        fresh = self.root._parent_load(self.root._doctype, self.root._name)
        if self._observe(self.root.document) != expected or self._observe(fresh) != expected:
            raise OwnerCurrencySourceError("owner_currency_getter_changed")

    def _applied(self):
        name = self.root._doctype
        supplied = self._metadata(self.root._policy._scope, (name,))
        if type(supplied) is not dict or set(supplied) != {name}:
            raise OwnerCurrencySourceError("owner_currency_metadata")
        meta = _pin_metadata(supplied[name])
        if meta.name != name or meta.profile != OWNER_CURRENCY_PROFILE or meta.get_field(FIELD) != self.definition:
            raise OwnerCurrencySourceError("owner_currency_metadata")
        return meta

    def prepare_metadata(self):
        self.applied = self._applied()
        self.recheck_access()

    def load_for_update(self, connection, financial):
        self.reader = MariaDBOwnerCurrencyReader(connection)
        self.native = self.reader.load_for_update(self.root._name,
            metadata=self._native_metadata(connection))
        self.require_binding(financial)

    def _native_metadata(self, connection):
        return MariaDBMetadataSourceReader(connection).load_for_update(self.applied)

    def require_binding(self, financial):
        observed = pin_owner_currency(self.native)
        root_meta = next(row for row in financial.metadata if row.applied.name == self.root._doctype)
        if (observed.name != financial.financial.name or observed.metadata.applied.name != financial.financial.doctype
                or observed.currency != self.currency or observed.revision != self.root.owner.revision
                or json.loads(observed.metadata._payload)["doctype"] != json.loads(root_meta._payload)["doctype"]):
            raise OwnerCurrencySourceError("owner_currency_financial_binding")
        self.recheck_access()

    def require_metadata_unchanged(self):
        if self._applied() != self.applied:
            raise OwnerCurrencySourceError("owner_currency_metadata_changed")
        self.recheck_access()

    def require_unchanged(self):
        self.reader.require_unchanged(self.native)
        self.recheck_access()
