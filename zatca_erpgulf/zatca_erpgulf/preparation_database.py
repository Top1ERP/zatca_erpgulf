"""Request-local read-only DB view for native invoice preparation.

A future owned worker transaction installs this view only during canonical
builders and restores its original DB on exit. It is not a global monkeypatch,
a database owner factory or a sandbox for privileged Python/raw connections.
Master reads use shared NOWAIT locks so concurrent preparations can read the same
settings while writers cannot change consumed rows inside that transaction.
"""

from contextlib import contextmanager
import re


READ_METHODS = frozenset((
    'get_value','get_values','exists','get_singles_dict','get_single_value',
    'get_singles_value','get_table_columns','get_db_table_columns','has_column',
    'table_exists','get_default','get_defaults','get_column_type','escape',
))
READ_ATTRIBUTES = frozenset(('db_type','db_name','cur_db_name','type_map','default_engine'))
TABLES = re.compile(r'\b(?:FROM|JOIN)\s+(?:`([^`]+)`|([A-Za-z_][A-Za-z0-9_]*))',re.I)
FOR_UPDATE = re.compile(r'\s+FOR\s+UPDATE(?:\s+(?:NOWAIT|WAIT\s+\d+))?\s*$',re.I)
SHARED = re.compile(r'\s+LOCK\s+IN\s+SHARE\s+MODE(?:\s+(?:NOWAIT|WAIT\s+\d+))?\s*$',re.I)


class PreparationDatabaseError(RuntimeError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)


class ReadOnlyPreparationDatabase:
    """Known framework read API only; transaction and write methods are denied.

    owner_check is a server coordinator check, not a client approval callback.
    Direct access to a previously cached original connection is outside this
    boundary. Canonical callback identity/owned connection checks remain required.
    """
    __slots__=('_database','_owner_check','_business_tables','_failed')

    def __init__(self,database,*,owner_check,business_tables):
        if (not callable(owner_check) or type(business_tables) is not frozenset
                or any(type(name) is not str or not name or '`' in name for name in business_tables)):
            raise PreparationDatabaseError('preparation_database_context')
        self._database=database
        self._owner_check=owner_check
        self._business_tables=business_tables
        self._failed=False

    def __repr__(self):return '<ReadOnlyPreparationDatabase protected>'

    def __reduce_ex__(self,protocol):raise TypeError('preparation_database_not_serializable')

    def _require(self):
        if self._failed:raise PreparationDatabaseError('preparation_database_unusable')
        invalid=False
        try:valid=self._owner_check() is True
        except Exception:invalid=True
        if invalid or not valid:
            self._failed=True
            raise PreparationDatabaseError('preparation_database_owner_changed')

    def _deny(self,code):
        self._failed=True
        raise PreparationDatabaseError(code)

    def __getattr__(self,name):
        self._require()
        if name in READ_ATTRIBUTES:
            return getattr(self._database,name)
        if name not in READ_METHODS:
            self._deny('preparation_database_operation_denied')
        def read(*args,**kwargs):
            self._require()
            # Never reuse a value from before the owned preparation transaction.
            if name in ('get_value','get_values','get_single_value','get_singles_value'):
                kwargs['cache']=False
            result=getattr(self._database,name)(*args,**kwargs)
            self._require()
            return result
        return read

    def sql(self,query,*args,**kwargs):
        self._require()
        if (type(query) is not str or not re.match(r'^\s*(?:SELECT|SHOW|DESC|DESCRIBE)\b',query,re.I)
                or ';' in query or re.search(r'\b(?:INTO|GET_LOCK|RELEASE_LOCK|SLEEP|LOAD_FILE)\b',query,re.I)):
            self._deny('preparation_database_write_denied')
        tables={first or second for first,second in TABLES.findall(query)}
        if tables & self._business_tables:
            # A native get_doc(for_update=True) propagates that flag to children.
            # Downgrade only its master read here; the coordinator already owns
            # the main source/chain write locks before entering this view.
            query=FOR_UPDATE.sub('',query).rstrip()
            query=SHARED.sub('',query).rstrip()
            query+=' LOCK IN SHARE MODE NOWAIT'
        result=self._database.sql(query,*args,**kwargs)
        self._require()
        return result


@contextmanager
def preparation_database(runtime,*,owner_check,business_tables):
    """Restore the exact original local DB on all failures, including handoff.

    The coordinator must reject a switched owner before a commit. Restoration
    never commits/rolls back/closes another handle or fixes a changed connection.
    """
    original=runtime.local.db
    guarded=ReadOnlyPreparationDatabase(original,owner_check=owner_check,business_tables=business_tables)
    runtime.local.db=guarded
    try:
        yield guarded
    finally:
        changed=runtime.local.db is not guarded
        runtime.local.db=original
        if changed:
            guarded._deny('preparation_database_binding_changed')
