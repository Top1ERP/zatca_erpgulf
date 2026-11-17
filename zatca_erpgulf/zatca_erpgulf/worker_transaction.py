"""Acquire a clean current-site worker transaction without taking parent writes.

Only the internal queue coordinator may enter this boundary. It creates neither
site/key/namespace nor another connection. Framework15 callbacks and connection
shape are checked explicitly; installed15/16 acceptance remains a release gate.
Unknown commit acknowledgments are surfaced, never retried or interpreted as a
rollback. No connection is closed or foreign transaction repaired here.
"""

import base64
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
import re

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .dispatch_record_codec import DispatchRecordCipher, DispatchRecordError, _identifier
from .preparation_database import preparation_database


OWNED_WORKER = ContextVar('zatca_owned_worker_transaction',default=None)
CALLBACKS = ('before_commit','after_commit','before_rollback','after_rollback')


class WorkerTransactionError(RuntimeError):
    def __init__(self,code,*,commit_uncertain=False):
        self.code=code;self.commit_uncertain=commit_uncertain
        super().__init__(code)


def _configuration(runtime,name):
    conf=runtime.conf
    getter=getattr(conf,'get',None)
    return getter(name) if callable(getter) else getattr(conf,name,None)


def _callbacks_empty(database):
    for name in CALLBACKS:
        callbacks=getattr(getattr(database,name,None),'_functions',None)
        if not isinstance(callbacks,(deque,list,tuple)) or callbacks:
            return False
    return True


class WorkerTransaction:
    """One owned transaction; scope transitions, not a reusable connection pool."""
    def __init__(self,runtime):
        self.runtime=runtime;self.database=runtime.local.db;self.site=runtime.local.site
        self.actor=runtime.session.user;self.db_name=_configuration(runtime,'db_name')
        self._encryption_text=_configuration(runtime,'encryption_key')
        self._connection=None;self._socket=None;self._expected_db=self.database
        self.state='NEW';self.storage_namespace=None;self.cipher=None
        if (type(self.site) is not str or not self.site or type(self.actor) is not str or not self.actor
                or type(self.db_name) is not str or not self.db_name
                or getattr(self.database,'db_type',None)!='mariadb'):
            raise WorkerTransactionError('worker_transaction_context')

    def __repr__(self):return '<WorkerTransaction protected>'
    def __reduce_ex__(self,protocol):raise TypeError('worker_transaction_not_serializable')

    def owner_current(self):
        """No SQL/repair while checking an existing site/actor/physical handle."""
        try:
            return (self.state=='ACTIVE' and self.runtime.local.site==self.site
                and self.runtime.local.db is self._expected_db and self.runtime.session.user==self.actor
                and _configuration(self.runtime,'db_name')==self.db_name
                and _configuration(self.runtime,'encryption_key')==self._encryption_text
                and self.database.cur_db_name==self.db_name and self.database._conn is self._connection
                and self._connection._sock is self._socket and bool(self._connection.open)
                and self._connection.get_autocommit() is False)
        except Exception:
            return False

    def require_owner(self):
        if not self.owner_current():raise WorkerTransactionError('worker_transaction_owner_changed')

    def start(self):
        if self.state!='NEW' or OWNED_WORKER.get() is not self:
            raise WorkerTransactionError('worker_transaction_lifetime')
        db=self.database
        if (type(getattr(db,'transaction_writes',None)) is not int or db.transaction_writes!=0
                or getattr(db,'auto_commit_on_many_writes',0) not in (0,False)
                or not _callbacks_empty(db)):
            raise WorkerTransactionError('worker_transaction_parent_state')
        # Read only from the current framework DB. A lazy connection is to this
        # already-selected site's configuration; no host/socket override exists.
        failed=False
        try:rows=db.sql('SELECT DATABASE() AS db_name',as_dict=True)
        except Exception:failed=True
        if failed or len(rows)!=1 or rows[0].get('db_name')!=self.db_name or db.cur_db_name!=self.db_name:
            raise WorkerTransactionError('worker_transaction_database')
        connection=db._conn;socket=getattr(connection,'_sock',None)
        if socket is None or connection.get_autocommit() is not False or not connection.open:
            raise WorkerTransactionError('worker_transaction_connection')
        self._connection=connection;self._socket=socket
        # Lazy connection hooks may have changed the parent transaction during
        # SELECT DATABASE(). Never discard writes/callbacks created by them.
        if (type(getattr(db,'transaction_writes',None)) is not int or db.transaction_writes!=0
                or getattr(db,'auto_commit_on_many_writes',0) not in (0,False)
                or not _callbacks_empty(db) or self.runtime.local.db is not db
                or self.runtime.local.site!=self.site or self.runtime.session.user!=self.actor
                or _configuration(self.runtime,'db_name')!=self.db_name
                or _configuration(self.runtime,'encryption_key')!=self._encryption_text):
            raise WorkerTransactionError('worker_transaction_parent_changed')
        # Frappe rollback also explicitly starts the next transaction. Parent
        # writes/callbacks were rejected above; only its read snapshot is discarded.
        try:db.rollback()
        except Exception:failed=True
        if failed:raise WorkerTransactionError('worker_transaction_begin_failed')
        self.state='ACTIVE';self.require_owner()
        self._load_storage_context()

    def _load_storage_context(self):
        self.require_owner();failed=False
        try:
            rows=self.database.sql('SELECT field,SUBSTRING(value,1,257) AS value FROM `tabSingles` '
                'WHERE doctype=%s AND field IN (%s,%s)',
                ('ZATCA Dispatch Control','storage_namespace','storage_version'),as_dict=True)
        except Exception:failed=True
        if failed:raise WorkerTransactionError('worker_storage_not_ready')
        values={row['field']:row['value'] for row in rows}
        if len(rows)!=2 or set(values)!=set(('storage_namespace','storage_version')) or values['storage_version']!='1':
            raise WorkerTransactionError('worker_storage_not_ready')
        try:_identifier(values['storage_namespace'])
        except DispatchRecordError:failed=True
        text=self._encryption_text
        if type(text) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{43}=',text):
            failed=True
        if failed:raise WorkerTransactionError('worker_storage_configuration')
        decoded=base64.urlsafe_b64decode(text)
        if len(decoded)!=32 or base64.urlsafe_b64encode(decoded).decode()!=text:
            raise WorkerTransactionError('worker_storage_configuration')
        namespace=values['storage_namespace']
        key=HKDF(algorithm=hashes.SHA256(),length=32,salt=None,
            info=b'zatca-native-dispatch/v1\0'+namespace.encode('ascii')).derive(decoded)
        self.storage_namespace=namespace
        self.cipher=DispatchRecordCipher(key,site=self.site,storage_namespace=namespace)
        self.require_owner()

    @contextmanager
    def preparing(self,business_tables):
        self.require_owner()
        if self._expected_db is not self.database:
            raise WorkerTransactionError('worker_preparation_nested')
        with preparation_database(self.runtime,owner_check=self.owner_current,business_tables=business_tables) as view:
            self._expected_db=view
            try:yield view
            finally:self._expected_db=self.database
        self.require_owner()

    def utc_now(self):
        """Use this transaction's server clock for lease/audit observations."""
        from datetime import datetime
        self.require_owner()
        rows=self.database.sql('SELECT UTC_TIMESTAMP(6) AS utc_now',as_dict=True)
        self.require_owner()
        if (len(rows)!=1 or type(rows[0].get('utc_now')) is not datetime
                or rows[0]['utc_now'].tzinfo is not None):
            raise WorkerTransactionError('worker_transaction_clock')
        return rows[0]['utc_now']

    def commit(self):
        self.require_owner()
        if self._expected_db is not self.database or not _callbacks_empty(self.database):
            raise WorkerTransactionError('worker_transaction_callbacks_changed')
        self.state='COMMITTING';failed=False
        try:self.database.commit()
        except Exception:failed=True
        if failed:
            self.state='COMMIT_UNKNOWN'
            raise WorkerTransactionError('worker_transaction_commit_unknown',commit_uncertain=True)
        self.state='COMMITTED'

    def close(self):
        if self.state=='ACTIVE':
            self.require_owner()
            if not _callbacks_empty(self.database):
                self.state='UNUSABLE'
                raise WorkerTransactionError('worker_transaction_callbacks_changed')
            failed=False
            try:self.database.rollback()
            except Exception:failed=True
            self.state='CLOSED'
            if failed:raise WorkerTransactionError('worker_transaction_rollback_unknown')
        elif self.state=='NEW':self.state='CLOSED'
        # COMMITTED/COMMIT_UNKNOWN are terminal. Never infer rollback or erase
        # an original that may already have been committed to InnoDB.


@contextmanager
def owned_worker_transaction(runtime):
    if OWNED_WORKER.get() is not None:
        raise WorkerTransactionError('worker_transaction_nested')
    owner=WorkerTransaction(runtime);token=OWNED_WORKER.set(owner)
    try:
        owner.start()
        yield owner
    finally:
        try:owner.close()
        finally:OWNED_WORKER.reset(token)
