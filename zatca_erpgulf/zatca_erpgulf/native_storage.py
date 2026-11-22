"""Explicit initial storage setup, without schema/site/key installation.

Only this internal System Manager service may create a missing native namespace.
Normal workers require authenticated readiness and never repair/reset it. The
existing site encryption key is mandatory. Generic Single saves are not used.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from uuid import uuid4

from .dispatch_storage_context import (
    CONTROL, CONTROL_FIELDS, derive_storage_cipher, make_storage_probe,
)
from .worker_transaction import _owned_transaction


TABLES = ('tabZATCA Issuing Chain', 'tabZATCA Issuance', 'tabZATCA Dispatch Attempt', 'tabZATCA Onboarding Attempt',
    'tabZATCA Submission Intent', 'tabZATCA Legacy History Page', 'tabZATCA CSID Renewal')


class NativeStorageError(RuntimeError):
    def __init__(self, code, *, commit_uncertain=False):
        self.code, self.commit_uncertain = code, commit_uncertain
        super().__init__(code)


@dataclass(frozen=True)
class StorageSetup:
    namespace: str
    reused: bool


def _sql(owner, statement, values=()):
    owner.require_owner()
    rows = owner.database.sql(statement, values, as_dict=True)
    owner.require_owner()
    return rows


@contextmanager
def _setup_mutex(owner):
    """Connection-bound zero-wait mutex; Singles has a nonunique index in v15.

    No row/gap-lock/isolation-level assumption makes an empty Single unique.
    Reject an already-held session lock instead of taking a recursive acquisition.
    Cleanup releases only this invocation's same-connection lock, even after an
    unknown COMMIT acknowledgment; it never rolls back or unlocks another worker.
    """
    name = 'zatca-storage-'+hashlib.sha256(owner.db_name.encode()).hexdigest()[:48]
    rows = _sql(owner, 'SELECT CONNECTION_ID() AS connection_id,IS_USED_LOCK(%s) AS holder', (name,))
    if (len(rows) != 1 or type(rows[0]['connection_id']) is not int or rows[0]['holder'] is not None):
        raise NativeStorageError('native_storage_setup_busy')
    connection_id = rows[0]['connection_id']
    acquired = False
    try:
        rows = _sql(owner, 'SELECT GET_LOCK(%s,0) AS acquired', (name,))
        if len(rows) != 1 or type(rows[0]['acquired']) is not int or rows[0]['acquired'] != 1:
            raise NativeStorageError('native_storage_setup_busy')
        acquired = True
        yield
    finally:
        # GET_LOCK itself may have succeeded before its acknowledgment was lost.
        # The preceding IS_USED_LOCK proved there was no parent session lock.
        failed = False
        if owner._binding_current():
            try:
                rows = owner.database.sql('SELECT CONNECTION_ID() AS connection_id,IS_USED_LOCK(%s) AS holder', (name,), as_dict=True)
                if len(rows) != 1 or rows[0]['connection_id'] != connection_id:
                    raise ValueError
                if rows[0]['holder'] == connection_id:
                    released = owner.database.sql('SELECT RELEASE_LOCK(%s) AS released', (name,), as_dict=True)
                    if len(released) != 1 or released[0]['released'] != 1:
                        raise ValueError
                elif acquired:
                    raise ValueError
            except Exception:
                failed = True
        else:
            failed = True
        if failed:
            raise NativeStorageError('native_storage_lock_review', commit_uncertain=owner.state in ('COMMITTED', 'COMMIT_UNKNOWN'))


def _installed_metadata(runtime):
    meta = runtime.get_meta(CONTROL)
    if meta.issingle != 1:
        raise NativeStorageError('native_storage_schema_review')
    for name in CONTROL_FIELDS:
        definition = meta.get_field(name)
        expected = 'Int' if name == 'storage_version' else 'Long Text' if name == 'storage_key_check' else 'Data'
        if definition is None or definition.fieldtype != expected or definition.read_only != 1:
            raise NativeStorageError('native_storage_schema_review')


def _capacity(owner, values):
    rows = _sql(owner, 'SELECT column_name,data_type,character_maximum_length AS max_chars,'
        'character_octet_length AS max_bytes FROM information_schema.columns '
        'WHERE table_schema=DATABASE() AND table_name=%s AND column_name IN (%s,%s,%s)',
        ('tabSingles', 'doctype', 'field', 'value'))
    found = {row['column_name']: row for row in rows}
    required = {'doctype': (CONTROL,), 'field': CONTROL_FIELDS, 'value': tuple(values)}
    if len(rows) != 3 or set(found) != set(required):
        raise NativeStorageError('native_storage_schema_review')
    for name, texts in required.items():
        row = found[name]
        if (row['data_type'] not in ('char', 'varchar', 'text', 'mediumtext', 'longtext')
                or type(row['max_chars']) is not int or type(row['max_bytes']) is not int
                or max(map(len, texts)) > row['max_chars']
                or max(len(value.encode()) for value in texts) > row['max_bytes']):
            raise NativeStorageError('native_storage_capacity_review')


def initialize_native_storage(*, runtime):
    """Create only an empty, installed native store; never adopt orphan records.

    This source service is neither an install/migrate hook nor public RPC. Actual
    installed/fictional-site rehearsals retain their separate authorization gates.
    """
    try:
        return _initialize(runtime)
    except Exception as error:
        code = error.code if isinstance(error, NativeStorageError) else 'native_storage_initialization_review'
        uncertain = getattr(error, 'commit_uncertain', False) is True
    raise NativeStorageError(code, commit_uncertain=uncertain)


def _initialize(runtime):
    with _owned_transaction(runtime, load_storage=False) as owner:
        if owner.actor == 'Guest' or 'System Manager' not in runtime.get_roles(owner.actor):
            raise NativeStorageError('native_storage_manager_required')
        _installed_metadata(runtime)
        with _setup_mutex(owner):
            rows = _sql(owner, 'SELECT field,SUBSTRING(value,1,513) AS value FROM `tabSingles` '
                'WHERE doctype=%s LIMIT 4 LOCK IN SHARE MODE NOWAIT', (CONTROL,))
            if rows:
                # A partial/duplicated/unknown Single is never repaired in place.
                if len(rows) != 3 or {row['field'] for row in rows} != set(CONTROL_FIELDS):
                    raise NativeStorageError('native_storage_existing_state_review')
                owner._load_storage_context()
                return StorageSetup(owner.storage_namespace, True)
            for table in TABLES:
                # Fixed names only; no configured database/site discovery or DDL.
                if _sql(owner, 'SELECT name FROM `'+table+'` LIMIT 1 LOCK IN SHARE MODE NOWAIT'):
                    raise NativeStorageError('native_storage_orphan_records_review')
            namespace = str(uuid4())
            cipher = derive_storage_cipher(owner._encryption_text, site=owner.site, namespace=namespace)
            probe = make_storage_probe(cipher, namespace)
            values = (namespace, '1', probe)
            _capacity(owner, values)
            for name, value in zip(CONTROL_FIELDS, values):
                _sql(owner, 'INSERT INTO `tabSingles` (`doctype`,`field`,`value`) VALUES (%s,%s,%s)', (CONTROL, name, value))
            owner._load_storage_context()
            owner.commit()
            return StorageSetup(namespace, False)
